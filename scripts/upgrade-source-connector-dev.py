#!/usr/bin/env python3
"""DEV lab only: update the existing connector code, without re-enrollment or a second pod deployment."""

import argparse
import base64
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
INSTANCE = "i-08e28d9b2242cbd53"
SOURCE = "SRC-2f0e434335e04ef0bdccd74cb3322f2c"
ACCOUNT = "905418045935"
REMOTE = r"""
import base64, json, subprocess, zlib
runtime = json.loads(zlib.decompress(base64.b64decode("__PAYLOAD__")))
def kubectl(*args, input=None):
    return subprocess.check_output(["sudo", "kubectl", "--kubeconfig", "/etc/kubernetes/admin.conf", *args], input=input, text=True, stderr=subprocess.STDOUT)
# Authenticate with existing connector credentials in its pod; print only the source identity.
source = kubectl("-n", "navigan-migration", "exec", "deployment/navigan-source-connector", "--", "python", "-c", "from migration_connector.agent import fetch_assignment; print(fetch_assignment().get('sourceClusterId',''))").strip()
if source != "SRC-2f0e434335e04ef0bdccd74cb3322f2c":
    raise SystemExit("Connector is not assigned to the approved DB Schenker source registration; upgrade stopped.")
role = json.loads(kubectl("get", "clusterrole", "navigan-source-connector", "-o", "json"))
for rule in role["rules"]:
    if rule.get("apiGroups") == [""]:
        rule["resources"] = sorted(set(rule["resources"]) | {"pods"})
    if rule.get("apiGroups") == ["apps"]:
        rule["resources"] = sorted(set(rule["resources"]) | {"replicasets"})
# Preserve existing privileges; add only list access for owner-linked runtime evidence.
kubectl("apply", "-f", "-", input=json.dumps(role))
config = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "navigan-source-runtime-dev-__DIGEST_SHORT__", "namespace": "navigan-migration"}, "data": runtime}
kubectl("apply", "-f", "-", input=json.dumps(config))
patch = {"spec": {"template": {"metadata": {"annotations": {"navigan.io/dev-runtime": "__DIGEST__"}}, "spec": {"volumes": [{"name": "dev-runtime", "configMap": {"name": "navigan-source-runtime-dev-__DIGEST_SHORT__", "defaultMode": 292}}], "containers": [{"name": "connector", "volumeMounts": [{"name": "dev-runtime", "mountPath": "/app/migration_connector", "readOnly": True}]}]}}}}
kubectl("-n", "navigan-migration", "patch", "deployment", "navigan-source-connector", "--type=strategic", "-p", json.dumps(patch))
try:
    kubectl("-n", "navigan-migration", "rollout", "status", "deployment/navigan-source-connector", "--timeout=120s")
    kubectl("-n", "navigan-migration", "exec", "deployment/navigan-source-connector", "--", "python", "-c", "from migration_connector.deployment_evidence import collect_runtime; from migration_connector.agent import fetch_assignment; assert fetch_assignment().get('sourceClusterId') == 'SRC-2f0e434335e04ef0bdccd74cb3322f2c'; print('Runtime evidence collector verified.')")
except subprocess.CalledProcessError:
    kubectl("-n", "navigan-migration", "rollout", "undo", "deployment/navigan-source-connector")
    raise SystemExit("Connector upgrade failed; previous Deployment revision restored.")
print("Existing DB Schenker connector upgraded; registration and credentials preserved.")
"""


def main():
    import hashlib
    import zlib
    import tempfile

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="navigan")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    def aws(*parts):
        return json.loads(
            subprocess.check_output(
                ["aws", "--profile", args.profile, "--region", "ap-south-1", "--output", "json", *parts],
                text=True,
            )
        )

    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != "new_migration_approach_18oct26" or aws("sts", "get-caller-identity")["Account"] != ACCOUNT:
        raise SystemExit("Use only the approved DEV branch and AWS account.")
    runtime = {p.name: p.read_text() for p in sorted((ROOT / "migration_connector").glob("*.py"))}
    payload = json.dumps(runtime, sort_keys=True).encode()
    digest = hashlib.sha256(payload).hexdigest()
    script = (
        REMOTE.replace("__PAYLOAD__", base64.b64encode(zlib.compress(payload)).decode())
        .replace("__DIGEST__", digest)
        .replace("__DIGEST_SHORT__", digest[:12])
    )
    if not args.apply:
        print(f"Prepared existing source connector update for {SOURCE} on {INSTANCE}; use --apply.")
        return
    encoded = base64.b64encode(script.encode()).decode()
    parameters = Path(tempfile.mkdtemp(prefix="navigan-source-runtime-dev-")) / "command.json"
    parameters.write_text(
        json.dumps({"commands": [f"python3 -c \"import base64; exec(base64.b64decode('{encoded}'))\""]})
    )
    command = aws(
        "ssm",
        "send-command",
        "--instance-ids",
        INSTANCE,
        "--document-name",
        "AWS-RunShellScript",
        "--timeout-seconds",
        "180",
        "--comment",
        "Update DEV source connector evidence collector without re-enrollment",
        "--parameters",
        "file://" + str(parameters),
    )["Command"]["CommandId"]
    print(f"DEV connector update started: {command}", flush=True)
    for _ in range(90):
        time.sleep(2)
        try:
            result = aws("ssm", "get-command-invocation", "--command-id", command, "--instance-id", INSTANCE)
        except subprocess.CalledProcessError:
            continue
        if result["Status"] == "Success":
            print(result.get("StandardOutputContent", ""))
            return
        if result["Status"] not in {"Pending", "InProgress", "Delayed"}:
            raise SystemExit(
                "DEV connector update failed: "
                + result["Status"]
                + "\n"
                + result.get("StandardErrorContent", "")
            )
    raise SystemExit("Connector update still running; check the printed SSM command ID before retrying.")


if __name__ == "__main__":
    main()
