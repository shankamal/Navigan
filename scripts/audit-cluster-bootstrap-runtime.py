#!/usr/bin/env python3
"""Capture live bootstrap packages before preparing a scoped CloudFormation release.

AWS operations are read-only. --inspect-runner also pulls the deployed ECR image
and copies files from an unstarted local Docker container. Private captures may
contain runtime configuration: share summary.json only, never the whole folder.
"""
from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.request
import zipfile

import boto3
import yaml

ROOT = Path(__file__).resolve().parents[1]
MODULE = "navigan/modules/cluster_management/"
STABLE = {"CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, default=str) + "\n")
    path.chmod(0o600)


def template_body(value):
    result = json.loads(value) if isinstance(value, str) else value
    require(isinstance(result, dict), "Processed template is not a JSON object.")
    return result


def validate_stack(stack, account, region, parent=None):
    require(stack["StackId"].startswith(f"arn:aws:cloudformation:{region}:{account}:stack/"),
            "Stack account or region differs from the requested target.")
    require(stack["StackStatus"] in STABLE, "Stack must be stable before capture.")
    if parent:
        require(stack.get("ParentId") == parent, "Nested stack has an unexpected parent.")


def function_names(source):
    return {node.name for node in ast.walk(ast.parse(source))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def inspect_package(raw):
    """Return only non-secret package facts, without extracting archive paths."""
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        require(len(archive.namelist()) == len(set(archive.namelist())),
                "Duplicate ZIP entries require review.")
        def read(name):
            return archive.read(MODULE + name).decode("utf-8")

        app = yaml.safe_load(read("system_repo_template/applications/20-falco.yaml"))
        values = yaml.safe_load(read("system_repo_template/values/falco.yaml"))
        charts = [s for s in app["spec"]["sources"] if s.get("chart") == "falco"]
        require(len(charts) == 1, "Unexpected Falco application layout.")
        handler = read("handler.py")
        installer = read("connector_installation.py")
        repository = read("repository.py")
        return {
            "falco": {
                "chart": charts[0]["targetRevision"],
                "imageTag": (values.get("image") or {}).get("tag"),
                "containerPlugin": ((values.get("collectors") or {}).get("containerEngine") or {}).get("pluginRef"),
                "protectedNodeSelector": (values.get("nodeSelector") or {}).get("navigan.io/platform-services"),
            },
            "failurePollingModule": MODULE + "bootstrap_status.py" in archive.namelist(),
            "failurePollingCall": any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                                      and n.func.id == "refresh_installer_status"
                                      for n in ast.walk(ast.parse(handler))),
            "installerStatusReader": "inspect_status" in function_names(installer),
            "repositoryMethodsAvailable": {name: name in function_names(repository)
                                           for name in ("get", "save", "pinned_environment_snapshot")},
            "sourceSha256": {name: sha(read(name).encode()) for name in
                             ("handler.py", "repository.py", "connector_installation.py")},
        }


def hcl_tokens(source):
    # Ignore terraform fmt whitespace, preserving quoted strings and comments.
    return re.findall(r'"(?:\\.|[^"\\])*"|\S', source)


def docker(config, *args, payload=None):
    result = subprocess.run(["docker", "--config", str(config), *args],
                            input=payload, capture_output=True)
    require(result.returncode == 0, "Docker " + args[0] + " failed; inspect locally.")
    return result.stdout.decode().strip()


def inspect_runner(session, image, account, region, private):
    match = re.fullmatch(
        rf"{account}\.dkr\.ecr\.{re.escape(region)}\.amazonaws\.com/"
        r"([a-z0-9][a-z0-9._/-]*)(?::([A-Za-z0-9_.-]+)|@(sha256:[a-f0-9]{64}))", image)
    require(match, "Runner must be an explicit image in the target account and region.")
    repository, tag, digest = match.groups()
    ecr = session.client("ecr")
    image_id = {"imageDigest": digest} if digest else {"imageTag": tag}
    details = ecr.describe_images(repositoryName=repository, imageIds=[image_id])["imageDetails"]
    require(len(details) == 1, "Runner image could not be resolved uniquely.")
    digest = details[0]["imageDigest"]
    require(re.fullmatch(r"sha256:[a-f0-9]{64}", digest), "Invalid ECR image digest.")
    registry = f"{account}.dkr.ecr.{region}.amazonaws.com"
    pinned = registry + "/" + repository + "@" + digest
    auth = ecr.get_authorization_token(registryIds=[account])["authorizationData"]
    entry = next((a for a in auth if a["proxyEndpoint"] == "https://" + registry), None)
    require(entry, "ECR authentication endpoint differs from target registry.")
    username, password = base64.b64decode(entry["authorizationToken"]).split(b":", 1)
    require(username == b"AWS", "Unexpected ECR authentication identity.")
    runner_dir = private / "runner"
    runner_dir.mkdir(mode=0o700)
    with tempfile.TemporaryDirectory(prefix="navigan-ecr-auth-") as directory:
        config = Path(directory)
        docker(config, "login", "--username", "AWS", "--password-stdin", registry, payload=password)
        docker(config, "pull", pinned)
        container = docker(config, "create", "--network", "none", pinned)
        require(re.fullmatch(r"[a-f0-9]{64}", container), "Invalid Docker container identifier.")
        try:
            docker(config, "cp", container + ":/app/runner.py", str(runner_dir / "runner.py"))
            docker(config, "cp", container + ":/app/modules/aws-eks", str(runner_dir / "aws-eks"))
        finally:
            docker(config, "rm", container)
    source = (runner_dir / "runner.py").read_bytes()
    live_module = runner_dir / "aws-eks"
    expected = ROOT / "terraform/modules/aws-eks"
    expected_files = {p.name for p in expected.glob("*.tf")}
    require(expected_files, "Local Terraform module is unavailable.")
    return {
        "resolvedImage": pinned,
        "runnerSha256": sha(source),
        "runnerMatchesSource": source == (ROOT / "provisioning/runner/runner.py").read_bytes(),
        "protectedPoolGuardPresent": "system_node_findings" in function_names(source.decode()),
        "terraformFilesMatchSource": {name: (live_module / name).exists() and
            hcl_tokens((live_module / name).read_text()) == hcl_tokens((expected / name).read_text())
            for name in sorted(expected_files)},
        "unexpectedTerraformFiles": sorted({p.name for p in live_module.glob("*.tf")} - expected_files),
    }


def capture(session, args, private):
    identity = session.client("sts").get_caller_identity()
    require(identity["Account"] == args.expected_account, "AWS account differs from requested target.")
    cfn, lam = session.client("cloudformation"), session.client("lambda")
    parent = cfn.describe_stacks(StackName=args.stack_name)["Stacks"][0]
    validate_stack(parent, args.expected_account, args.region)
    parameters = {item["ParameterKey"]: item.get("ParameterValue") for item in parent.get("Parameters", [])}
    require(parameters.get("DatabaseName") == args.expected_database,
            "Root stack database differs from requested target.")
    root_template = template_body(cfn.get_template(StackName=parent["StackId"], TemplateStage="Processed")["TemplateBody"])
    nested_id = cfn.describe_stack_resource(StackName=parent["StackId"], LogicalResourceId="ClusterManagement")["StackResourceDetail"]["PhysicalResourceId"]
    child = cfn.describe_stacks(StackName=nested_id)["Stacks"][0]
    validate_stack(child, args.expected_account, args.region, parent["StackId"])
    child_template = template_body(cfn.get_template(StackName=nested_id, TemplateStage="Processed")["TemplateBody"])
    write_json(private / "root-stack.json", parent)
    write_json(private / "root-template.json", root_template)
    write_json(private / "cluster-stack.json", child)
    write_json(private / "cluster-template.json", child_template)
    summary = {"environment": args.environment, "account": args.expected_account,
               "region": args.region, "stackName": args.stack_name, "functions": {}}
    for logical in ("ClusterFunction", "StatusFunction"):
        physical = cfn.describe_stack_resource(StackName=nested_id, LogicalResourceId=logical)["StackResourceDetail"]["PhysicalResourceId"]
        response = lam.get_function(FunctionName=physical)
        config = response["Configuration"]
        require(config["FunctionArn"].startswith(f"arn:aws:lambda:{args.region}:{args.expected_account}:function:"),
                "Lambda account or region differs from target.")
        require(config.get("Runtime") == "python3.12" and config.get("PackageType") == "Zip",
                "Unexpected Lambda runtime or package type.")
        require(config.get("Environment", {}).get("Variables", {}).get("DB_NAME") == args.expected_database,
                "Lambda database differs from requested target.")
        require(config.get("State") == "Active" and config.get("LastUpdateStatus") == "Successful",
                "Lambda must be stable before capture.")
        with urllib.request.urlopen(response["Code"]["Location"], timeout=60) as stream:
            raw = stream.read()
        require(base64.b64encode(hashlib.sha256(raw).digest()).decode() == config["CodeSha256"],
                "Downloaded Lambda package does not match its recorded hash.")
        archive_path = private / (logical + ".zip")
        archive_path.write_bytes(raw)
        archive_path.chmod(0o600)
        write_json(private / (logical + "-config.json"), config)
        summary["functions"][logical] = {"name": physical, "revisionId": config["RevisionId"],
                                         "codeSha256": config["CodeSha256"], **inspect_package(raw)}
    project = cfn.describe_stack_resource(StackName=nested_id, LogicalResourceId="TerraformProject")["StackResourceDetail"]["PhysicalResourceId"]
    projects = session.client("codebuild").batch_get_projects(names=[project])
    require(not projects.get("projectsNotFound") and len(projects["projects"]) == 1,
            "Terraform project could not be resolved uniquely.")
    build = projects["projects"][0]
    require(build["arn"] == f"arn:aws:codebuild:{args.region}:{args.expected_account}:project/{project}",
            "Terraform project account or region differs from target.")
    write_json(private / "terraform-project.json", build)
    image = build["environment"]["image"]
    summary["terraformProject"] = {"name": project, "image": image}
    summary["runnerInspection"] = inspect_runner(session, image, args.expected_account, args.region, private) if args.inspect_runner else "Not requested"
    write_json(private / "summary.json", summary)
    return summary


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--profile", default="navigan")
    result.add_argument("--region", default="ap-south-1")
    result.add_argument("--environment", choices=("dev", "prod"), required=True)
    result.add_argument("--stack-name", required=True)
    result.add_argument("--expected-account", default="905418045935")
    result.add_argument("--expected-database", required=True)
    result.add_argument("--inspect-runner", action="store_true")
    return result


def main():
    args = parser().parse_args()
    os.umask(0o077)
    private = Path(tempfile.mkdtemp(prefix="navigan-bootstrap-audit-"))
    try:
        session = boto3.Session(profile_name=args.profile, region_name=args.region)
        summary = capture(session, args, private)
    except Exception as error:
        # Avoid exposing SDK responses, configuration or presigned URLs on error.
        reason = str(error) if type(error) is ValueError else type(error).__name__
        code = getattr(error, "response", {}).get("Error", {}).get("Code", "")
        if re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", code):
            reason += ": " + code
        raise SystemExit(f"Capture stopped: {reason}. Private capture: {private}") from None
    print(json.dumps(summary, indent=2))
    print(f"Private capture: {private}\nShare only summary.json; keep the remaining capture private.")


if __name__ == "__main__":
    main()
