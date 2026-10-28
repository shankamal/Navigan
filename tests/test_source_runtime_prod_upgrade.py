import copy
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("source_runtime_prod", ROOT / "scripts/upgrade-source-runtime-prod.py")
upgrade = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upgrade)
SOURCE = "SRC-" + "a" * 32
API = "https://production.example/v1/api/v1"


def runtime():
    return {name: (ROOT / "migration_connector" / name).read_text() for name in upgrade.RUNTIME}


def execute_remote(monkeypatch, tmp_path, source=SOURCE, fail_rollout=False):
    script, digest = upgrade.make_script(SOURCE, API, runtime())
    script = script.replace('pathlib.Path("/var/lib/navigan/source-runtime-backups")', 'pathlib.Path(' + repr(str(tmp_path)) + ')')
    original = {"metadata": {"resourceVersion": "1"}, "spec": {"replicas": 1, "template": {"metadata": {"annotations": {}}, "spec": {
        "serviceAccountName": "registered-source", "volumes": [{"name": "credentials", "secret": {"secretName": "existing"}}],
        "containers": [{"name": "connector", "image": "original@sha256:digest", "env": [{"name": "CREDENTIAL", "valueFrom": {"secretKeyRef": {"name": "existing", "key": "token"}}}],
            "securityContext": {"readOnlyRootFilesystem": True}, "volumeMounts": [{"name": "credentials", "mountPath": "/credentials"}]}]}}}}
    current = copy.deepcopy(original)
    calls = []
    configs = []
    patches = []

    def run(command, **kwargs):
        calls.append(command)
        stdout = ""
        if "exec" in command:
            assert "deployment/navigan-source-" + "a" * 32 in command
            if "fetch_assignment" in command[-1]:
                stdout = json.dumps({"source": source, "api": API})
            else:
                assert "collect_runtime" in command[-1]
        elif "get" in command:
            stdout = json.dumps(current)
        elif "can-i" in command:
            stdout = "yes"
        elif "apply" in command:
            configs.append(json.loads(kwargs["input"]))
        elif "patch" in command:
            patch = json.loads(command[-1])
            patches.append(patch)
            if "--type=strategic" in command:
                current["spec"]["template"]["metadata"]["annotations"]["navigan.io/prod-source-runtime"] = digest
                current["metadata"]["resourceVersion"] = "2"
            else:
                assert "--type=merge" in command
                current["spec"] = copy.deepcopy(patch["spec"])
        elif "rollout" in command:
            if fail_rollout:
                return SimpleNamespace(returncode=1, stdout="", stderr="rollout failed")
        else:
            raise AssertionError(command)
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(upgrade.subprocess, "run", run)
    if source != SOURCE or fail_rollout:
        with pytest.raises((AssertionError, RuntimeError)):
            exec(compile(script, "upgrade.py", "exec"), {})
    else:
        exec(compile(script, "upgrade.py", "exec"), {})
    return original, current, calls, configs, patches


def test_upgrade_changes_only_named_deployment_runtime_and_immutable_source_config(monkeypatch, tmp_path):
    original, current, calls, configs, patches = execute_remote(monkeypatch, tmp_path)
    assert len(configs) == 1 and configs[0]["kind"] == "ConfigMap" and configs[0]["immutable"] is True
    assert set(configs[0]["data"]) == set(upgrade.RUNTIME)
    assert len(patches) == 1
    patch = patches[0]
    assert patch["metadata"]["resourceVersion"] == "1"
    container_patch = patch["spec"]["template"]["spec"]["containers"][0]
    assert set(container_patch) == {"name", "volumeMounts"}
    assert container_patch["volumeMounts"][0]["readOnly"] is True
    assert current["spec"]["template"]["spec"]["containers"] == original["spec"]["template"]["spec"]["containers"]
    assert not any("delete" in command or "secret" in command or "clusterrole" in command for command in calls)
    backups = list(tmp_path.glob("*/deployment-original.json"))
    assert len(backups) == 1 and json.loads(backups[0].read_text()) == original
    assert backups[0].stat().st_mode & 0o777 == 0o600


def test_wrong_customer_source_identity_stops_before_mutation(monkeypatch, tmp_path):
    _, _, calls, configs, patches = execute_remote(monkeypatch, tmp_path, source="SRC-" + "b" * 32)
    assert len(calls) == 1
    assert configs == patches == []
    assert list(tmp_path.iterdir()) == []


def test_rollout_failure_restores_original_spec_with_revision_guard(monkeypatch, tmp_path):
    original, current, _, _, patches = execute_remote(monkeypatch, tmp_path, fail_rollout=True)
    assert len(patches) == 2
    assert patches[-1] == {"metadata": {"resourceVersion": "2"}, "spec": original["spec"]}
    assert current["spec"] == original["spec"]


def test_invalid_source_or_incomplete_runtime_rejected():
    with pytest.raises(ValueError):
        upgrade.make_script("SRC-wrong", API, runtime())
    with pytest.raises(ValueError):
        upgrade.make_script(SOURCE, API, {"agent.py": "old runtime"})


def test_api_contract_must_match_before_agent_upgrade():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as package:
        for name in ("models.py", "deployment_sources.py"):
            path = "navigan/modules/migration_management/" + name
            package.writestr(path, (ROOT / "src" / path).read_bytes())
    upgrade.check_contract(stream.getvalue())
    bad = io.BytesIO()
    with zipfile.ZipFile(bad, "w") as package:
        package.writestr("navigan/modules/migration_management/models.py", b"old schema")
    with pytest.raises(RuntimeError, match="contract"):
        upgrade.check_contract(bad.getvalue())
