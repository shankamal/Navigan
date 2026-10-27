import ast
import base64
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock
import zipfile
import shutil

import pytest
import yaml

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("bootstrap_release", ROOT / "scripts/deploy-cluster-bootstrap-prod.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
patch = release.patch
FIXTURE = ROOT / "tests/fixtures/bootstrap-runtime"


def historical(name):
    # Reconstructed from the supplied runtime/source diff; package hashes are
    # verified against AWS separately by the release preflight.
    return (FIXTURE / name).read_text()


def test_overlay_preserves_unrelated_runner_behavior_and_checks_protected_plans():
    original = historical("runner.py.txt")
    updated = patch.patch_runner(original)
    before, after = ast.parse(original), ast.parse(updated)
    for node in before.body:
        if isinstance(node, ast.FunctionDef) and node.name != "security_scan":
            other = next(n for n in after.body if isinstance(n, ast.FunctionDef) and n.name == node.name)
            assert patch.same(node, other)
    assert "import sys" in updated
    assert 'if mode != "delete"' not in updated
    assert '"installer_security_group_id"' not in updated
    assert "allowed_destructive" not in updated
    namespace = {"json": json}
    functions = ast.Module(body=[n for n in after.body if isinstance(n, ast.FunctionDef)], type_ignores=[])
    exec(compile(functions, "runner.py", "exec"), namespace)
    request = {"configuration": {"endpointAccess": "PRIVATE", "nodeGroups": [{"name": "system", "purpose": "SYSTEM"}]}}
    assert namespace["security_scan"]({"resource_changes": []}, request)["status"] == "FAILED"
    request["configuration"]["nodeGroups"] = []
    request["configuration"]["systemNodeGroupMigration"] = {"legacyNodeGroupName": "legacy"}
    plan = {"resource_changes": [{"address": 'aws_eks_node_group.this["legacy"]', "change": {"actions": ["delete"]}}]}
    assert namespace["security_scan"](plan, request)["status"] == "FAILED"
    assert updated.index('"Approved Terraform plan hash mismatch."') < updated.index('shown = run_json("terraform", "show", "-json", "terraform.tfplan")', updated.index('elif mode == "apply"'))


def test_overlay_changes_only_node_group_labels_taints_and_purpose_type():
    original_main, original_vars = historical("main.tf"), historical("variables.tf")
    main, variables = patch.patch_module(original_main, original_vars)
    start, end = patch.block(main, r'resource "aws_eks_node_group" "this"')
    before_start, before_end = patch.block(original_main, r'resource "aws_eks_node_group" "this"')
    assert main[:start] == original_main[:before_start]
    assert main[end:] == original_main[before_end:]
    assert "for_each = local.node_groups" in main
    assert "aws_security_group.managed_nodes" not in main
    assert "data \"aws_eks_node_group\"" not in main
    assert 'security_groups = var.node_security_group_ids' in main
    assert variables.replace("\n    purpose = string", "", 1) == original_vars
    assert 'navigan.io/platform-services' in main and 'NO_SCHEDULE' in main


def old_source(name):
    # Fixed runtime-shaped samples keep this test independent of Git history or
    # CI checkout depth. The complete historical runner is a separate fixture.
    if name == "handler.py":
        return '''from contextlib import nullcontext

def execute(event, principal, correlation):
    read, identifier, action = event['read'], event['id'], event['action']
    with transaction() as db:
        repo = Repository(db, principal)
        if read:
            if not identifier:
                return repo.list()
            else:
                row = repo.get(identifier)
                if action == "identity":
                    access.require("cluster.identity.view")
                    return repo.identity(identifier)
                return serialize(row, access)
        row = repo.get(identifier)
        return write_existing_action(row)
'''
    if name == "connector_installation.py":
        return '''import boto3
from botocore.config import Config

class ConnectorInstaller:
    def __init__(self, sts=None, secrets=None, client_factory=None):
        self.sts = sts or boto3.client("sts")
        self.secrets = secrets or boto3.client("secretsmanager")
        self.client_factory = client_factory or boto3.client

    def start(self, *args):
        return "preserve existing start behavior"

    def existing_network_checks(self):
        return "preserve existing network behavior"
'''
    return '''class Repository:
    def get(self, identifier, lock=False): pass
    def save(self, row): pass
    def pinned_environment_snapshot(self, identifier, version): pass
'''


def original_zip(path):
    with zipfile.ZipFile(path, "w") as archive:
        for name in ("handler.py", "connector_installation.py", "repository.py"):
            archive.writestr(patch.PREFIX + name, old_source(name))
        app = yaml.safe_load((ROOT / "src" / patch.PREFIX / "system_repo_template/applications/20-falco.yaml").read_text())
        app["spec"]["sources"][0]["targetRevision"] = "9.1.0"
        values = yaml.safe_load((ROOT / "src" / patch.PREFIX / "system_repo_template/values/falco.yaml").read_text())
        values.pop("image"); values.pop("collectors")
        values["resources"]["limits"]["memory"] = "999Mi"
        archive.writestr(patch.PREFIX + "system_repo_template/applications/20-falco.yaml", yaml.safe_dump(app))
        archive.writestr(patch.PREFIX + "system_repo_template/values/falco.yaml", yaml.safe_dump(values))
        archive.writestr("unrelated.py", "def preserve(): return 42\n")
        archive.writestr(patch.PREFIX + "__pycache__/handler.cpython-312.pyc", b"old handler cache")
        archive.writestr(patch.PREFIX + "__pycache__/repository.cpython-312.pyc", b"preserved repository cache")


@pytest.mark.parametrize("polling", [True, False])
def test_package_preserves_unrelated_live_files_and_custom_falco_settings(tmp_path, polling):
    original, updated = tmp_path / "old.zip", tmp_path / "new.zip"
    original_zip(original)
    patch.patch_package(original, updated, polling=polling)
    with zipfile.ZipFile(original) as old, zipfile.ZipFile(updated) as new:
        for name in ("unrelated.py", patch.PREFIX + "repository.py", patch.PREFIX + "__pycache__/repository.cpython-312.pyc"):
            assert old.read(name) == new.read(name)
        assert (patch.PREFIX + "bootstrap_status.py" in new.namelist()) == polling
        assert (patch.PREFIX + "__pycache__/handler.cpython-312.pyc" in new.namelist()) != polling
        if not polling:
            assert old.read(patch.PREFIX + "handler.py") == new.read(patch.PREFIX + "handler.py")
        values = yaml.safe_load(new.read(patch.PREFIX + "system_repo_template/values/falco.yaml"))
        assert values["image"]["tag"] == "0.45.1"
        assert values["resources"]["limits"]["memory"] == "999Mi"


def test_patch_refuses_unrecognized_or_already_changed_runtime_contracts():
    with pytest.raises(ValueError, match="already present"):
        patch.patch_runner((ROOT / "provisioning/runner/runner.py").read_text())
    with pytest.raises(ValueError, match="labels or taints"):
        patch.patch_module(historical("main.tf").replace('  tags = var.tags', '  labels = {}\n  tags = var.tags'), historical("variables.tf"))
    with pytest.raises(ValueError, match="Duplicate YAML"):
        yaml.load("driver: a\ndriver: b\n", Loader=patch.UniqueLoader)


def templates():
    root = {"Resources": {"ClusterManagement": {"Type": "AWS::CloudFormation::Stack", "Properties": {"TemplateURL": "old"}},
                          "Unrelated": {"Type": "AWS::S3::Bucket"}}}
    child = {"Resources": {name: {"Type": "AWS::Lambda::Function", "Properties": {"Code": {"S3Bucket": "old"}, "Role": "keep", "Environment": {"Variables": {"DB_NAME": "navigan"}}}} for name in release.FUNCTIONS}}
    child["Resources"]["TerraformProject"] = {"Type": "AWS::CodeBuild::Project", "Properties": {"Environment": {"Image": {"Ref": "TerraformRunnerImageUri"}}}}
    child["Resources"]["Role"] = {"Type": "AWS::IAM::Role", "Properties": {"RoleName": "keep"}}
    codes = {name: {"S3Bucket": "bucket", "S3Key": name, "S3ObjectVersion": "version"} for name in release.FUNCTIONS}
    saved = {"rootTemplate": root, "childTemplate": child,
             "root": {"StackId": "root", "Parameters": [{"ParameterKey": "TerraformRunnerImageUri", "ParameterValue": "old"}, {"ParameterKey": "DatabaseName", "ParameterValue": "navigan"}]}, "child": {"StackId": "child"}}
    new_root, new_child = release.proposed_templates(saved, codes, "new")
    return saved, new_root, new_child


@pytest.mark.parametrize("fault", ["role", "environment", "project", "root", "addition", "deletion", "unversioned"])
def test_template_validator_rejects_changes_outside_the_two_lambda_code_properties(fault):
    saved, root, child = templates()
    if fault == "role": child["Resources"]["Role"]["Properties"]["RoleName"] = "changed"
    elif fault == "environment": child["Resources"]["ClusterFunction"]["Properties"]["Environment"]["Variables"]["DB_NAME"] = "other"
    elif fault == "project": child["Resources"]["TerraformProject"]["Properties"]["Environment"]["Image"] = "other"
    elif fault == "root": root["Resources"]["Unrelated"]["Properties"] = {}
    elif fault == "addition": child["Resources"]["Other"] = {"Type": "AWS::S3::Bucket"}
    elif fault == "deletion": child["Resources"].pop("Role")
    else: child["Resources"]["ClusterFunction"]["Properties"]["Code"].pop("S3ObjectVersion")
    with pytest.raises(ValueError): release.validate_templates(saved, root, child)


def change_set():
    saved, root, child = templates()
    plan = {"changeSet": "release", "newImage": "new-image", "rootHash": release.fingerprint(root), "childHash": release.fingerprint(child)}
    client = MagicMock()
    root_change = {"ResourceChange": {"LogicalResourceId": "ClusterManagement", "ResourceType": "AWS::CloudFormation::Stack", "Action": "Modify", "Replacement": "False", "ChangeSetId": "nested"}}
    child_changes = [{"ResourceChange": {"LogicalResourceId": name, "ResourceType": "AWS::Lambda::Function" if name in release.FUNCTIONS else "AWS::CodeBuild::Project", "Action": "Modify", "Replacement": "False", "Details": [{"Target": {"Attribute": "Properties", "Name": "Code" if name in release.FUNCTIONS else "Environment"}}]}} for name in (*release.FUNCTIONS, "TerraformProject")]
    def describe(**kwargs):
        if kwargs["ChangeSetName"] == "release":
            return {"StackId": "root", "Status": "CREATE_COMPLETE", "ExecutionStatus": "AVAILABLE", "Parameters": [{"ParameterKey": "TerraformRunnerImageUri", "ParameterValue": "new-image"}, {"ParameterKey": "DatabaseName", "ParameterValue": "navigan"}], "Changes": [root_change]}
        return {"StackId": "child", "Changes": child_changes}
    client.describe_change_set.side_effect = describe
    client.get_template.side_effect = lambda **kw: {"TemplateBody": root if kw["ChangeSetName"] == "release" else child}
    return client, saved, plan, root_change, child_changes


def test_valid_scoped_change_set_can_be_reviewed_without_execution():
    client, saved, plan, _, _ = change_set()
    release.inspect_change_set(client, saved, plan)
    client.execute_change_set.assert_not_called()


@pytest.mark.parametrize("fault", ["replacement", "iam", "unrelated_property", "missing_project", "extra_root"])
def test_change_set_validator_refuses_unrelated_or_incomplete_changes(fault):
    client, saved, plan, root, changes = change_set()
    if fault == "replacement": changes[0]["ResourceChange"]["Replacement"] = "True"
    elif fault == "iam": changes.append({"ResourceChange": {"LogicalResourceId": "Role", "ResourceType": "AWS::IAM::Role", "Action": "Modify", "Replacement": "False"}})
    elif fault == "unrelated_property": changes[0]["ResourceChange"]["Details"][0]["Target"]["Name"] = "Role"
    elif fault == "missing_project": changes.pop()
    else: root["ResourceChange"]["LogicalResourceId"] = "Other"
    with pytest.raises(ValueError): release.inspect_change_set(client, saved, plan)
    client.execute_change_set.assert_not_called()


def test_runner_overlay_uses_pinned_base_and_only_three_changed_files(tmp_path, monkeypatch):
    capture = tmp_path / "capture"
    runner = capture / "runner"
    (runner / "aws-eks").mkdir(parents=True)
    (runner / "runner.py").write_text(historical("runner.py.txt"))
    for name in ("main.tf", "variables.tf", "outputs.tf"):
        (runner / "aws-eks" / name).write_text(historical(name))
    (runner / "aws-eks/versions.tf").write_text((ROOT / "terraform/modules/aws-eks/versions.tf").read_text())
    old = f"{release.ACCOUNT}.dkr.ecr.{release.REGION}.amazonaws.com/navigan-terraform-runner@sha256:" + "a" * 64
    directory = tmp_path / "release"
    directory.mkdir()
    def inspect(session, image, account, region, target):
        shutil.copytree(runner, target / "runner")
        if image != old:
            context = directory / "runner-build"
            shutil.copyfile(context / "runner.py", target / "runner/runner.py")
            for name in ("main.tf", "variables.tf"):
                shutil.copyfile(context / name, target / "runner/aws-eks" / name)
        return {"protectedPoolGuardPresent": image != old}
    monkeypatch.setattr(release.audit, "inspect_runner", inspect)
    calls = []
    monkeypatch.setattr(release.audit, "docker", lambda config, *args, **kw: calls.append(args))
    session, ecr = MagicMock(), MagicMock()
    session.client.return_value = ecr
    ecr.get_authorization_token.return_value = {"authorizationData": [{
        "proxyEndpoint": "https://" + old.split("/")[0],
        "authorizationToken": base64.b64encode(b"AWS:hidden").decode(),
    }]}
    ecr.describe_images.return_value = {"imageDetails": [{"imageDigest": "sha256:" + "b" * 64}]}
    pinned = release.runner_overlay(session, {"directory": capture, "image": old}, directory)
    assert pinned.endswith("@sha256:" + "b" * 64)
    dockerfile = (directory / "runner-build/Dockerfile").read_text()
    assert dockerfile.startswith("FROM " + old + "\n")
    assert dockerfile.count("COPY ") == 3
    assert "ENTRYPOINT" not in dockerfile and "USER navigan\n" in dockerfile
    assert {args[0] for args in calls} == {"login", "build", "push"}
    build = next(args for args in calls if args[0] == "build")
    assert build[build.index("--network") + 1] == "none"
    assert (directory / "overlay-verification/runner/aws-eks/outputs.tf").read_text() == historical("outputs.tf")


def captured_runtime(tmp_path):
    saved, root, child = templates()
    old_image = f"{release.ACCOUNT}.dkr.ecr.{release.REGION}.amazonaws.com/navigan-terraform-runner@sha256:" + "a" * 64
    root["Resources"]["ClusterManagement"]["Properties"]["Parameters"] = {"TerraformRunnerImageUri": {"Ref": "TerraformRunnerImageUri"}}
    saved["rootTemplate"] = root
    saved["childTemplate"] = child
    parent_id = f"arn:aws:cloudformation:{release.REGION}:{release.ACCOUNT}:stack/{release.PARENT}/root"
    child_id = f"arn:aws:cloudformation:{release.REGION}:{release.ACCOUNT}:stack/{release.PARENT}-ClusterManagement/child"
    for key, identifier in (("root", parent_id), ("child", child_id)):
        saved[key] = {"StackId": identifier, "StackStatus": "UPDATE_COMPLETE", "CreationTime": "2026-10-27 01:00:00+00:00",
                      "Parameters": [{"ParameterKey": "DatabaseName", "ParameterValue": "navigan"}, {"ParameterKey": "TerraformRunnerImageUri", "ParameterValue": old_image}]}
    saved["child"]["ParentId"] = parent_id
    saved["image"] = old_image
    saved["configs"] = {name: {"FunctionName": name, "CodeSha256": name + "-sha", "RevisionId": "revision", "Environment": {"Variables": {"DB_NAME": "navigan"}}} for name in release.FUNCTIONS}
    saved["project"] = {"name": "TerraformProject", "environment": {"image": old_image}, "serviceRole": "unchanged-role"}
    clients = {name: MagicMock() for name in ("sts", "cloudformation", "lambda", "codebuild")}
    session = MagicMock()
    session.client.side_effect = clients.__getitem__
    clients["sts"].get_caller_identity.return_value = {"Account": release.ACCOUNT}
    cfn = clients["cloudformation"]
    cfn.describe_stacks.side_effect = lambda **kw: {"Stacks": [deepcopy(saved["root"] if kw["StackName"] == release.PARENT else saved["child"])]}
    cfn.get_template.side_effect = lambda **kw: {"TemplateBody": deepcopy(root if kw["StackName"] == parent_id else child)}
    cfn.describe_stack_resource.side_effect = lambda **kw: {"StackResourceDetail": {"PhysicalResourceId": child_id if kw["LogicalResourceId"] == "ClusterManagement" else kw["LogicalResourceId"]}}
    clients["lambda"].get_function_configuration.side_effect = lambda **kw: {**deepcopy(saved["configs"][kw["FunctionName"]]), "State": "Active", "LastUpdateStatus": "Successful"}
    clients["codebuild"].batch_get_projects.return_value = {"projects": [deepcopy(saved["project"])]}
    return saved, session, clients


def test_preflight_reads_only_and_requires_live_bindings_and_configs_to_match_capture(tmp_path):
    saved, session, clients = captured_runtime(tmp_path)
    release.preflight(session, saved)
    allowed = {"get_caller_identity", "describe_stacks", "get_template", "describe_stack_resource", "get_function_configuration", "batch_get_projects"}
    for client in clients.values():
        assert {call[0] for call in client.method_calls} <= allowed


@pytest.mark.parametrize("fault", ["lambda_revision", "project_role", "stack_revision", "other_consumer"])
def test_preflight_rejects_stale_or_wider_runtime_scope(tmp_path, fault):
    saved, session, clients = captured_runtime(tmp_path)
    if fault == "lambda_revision":
        clients["lambda"].get_function_configuration.side_effect = lambda **kw: {**saved["configs"][kw["FunctionName"]], "State": "Active", "LastUpdateStatus": "Successful", "RevisionId": "changed"}
    elif fault == "project_role":
        clients["codebuild"].batch_get_projects.return_value["projects"][0]["serviceRole"] = "different-role"
    elif fault == "stack_revision":
        clients["cloudformation"].describe_stacks.side_effect = lambda **kw: {"Stacks": [{**saved["root"], "LastUpdatedTime": "changed"}]}
    else:
        saved["rootTemplate"]["Resources"]["OtherConsumer"] = {"Properties": {"Image": {"Ref": "TerraformRunnerImageUri"}}}
    with pytest.raises(ValueError): release.preflight(session, saved)
    clients["cloudformation"].execute_change_set.assert_not_called()


def test_execute_refuses_changed_runtime_before_cloudformation_execution(tmp_path, monkeypatch):
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"format": release.FORMAT, "account": release.ACCOUNT, "region": release.REGION, "parent": release.PARENT,
        "newImage": f"{release.ACCOUNT}.dkr.ecr.{release.REGION}.amazonaws.com/navigan-terraform-runner@sha256:" + "a" * 64,
        "baseline": str(tmp_path)}))
    monkeypatch.setattr(release, "baseline", lambda p: {})
    def changed(session, saved): raise ValueError("changed runtime")
    monkeypatch.setattr(release, "preflight", changed)
    session = MagicMock()
    with pytest.raises(ValueError, match="changed runtime"): release.execute(session, plan)
    session.client.assert_not_called()
