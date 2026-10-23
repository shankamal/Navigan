"""Connector API promotion scope and dependency preservation; no live AWS calls."""
import copy
import importlib.util
from pathlib import Path
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("connector_prod_release", ROOT / "scripts/deploy-migration-connector-prod.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
CODE = {"S3Bucket": "private", "S3Key": "connector.zip", "S3ObjectVersion": "immutable"}
CONFIG = {"Environment": {"Variables": {"DB_NAME": "navigan", "OTHER": "preserved"}}}


def template():
    return {"Resources": {
        release.FUNCTION: {"Type": "AWS::Lambda::Function", "Properties": {
            "Code": {"S3Bucket": "old", "S3Key": "old.zip"},
            "Handler": "navigan.modules.migration_management.connector_handler.lambda_handler",
            "Environment": {"Variables": {"DB_NAME": {"Ref": "DatabaseName"}}},
            "Role": "original-role", "VpcConfig": {"SubnetIds": ["private-subnet"]}, "Timeout": 30}},
        "MigrationFunction": {"Type": "AWS::Lambda::Function", "Properties": {"Code": "unchanged"}},
        "MigrationConnectorIntegration": {"Type": "AWS::ApiGatewayV2::Integration", "Properties": {
            "IntegrationType": "AWS_PROXY", "IntegrationUri": {"Fn::GetAtt": [release.FUNCTION, "Arn"]}}},
        "SourceConnectorInvokePermission": {"Type": "AWS::Lambda::Permission", "Properties": {
            "Action": "lambda:InvokeFunction", "Principal": "apigateway.amazonaws.com", "FunctionName": {"Ref": release.FUNCTION}}},
        "ConnectorRoute": {"Type": "AWS::ApiGatewayV2::Route", "Properties": {"RouteKey": "POST /source-inventory", "AuthorizationType": "NONE"}}
    }}


def change(logical=release.FUNCTION, kind="AWS::Lambda::Function", action="Modify", replacement="False"):
    return {"ResourceChange": {"LogicalResourceId": logical, "ResourceType": kind, "Action": action, "Replacement": replacement}}


def test_template_changes_only_connector_code_and_flag_without_mutating_input():
    before = template()
    original = copy.deepcopy(before)
    after = release.connector_template(before, CONFIG, CODE)
    assert before == original
    assert after["Resources"]["MigrationFunction"] == before["Resources"]["MigrationFunction"]
    props = after["Resources"][release.FUNCTION]["Properties"]
    assert props["Environment"]["Variables"] == {"DB_NAME": "navigan", "OTHER": "preserved", release.FLAG: "true"}
    assert props["Code"] == CODE
    release.validate_children([change()], before, after, CONFIG, CODE)


@pytest.mark.parametrize("bad_db", ["navigan_dev", "", None])
def test_wrong_database_is_rejected(bad_db):
    with pytest.raises(RuntimeError):
        release.connector_template(template(), {"Environment": {"Variables": {"DB_NAME": bad_db}}}, CODE)


@pytest.mark.parametrize("logical,kind", [
    ("MigrationFunction", "AWS::Lambda::Function"),
    ("ConnectorRole", "AWS::IAM::Role"),
    ("ConnectorRoute", "AWS::ApiGatewayV2::Route"),
])
def test_unexpected_changes_rejected(logical, kind):
    before = template()
    after = release.connector_template(before, CONFIG, CODE)
    with pytest.raises(RuntimeError):
        release.validate_children([change(), change(logical, kind)], before, after, CONFIG, CODE)


@pytest.mark.parametrize("action,replacement", [("Add", "False"), ("Remove", "False"), ("Modify", "True"), ("Modify", "Conditional")])
def test_connector_replacement_or_deletion_rejected(action, replacement):
    before = template()
    after = release.connector_template(before, CONFIG, CODE)
    with pytest.raises(RuntimeError):
        release.validate_children([change(action=action, replacement=replacement)], before, after, CONFIG, CODE)


def test_only_identical_connector_dependencies_are_allowed():
    before = template()
    after = release.connector_template(before, CONFIG, CODE)
    changes = [change(), change("MigrationConnectorIntegration", "AWS::ApiGatewayV2::Integration"), change("SourceConnectorInvokePermission", "AWS::Lambda::Permission")]
    release.validate_children(changes, before, after, CONFIG, CODE)
    after["Resources"]["MigrationConnectorIntegration"]["Properties"]["IntegrationUri"] = "other-function"
    with pytest.raises(RuntimeError):
        release.validate_children(changes, before, after, CONFIG, CODE)


@pytest.mark.parametrize("field,value", [("Role", "broader-role"), ("Timeout", 900), ("VpcConfig", {})])
def test_connector_configuration_outside_scope_rejected(field, value):
    before = template()
    after = release.connector_template(before, CONFIG, CODE)
    after["Resources"][release.FUNCTION]["Properties"][field] = value
    with pytest.raises(RuntimeError):
        release.validate_children([change()], before, after, CONFIG, CODE)


def test_environment_and_package_reference_tampering_rejected():
    before = template()
    after = release.connector_template(before, CONFIG, CODE)
    after["Resources"][release.FUNCTION]["Properties"]["Environment"]["Variables"]["OTHER"] = "changed"
    with pytest.raises(RuntimeError):
        release.validate_children([change()], before, after, CONFIG, CODE)
    after = release.connector_template(before, CONFIG, CODE)
    after["Resources"][release.FUNCTION]["Properties"]["Code"] = {"ZipFile": "other code"}
    with pytest.raises(RuntimeError):
        release.validate_children([change()], before, after, CONFIG, CODE)


def test_package_replaces_two_modules_and_preserves_dependencies(tmp_path):
    original = tmp_path / "original.zip"
    entries = {release.PREFIX + name: b"old source" for name in release.MODULES}
    entries.update({release.PREFIX + "models.py": b"original models", "dependency.so": b"native-dependency",
        release.PREFIX + "__pycache__/connector_handler.cpython-312.pyc": b"old-bytecode"})
    with zipfile.ZipFile(original, "w") as package:
        for name, content in entries.items():
            package.writestr(name, content)
    result = release.package_connector(original, tmp_path)
    with zipfile.ZipFile(result) as package:
        for name in release.MODULES:
            assert package.read(release.PREFIX + name) == (ROOT / "src" / release.PREFIX / name).read_bytes()
        assert package.read("dependency.so") == b"native-dependency"
        assert package.read(release.PREFIX + "models.py") == b"original models"
        assert not any(name.endswith(".pyc") for name in package.namelist())
    with zipfile.ZipFile(original) as package:
        assert package.read("dependency.so") == b"native-dependency"


def test_unexpected_package_layout_is_rejected(tmp_path):
    original = tmp_path / "wrong.zip"
    with zipfile.ZipFile(original, "w") as package:
        package.writestr("unrelated.py", b"pass")
    with pytest.raises(RuntimeError):
        release.package_connector(original, tmp_path)
