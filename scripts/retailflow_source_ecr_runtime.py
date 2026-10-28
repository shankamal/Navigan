"""Remote, namespace-scoped Retailflow source image switch. Standard library only."""

import base64
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

ACCOUNT = "905418045935"
REGION = "ap-south-1"
REGISTRY = f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com"
NAMESPACE = "retailflow"
PULL_SECRET = "retailflow-source-ecr-pull"
DIRECTORY = Path("/opt/navigan/retailflow-ecr")
KINDS = {"Deployment", "StatefulSet", "DaemonSet", "CronJob"}


def command(args, *, input=None, sensitive=False):
    result = subprocess.run(args, input=input, text=True, capture_output=True)
    if result.returncode:
        # No remote API bodies, Pod environment values or registry tokens in command errors.
        raise RuntimeError(
            "Source operation failed: " + ("credential refresh" if sensitive else " ".join(args[:5]))
        )
    return result.stdout


def kubectl(*args, payload=None, sensitive=False):
    return command(
        ["kubectl", "--kubeconfig", "/etc/kubernetes/admin.conf", "-n", NAMESPACE, *args],
        input=json.dumps(payload) if payload is not None else None,
        sensitive=sensitive,
    )


def canonical(image):
    base, separator, digest = image.partition("@")
    first, slash, tail = base.partition("/")
    if slash and ("." in first or ":" in first or first == "localhost"):
        host, path = first, tail
    else:
        host, path = "docker.io", base
    if host in {"index.docker.io", "registry-1.docker.io"}:
        host = "docker.io"
    if ":" not in path.rsplit("/", 1)[-1] and not separator:
        path += ":latest"
    if host == "docker.io" and "/" not in path:
        path = "library/" + path
    return host + "/" + path + ("@" + digest if separator else "")


def pod_template(resource):
    spec = resource.get("spec", {})
    if resource["kind"] == "CronJob":
        return spec.get("jobTemplate", {}).get("spec", {}).get("template", {})
    return spec.get("template", {})


def image_patch(resource, mapping):
    if resource["kind"] not in KINDS:
        raise ValueError("Only application controllers can be updated.")
    if resource.get("metadata", {}).get("namespace") != NAMESPACE:
        raise ValueError("Only the Retailflow source namespace can be updated.")
    spec = resource.get("spec", {})
    if resource["kind"] == "Deployment" and spec.get("paused"):
        raise ValueError("Resume the paused source Deployment before switching its images.")
    if resource["kind"] in {"StatefulSet", "DaemonSet"}:
        strategy = spec.get("updateStrategy", {})
        if strategy.get("type", "RollingUpdate") != "RollingUpdate" or strategy.get("rollingUpdate", {}).get(
            "partition", 0
        ):
            raise ValueError(
                "OnDelete/partitioned controllers need an explicit rollout plan before this image switch."
            )
    original = pod_template(resource)
    pod = original.get("spec", {})
    patch = {}
    for field in ("containers", "initContainers"):
        replacements = []
        for container in pod.get(field, []):
            image = container["image"]
            target = mapping.get(canonical(image))
            if target is None:
                if image.startswith(REGISTRY + "/"):
                    target = image
                else:
                    raise ValueError("An image is missing from the ECR mapping report: " + image)
            replacements.append({"name": container["name"], "image": target})
        if replacements:
            patch[field] = replacements
    patch["imagePullSecrets"] = [{"name": PULL_SECRET}]
    template = {"spec": patch}
    if resource["kind"] == "CronJob":
        return {"spec": {"jobTemplate": {"spec": {"template": template}}}}
    return {"spec": {"template": template}}


def plan(resources, mapping):
    controllers = [r for r in resources if r.get("kind") in KINDS]
    if not {"retailflow-api", "retailflow-frontend"} <= {r["metadata"]["name"] for r in controllers}:
        raise ValueError("The approved Retailflow API/frontend controllers were not found on this source.")
    standalone = [
        r for r in resources if r.get("kind") == "Pod" and not r.get("metadata", {}).get("ownerReferences")
    ]
    if standalone:
        raise ValueError(
            "Standalone Pods need a reviewed recreation plan; no controller changes were applied."
        )
    changes = [
        {"kind": r["kind"], "name": r["metadata"]["name"], "patch": image_patch(r, mapping)}
        for r in controllers
    ]
    priority = {"StatefulSet": 0, "DaemonSet": 1, "Deployment": 2, "CronJob": 3}
    changes.sort(key=lambda c: (priority[c["kind"]], c["name"]))
    return changes


def refresh_credentials():
    identity = json.loads(command(["aws", "sts", "get-caller-identity", "--output", "json"], sensitive=True))
    if identity.get("Account") != ACCOUNT:
        raise ValueError("Source host AWS identity belongs to another account.")
    password = command(["aws", "ecr", "get-login-password", "--region", REGION], sensitive=True).strip()
    if not password:
        raise RuntimeError("Source ECR authentication returned no credential.")
    config = {
        "auths": {
            REGISTRY: {
                "username": "AWS",
                "password": password,
                "auth": base64.b64encode(("AWS:" + password).encode()).decode(),
            }
        }
    }
    secret = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": PULL_SECRET, "namespace": NAMESPACE},
        "type": "kubernetes.io/dockerconfigjson",
        "data": {".dockerconfigjson": base64.b64encode(json.dumps(config).encode()).decode()},
    }
    kubectl(
        "apply",
        "--server-side",
        "--field-manager=navigan-retailflow-ecr",
        "-f",
        "-",
        payload=secret,
        sensitive=True,
    )


def install_refresh(runtime_source):
    DIRECTORY.mkdir(parents=True, exist_ok=True, mode=0o700)
    script = DIRECTORY / "runtime.py"
    script.write_text(runtime_source)
    script.chmod(0o600)
    service = Path("/etc/systemd/system/navigan-retailflow-ecr-refresh.service")
    timer = Path("/etc/systemd/system/navigan-retailflow-ecr-refresh.timer")
    service.write_text(
        "[Unit]\nDescription=Refresh DEV Retailflow ECR pull credentials\nWants=network-online.target\nAfter=network-online.target\n[Service]\nType=oneshot\nUser=root\nUMask=0077\nEnvironment=AWS_PAGER=\nEnvironment=PYTHONDONTWRITEBYTECODE=1\nExecStart=/usr/bin/python3 /opt/navigan/retailflow-ecr/runtime.py refresh\n"
    )
    timer.write_text(
        "[Unit]\nDescription=Refresh DEV Retailflow ECR token every six hours\n[Timer]\nOnBootSec=1min\nOnUnitActiveSec=6h\nRandomizedDelaySec=60\nPersistent=true\n[Install]\nWantedBy=timers.target\n"
    )
    command(["systemctl", "daemon-reload"])
    command(["systemctl", "enable", "--now", timer.name])
    command(["systemctl", "start", service.name])
    command(["systemctl", "is-active", "--quiet", timer.name])


def health_check(curl_image):
    name = "retailflow-ecr-check-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    job = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"namespace": NAMESPACE, "name": name},
        "spec": {
            "backoffLimit": 0,
            "ttlSecondsAfterFinished": 600,
            "template": {
                "metadata": {"labels": {"tier": "diagnostics"}},
                "spec": {
                    "restartPolicy": "Never",
                    "automountServiceAccountToken": False,
                    "imagePullSecrets": [{"name": PULL_SECRET}],
                    "securityContext": {
                        "runAsNonRoot": True,
                        "runAsUser": 10001,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "containers": [
                        {
                            "name": "check",
                            "image": curl_image,
                            "imagePullPolicy": "Always",
                            "command": [
                                "sh",
                                "-c",
                                "curl --fail --silent --show-error --retry 12 --retry-delay 5 --retry-all-errors http://retailflow-api:8080/readyz >/dev/null && curl --fail --silent --show-error --retry 12 --retry-delay 5 --retry-all-errors http://retailflow-frontend/healthz >/dev/null",
                            ],
                            "resources": {
                                "requests": {"cpu": "10m", "memory": "16Mi"},
                                "limits": {"cpu": "100m", "memory": "64Mi"},
                            },
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": True,
                                "capabilities": {"drop": ["ALL"]},
                            },
                        }
                    ],
                },
            },
        },
    }
    kubectl("create", "-f", "-", payload=job)
    kubectl("wait", "--for=condition=complete", "job/" + name, "--timeout=240s")
    return name


def apply_changes(changes, originals, mutate, rollout, check):
    """Restore the prior templates after any patch, rollout or health-check failure."""
    changed = []
    try:
        for change in changes:
            current = originals[(change["kind"], change["name"])]
            patch = copy.deepcopy(change["patch"])
            patch["metadata"] = {"resourceVersion": current["metadata"]["resourceVersion"]}
            changed.append(change)
            mutate(change, patch, "strategic")
            if change["kind"] != "CronJob":
                rollout(change)
        check()
    except Exception as error:
        failed_restore = []
        for change in reversed(changed):
            old = originals[(change["kind"], change["name"])]
            template = copy.deepcopy(pod_template(old))
            template.setdefault("spec", {})["imagePullSecrets"] = (
                template.get("spec", {}).get("imagePullSecrets") or None
            )
            # JSON merge replaces the complete prior template and removes the added pull-secret reference.
            patch = (
                {"spec": {"template": template}}
                if change["kind"] != "CronJob"
                else {"spec": {"jobTemplate": {"spec": {"template": template}}}}
            )
            try:
                mutate(change, patch, "merge")
            except Exception:
                failed_restore.append(change["kind"] + "/" + change["name"])
        if failed_restore:
            raise RuntimeError(
                "Image switch failed; rollback needs review for: " + ", ".join(failed_restore)
            ) from None
        raise RuntimeError(
            "Image switch failed; previous controller templates were restored. Use the saved source backup to inspect before retrying."
        ) from error


def execute(mapping, *, apply=False, runtime_source=""):
    resources = json.loads(
        kubectl("get", "deployments,statefulsets,daemonsets,cronjobs,jobs,pods", "-o", "json")
    )["items"]
    nodes = json.loads(kubectl("get", "nodes", "-o", "json"))["items"]
    if not nodes or any(
        n.get("status", {}).get("nodeInfo", {}).get("architecture") != "amd64" for n in nodes
    ):
        raise ValueError("Source nodes must match the mirrored linux/amd64 image platform.")
    if any(
        not any(
            c.get("type") == "Ready" and c.get("status") == "True"
            for c in n.get("status", {}).get("conditions", [])
        )
        for n in nodes
    ):
        raise ValueError("Wait for all source nodes to be Ready before changing application images.")
    changes = plan(resources, mapping)
    originals = {(r["kind"], r["metadata"]["name"]): r for r in resources if r.get("kind") in KINDS}
    curl_image = next(
        (target for original, target in mapping.items() if original.startswith("docker.io/curlimages/curl:")),
        None,
    )
    if not curl_image:
        raise ValueError("The ECR mapping must include the Retailflow curl connectivity-check image.")
    result = {
        "namespace": NAMESPACE,
        "controllers": [{"kind": c["kind"], "name": c["name"]} for c in changes],
        "existingJobsRetained": sum(r.get("kind") == "Job" for r in resources),
        "patches": changes,
    }
    if not apply:
        return {**result, "status": "PLANNED"}
    DIRECTORY.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup_dir = DIRECTORY / ("backup-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f"))
    backup_dir.mkdir(mode=0o700)
    backup = backup_dir / "controllers.json"
    backup.write_text(json.dumps(list(originals.values())))
    backup.chmod(0o600)
    # Install the refresh timer before any workload depends on private ECR.
    install_refresh(runtime_source)
    health_check(curl_image)  # Verify ECR pull + baseline API/frontend health before controller changes.
    applied_templates = {}

    def mutate(change, patch, mode):
        key = (change["kind"], change["name"])
        latest = json.loads(kubectl("get", change["kind"], change["name"], "-o", "json"))
        if mode == "strategic":
            if pod_template(latest) != pod_template(originals[key]):
                raise ValueError("A source workload was edited concurrently; image switch stopped.")
        else:
            if key not in applied_templates:
                if pod_template(latest) == pod_template(originals[key]):
                    return
                raise ValueError("An interrupted patch needs source backup review before rollback.")
            if pod_template(latest) != applied_templates[key]:
                raise ValueError("A source workload was edited concurrently; automatic rollback stopped.")
        patch["metadata"] = {"resourceVersion": latest["metadata"]["resourceVersion"]}
        updated = json.loads(
            kubectl(
                "patch",
                change["kind"],
                change["name"],
                "--type=" + mode,
                "--patch-file",
                "/dev/stdin",
                "-o",
                "json",
                payload=patch,
            )
        )
        if mode == "strategic":
            applied_templates[key] = pod_template(updated)

    def rollout(change):
        kubectl("rollout", "status", change["kind"].lower() + "/" + change["name"], "--timeout=300s")

    apply_changes(changes, originals, mutate, rollout, lambda: health_check(curl_image))
    (DIRECTORY / "source-image-patches.json").write_text(json.dumps(changes, indent=2))
    return {
        **result,
        "status": "VERIFIED",
        "backupDirectory": str(backup_dir),
        "credentialsRefresh": "Every 6 hours",
    }


if __name__ == "__main__" and sys.argv[1:] == ["refresh"]:
    refresh_credentials()
