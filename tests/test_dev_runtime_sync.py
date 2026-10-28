from copy import deepcopy
import ast
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from botocore.handlers import json_decode_template_body

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("dev_runtime_sync", ROOT / "scripts/sync-dev-runtime.py")
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)


def fixture():
    resources = {
        "ClusterFunction": {
            "Type": "AWS::Lambda::Function",
            "Properties": {
                "Code": {"S3Bucket": "old", "S3Key": "old"},
                "Environment": {
                    "Variables": {
                        "DB_NAME": {"Ref": "DatabaseName"},
                        "PLATFORM_TOOLS_BASE_URL": {"Ref": "PlatformToolsBaseUrl"},
                    }
                },
            },
        },
        "StatusFunction": {
            "Type": "AWS::Lambda::Function",
            "Properties": {
                "Code": {"S3Bucket": "old", "S3Key": "old"},
                "Environment": {"Variables": {"DB_NAME": {"Ref": "DatabaseName"}}},
            },
        },
        "MigrationConnectorFunction": {
            "Type": "AWS::Lambda::Function",
            "Properties": {
                "Code": {"S3Bucket": "old", "S3Key": "old"},
                "Environment": {"Variables": {"DB_NAME": {"Ref": "DatabaseName"}}},
            },
        },
        "TerraformProject": {
            "Type": "AWS::CodeBuild::Project",
            "Properties": {"Environment": {"Image": {"Ref": "TerraformRunnerImageUri"}}},
        },
        "BuildStateRule": {
            "Type": "AWS::Events::Rule",
            "Properties": {"Targets": [{"Arn": {"Fn::GetAtt": ["StatusFunction", "Arn"]}}]},
        },
        "BuildStatePermission": {
            "Type": "AWS::Lambda::Permission",
            "Properties": {"SourceArn": {"Fn::GetAtt": ["BuildStateRule", "Arn"]}},
        },
    }
    params = {
        "DatabaseName": "navigan_dev",
        "PlatformToolsBaseUrl": "https://dev.example.test/tools",
        "TerraformRunnerImageUri": "old-image",
    }
    root = {
        "Parameters": {k: {"Type": "String"} for k in params},
        "Resources": {
            module: {
                "Type": "AWS::CloudFormation::Stack",
                "Properties": {
                    "TemplateURL": "https://old.example.test/template.json",
                    "Parameters": {k: {"Ref": k} for k in params},
                },
            }
            for module in ("ClusterManagement", "MigrationManagement")
        },
    }
    state = {"stacks": {}, "functions": {}}
    for key in ("root", "root/ClusterManagement", "root/MigrationManagement"):
        template = (
            root if key == "root" else {"Parameters": root["Parameters"], "Resources": deepcopy(resources)}
        )
        state["stacks"][key] = {
            "stack": {
                "StackId": "dev-id-" + key,
                "StackName": "dev-" + key.replace("/", "-"),
                "Parameters": [{"ParameterKey": k, "ParameterValue": v} for k, v in params.items()],
            },
            "processed": template,
            "resources": [{"LogicalResourceId": k, "PhysicalResourceId": "physical-" + k} for k in resources],
        }
    for module, logical in (
        ("ClusterManagement", "ClusterFunction"),
        ("ClusterManagement", "StatusFunction"),
        ("MigrationManagement", "MigrationConnectorFunction"),
    ):
        env = {"DB_NAME": "navigan_dev", "DEV_ONLY_ALLOWLIST": "keep-dev-allowlist"}
        if logical == "ClusterFunction":
            env["PLATFORM_TOOLS_BASE_URL"] = params["PlatformToolsBaseUrl"]
        state["functions"]["root/" + module + "/" + logical] = {
            "Environment": {"Variables": env},
            "CodeSha256": "old-hash",
        }
    prod = {
        p: {"Environment": {"Variables": {"DB_NAME": "navigan", "MIGRATION_SOURCE_FIRST_ENABLED": "true"}}}
        for p in state["functions"]
    }
    return state, prod


def candidate():
    state, prod = fixture()
    settings = h.expected_environment(state, prod)
    path = "root/ClusterManagement/StatusFunction"
    codes = {path: {"S3Bucket": "existing-dev", "S3Key": "immutable-code", "S3ObjectVersion": "v1"}}
    root, children = h.desired_templates(state, codes, settings)
    plan = {
        "newImage": "new-image",
        "codes": codes,
        "settings": settings,
        "expectedFunctions": sorted(set(codes) | set(settings)),
        "children": list(children),
        "templateHashes": {k: h.fingerprint(v) for k, v in children.items()},
        "previews": {"ClusterManagement": "preview"},
    }
    return state, plan, children, path


def test_promotes_only_verified_code_and_two_settings_preserving_dev_bindings():
    state, prod = fixture()
    original = deepcopy(state)
    settings = h.expected_environment(state, prod)
    codes = {
        "root/ClusterManagement/StatusFunction": {
            "S3Bucket": "dev-bucket",
            "S3Key": "digest",
            "S3ObjectVersion": "version",
        }
    }
    root, children = h.desired_templates(state, codes, settings)
    assert state == original
    assert root == state["stacks"]["root"]["processed"]
    env = children["ClusterManagement"]["Resources"]["StatusFunction"]["Properties"]["Environment"][
        "Variables"
    ]
    assert env == {
        "DB_NAME": {"Ref": "DatabaseName"},
        "DEV_ONLY_ALLOWLIST": "keep-dev-allowlist",
        "PLATFORM_TOOLS_BASE_URL": {"Ref": "PlatformToolsBaseUrl"},
    }
    migration = children["MigrationManagement"]["Resources"]["MigrationConnectorFunction"]["Properties"][
        "Environment"
    ]["Variables"]
    assert migration["MIGRATION_SOURCE_FIRST_ENABLED"] == "true"
    assert migration["DB_NAME"] == {"Ref": "DatabaseName"}
    assert '"DB_NAME":"navigan"' not in h.common.canonical(children).decode()


def test_guard_can_use_captured_prod_source_without_reading_branch_runner(monkeypatch, tmp_path):
    original = (ROOT / "tests/fixtures/bootstrap-runtime/runner.py.txt").read_text()
    desired = (ROOT / "provisioning/runner/runner.py").read_text()
    monkeypatch.setattr(h.patch, "ROOT", tmp_path / "nonexistent-source")
    changed = h.patch.patch_runner(original, desired=desired)
    assert "def system_node_findings" in changed
    assert "Approved plan does not provision a protected system node group" in changed


@pytest.mark.parametrize(
    "fault",
    [
        "missing_url",
        "credentials_url",
        "remote_http",
        "query",
        "conflicting_status",
        "flag_disabled",
        "prod_disabled",
    ],
)
def test_rejects_unknown_gateway_or_feature_configuration(fault):
    state, prod = fixture()
    cluster = state["functions"]["root/ClusterManagement/ClusterFunction"]["Environment"]["Variables"]
    if fault == "missing_url":
        cluster.pop("PLATFORM_TOOLS_BASE_URL")
    if fault == "credentials_url":
        cluster["PLATFORM_TOOLS_BASE_URL"] = "https://user:secret@dev.example.test/tools"
    if fault == "remote_http":
        cluster["PLATFORM_TOOLS_BASE_URL"] = "http://dev.example.test/tools"
    if fault == "query":
        cluster["PLATFORM_TOOLS_BASE_URL"] += "?token=private"
    if fault == "conflicting_status":
        state["functions"]["root/ClusterManagement/StatusFunction"]["Environment"]["Variables"][
            "PLATFORM_TOOLS_BASE_URL"
        ] = "https://other.example/tools"
    if fault == "flag_disabled":
        state["functions"]["root/MigrationManagement/MigrationConnectorFunction"]["Environment"]["Variables"][
            "MIGRATION_SOURCE_FIRST_ENABLED"
        ] = "false"
    if fault == "prod_disabled":
        prod["root/MigrationManagement/MigrationConnectorFunction"]["Environment"]["Variables"][
            "MIGRATION_SOURCE_FIRST_ENABLED"
        ] = "false"
    with pytest.raises(ValueError):
        h.expected_environment(state, prod)


def test_matching_settings_are_not_selected_again():
    state, prod = fixture()
    state["functions"]["root/ClusterManagement/StatusFunction"]["Environment"]["Variables"][
        "PLATFORM_TOOLS_BASE_URL"
    ] = "https://dev.example.test/tools"
    state["functions"]["root/MigrationManagement/MigrationConnectorFunction"]["Environment"]["Variables"][
        "MIGRATION_SOURCE_FIRST_ENABLED"
    ] = "true"
    assert h.expected_environment(state, prod) == {}


def test_environment_update_detects_drift_instead_of_dropping_private_dev_bindings():
    state, prod = fixture()
    state["functions"]["root/ClusterManagement/StatusFunction"]["Environment"]["Variables"]["DB_NAME"] = (
        "another-database"
    )
    with pytest.raises(ValueError, match="environment drift"):
        h.desired_templates(state, {}, h.expected_environment(state, prod))


def test_environment_intrinsics_preserve_api_and_kms_references():
    state, _ = fixture()
    record = state["stacks"]["root/ClusterManagement"]
    record["stack"]["Parameters"].append({"ParameterKey": "ApiId", "ParameterValue": "dev-api"})
    record["resources"].append({"LogicalResourceId": "Key", "PhysicalResourceId": "key-uuid"})
    record["processed"]["Resources"]["Key"] = {"Type": "AWS::KMS::Key"}
    assert (
        h.resolve_binding(
            {"Fn::Sub": "https://${ApiId}.execute-api.${AWS::Region}.${AWS::URLSuffix}/v1/api/v1"}, record
        )
        == "https://dev-api.execute-api.ap-south-1.amazonaws.com/v1/api/v1"
    )
    assert (
        h.resolve_binding({"Fn::GetAtt": ["Key", "Arn"]}, record)
        == "arn:aws:kms:ap-south-1:905418045935:key/key-uuid"
    )


def preview_fixture(monkeypatch):
    state, plan, children, path = candidate()
    module = "ClusterManagement"
    cfn = MagicMock()
    cfn.describe_change_set.return_value = {
        "StackId": state["stacks"]["root/" + module]["stack"]["StackId"],
        "IncludeNestedStacks": False,
        "Status": "CREATE_COMPLETE",
        "ExecutionStatus": "AVAILABLE",
        "Parameters": [
            {
                "ParameterKey": p["ParameterKey"],
                "ParameterValue": "new-image"
                if p["ParameterKey"] == "TerraformRunnerImageUri"
                else p["ParameterValue"],
            }
            for p in state["stacks"]["root/" + module]["stack"]["Parameters"]
        ],
    }
    cfn.get_template.return_value = {"TemplateBody": children[module]}
    rows = [
        {
            "ResourceChange": {
                "LogicalResourceId": "StatusFunction",
                "ResourceType": "AWS::Lambda::Function",
                "Action": "Modify",
                "Replacement": "False",
                "Details": [
                    {
                        "Target": {"Attribute": "Properties", "Name": name, "RequiresRecreation": "Never"},
                        "Evaluation": "Static",
                        "ChangeSource": "DirectModification",
                    }
                    for name in ("Code", "Environment")
                ],
            }
        }
    ]
    monkeypatch.setattr(h.common, "pages", lambda *a, **kw: deepcopy(rows))
    return state, plan, cfn, rows


def test_concrete_preview_accepts_only_intended_nonreplacing_update(monkeypatch):
    state, plan, cfn, _ = preview_fixture(monkeypatch)
    h.inspect_preview(cfn, state, plan, "ClusterManagement", "preview")
    assert not cfn.execute_change_set.called


@pytest.mark.parametrize(
    "fault",
    ["wrong_stack", "db_parameter", "template_change", "replacement", "delete", "role_change", "nested"],
)
def test_preview_blocks_unrelated_or_destructive_changes(monkeypatch, fault):
    state, plan, cfn, rows = preview_fixture(monkeypatch)
    if fault == "wrong_stack":
        cfn.describe_change_set.return_value["StackId"] = "prod-stack"
    if fault == "db_parameter":
        cfn.describe_change_set.return_value["Parameters"][0]["ParameterValue"] = "navigan"
    if fault == "template_change":
        cfn.get_template.return_value["TemplateBody"]["Resources"]["StatusFunction"]["Properties"]["Role"] = (
            "another-role"
        )
    if fault == "replacement":
        rows[0]["ResourceChange"]["Replacement"] = "True"
    if fault == "delete":
        rows[0]["ResourceChange"]["Action"] = "Remove"
    if fault == "role_change":
        rows[0]["ResourceChange"]["Details"][0]["Target"]["Name"] = "Role"
    if fault == "nested":
        cfn.describe_change_set.return_value["IncludeNestedStacks"] = True
    with pytest.raises(ValueError):
        h.inspect_preview(cfn, state, plan, "ClusterManagement", "preview")
    assert not cfn.execute_change_set.called


def test_stable_eventbridge_permission_dependency_is_proved_without_ignoring_actual_replacement(monkeypatch):
    state, plan, cfn, rows = preview_fixture(monkeypatch)
    for name, kind, producer, replacement in (
        ("BuildStateRule", "AWS::Events::Rule", "StatusFunction.Arn", "False"),
        ("BuildStatePermission", "AWS::Lambda::Permission", "BuildStateRule.Arn", "Conditional"),
    ):
        rows.append(
            {
                "ResourceChange": {
                    "LogicalResourceId": name,
                    "ResourceType": kind,
                    "Action": "Modify",
                    "Replacement": replacement,
                    "Details": [
                        {
                            "Target": {
                                "Attribute": "Properties",
                                "Name": "Targets" if name == "BuildStateRule" else "SourceArn",
                            },
                            "Evaluation": "Dynamic",
                            "ChangeSource": "ResourceAttribute",
                            "CausingEntity": producer,
                        }
                    ],
                }
            }
        )
    h.inspect_preview(cfn, state, plan, "ClusterManagement", "preview")
    rows[-1]["ResourceChange"]["Replacement"] = "True"
    with pytest.raises(ValueError):
        h.inspect_preview(cfn, state, plan, "ClusterManagement", "preview")


def test_upload_reuses_existing_content_addressed_storage(monkeypatch):
    session = MagicMock()
    put = MagicMock(return_value={"uri": "s3://existing-bucket/key", "versionId": "version"})
    monkeypatch.setattr(h.common, "put_content", put)
    item = h.upload(session, "existing-bucket", "api.zip", b"immutable-package")
    assert put.call_args.args[1] == "existing-bucket"
    assert put.call_args.args[2].startswith("dev-runtime-sync/" + h.common.sha(b"immutable-package"))
    assert h.artifact_code(item) == {
        "S3Bucket": "existing-bucket",
        "S3Key": "key",
        "S3ObjectVersion": "version",
    }
    assert "versionId=version" in h.artifact_url(item)


def test_no_runtime_write_after_preflight_rejection(tmp_path, monkeypatch):
    session = MagicMock()
    plan = {
        "format": h.FORMAT,
        "account": h.ACCOUNT,
        "region": h.REGION,
        "parent": h.DEV,
        "directory": str(tmp_path),
    }
    path = tmp_path / "release-plan.json"
    h.common.write(path, plan)
    monkeypatch.setattr(h, "verify_inputs", MagicMock(side_effect=ValueError("changed")))
    with pytest.raises(ValueError, match="changed"):
        h.execute(session, path)
    assert not session.client.called
    assert not (tmp_path / "execution.json").exists()


def test_cannot_execute_prod_plan(tmp_path):
    path = tmp_path / "release-plan.json"
    h.common.write(
        path,
        {
            "format": h.FORMAT,
            "account": h.ACCOUNT,
            "region": h.REGION,
            "parent": h.PROD,
            "directory": str(tmp_path),
        },
    )
    with pytest.raises(ValueError, match="Not a DEV"):
        h.read_plan(path)


def test_postdeploy_verifies_exact_code_dev_configuration_and_physical_identity(tmp_path, monkeypatch):
    state, plan, children, _ = candidate()
    state["apiId"] = "dev-api"
    state["roles"] = {"dev-role": {"policy": "preserved"}}
    for record in state["stacks"].values():
        record["resources"] = [dict(r, ResourceType="unchanged") for r in record["resources"]]
    plan.update(
        {
            "format": h.FORMAT,
            "account": h.ACCOUNT,
            "region": h.REGION,
            "parent": h.DEV,
            "directory": str(tmp_path),
            "project": "dev-project",
            "expectedCodeHashes": {"root/ClusterManagement/StatusFunction": "prod-status-package"},
        }
    )
    after = deepcopy(state)
    for module, template in children.items():
        after["stacks"]["root/" + module]["processed"] = template
    plan["templateHashes"]["root"] = h.fingerprint(state["stacks"]["root"]["processed"])
    for module in ("root", "root/ClusterManagement"):
        for param in after["stacks"][module]["stack"]["Parameters"]:
            if param["ParameterKey"] == "TerraformRunnerImageUri":
                param["ParameterValue"] = "new-image"
    for path in plan["expectedFunctions"]:
        for key, item in plan["settings"].get(path, {}).items():
            after["functions"][path]["Environment"]["Variables"][key] = item["value"]
        if path in plan["expectedCodeHashes"]:
            after["functions"][path]["CodeSha256"] = plan["expectedCodeHashes"][path]
    path = tmp_path / "release-plan.json"
    h.common.write(path, plan)
    h.common.write(tmp_path / "dev-state.json", state)
    h.common.write(tmp_path / "api-before.json", {"routes": ["keep-dev-upgrade-route"]})
    h.common.write(
        tmp_path / "project-before.json", {"name": "dev-project", "environment": {"image": "old-image"}}
    )
    monkeypatch.setattr(h.target, "snapshot", lambda *a: after)
    monkeypatch.setattr(h, "api_snapshot", lambda *a: {"routes": ["keep-dev-upgrade-route"]})
    session = MagicMock()
    session.client.return_value.batch_get_projects.return_value = {
        "projects": [{"name": "dev-project", "environment": {"image": "new-image"}}]
    }
    h.verify(session, path)
    assert h.common.read(tmp_path / "verification.json")["authenticatedWorkflowAcceptance"] == "PENDING"
    after["functions"]["root/ClusterManagement/StatusFunction"]["Environment"]["Variables"][
        "DEV_ONLY_ALLOWLIST"
    ] = "lost"
    with pytest.raises(ValueError, match="config verification failed"):
        h.verify(session, path)


def test_capture_cannot_substitute_another_environment(tmp_path):
    h.common.write(
        tmp_path / "summary.json",
        {"environment": "prod", "account": h.ACCOUNT, "region": h.REGION, "stackName": h.PROD},
    )
    with pytest.raises(ValueError, match="another target"):
        h.captured(tmp_path, "dev")


@pytest.mark.parametrize(
    "expression",
    [
        '[{**group, "purpose": group.get("purpose", "SYSTEM" if index == 0 else "APPLICATION")} '
        'for index, group in enumerate(request["configuration"]["nodeGroups"])]',
        '[{**group, "purpose": group["purpose"], "customSetting": "keep"} '
        'for group in request["configuration"]["nodeGroups"] if group.get("managementMode") != "ADOPTED"]',
        'normalize_node_groups(request["configuration"]["nodeGroups"])',
    ],
)
def test_existing_node_group_transforms_are_preserved_and_plan_guard_is_added(expression):
    raw = (ROOT / "tests/fixtures/bootstrap-runtime/runner.py.txt").read_text()
    original = raw.replace(
        '"node_groups": request["configuration"]["nodeGroups"],', '"node_groups": ' + expression + ",", 1
    )
    assert original != raw
    updated = h.patch.patch_runner(original)

    def groups(source):
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value == "node_groups":
                        return value
        raise AssertionError("node_groups missing")

    assert h.patch.same(groups(original), groups(updated))
    assert '"node_groups": ' + expression + "," in updated
    namespace = {"json": json}
    functions = ast.Module(
        body=[n for n in ast.parse(updated).body if isinstance(n, ast.FunctionDef)], type_ignores=[]
    )
    exec(compile(functions, "runner.py", "exec"), namespace)
    request = {
        "configuration": {
            "endpointAccess": "PRIVATE",
            "nodeGroups": [{"name": "system", "purpose": "SYSTEM"}],
        }
    }
    # Keeping a normalization expression does not bypass the actual plan check.
    assert namespace["security_scan"]({"resource_changes": []}, request)["status"] == "FAILED"
    assert "if system_node_findings(shown, request):" in updated


def test_local_runner_preflight_failure_stops_before_cloud_access_or_staging(tmp_path, monkeypatch):
    session = MagicMock()
    args = SimpleNamespace(dev_capture=tmp_path / "dev", prod_capture=tmp_path / "prod")
    monkeypatch.setattr(h, "captured", lambda *a: {})
    monkeypatch.setattr(h, "runner_sources", MagicMock(side_effect=h.common.ReleaseError("runner contract")))
    workspace = MagicMock()
    monkeypatch.setattr(h.common, "workspace", workspace)
    with pytest.raises(ValueError, match="runner contract"):
        h.prepare(session, args)
    session.client.assert_not_called()
    workspace.assert_not_called()


def test_known_validation_messages_are_visible_but_private_errors_stay_redacted():
    for check in (h.patch.require, h.audit.require):
        try:
            check(False, "Known static contract check failed.")
        except ValueError as error:
            assert h.failure_reason(error) == "Known static contract check failed."
    assert h.failure_reason(ValueError("private runtime value")) == "ValueError"
    assert (
        h.failure_reason(h.common.ReleaseError("Reviewed release check failed."))
        == "Reviewed release check failed."
    )


def sdk_template(value, *, sort_keys):
    # Exercise the real GetTemplate response hook rather than ordinary dicts.
    response = {"TemplateBody": json.dumps(value, sort_keys=sort_keys)}
    json_decode_template_body(response)
    return response["TemplateBody"]


def ordered_dependency_fixture(monkeypatch):
    state, plan, cfn, rows = preview_fixture(monkeypatch)
    key = "root/ClusterManagement"
    before = state["stacks"][key]["processed"]
    after = cfn.get_template.return_value["TemplateBody"]
    for template in (before, after):
        template["Resources"]["BuildStateRule"]["Metadata"] = {"SamResourceId": "BuildStateRule"}
        template["Resources"]["BuildStateRule"]["Properties"]["Targets"] = [
            {"Id": "first", "Arn": {"Fn::GetAtt": ["StatusFunction", "Arn"]}},
            {"Id": "second", "Arn": {"Fn::GetAtt": ["StatusFunction", "Arn"]}},
        ]
    state["stacks"][key]["processed"] = sdk_template(before, sort_keys=False)
    cfn.get_template.return_value["TemplateBody"] = sdk_template(after, sort_keys=True)
    plan["templateHashes"]["ClusterManagement"] = h.fingerprint(after)
    rows.append(
        {
            "ResourceChange": {
                "LogicalResourceId": "BuildStateRule",
                "ResourceType": "AWS::Events::Rule",
                "Action": "Modify",
                "Replacement": "False",
                "Details": [
                    {
                        "Target": {
                            "Attribute": "Properties",
                            "Name": "Targets",
                            "RequiresRecreation": "Never",
                        },
                        "Evaluation": "Dynamic",
                        "ChangeSource": "ResourceAttribute",
                        "CausingEntity": "StatusFunction.Arn",
                    }
                ],
            }
        }
    )
    return state, plan, cfn


def test_sdk_ordered_templates_do_not_turn_key_sorting_into_a_dependency_change(monkeypatch):
    state, plan, cfn = ordered_dependency_fixture(monkeypatch)
    before = state["stacks"]["root/ClusterManagement"]["processed"]["Resources"]["BuildStateRule"]
    after = cfn.get_template.return_value["TemplateBody"]["Resources"]["BuildStateRule"]
    assert before != after  # Real SDK OrderedDict equality sees only key reordering.
    assert h.fingerprint(before) == h.fingerprint(after)
    h.inspect_preview(cfn, state, plan, "ClusterManagement", "preview")
    cfn.execute_change_set.assert_not_called()


@pytest.mark.parametrize("fault", ["binding", "list_order", "metadata", "type"])
def test_order_independent_comparison_still_rejects_real_dependency_changes(monkeypatch, fault):
    state, plan, cfn = ordered_dependency_fixture(monkeypatch)
    after = cfn.get_template.return_value["TemplateBody"]
    resource = after["Resources"]["BuildStateRule"]
    if fault == "binding":
        resource["Properties"]["Targets"][0]["Arn"] = {"Fn::GetAtt": ["ClusterFunction", "Arn"]}
    elif fault == "list_order":
        resource["Properties"]["Targets"].reverse()
    elif fault == "metadata":
        resource["Metadata"]["SamResourceId"] = "changed"
    else:
        resource["Type"] = "AWS::IAM::Role"
    plan["templateHashes"]["ClusterManagement"] = h.fingerprint(after)
    with pytest.raises(ValueError, match="Dependency resource definition changed"):
        h.inspect_preview(cfn, state, plan, "ClusterManagement", "preview")
    cfn.execute_change_set.assert_not_called()
