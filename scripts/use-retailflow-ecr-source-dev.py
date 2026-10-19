#!/usr/bin/env python3
"""Switch the approved DEV source Retailflow controllers to their mirrored ECR images."""

import argparse
import base64
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time
import zlib

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = "905418045935"
REGION = "ap-south-1"
INSTANCE = "i-08e28d9b2242cbd53"
REGISTRY = f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com"
RUNTIME = Path(__file__).with_name("retailflow_source_ecr_runtime.py")
POLICY_NAME = "NaviganRetailflowSourceEcrPull"


def run(args):
    process = subprocess.run(args, text=True, capture_output=True)
    if process.returncode:
        raise RuntimeError(process.stderr.strip() or "Command failed: " + args[0])
    return process.stdout


def validate_report(report):
    if (
        report.get("accountId"),
        report.get("region"),
        report.get("sourceNamespace"),
        report.get("registry"),
    ) != (ACCOUNT, REGION, "retailflow", REGISTRY):
        raise ValueError(
            "Image mapping does not identify the approved source account, region, registry and namespace."
        )
    spec = importlib.util.spec_from_file_location(
        "retailflow_mirror", Path(__file__).with_name("mirror-retailflow-images-dev.py")
    )
    mirror = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mirror)
    mapping = {}
    for entry in report.get("images", []):
        if entry.get("status") == "AVAILABLE" and entry.get("platform") == "linux/amd64":
            target = entry.get("destinationDigestReference", "")
            if not re.fullmatch(
                re.escape(REGISTRY) + r"/retailflow/[a-z0-9._/-]+@sha256:[a-f0-9]{64}", target
            ):
                raise ValueError("An image mapping is missing its verified source-account ECR digest.")
        elif entry.get("status") == "ALREADY_IN_ECR":
            target = entry.get("destination", "")
            if not target.startswith(REGISTRY + "/"):
                raise ValueError("Existing image does not belong to the source ECR registry.")
        else:
            raise ValueError("Finish mirroring every image successfully before switching the source.")
        source = mirror.source_identity(entry["source"])["source"]
        if source in mapping and mapping[source] != target:
            raise ValueError("Source image has conflicting ECR mappings.")
        mapping[source] = target
    if not mapping:
        raise ValueError("The image mapping report is empty.")
    return mapping


def target_repository(target):
    relative = target.removeprefix(REGISTRY + "/")
    if "@" in relative:
        repo, digest = relative.split("@", 1)
        image_id = "imageDigest=" + digest
    else:
        repo, tag = relative.rsplit(":", 1)
        image_id = "imageTag=" + tag
    return repo, image_id


def source_role(aws):
    instances = aws("ec2", "describe-instances", "--instance-ids", INSTANCE)["Reservations"][0]["Instances"]
    if (
        len(instances) != 1
        or instances[0]["InstanceId"] != INSTANCE
        or instances[0]["State"]["Name"] != "running"
    ):
        raise ValueError("The approved source control-plane EC2 instance is not running.")
    profile = instances[0].get("IamInstanceProfile", {}).get("Arn", "")
    if not profile.startswith(f"arn:aws:iam::{ACCOUNT}:instance-profile/"):
        raise ValueError("Source control plane has no approved same-account instance profile.")
    roles = aws("iam", "get-instance-profile", "--instance-profile-name", profile.rsplit("/", 1)[-1])[
        "InstanceProfile"
    ]["Roles"]
    if len(roles) != 1 or not roles[0]["Arn"].startswith(f"arn:aws:iam::{ACCOUNT}:role/"):
        raise ValueError("Source instance profile does not identify one same-account role.")
    return roles[0]["RoleName"]


def remote(aws, mapping, role, apply):
    code = RUNTIME.read_text()
    payload = {"mapping": mapping, "role": role, "apply": apply, "code": code}
    encoded = base64.b64encode(zlib.compress(json.dumps(payload).encode())).decode()
    loader = f'''import base64,json,zlib,subprocess
payload=json.loads(zlib.decompress(base64.b64decode("{encoded}")))
identity=json.loads(subprocess.check_output(["aws","sts","get-caller-identity","--output","json"],text=True))
if identity.get("Account") != "{ACCOUNT}" or ":assumed-role/" + payload["role"] + "/" not in identity.get("Arn", ""):
    raise SystemExit("Source host AWS identity does not match its approved instance-profile role.")
namespace={{"__name__":"retailflow_source_ecr_runtime"}}
exec(compile(payload["code"],"retailflow_source_ecr_runtime.py","exec"),namespace)
result=namespace["execute"](payload["mapping"],apply=payload["apply"],runtime_source=payload["code"])
print(json.dumps(result))
'''
    encoded_loader = base64.b64encode(loader.encode()).decode()
    with tempfile.TemporaryDirectory(prefix="navigan-retailflow-source-command-") as folder:
        parameters = Path(folder) / "command.json"
        parameters.write_text(
            json.dumps(
                {
                    "commands": [f"python3 -c \"import base64; exec(base64.b64decode('{encoded_loader}'))\""],
                    "executionTimeout": ["3600"],
                }
            )
        )
        command_id = aws(
            "ssm",
            "send-command",
            "--instance-ids",
            INSTANCE,
            "--document-name",
            "AWS-RunShellScript",
            "--comment",
            "Apply source-only DEV Retailflow ECR images"
            if apply
            else "Plan source-only DEV Retailflow ECR images",
            "--parameters",
            "file://" + str(parameters),
        )["Command"]["CommandId"]
    print(f"{'Applying' if apply else 'Checking'} source Retailflow: SSM command {command_id}", flush=True)
    for attempt in range(1800):
        time.sleep(2)
        try:
            invocation = aws(
                "ssm", "get-command-invocation", "--command-id", command_id, "--instance-id", INSTANCE
            )
        except RuntimeError as error:
            if "InvocationDoesNotExist" in str(error):
                continue
            raise
        if invocation["Status"] == "Success":
            return json.loads(invocation["StandardOutputContent"].strip())
        if invocation["Status"] not in {"Pending", "InProgress", "Delayed"}:
            raise RuntimeError(
                "Source update stopped: "
                + invocation["Status"]
                + ". "
                + invocation.get("StandardErrorContent", "")[-2500:]
                + " SSM command: "
                + command_id
            )
        if attempt % 15 == 14:
            print("Source operation still running; waiting for controller/health checks.", flush=True)
    raise RuntimeError(
        "Source command still pending; inspect SSM command " + command_id + " before retrying."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="navigan")
    parser.add_argument("--report", default="retailflow-ecr-images.json")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if run(["git", "branch", "--show-current"]).strip() != "new_migration_approach_18oct26":
        raise SystemExit("Run only from the approved DEV branch checkout.")
    report_path = Path(args.report)
    if not report_path.is_file():
        raise SystemExit(
            "Image mapping report not found: "
            + str(report_path)
            + ". Run from the directory where step 1 saved retailflow-ecr-images.json, or provide --report /path/to/retailflow-ecr-images.json."
        )
    mapping = validate_report(json.loads(report_path.read_text()))

    def aws(*parts):
        output = run(["aws", "--profile", args.profile, "--region", REGION, "--output", "json", *parts])
        return json.loads(output) if output.strip() else {}

    if aws("sts", "get-caller-identity").get("Account") != ACCOUNT:
        raise SystemExit("Unexpected AWS account; source update stopped.")
    for target in set(mapping.values()):
        repository, image_id = target_repository(target)
        if not aws("ecr", "describe-images", "--repository-name", repository, "--image-ids", image_id).get(
            "imageDetails"
        ):
            raise ValueError("An ECR image is unavailable; no source changes were applied.")
    role = source_role(aws)
    plan = remote(aws, mapping, role, False)
    print(
        f"Preflight passed: {len(plan['controllers'])} source controllers; {plan['existingJobsRetained']} existing Jobs retained."
    )
    if not args.apply:
        print(
            "Add --apply to install source pull access, automatic credential refresh and controller image updates."
        )
        return
    backup = Path(tempfile.mkdtemp(prefix="navigan-retailflow-source-"))
    backup.chmod(0o700)
    try:
        existing = aws("iam", "get-role-policy", "--role-name", role, "--policy-name", POLICY_NAME)
    except RuntimeError as error:
        if "NoSuchEntity" not in str(error):
            raise
        existing = {"absent": True}
    (backup / "previous-role-policy.json").write_text(json.dumps(existing, indent=2))
    resources = sorted(
        {f"arn:aws:ecr:{REGION}:{ACCOUNT}:repository/{target_repository(t)[0]}" for t in mapping.values()}
    )
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {"Effect": "Allow", "Action": ["ecr:GetAuthorizationToken"], "Resource": "*"},
            {
                "Effect": "Allow",
                "Action": [
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:BatchGetImage",
                    "ecr:GetDownloadUrlForLayer",
                ],
                "Resource": resources,
            },
        ],
    }
    policy_path = backup / "source-pull-policy.json"
    policy_path.write_text(json.dumps(policy))
    aws(
        "iam",
        "put-role-policy",
        "--role-name",
        role,
        "--policy-name",
        POLICY_NAME,
        "--policy-document",
        "file://" + str(policy_path),
    )
    result = remote(aws, mapping, role, True)
    output = report_path.with_name("retailflow-source-ecr-result.json")
    output.write_text(json.dumps(result, indent=2) + "\n")
    print("Retailflow source image rollouts and API/frontend health checks passed.")
    print("Source backup: " + result["backupDirectory"])
    print("Local IAM backup: " + str(backup))
    print("Result and reusable source patches: " + str(output.resolve()))
    print(
        "ECR credentials refresh every six hours. Refresh Navigan source discovery to collect the new image references."
    )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, FileNotFoundError) as error:
        raise SystemExit(str(error)) from None
