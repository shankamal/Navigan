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
