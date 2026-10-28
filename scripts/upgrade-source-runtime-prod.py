#!/usr/bin/env python3
"""Upgrade one existing PROD source agent's runtime without re-enrollment.

The immutable source-code ConfigMap overlay follows the existing DEV runtime
upgrade method. Only the named source Deployment's runtime volume is changed;
credentials, image, security context and other source agents are preserved.
The connector API contract must be promoted first. Default prepares a private
SSM script; --apply performs the scoped rolling update and verifies identity.
New installations still need the runtime-capable connector image promoted.
"""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import time
import urllib.request
import uuid
import zipfile
import zlib

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
NAMESPACE = "navigan-migration"
RUNTIME = ("__init__.py", "agent.py", "inventory.py", "deployment_evidence.py")

REMOTE = r'''
import base64, hashlib, json, os, pathlib, subprocess, uuid, zlib
value = json.loads(zlib.decompress(base64.b64decode("__PAYLOAD__")))
source_id, expected_api, runtime, digest = value["source"], value["api"], value["runtime"], value["digest"]
assert hashlib.sha256(json.dumps(runtime, sort_keys=True).encode()).hexdigest() == digest
deployment_name = "navigan-source-" + source_id[4:]
namespace = "navigan-migration"
def kubectl(*args):
    result = subprocess.run(["kubectl", "--kubeconfig=/etc/kubernetes/admin.conf", *args], text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError("Kubernetes command failed: " + args[0])
    return result.stdout
def get_deployment():
    return json.loads(kubectl("-n", namespace, "get", "deployment", deployment_name, "-o", "json"))
def identity():
    check = "import json,os;from migration_connector.agent import fetch_assignment;print(json.dumps({'source':fetch_assignment().get('sourceClusterId'),'api':os.environ.get('NAVIGAN_API_BASE_URL')}))"
    data = json.loads(kubectl("-n", namespace, "exec", "deployment/" + deployment_name, "--", "python", "-c", check))
    assert data == {"source": source_id, "api": expected_api}, "Source identity or PROD API mismatch; update stopped"
identity()
original = get_deployment()
pod_spec = original["spec"]["template"]["spec"]
containers = [c for c in pod_spec["containers"] if c["name"] == "connector"]
assert len(containers) == 1, "Expected exactly one connector container"
for mount in containers[0].get("volumeMounts", []):
    assert mount.get("mountPath") != "/app/migration_connector" or mount["name"] == "navigan-runtime-prod", "Unexpected runtime mount"
service_account = pod_spec["serviceAccountName"]
for resource in ("pods", "replicasets.apps", "jobs.batch"):
    permission = kubectl("auth", "can-i", "list", resource, "-n", "headlamp", "--as=system:serviceaccount:" + namespace + ":" + service_account).strip()
    assert permission == "yes", "Connector lacks runtime evidence read permission"
backup_dir = pathlib.Path("/var/lib/navigan/source-runtime-backups") / uuid.uuid4().hex
backup_dir.mkdir(parents=True, mode=0o700)
os.chmod(backup_dir, 0o700)
backup = backup_dir / "deployment-original.json"
backup.write_text(json.dumps(original, indent=2))
os.chmod(backup, 0o600)
config_name = "navigan-runtime-prod-" + source_id[4:12] + "-" + digest[:12]
config = {"apiVersion":"v1","kind":"ConfigMap","metadata":{"name":config_name,"namespace":namespace},"immutable":True,"data":runtime}
def apply_document(document, label):
    result = subprocess.run(["kubectl", "--kubeconfig=/etc/kubernetes/admin.conf", "apply", "-f", "-"], input=json.dumps(document), text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(label + " failed; deployment backup retained")
apply_document(config, "Runtime ConfigMap creation")
patch = {"metadata":{"resourceVersion":original["metadata"]["resourceVersion"]},"spec":{"template":{"metadata":{"annotations":{"navigan.io/prod-source-runtime":digest}},"spec":{
    "volumes":[{"name":"navigan-runtime-prod","configMap":{"name":config_name,"defaultMode":292}}],
    "containers":[{"name":"connector","volumeMounts":[{"name":"navigan-runtime-prod","mountPath":"/app/migration_connector","readOnly":True}]}]}}}}
kubectl("-n", namespace, "patch", "deployment", deployment_name, "--type=strategic", "-p", json.dumps(patch))
try:
    kubectl("-n", namespace, "rollout", "status", "deployment/" + deployment_name, "--timeout=120s")
    identity()
    check = "import inspect;from migration_connector import agent;assert 'collect_runtime' in inspect.getsource(agent.collect_inventory);print('Runtime evidence collector verified')"
    kubectl("-n", namespace, "exec", "deployment/" + deployment_name, "--", "python", "-c", check)
except Exception:
    current = get_deployment()
    marker = current["spec"]["template"].get("metadata",{}).get("annotations",{}).get("navigan.io/prod-source-runtime")
    if marker == digest:
        rollback = {"metadata":{"resourceVersion":current["metadata"]["resourceVersion"]}, "spec": original["spec"]}
        kubectl("-n", namespace, "patch", "deployment", deployment_name, "--type=merge", "-p", json.dumps(rollback))
        print("Source runtime verification failed; original Deployment spec restored. Backup: " + str(backup))
    else:
        print("Deployment changed concurrently; automatic rollback skipped. Backup: " + str(backup))
    raise RuntimeError("Source runtime upgrade failed; inspect Deployment readiness before retrying") from None
print("Existing PROD source runtime upgraded; registration and credentials preserved. Backup: " + str(backup))
'''


def make_script(source_id, expected_api, runtime):
    if not re.fullmatch(r"SRC-[0-9a-f]{32}", source_id):
        raise ValueError("Use an exact source registration ID")
    if set(runtime) != set(RUNTIME) or "collect_runtime" not in runtime["agent.py"]:
        raise ValueError("Current runtime evidence collector files are required")
    digest = hashlib.sha256(json.dumps(runtime, sort_keys=True).encode()).hexdigest()
    payload = {"source": source_id, "api": expected_api, "runtime": runtime, "digest": digest}
    encoded = base64.b64encode(zlib.compress(json.dumps(payload).encode())).decode()
    return REMOTE.replace("__PAYLOAD__", encoded), digest


def check_contract(package, source=ROOT):
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        for name in ("models.py", "deployment_sources.py"):
            path = "navigan/modules/migration_management/" + name
            if archive.read(path) != (source / "src" / path).read_bytes():
                raise RuntimeError("Promote the current connector API inventory contract before upgrading the source runtime")


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--expected-account", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--stack-name", required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9]{12}", args.expected_account):
        raise RuntimeError("Use the expected AWS account ID")
    if not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-[0-9]", args.region):
        raise RuntimeError("Use an explicit AWS region")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,127}", args.stack_name):
        raise RuntimeError("Use an explicit parent stack name")
    if not re.fullmatch(r"i-[0-9a-f]{8,17}", args.instance_id):
        raise RuntimeError("Use an exact managed EC2 source instance ID")
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != "new_migration_approach_18oct26":
        raise RuntimeError("Use the approved migration branch")
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--", "migration_connector", "scripts/upgrade-source-runtime-prod.py"], cwd=ROOT, text=True)
    if dirty.strip():
        raise RuntimeError("Commit/review local source runtime changes before promotion")
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    if session.client("sts").get_caller_identity()["Account"] != args.expected_account:
        raise RuntimeError("Unexpected AWS account")
    cfn = session.client("cloudformation")
    nested = cfn.describe_stack_resource(StackName=args.stack_name, LogicalResourceId="MigrationManagement")["StackResourceDetail"]["PhysicalResourceId"]
    params = {p["ParameterKey"]: p["ParameterValue"] for p in cfn.describe_stacks(StackName=nested)["Stacks"][0]["Parameters"]}
    if params.get("DatabaseName") != "navigan" or not re.fullmatch(r"[a-z0-9]+", params.get("ApiId", "")):
        raise RuntimeError("Unexpected production API identity")
    name = cfn.describe_stack_resource(StackName=nested, LogicalResourceId="MigrationConnectorFunction")["StackResourceDetail"]["PhysicalResourceId"]
    deployed = session.client("lambda").get_function(FunctionName=name)
    with urllib.request.urlopen(deployed["Code"]["Location"], timeout=30) as response:
        check_contract(response.read())
    expected_api = f"https://{params['ApiId']}.execute-api.{args.region}.amazonaws.com/v1/api/v1"
    runtime = {name: (ROOT / "migration_connector" / name).read_text() for name in RUNTIME}
    script, digest = make_script(args.source_id, expected_api, runtime)
    directory = Path(tempfile.mkdtemp(prefix="navigan-prod-source-runtime-"))
    directory.chmod(0o700)
    (directory / "upgrade.py").write_text(script)
    print("Prepared scoped runtime upgrade: " + args.source_id + "; SHA-256: " + digest)
    print("Private record: " + str(directory))
    if not args.apply:
        print("No source changes made. Use --apply after reviewing the selected source and instance.")
        return
    command = shlex.join(["python3", "-c", "import base64;exec(base64.b64decode(" + repr(base64.b64encode(script.encode()).decode()) + "))"])
    ssm = session.client("ssm")
    identifier = ssm.send_command(InstanceIds=[args.instance_id], DocumentName="AWS-RunShellScript", Parameters={"commands": [command], "executionTimeout": ["240"]})["Command"]["CommandId"]
    print("Source runtime upgrade command: " + identifier, flush=True)
    for _ in range(60):
        time.sleep(5)
        try:
            result = ssm.get_command_invocation(CommandId=identifier, InstanceId=args.instance_id)
        except ClientError as error:
            if error.response["Error"]["Code"] == "InvocationDoesNotExist":
                continue
            raise
        if result["Status"] in {"Pending", "InProgress", "Delayed"}:
            continue
        print(result.get("StandardOutputContent", ""))
        if result["Status"] != "Success":
            raise RuntimeError("Source runtime upgrade failed: " + result["Status"] + "; inspect the printed SSM command")
        return
    raise RuntimeError("Source runtime upgrade is still running; inspect its command before retrying")


if __name__ == "__main__":
    main()
