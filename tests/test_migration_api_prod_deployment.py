"""Scope, rollback and packaging checks for the production migration API release."""
import base64
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("prod_api", ROOT / "scripts/deploy-migration-api-prod.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def config():
    return {"Role": f"arn:aws:iam::{release.ACCOUNT}:role/ProdApiRole"}


def reference():
    return {"AuthorizerId": "production-jwt", "AuthorizationScopes": ["navigan/api"], "Target": "integrations/prod"}


def workspace():
    return {"WorkspaceBucketName": "production-workspace", "WorkspaceKmsKeyArn": "production-key"}


def original():
    return {"Parameters": {"DatabaseName": {"Type": "String"}}, "Resources": {
        "MigrationFunction": {"Type": "AWS::Lambda::Function", "Properties": {"Code": {"S3Bucket": "old"},
            "Role": "original-role-reference", "Runtime": "python3.12", "Layers": ["original-ca-layer"],
            "VpcConfig": {"SubnetIds": ["production-private"]}, "Environment": {"Variables": {"DB_NAME": "navigan"}}}},
        "MigrationConnectorFunction": {"Type": "AWS::Lambda::Function", "Properties": {"Code": {"S3Bucket": "connector-original"}}},
        "MigrationFunctionRole": {"Type": "AWS::IAM::Role", "Properties": {"AssumeRolePolicyDocument": {"existing": "trust"}}},
        "MigrationIntegration": {"Type": "AWS::ApiGatewayV2::Integration", "Properties": {"IntegrationUri": "original"}},
        "ExistingRoute": {"Type": "AWS::ApiGatewayV2::Route", "Properties": {"RouteKey": "GET /api/v1/migrations/{migrationId}"}},
    }, "Outputs": {"existing": {"Value": "unchanged"}}}


def build(template=None, routes=None, env=None):
    return release.child_template(template or original(), config(), "production-api", reference(), routes or [],
        env or {"DB_NAME": "navigan", "OIDC_EXISTING": "preserve", "DB_SECRET_ARN": "existing-reference"},
        workspace(), {"S3Bucket": "production-workspace", "S3Key": "immutable", "S3ObjectVersion": "version"},
        {"Version": "2012-10-17", "Statement": []})


def test_child_preserves_connector_role_trust_network_runtime_and_existing_routes():
    before = original()
    snapshot = copy.deepcopy(before)
    after = build(before)
    assert before == snapshot
    for logical in ("MigrationConnectorFunction", "MigrationFunctionRole", "MigrationIntegration", "ExistingRoute"):
        assert after["Resources"][logical] == before["Resources"][logical]
    fn = after["Resources"]["MigrationFunction"]["Properties"]
    for key in ("VpcConfig", "Layers", "Runtime", "Role"):
        assert fn[key] == before["Resources"]["MigrationFunction"]["Properties"][key]
    assert fn["Environment"]["Variables"]["DB_SECRET_ARN"] == "existing-reference"
    assert fn["Environment"]["Variables"]["MIGRATION_WORKSPACE_BUCKET"] == "production-workspace"
    assert fn["Environment"]["Variables"]["MIGRATION_SOURCE_FIRST_ENABLED"] == "true"
    assert "MIGRATION_RECOVERY_BUCKET" not in fn["Environment"]["Variables"]
    assert release.POLICY in after["Resources"]["MigrationFunction"]["DependsOn"]
    assert after["Parameters"] == before["Parameters"] and after["Outputs"] == before["Outputs"]


def test_every_new_route_inherits_production_jwt_scopes_and_integration():
    after = build()
    assert len(release.ROUTES) == len(set(release.ROUTES))
    for route, logical in release.ROUTE_IDS.items():
        props = after["Resources"][logical]["Properties"]
        assert props == {"ApiId": "production-api", "RouteKey": route, "AuthorizationType": "JWT", **reference()}
    policy = after["Resources"][release.POLICY]["Properties"]
    assert policy["Roles"] == ["ProdApiRole"]
    permission = after["Resources"][release.PERMISSION]["Properties"]
    assert permission["SourceAccount"] == release.ACCOUNT
    assert permission["SourceArn"].endswith("production-api/v1/*/api/v1/source-clusters*")


@pytest.mark.parametrize("field,value", [("AuthorizationType", "NONE"), ("AuthorizerId", "other-jwt"),
    ("AuthorizationScopes", []), ("Target", "integrations/other")])
def test_existing_artifact_route_with_different_security_or_target_is_rejected(field, value):
    route = {"RouteKey": release.ROUTES[0], "AuthorizationType": "JWT", **reference(), field: value}
    with pytest.raises(RuntimeError, match="protection/integration"):
        build(routes=[route])


def test_existing_matching_route_is_not_duplicated():
    route = {"RouteKey": release.ROUTES[0], "AuthorizationType": "JWT", **reference()}
    assert release.ROUTE_IDS[release.ROUTES[0]] not in build(routes=[route])["Resources"]


def test_dev_database_cannot_be_promoted_as_prod():
    with pytest.raises(RuntimeError, match="database identity"):
        build(env={"DB_NAME": "navigan_dev"})


def test_parent_only_changes_migration_template_url():
    before = {"Parameters": {"preserve": {}}, "Resources": {
        "MigrationManagement": {"Type": "AWS::CloudFormation::Stack", "Properties": {"TemplateURL": "old", "Parameters": {"preserve": "value"}}},
        "Customers": {"Type": "AWS::CloudFormation::Stack", "Properties": {"TemplateURL": "customer-original"}},
        "Authentication": {"Type": "AWS::Cognito::UserPool", "Properties": {"existing": "auth"}},
    }}
    expected = copy.deepcopy(before)
    expected["Resources"]["MigrationManagement"]["Properties"]["TemplateURL"] = "new-versioned-url"
    assert release.parent_template(before, "new-versioned-url") == expected
    assert before["Resources"]["MigrationManagement"]["Properties"]["TemplateURL"] == "old"


@pytest.mark.parametrize("template", ["unparsed: yaml", {"Resources": {"Function": {"Type": "AWS::Serverless::Function"}}}, {}])
def test_unprocessed_or_invalid_templates_are_rejected(template):
    with pytest.raises(RuntimeError):
        release.body(template)


def test_processed_json_is_supported():
    assert release.body(json.dumps(original())) == original()


def resource(logical, kind, action="Modify", **extra):
    return {"ResourceChange": {"LogicalResourceId": logical, "ResourceType": kind, "Action": action, "Replacement": "False", **extra}}


class ChangeSets:
    def __init__(self, root=None, child=None):
        self.root = root if root is not None else [resource("MigrationManagement", "AWS::CloudFormation::Stack", ChangeSetId="nested")]
        self.child = child if child is not None else [resource("MigrationFunction", "AWS::Lambda::Function")]

    def describe_change_set(self, ChangeSetName, **kwargs):
        if ChangeSetName == "root":
            return {"Status": "CREATE_COMPLETE", "ExecutionStatus": "AVAILABLE", "StackName": release.PARENT, "Changes": self.root}
        assert ChangeSetName == "nested"
        return {"StackId": f"arn:aws:cloudformation:{release.REGION}:{release.ACCOUNT}:stack/{release.PARENT}-MigrationManagement-example/id", "Changes": self.child}


def test_hierarchy_accepts_only_scoped_migration_update():
    root, child = release.inspect_plan(ChangeSets(), "root")
    assert len(root) == len(child) == 1


@pytest.mark.parametrize("changes", [[], [resource("CustomerManagement", "AWS::CloudFormation::Stack", ChangeSetId="nested")],
    [resource("MigrationManagement", "AWS::CloudFormation::Stack", Replacement="True", ChangeSetId="nested")],
    [resource("MigrationManagement", "AWS::CloudFormation::Stack")],
    [resource("MigrationManagement", "AWS::CloudFormation::Stack", ChangeSetId="nested"), resource("Identity", "AWS::Cognito::UserPool")]])
def test_hierarchy_rejects_unrelated_parent_changes(changes):
    with pytest.raises(RuntimeError):
        release.inspect_plan(ChangeSets(root=changes), "root")


@pytest.mark.parametrize("changes", [[], [resource("MigrationConnectorFunction", "AWS::Lambda::Function")],
    [resource("MigrationFunctionRole", "AWS::IAM::Role")], [resource("MigrationFunction", "AWS::Lambda::Function", action="Remove")],
    [resource("MigrationFunction", "AWS::Lambda::Function", action="Add")],
    [resource("MigrationFunction", "AWS::Lambda::Function", Replacement="Conditional")],
    [resource("MigrationFunction", "AWS::Lambda::Function", ChangeSetId="unexpected-nesting")]])
def test_hierarchy_rejects_connector_trust_deletion_replacement_or_empty_changes(changes):
    with pytest.raises(RuntimeError):
        release.inspect_plan(ChangeSets(child=changes), "root")


def test_package_preserves_original_dependencies_and_replaces_only_authorized_modules(monkeypatch, tmp_path):
    source = tmp_path / "checkout"
    modules = source / "src" / release.PREFIX
    modules.mkdir(parents=True)
    for name in ("handler.py", "service.py", "repository.py", "artifact_workspace.py", "workspace_export.py", "workspace_worker.py", "image_worker.py"):
        (modules / name).write_text("RELEASE = 'new'\n")
    github = source / "src/navigan/modules/cluster_management/github_app.py"
    github.parent.mkdir(parents=True)
    github.write_text("RELEASE = 'new'\n")
    archive = tmp_path / "original.zip"
    with zipfile.ZipFile(archive, "w") as package:
        for name in ("handler.py", "service.py", "repository.py"):
            package.writestr(release.PREFIX + name, b"old")
        package.writestr("psycopg/dependency.py", b"unchanged")
        package.writestr("navigan/modules/customer_management/service.py", b"unchanged customer")
        package.writestr(release.PREFIX + "__pycache__/handler.cpython-312.pyc", b"old bytecode")
        package.writestr("navigan/modules/cluster_management/__pycache__/github_app.cpython-312.pyc", b"old GitHub bytecode")
    def download(command):
        assert command[-1] == "PyYAML==6.0.2" and "312" in command and "manylinux2014_x86_64" in command
        with zipfile.ZipFile(tmp_path / "wheels/PyYAML-test.whl", "w") as wheel:
            wheel.writestr("yaml/__init__.py", b"pinned YAML")
    monkeypatch.setattr(release.subprocess, "check_call", download)
    target = release.package_api(archive, tmp_path, source)
    with zipfile.ZipFile(target) as package:
        assert package.read("psycopg/dependency.py") == b"unchanged"
        assert package.read("navigan/modules/customer_management/service.py") == b"unchanged customer"
        assert package.read(release.PREFIX + "handler.py") == b"RELEASE = 'new'\n"
        assert package.read("yaml/__init__.py") == b"pinned YAML"
        assert not any(n.endswith(".pyc") for n in package.namelist())


def test_versioned_upload_enforces_prod_owner_and_kms():
    calls = []
    client = SimpleNamespace(put_object=lambda **kw: calls.append(kw) or {"VersionId": "exact/version+"})
    session = SimpleNamespace(client=lambda name: client)
    code, url = release.upload(session, workspace(), None, "migration-api.zip", b"artifact")
    assert calls[0]["ExpectedBucketOwner"] == release.ACCOUNT
    assert calls[0]["ServerSideEncryption"] == "aws:kms"
    assert calls[0]["SSEKMSKeyId"] == "production-key"
    assert hashlib.sha256(b"artifact").hexdigest() in code["S3Key"]
    assert code["S3ObjectVersion"] == "exact/version+" and "versionId=exact%2Fversion%2B" in url


def test_unversioned_upload_is_not_accepted():
    session = SimpleNamespace(client=lambda name: SimpleNamespace(put_object=lambda **kw: {}))
    with pytest.raises(RuntimeError, match="versioned"):
        release.upload(session, workspace(), None, "migration-api.zip", b"artifact")


@pytest.mark.parametrize("allowlist", ['["*"]', '{}', '[123]'])
def test_registry_policy_rejects_wildcards_or_invalid_allowlist(allowlist):
    with pytest.raises(RuntimeError, match="allowlist"):
        release.policy_document(None, {"SOURCE_REGISTRY_ALLOWED_ROLE_ARNS": allowlist})


def test_deployment_policy_does_not_change_trust_or_source_node_permissions():
    doc = release.policy_document(None, {})
    actions = {a for statement in doc["Statement"] for a in statement["Action"]}
    assert actions == {"sts:AssumeRole", "secretsmanager:CreateSecret", "secretsmanager:PutSecretValue", "secretsmanager:GetSecretValue"}
    assert "ssm:SendCommand" not in actions


def test_execute_rejects_changed_api_before_cloud_mutation(tmp_path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({"format": 1, "account": release.ACCOUNT, "region": release.REGION,
        "changeSet": f"arn:aws:cloudformation:{release.REGION}:{release.ACCOUNT}:changeSet/prod/id",
        "parentStamp": "before", "function": "prod", "revision": "old", "originalCodeSha256": "old"}))
    cfn = SimpleNamespace(describe_stacks=lambda **kw: {"Stacks": [{"StackStatus": "UPDATE_COMPLETE", "LastUpdatedTime": "before"}]},
                          execute_change_set=lambda **kw: pytest.fail("Executed a stale release"))
    clients = {"sts": SimpleNamespace(get_caller_identity=lambda: {"Account": release.ACCOUNT}), "cloudformation": cfn,
        "lambda": SimpleNamespace(get_function_configuration=lambda **kw: {"FunctionArn": f"arn:aws:lambda:{release.REGION}:{release.ACCOUNT}:function:{release.PARENT}-api", "RevisionId": "changed", "CodeSha256": "changed"})}
    with pytest.raises(RuntimeError, match="changed since preparation"):
        release.execute(SimpleNamespace(client=lambda name: clients[name]), path)


def test_default_readiness_does_not_upload_or_create_change_sets(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["release"])
    monkeypatch.setattr(release, "check_checkout", lambda: None)
    monkeypatch.setattr(release.storage, "preflight", lambda s: {"role": "ProdApiRole"})
    monkeypatch.setattr(release.storage, "verify_storage", lambda *a: workspace())
    monkeypatch.setattr(release, "runtime", lambda *a: ({}, config(), "production-api", reference(), [],
        {"DB_NAME": "navigan"}, {}, original()))
    paginator = SimpleNamespace(paginate=lambda **kw: [{"PolicyNames": []}])
    fake = SimpleNamespace(client=lambda name: SimpleNamespace(get_paginator=lambda operation: paginator))
    monkeypatch.setattr(release.boto3, "Session", lambda **kw: fake)
    monkeypatch.setattr(release, "upload", lambda *a: pytest.fail("Uploaded during read-only readiness"))
    assert release.main() == 0
