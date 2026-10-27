import base64
import hashlib
import importlib.util
import io
from pathlib import Path
import shutil
from types import SimpleNamespace
from unittest.mock import MagicMock
import zipfile

import pytest


ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("bootstrap_audit", ROOT / "scripts/audit-cluster-bootstrap-runtime.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def package():
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as archive:
        for path in ("handler.py", "repository.py", "connector_installation.py", "bootstrap_status.py",
                     "system_repo_template/applications/20-falco.yaml", "system_repo_template/values/falco.yaml"):
            archive.write(ROOT / "src" / audit.MODULE / path, audit.MODULE + path)
        archive.writestr("unrelated.txt", "private unrelated package contents")
    return raw.getvalue()


def test_summary_reports_packaged_defaults_and_failure_poll_without_package_contents():
    result = audit.inspect_package(package())
    assert result["falco"] == {
        "chart": "9.2.0", "imageTag": "0.45.1", "protectedNodeSelector": "true",
        "containerPlugin": "ghcr.io/falcosecurity/plugins/plugin/container:0.7.5",
    }
    assert result["failurePollingModule"] and result["failurePollingCall"]
    assert result["installerStatusReader"]
    assert all(result["repositoryMethodsAvailable"].values())
    assert "private unrelated" not in str(result)


def test_capture_refuses_wrong_account_before_reading_any_stack(tmp_path):
    session = MagicMock()
    session.client.return_value.get_caller_identity.return_value = {"Account": "wrong"}
    with pytest.raises(ValueError, match="AWS account"):
        audit.capture(session, SimpleNamespace(expected_account="123456789012"), tmp_path)
    assert session.client.call_count == 1


def test_capture_is_read_only_and_keeps_environment_out_of_shareable_summary(tmp_path, monkeypatch):
    account, region = "123456789012", "ap-south-1"
    parent_id = f"arn:aws:cloudformation:{region}:{account}:stack/platform/root"
    child_id = f"arn:aws:cloudformation:{region}:{account}:stack/platform-ClusterManagement/child"
    clients = {key: MagicMock() for key in ("sts", "cloudformation", "lambda", "codebuild")}
    session = MagicMock()
    session.client.side_effect = clients.__getitem__
    clients["sts"].get_caller_identity.return_value = {"Account": account}
    cfn = clients["cloudformation"]
    cfn.describe_stacks.side_effect = lambda **kw: {"Stacks": [{
        "StackId": child_id if kw["StackName"] == child_id else parent_id,
        "StackStatus": "UPDATE_COMPLETE",
        "Parameters": [{"ParameterKey": "DatabaseName", "ParameterValue": "navigan"}],
        **({"ParentId": parent_id} if kw["StackName"] == child_id else {}),
    }]}
    cfn.get_template.return_value = {"TemplateBody": {"Resources": {}}}
    cfn.describe_stack_resource.side_effect = lambda **kw: {"StackResourceDetail": {
        "PhysicalResourceId": child_id if kw["LogicalResourceId"] == "ClusterManagement" else kw["LogicalResourceId"]}}
    raw = package()
    clients["lambda"].get_function.side_effect = lambda **kw: {
        "Configuration": {"FunctionArn": f"arn:aws:lambda:{region}:{account}:function:{kw['FunctionName']}",
                          "Runtime": "python3.12", "PackageType": "Zip", "State": "Active",
                          "LastUpdateStatus": "Successful", "RevisionId": "revision",
                          "CodeSha256": base64.b64encode(hashlib.sha256(raw).digest()).decode(),
                          "Environment": {"Variables": {"DB_NAME": "navigan", "SECRET": "do-not-share"}}},
        "Code": {"Location": "https://private-package.example.test"},
    }
    clients["codebuild"].batch_get_projects.return_value = {"projects": [{
        "arn": f"arn:aws:codebuild:{region}:{account}:project/TerraformProject",
        "environment": {"image": "deployed-runner:tag", "environmentVariables": [{"value": "private"}]},
    }]}
    monkeypatch.setattr(audit.urllib.request, "urlopen", lambda *a, **kw: io.BytesIO(raw))
    args = SimpleNamespace(expected_account=account, region=region, stack_name="platform",
                           expected_database="navigan", environment="prod", inspect_runner=False)
    summary = audit.capture(session, args, tmp_path)
    assert summary["runnerInspection"] == "Not requested"
    assert summary["terraformProject"]["image"] == "deployed-runner:tag"
    assert "do-not-share" not in str(summary)
    assert "private-package" not in str(summary)
    allowed = {"get_caller_identity", "describe_stacks", "get_template", "describe_stack_resource",
               "get_function", "batch_get_projects"}
    for client in clients.values():
        assert {call[0] for call in client.method_calls} <= allowed
    assert (tmp_path / "ClusterFunction-config.json").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("fault", ["parent", "region", "account", "updating"])
def test_stack_target_and_stability_are_required(fault):
    stack = {"StackId": "arn:aws:cloudformation:ap-south-1:123456789012:stack/a/id",
             "StackStatus": "UPDATE_COMPLETE", "ParentId": "parent"}
    if fault == "parent":
        stack["ParentId"] = "other"
    elif fault == "updating":
        stack["StackStatus"] = "UPDATE_IN_PROGRESS"
    else:
        stack["StackId"] = stack["StackId"].replace("ap-south-1" if fault == "region" else "123456789012", "wrong")
    with pytest.raises(ValueError):
        audit.validate_stack(stack, "123456789012", "ap-south-1", "parent")


def test_runner_inspection_must_be_requested_and_preserves_hcl_string_values():
    args = audit.parser().parse_args(["--environment", "prod", "--stack-name", "platform",
                                      "--expected-database", "navigan"])
    assert not args.inspect_runner
    assert audit.hcl_tokens('x = "two words"') == audit.hcl_tokens('x="two words"')
    assert audit.hcl_tokens('x = "two words"') != audit.hcl_tokens('x = "twowords"')


def test_runner_inspection_pins_digest_and_never_starts_the_container(tmp_path, monkeypatch):
    account, region = "123456789012", "ap-south-1"
    registry = f"{account}.dkr.ecr.{region}.amazonaws.com"
    digest = "sha256:" + "a" * 64
    session, ecr = MagicMock(), MagicMock()
    session.client.return_value = ecr
    ecr.describe_images.return_value = {"imageDetails": [{"imageDigest": digest}]}
    ecr.get_authorization_token.return_value = {"authorizationData": [{
        "proxyEndpoint": "https://" + registry,
        "authorizationToken": base64.b64encode(b"AWS:private-password").decode(),
    }]}
    calls = []
    def docker(config, *args, payload=None):
        calls.append(args)
        if args[0] == "create":
            assert args[1:3] == ("--network", "none")
            return "b" * 64
        if args[0] == "cp":
            if args[1].endswith(":/app/runner.py"):
                shutil.copyfile(ROOT / "provisioning/runner/runner.py", args[2])
            else:
                shutil.copytree(ROOT / "terraform/modules/aws-eks", args[2])
        return ""
    monkeypatch.setattr(audit, "docker", docker)
    result = audit.inspect_runner(session, registry + "/runner:mutable-tag", account, region, tmp_path)
    assert result["resolvedImage"] == registry + "/runner@" + digest
    assert result["runnerMatchesSource"] and result["protectedPoolGuardPresent"]
    assert all(result["terraformFilesMatchSource"].values())
    assert {args[0] for args in calls} == {"login", "pull", "create", "cp", "rm"}
    assert calls[-1] == ("rm", "b" * 64)
    assert all("mutable-tag" not in " ".join(args) for args in calls)
    assert "private-password" not in str(result)


def test_runner_inspection_rejects_another_registry_before_authentication(tmp_path):
    session = MagicMock()
    with pytest.raises(ValueError, match="target account"):
        audit.inspect_runner(session, "999999999999.dkr.ecr.ap-south-1.amazonaws.com/runner:tag",
                             "123456789012", "ap-south-1", tmp_path)
    session.client.assert_not_called()
