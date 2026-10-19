"""Exercise deployment guardrails without contacting AWS or Kubernetes."""

import base64
import importlib.util
import json
from pathlib import Path
import subprocess
import zlib

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / (name + ".py"))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def test_existing_connector_upgrade_preserves_registration_and_is_read_only(monkeypatch):
    upgrade = module("upgrade-source-connector-dev")
    calls = []

    def kubectl(args, input=None, **kwargs):
        calls.append((args, input))
        if "get" in args and "clusterrole" in args:
            return json.dumps(
                {
                    "apiVersion": "rbac.authorization.k8s.io/v1",
                    "kind": "ClusterRole",
                    "metadata": {"name": "navigan-source-connector"},
                    "rules": [
                        {"apiGroups": [""], "resources": ["services"], "verbs": ["list"]},
                        {"apiGroups": ["apps"], "resources": ["deployments"], "verbs": ["list"]},
                    ],
                }
            )
        if "exec" in args:
            return upgrade.SOURCE + "\n"
        return ""

    monkeypatch.setattr(subprocess, "check_output", kubectl)
    payload = {"__init__.py": "", "agent.py": "# updated agent", "deployment_evidence.py": "# metadata only"}
    script = (
        upgrade.REMOTE.replace(
            "__PAYLOAD__", base64.b64encode(zlib.compress(json.dumps(payload).encode())).decode()
        )
        .replace("__DIGEST__", "a" * 64)
        .replace("__DIGEST_SHORT__", "a" * 12)
    )
    exec(compile(script, "remote.py", "exec"), {})
    objects = [json.loads(data) for args, data in calls if data]
    role = next(o for o in objects if o["kind"] == "ClusterRole")
    assert all(r["verbs"] == ["list"] for r in role["rules"])
    assert "pods" in role["rules"][0]["resources"]
    assert "replicasets" in role["rules"][1]["resources"]
    config = next(o for o in objects if o["kind"] == "ConfigMap")
    assert config["data"] == payload
    patch = next(json.loads(args[args.index("-p") + 1]) for args, _ in calls if "patch" in args)
    pod = patch["spec"]["template"]["spec"]
    assert pod["containers"][0] == {
        "name": "connector",
        "volumeMounts": [{"name": "dev-runtime", "mountPath": "/app/migration_connector", "readOnly": True}],
    }
    assert "image" not in pod["containers"][0]
    assert "env" not in pod["containers"][0]
    assert not any("secret" in args for args, _ in calls)


def test_wrong_customer_registration_stops_before_any_kubernetes_write(monkeypatch):
    upgrade = module("upgrade-source-connector-dev")
    calls = []
    monkeypatch.setattr(subprocess, "check_output", lambda args, **kw: calls.append(args) or "SRC-other")
    script = upgrade.REMOTE.replace("__PAYLOAD__", base64.b64encode(zlib.compress(b"{}")).decode())
    with pytest.raises(SystemExit, match="approved DB Schenker"):
        exec(compile(script, "remote.py", "exec"), {})
    assert len(calls) == 1
    assert "exec" in calls[0]


def test_packaging_new_files_preserves_stack_lambda_names(monkeypatch, tmp_path):
    """New ZIP entries must never overwrite the AWS function identity."""
    import io
    import sys
    import zipfile

    deploy = module("deploy-source-connection-screen-dev")
    prefix = "navigan/modules/migration_management/"
    original = io.BytesIO()
    with zipfile.ZipFile(original, "w") as archive:
        for file_name in deploy.FILES:
            if file_name != "deployment_sources.py":
                archive.writestr(prefix + file_name, "# original deployed module\n")
    updates = []

    def configuration(function_name):
        return {
            "FunctionName": function_name,
            "FunctionArn": f"arn:aws:lambda:ap-south-1:{deploy.ACCOUNT}:function:{function_name}",
            "State": "Active",
            "LastUpdateStatus": "Successful",
            "RevisionId": "revision-" + function_name,
            "Environment": {"Variables": {"MIGRATION_SOURCE_FIRST_ENABLED": "true"}},
        }

    def check_output(command, **kwargs):
        if command[0] == "git":
            return "new_migration_approach_18oct26\n"
        parts = command[7:]
        if parts[:2] == ["sts", "get-caller-identity"]:
            result = {"Account": deploy.ACCOUNT}
        elif parts[:2] == ["cloudformation", "describe-stacks"]:
            result = {
                "Stacks": [
                    {
                        "Outputs": [
                            {
                                "OutputKey": "MigrationManagementStackId",
                                "OutputValue": f"arn:aws:cloudformation:ap-south-1:{deploy.ACCOUNT}:stack/dev-migration/test",
                            }
                        ]
                    }
                ]
            }
        elif parts[:2] == ["cloudformation", "describe-stack-resource"]:
            result = {"StackResourceDetail": {"PhysicalResourceId": "DEV-" + parts[-1]}}
        elif parts[:2] == ["lambda", "get-function"]:
            name = parts[parts.index("--function-name") + 1]
            result = {
                "Configuration": configuration(name),
                "Code": {"Location": "https://example.test/deployed.zip"},
            }
        elif parts[:2] == ["lambda", "update-function-code"]:
            name = parts[parts.index("--function-name") + 1]
            updates.append((name, parts[parts.index("--zip-file") + 1]))
            result = {}
        elif parts[:2] == ["lambda", "get-function-configuration"]:
            result = configuration(parts[parts.index("--function-name") + 1])
        elif parts[:2] == ["lambda", "update-function-configuration"]:
            result = {}
        else:
            raise AssertionError(f"Unexpected AWS operation: {parts}")
        return json.dumps(result)

    def check_call(command, **kwargs):
        if "download" in command:
            wheels = Path(command[command.index("--dest") + 1])
            with zipfile.ZipFile(wheels / "PyYAML-test.whl", "w") as wheel:
                wheel.writestr("yaml/__init__.py", "# test dependency\n")
        else:
            assert command[0] == "aws" and "wait" in command
        return 0

    monkeypatch.setattr(subprocess, "check_output", check_output)
    monkeypatch.setattr(subprocess, "check_call", check_call)
    monkeypatch.setattr(deploy.tempfile, "mkdtemp", lambda **kwargs: str(tmp_path))
    monkeypatch.setattr(
        deploy.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(original.getvalue())
    )
    monkeypatch.setattr(deploy, "configure_deployment_discovery", lambda *args: None)
    monkeypatch.setattr(sys, "argv", ["deploy-source-connection-screen-dev.py", "--apply"])
    deploy.main()
    assert [name for name, _ in updates] == ["DEV-MigrationConnectorFunction", "DEV-MigrationFunction"]
    for name, artifact in updates:
        with zipfile.ZipFile(artifact.removeprefix("fileb://")) as archive:
            assert prefix + "deployment_sources.py" in archive.namelist()
            if name == "DEV-MigrationFunction":
                assert "yaml/__init__.py" in archive.namelist()
                assert "navigan/modules/cluster_management/github_app.py" in archive.namelist()
