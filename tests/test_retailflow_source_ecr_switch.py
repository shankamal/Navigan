import base64
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runtime = load("retailflow_source_ecr_runtime")
cli = load("use-retailflow-ecr-source-dev")
DIGEST = "sha256:" + "a" * 64
TARGET = cli.REGISTRY + "/retailflow/docker.io/library/python@" + DIGEST
MAPPING = {
    "docker.io/library/python:3.12-alpine": TARGET,
    "docker.io/library/busybox:1.37": cli.REGISTRY + "/retailflow/docker.io/library/busybox@" + DIGEST,
    "docker.io/curlimages/curl:8.16.0": cli.REGISTRY + "/retailflow/docker.io/curlimages/curl@" + DIGEST,
}


def resource(name="retailflow-api", kind="Deployment"):
    template = {
        "metadata": {"labels": {"app": name}},
        "spec": {
            "containers": [
                {
                    "name": "api",
                    "image": "python:3.12-alpine",
                    "env": [{"name": "DO_NOT_EXPORT", "value": "private-value"}],
                }
            ],
            "initContainers": [{"name": "init", "image": "busybox:1.37"}],
            "imagePullSecrets": [{"name": "existing-secret"}],
        },
    }
    spec = {"template": template}
    if kind == "CronJob":
        spec = {"jobTemplate": {"spec": {"template": template}}, "schedule": "*/5 * * * *"}
    return {
        "apiVersion": "batch/v1" if kind == "CronJob" else "apps/v1",
        "kind": kind,
        "metadata": {"name": name, "namespace": "retailflow", "resourceVersion": "5"},
        "spec": spec,
    }


def report():
    return {
        "accountId": cli.ACCOUNT,
        "region": cli.REGION,
        "sourceNamespace": "retailflow",
        "registry": cli.REGISTRY,
        "images": [
            {
                "source": "docker.io/library/python:3.12-alpine",
                "destinationDigestReference": TARGET,
                "platform": "linux/amd64",
                "status": "AVAILABLE",
            }
        ],
    }


def test_regular_and_init_images_are_patched_without_config_or_storage_changes():
    original = resource()
    patch = runtime.image_patch(original, MAPPING)
    pod = patch["spec"]["template"]["spec"]
    assert pod["containers"] == [{"name": "api", "image": TARGET}]
    assert pod["initContainers"][0]["image"].startswith(cli.REGISTRY)
    assert pod["imagePullSecrets"] == [{"name": runtime.PULL_SECRET}]
    assert "private-value" not in json.dumps(patch)
    assert "existing-secret" in json.dumps(original)  # preserved by strategic name-keyed list merge
    assert original["spec"]["template"]["spec"]["containers"][0]["image"] == "python:3.12-alpine"
    assert "volumes" not in pod and "volumeClaimTemplates" not in patch["spec"]


def test_cronjobs_update_future_templates_without_replaying_historical_jobs():
    objects = [
        resource(),
        resource("retailflow-frontend"),
        resource("periodic", "CronJob"),
        {"kind": "Job", "metadata": {"namespace": "retailflow", "name": "historical"}},
    ]
    changes = runtime.plan(objects, MAPPING)
    assert len(changes) == 3
    cron = next(c for c in changes if c["kind"] == "CronJob")
    assert (
        cron["patch"]["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]["image"] == TARGET
    )
    assert all(c["kind"] != "Job" for c in changes)


@pytest.mark.parametrize("change", ["namespace", "unmapped", "paused", "ondelete"])
def test_preflight_rejects_unapproved_or_nonrolling_changes(change):
    item = resource()
    if change == "namespace":
        item["metadata"]["namespace"] = "other-customer"
    elif change == "unmapped":
        item["spec"]["template"]["spec"]["containers"][0]["image"] = "unknown/private:v1"
    elif change == "paused":
        item["spec"]["paused"] = True
    else:
        item["kind"] = "StatefulSet"
        item["spec"]["updateStrategy"] = {"type": "OnDelete"}
    with pytest.raises(ValueError):
        runtime.image_patch(item, MAPPING)


def test_failed_rollout_restores_prior_images_and_removes_new_secret_reference():
    old = resource()
    old["spec"]["template"]["spec"].pop("imagePullSecrets")
    changes = runtime.plan([old, resource("retailflow-frontend")], MAPPING)
    originals = {(r["kind"], r["metadata"]["name"]): r for r in [old, resource("retailflow-frontend")]}
    calls = []

    def mutate(change, patch, mode):
        calls.append((change, patch, mode))

    def fail(change):
        raise RuntimeError("rollout failure")

    with pytest.raises(RuntimeError, match="previous controller templates were restored"):
        runtime.apply_changes(changes, originals, mutate, fail, lambda: None)
    assert [mode for _, _, mode in calls] == ["strategic", "merge"]
    restored = calls[-1][1]["spec"]["template"]["spec"]
    assert restored["containers"][0]["image"] == "python:3.12-alpine"
    assert restored["imagePullSecrets"] is None


def test_failed_rollback_does_not_claim_success():
    old = resource()
    changes = runtime.plan([old, resource("retailflow-frontend")], MAPPING)
    originals = {("Deployment", r["metadata"]["name"]): r for r in [old, resource("retailflow-frontend")]}

    def mutate(change, patch, mode):
        if mode == "merge":
            raise RuntimeError("conflict")

    with pytest.raises(RuntimeError, match="rollback needs review"):
        runtime.apply_changes(
            changes,
            originals,
            mutate,
            lambda _: (_ for _ in ()).throw(RuntimeError("rollout failed")),
            lambda: None,
        )


def test_refresh_keeps_token_out_of_argv_and_uses_namespace_secret(monkeypatch):
    commands = []
    secret_writes = []

    def command(args, **kwargs):
        commands.append(args)
        return json.dumps({"Account": cli.ACCOUNT}) if "get-caller-identity" in args else "secret-token\n"

    monkeypatch.setattr(runtime, "command", command)
    monkeypatch.setattr(runtime, "kubectl", lambda *a, **k: secret_writes.append((a, k)))
    runtime.refresh_credentials()
    assert "secret-token" not in json.dumps(commands)
    secret = secret_writes[0][1]["payload"]
    assert secret["metadata"] == {"name": runtime.PULL_SECRET, "namespace": "retailflow"}
    assert secret_writes[0][1]["sensitive"] is True
    encoded = secret["data"][".dockerconfigjson"]
    assert json.loads(base64.b64decode(encoded))["auths"][cli.REGISTRY]["password"] == "secret-token"


def test_report_is_bound_to_source_account_and_digest():
    assert cli.validate_report(report())["docker.io/library/python:3.12-alpine"] == TARGET
    invalid = report()
    invalid["accountId"] = "999999999999"
    with pytest.raises(ValueError):
        cli.validate_report(invalid)
    invalid = report()
    invalid["images"][0]["destinationDigestReference"] = "other.ecr.example/target@" + DIGEST
    with pytest.raises(ValueError):
        cli.validate_report(invalid)


def test_credential_refresh_is_installed_before_workload_changes(monkeypatch, tmp_path):
    events = []
    resources = [resource(), resource("retailflow-frontend")]

    def kubectl(*args, **kwargs):
        assert args[0] == "get"
        if args[1] == "nodes":
            return json.dumps(
                {
                    "items": [
                        {
                            "status": {
                                "nodeInfo": {"architecture": "amd64"},
                                "conditions": [{"type": "Ready", "status": "True"}],
                            }
                        }
                    ]
                }
            )
        return json.dumps({"items": resources})

    monkeypatch.setattr(runtime, "kubectl", kubectl)
    monkeypatch.setattr(runtime, "DIRECTORY", tmp_path)
    monkeypatch.setattr(runtime, "install_refresh", lambda _: events.append("refresh-installed"))
    monkeypatch.setattr(runtime, "health_check", lambda _: events.append("health"))
    monkeypatch.setattr(runtime, "apply_changes", lambda *args: events.append("controller-update"))
    result = runtime.execute(MAPPING, apply=True, runtime_source="# code")
    assert events == ["refresh-installed", "health", "controller-update"]
    assert result["status"] == "VERIFIED"
    assert Path(result["backupDirectory"], "controllers.json").stat().st_mode & 0o777 == 0o600


def test_cli_reads_existing_mapping_and_limits_iam_policy_to_source_images(monkeypatch, tmp_path):
    path = tmp_path / "retailflow-ecr-images.json"
    path.write_text(json.dumps(report()))
    aws_calls = []
    writes = []

    def run(args):
        if args[0] == "git":
            return "new_migration_approach_18oct26"
        operation = args[7:]
        aws_calls.append(operation)
        if operation[:2] == ["sts", "get-caller-identity"]:
            return json.dumps({"Account": cli.ACCOUNT})
        if operation[:2] == ["ecr", "describe-images"]:
            return json.dumps({"imageDetails": [{"imageDigest": DIGEST}]})
        if operation[:2] == ["ec2", "describe-instances"]:
            return json.dumps(
                {
                    "Reservations": [
                        {
                            "Instances": [
                                {
                                    "InstanceId": cli.INSTANCE,
                                    "State": {"Name": "running"},
                                    "IamInstanceProfile": {
                                        "Arn": f"arn:aws:iam::{cli.ACCOUNT}:instance-profile/source-profile"
                                    },
                                }
                            ]
                        }
                    ]
                }
            )
        if operation[:2] == ["iam", "get-instance-profile"]:
            return json.dumps(
                {
                    "InstanceProfile": {
                        "Roles": [
                            {"Arn": f"arn:aws:iam::{cli.ACCOUNT}:role/source-role", "RoleName": "source-role"}
                        ]
                    }
                }
            )
        if operation[:2] == ["iam", "get-role-policy"]:
            raise RuntimeError("NoSuchEntity")
        if operation[:2] == ["iam", "put-role-policy"]:
            policy = json.loads(Path(operation[-1].removeprefix("file://")).read_text())
            assert policy["Statement"][1]["Resource"] == [
                f"arn:aws:ecr:{cli.REGION}:{cli.ACCOUNT}:repository/retailflow/docker.io/library/python"
            ]
            writes.append(operation)
            return ""  # Successful IAM writes have no JSON response.
        raise AssertionError(operation)

    def remote(aws, mapping, role, apply):
        assert role == "source-role"
        assert mapping["docker.io/library/python:3.12-alpine"] == TARGET
        return {
            "controllers": [{"kind": "Deployment", "name": "retailflow-api"}],
            "existingJobsRetained": 2,
            "backupDirectory": "/opt/navigan/retailflow-ecr/backup-test",
            "status": "VERIFIED" if apply else "PLANNED",
        }

    monkeypatch.setattr(cli, "run", run)
    monkeypatch.setattr(cli, "remote", remote)
    monkeypatch.setattr(sys, "argv", ["use-retailflow-ecr-source-dev.py", "--apply", "--report", str(path)])
    cli.main()
    assert len(writes) == 1
    assert (tmp_path / "retailflow-source-ecr-result.json").is_file()
    assert all("target" not in " ".join(c) for c in aws_calls)
