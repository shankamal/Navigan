#!/usr/bin/env python3
"""Build and release the canonical Terraform runner to PROD without changing cluster resources.

The image is built from an exact git archive of the selected revision, not the working tree.
The full provisioning runner and full terraform/modules/aws-eks module are embedded by the
canonical Dockerfile. Preparation builds/pushes/verifies the image and creates a CloudFormation
change set that may update only the TerraformRunnerImageUri parameter and TerraformProject
environment image. Execution revalidates the immutable plan before applying it.
"""
from __future__ import annotations

import argparse
import base64
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import uuid

import boto3

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = "905418045935"
REGION = "ap-south-1"
PARENT = "navigan-custmanagement-cfnstk"
REPOSITORY = "navigan-terraform-runner"
FORMAT = "navigan-terraform-runner-prod-v1"
EXPECTED_BRANCH = "feature/eks-upgrade-readiness"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def run(args, *, cwd=None, input_bytes=None):
    return subprocess.run(
        args,
        cwd=cwd,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout.decode().strip()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()


def fingerprint(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def git_revision(revision):
    return run(["git", "rev-parse", revision + "^{commit}"], cwd=ROOT)


def branch():
    return run(["git", "branch", "--show-current"], cwd=ROOT)


def export_revision(revision, destination):
    archive = destination.parent / "source.tar"
    with archive.open("wb") as handle:
        subprocess.run(
            ["git", "archive", "--format=tar", revision],
            cwd=ROOT,
            stdout=handle,
            check=True,
        )
    destination.mkdir()
    with tarfile.open(archive) as handle:
        handle.extractall(destination)
    archive.unlink()


def docker_login(session, config):
    registry = f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com"
    auth = session.client("ecr").get_authorization_token(
        registryIds=[ACCOUNT]
    )["authorizationData"]
    item = next(
        value for value in auth
        if value["proxyEndpoint"] == "https://" + registry
    )
    username, password = base64.b64decode(item["authorizationToken"]).split(b":", 1)
    require(username == b"AWS", "Unexpected ECR login identity.")
    subprocess.run(
        [
            "docker", "--config", str(config), "login",
            "--username", "AWS", "--password-stdin", registry,
        ],
        input=password,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )


def build_image(session, source, revision, directory):
    ecr = session.client("ecr")
    ecr.describe_repositories(repositoryNames=[REPOSITORY])
    short = revision[:12]
    tag = f"canonical-{short}-{uuid.uuid4().hex[:10]}"
    repository_uri = f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/{REPOSITORY}"
    tagged = f"{repository_uri}:{tag}"
    with tempfile.TemporaryDirectory(prefix="navigan-runner-docker-") as config:
        docker_login(session, Path(config))
        subprocess.run(
            [
                "docker", "--config", config, "build",
                "--platform", "linux/amd64",
                "--tag", tagged,
                "--file", str(source / "provisioning/runner/Dockerfile"),
                str(source),
            ],
            check=True,
        )
        subprocess.run(
            ["docker", "--config", config, "push", tagged],
            check=True,
        )
    details = ecr.describe_images(
        repositoryName=REPOSITORY,
        imageIds=[{"imageTag": tag}],
    )["imageDetails"]
    require(
        len(details) == 1
        and re.fullmatch(r"sha256:[a-f0-9]{64}", details[0]["imageDigest"]),
        "Pushed runner digest is unavailable.",
    )
    pinned = repository_uri + "@" + details[0]["imageDigest"]
    verify_image(pinned, source, directory)
    return pinned


def verify_image(image, source, directory):
    container = run(["docker", "create", image])
    extracted = directory / "image"
    extracted.mkdir()
    try:
        subprocess.run(
            ["docker", "cp", f"{container}:/app/runner.py", str(extracted / "runner.py")],
            check=True,
        )
        subprocess.run(
            ["docker", "cp", f"{container}:/app/modules/aws-eks", str(extracted / "aws-eks")],
            check=True,
        )
    finally:
        subprocess.run(["docker", "rm", container], check=False, stdout=subprocess.PIPE)

    require(
        (extracted / "runner.py").read_bytes()
        == (source / "provisioning/runner/runner.py").read_bytes(),
        "Built runner.py differs from the selected git revision.",
    )
    expected = source / "terraform/modules/aws-eks"
    actual = extracted / "aws-eks"
    expected_files = sorted(
        p.relative_to(expected).as_posix()
        for p in expected.rglob("*") if p.is_file()
    )
    actual_files = sorted(
        p.relative_to(actual).as_posix()
        for p in actual.rglob("*") if p.is_file()
    )
    require(actual_files == expected_files, "Built Terraform module members differ.")
    for relative in expected_files:
        require(
            (actual / relative).read_bytes() == (expected / relative).read_bytes(),
            "Built Terraform module differs: " + relative,
        )

    main = (actual / "main.tf").read_text()
    required = [
        'resource "aws_security_group" "managed_nodes"',
        'resource "aws_vpc_security_group_ingress_rule" "managed_nodes_self"',
        'resource "aws_vpc_security_group_egress_rule" "managed_nodes_ipv4"',
        'resource "aws_vpc_security_group_ingress_rule" "managed_nodes_from_control_plane_https"',
        'resource "aws_vpc_security_group_ingress_rule" "managed_nodes_from_control_plane_kubelet"',
        'resource "aws_vpc_security_group_ingress_rule" "control_plane_from_managed_nodes_https"',
        "for_each = local.managed_node_groups",
        "[aws_security_group.managed_nodes.id]",
    ]
    require(all(value in main for value in required), "Canonical EKS module safeguards are missing.")


def stack_parameters(stack):
    return {
        item["ParameterKey"]: item.get("ParameterValue")
        for item in stack.get("Parameters", [])
    }


def stable_project_fingerprint(project):
    value = copy.deepcopy(project)
    value.pop("lastModified", None)
    value["environment"]["image"] = "<RUNNER_IMAGE>"
    return fingerprint(value)


def snapshot(session):
    cfn = session.client("cloudformation")
    root = cfn.describe_stacks(StackName=PARENT)["Stacks"][0]
    child_id = cfn.describe_stack_resource(
        StackName=PARENT, LogicalResourceId="ClusterManagement"
    )["StackResourceDetail"]["PhysicalResourceId"]
    child = cfn.describe_stacks(StackName=child_id)["Stacks"][0]
    project_name = cfn.describe_stack_resource(
        StackName=child_id, LogicalResourceId="TerraformProject"
    )["StackResourceDetail"]["PhysicalResourceId"]
    project = session.client("codebuild").batch_get_projects(
        names=[project_name]
    )["projects"][0]
    current = stack_parameters(root).get("TerraformRunnerImageUri")
    require(current == project["environment"]["image"], "Runner parameter/project image mismatch.")
    return {
        "rootId": root["StackId"],
        "rootStatus": root["StackStatus"],
        "childId": child["StackId"],
        "childStatus": child["StackStatus"],
        "projectName": project_name,
        "currentImage": current,
        "rootParameters": stack_parameters(root),
        "childParameters": stack_parameters(child),
        "projectFingerprint": fingerprint(project),
        "projectStableFingerprint": stable_project_fingerprint(project),
    }


def list_changes(cfn, change_set):
    result = []
    token = None
    while True:
        args = {"ChangeSetName": change_set}
        if token:
            args["NextToken"] = token
        response = cfn.describe_change_set(**args)
        result.extend(response.get("Changes", []))
        token = response.get("NextToken")
        if not token:
            return result


def processed_template(cfn, stack_id, change_set=None):
    args = {"StackName": stack_id, "TemplateStage": "Processed"}
    if change_set:
        args["ChangeSetName"] = change_set
    body = cfn.get_template(**args)["TemplateBody"]
    if isinstance(body, str):
        import yaml
        body = yaml.safe_load(body)
    require(isinstance(body, dict), "Processed CloudFormation template is invalid.")
    return body


def validate_dependency_change(resource, before, after):
    logical = resource.get("LogicalResourceId")
    require(
        logical in {"BuildStateRule", "BuildStatePermission"},
        "Unexpected dependent child resource: " + str(logical),
    )
    require(
        before.get(logical) == after.get(logical),
        "Dependent resource definition changed: " + logical,
    )
    require(
        resource.get("Action") == "Modify"
        and not resource.get("ChangeSetId")
        and resource.get("Details"),
        "Dependent resource is not an in-place dynamic modification: " + logical,
    )
    details = resource["Details"]
    require(
        all(detail.get("Target", {}).get("Attribute") == "Properties" for detail in details),
        "Dependent resource has a non-property change: " + logical,
    )
    if logical == "BuildStateRule":
        require(
            resource.get("ResourceType") == "AWS::Events::Rule"
            and resource.get("Replacement") == "False",
            "BuildStateRule replacement is not allowed.",
        )
        require(
            all(
                detail.get("Target", {}).get("Name") == "EventPattern"
                and detail.get("Target", {}).get("RequiresRecreation") == "Never"
                and detail.get("Evaluation") == "Dynamic"
                and detail.get("ChangeSource") == "ResourceReference"
                and detail.get("CausingEntity") == "TerraformProject"
                for detail in details
            ),
            "BuildStateRule change is not the verified TerraformProject Ref dependency.",
        )
    else:
        require(
            resource.get("ResourceType") == "AWS::Lambda::Permission"
            and resource.get("Replacement") == "Conditional",
            "BuildStatePermission replacement contract changed.",
        )
        require(
            all(
                detail.get("Target", {}).get("Name") == "SourceArn"
                and detail.get("Target", {}).get("RequiresRecreation") == "Always"
                and detail.get("Evaluation") == "Dynamic"
                and detail.get("ChangeSource") == "ResourceAttribute"
                and detail.get("CausingEntity") == "BuildStateRule.Arn"
                for detail in details
            ),
            "BuildStatePermission change is not the verified BuildStateRule ARN dependency.",
        )


def validate_child_preview(session, plan):
    cfn = session.client("cloudformation")
    preview = plan["childPreview"]
    meta = cfn.describe_change_set(ChangeSetName=preview)
    require(
        meta["StackId"] == plan["baseline"]["childId"]
        and meta["Status"] == "CREATE_COMPLETE"
        and meta["ExecutionStatus"] == "AVAILABLE"
        and not meta.get("ParentChangeSetId"),
        "Direct ClusterManagement preview is unavailable or targets another stack.",
    )
    chosen = stack_parameters(meta)
    before = plan["baseline"]["childParameters"]
    require(
        chosen.get("TerraformRunnerImageUri") == plan["newImage"],
        "Direct child preview runner parameter changed.",
    )
    require(
        set(chosen) == set(before)
        and all(
            chosen[key] == value
            for key, value in before.items()
            if key != "TerraformRunnerImageUri"
        ),
        "Direct child preview changes unrelated parameters.",
    )
    before_template = processed_template(cfn, plan["baseline"]["childId"])
    after_template = processed_template(cfn, plan["baseline"]["childId"], preview)
    require(
        fingerprint(before_template) == fingerprint(after_template),
        "Cluster Management template changed; runner-only release is blocked.",
    )
    before_resources = before_template.get("Resources", {})
    after_resources = after_template.get("Resources", {})
    seen = set()
    for entry in list_changes(cfn, preview):
        resource = entry["ResourceChange"]
        logical = resource.get("LogicalResourceId")
        require(logical not in seen, "Duplicate child preview resource: " + str(logical))
        seen.add(logical)
        print(
            "  Direct child preview: "
            + str(logical)
            + " "
            + str(resource.get("Action"))
            + " replacement="
            + str(resource.get("Replacement")),
            flush=True,
        )
        if logical == "TerraformProject":
            require(
                resource["ResourceType"] == "AWS::CodeBuild::Project"
                and resource["Action"] == "Modify"
                and resource.get("Replacement") == "False"
                and not resource.get("ChangeSetId"),
                "Unexpected TerraformProject change.",
            )
            require(
                resource.get("Details")
                and all(
                    detail.get("Target", {}).get("Attribute") == "Properties"
                    and detail.get("Target", {}).get("Name") == "Environment"
                    and detail.get("Target", {}).get("RequiresRecreation") == "Never"
                    for detail in resource["Details"]
                ),
                "Only the CodeBuild Environment image may change.",
            )
        else:
            validate_dependency_change(resource, before_resources, after_resources)
    require("TerraformProject" in seen, "TerraformProject change is missing.")
    require(
        seen <= {"TerraformProject", "BuildStateRule", "BuildStatePermission"},
        "Unexpected direct child resource change set.",
    )


def validate_change_set(session, plan):
    cfn = session.client("cloudformation")
    parent = cfn.describe_change_set(ChangeSetName=plan["changeSet"])
    require(parent["StackId"] == plan["baseline"]["rootId"], "Wrong parent stack.")
    require(parent["Status"] == "CREATE_COMPLETE", "Change set is not ready.")
    require(
        parent.get("IncludeNestedStacks") is False,
        "Parent execution plan must not contain precomputed nested child plans.",
    )
    chosen = stack_parameters(parent)
    before = plan["baseline"]["rootParameters"]
    require(
        chosen.get("TerraformRunnerImageUri") == plan["newImage"],
        "Prepared runner parameter changed.",
    )
    require(
        set(chosen) == set(before)
        and all(
            chosen[key] == value
            for key, value in before.items()
            if key != "TerraformRunnerImageUri"
        ),
        "An unrelated parent parameter changed.",
    )
    parent_changes = list_changes(cfn, plan["changeSet"])
    require(
        len(parent_changes) == 1,
        "Only ClusterManagement may change in the parent execution plan.",
    )
    change = parent_changes[0]["ResourceChange"]
    require(
        change["LogicalResourceId"] == "ClusterManagement"
        and change["ResourceType"] == "AWS::CloudFormation::Stack"
        and change["Action"] == "Modify"
        and change.get("Replacement") == "False"
        and not change.get("ChangeSetId"),
        "Unexpected parent change.",
    )
    validate_child_preview(session, plan)

def prepare(session, revision):
    require(session.client("sts").get_caller_identity()["Account"] == ACCOUNT, "Wrong AWS account.")
    exact = git_revision(revision)
    directory = Path(tempfile.mkdtemp(prefix="navigan-terraform-runner-prod-"))
    source = directory / "source"
    export_revision(exact, source)
    image = build_image(session, source, exact, directory)
    baseline = snapshot(session)
    require(baseline["rootStatus"] in {"CREATE_COMPLETE", "UPDATE_COMPLETE"}, "Parent stack is not stable.")
    require(baseline["childStatus"] in {"CREATE_COMPLETE", "UPDATE_COMPLETE"}, "Cluster stack is not stable.")

    cfn = session.client("cloudformation")
    root = cfn.describe_stacks(StackName=PARENT)["Stacks"][0]
    child = cfn.describe_stacks(StackName=baseline["childId"])["Stacks"][0]

    child_parameters = []
    for item in child.get("Parameters", []):
        child_parameters.append({
            "ParameterKey": item["ParameterKey"],
            **(
                {"ParameterValue": image}
                if item["ParameterKey"] == "TerraformRunnerImageUri"
                else {"UsePreviousValue": True}
            ),
        })
    child_request = {
        "StackName": baseline["childId"],
        "ChangeSetName": "navigan-terraform-runner-child-" + uuid.uuid4().hex[:16],
        "ChangeSetType": "UPDATE",
        "UsePreviousTemplate": True,
        "IncludeNestedStacks": False,
        "Capabilities": ["CAPABILITY_NAMED_IAM", "CAPABILITY_AUTO_EXPAND"],
        "Parameters": child_parameters,
    }
    if child.get("RoleARN"):
        child_request["RoleARN"] = child["RoleARN"]
    child_preview = cfn.create_change_set(**child_request)["Id"]
    cfn.get_waiter("change_set_create_complete").wait(
        ChangeSetName=child_preview,
        WaiterConfig={"Delay": 5, "MaxAttempts": 180},
    )

    parameters = []
    for item in root.get("Parameters", []):
        parameters.append({
            "ParameterKey": item["ParameterKey"],
            **(
                {"ParameterValue": image}
                if item["ParameterKey"] == "TerraformRunnerImageUri"
                else {"UsePreviousValue": True}
            ),
        })
    request = {
        "StackName": PARENT,
        "ChangeSetName": "navigan-terraform-runner-" + uuid.uuid4().hex[:16],
        "ChangeSetType": "UPDATE",
        "UsePreviousTemplate": True,
        "IncludeNestedStacks": False,
        "Capabilities": ["CAPABILITY_NAMED_IAM", "CAPABILITY_AUTO_EXPAND"],
        "Parameters": parameters,
    }
    if root.get("RoleARN"):
        request["RoleARN"] = root["RoleARN"]
    change_set = cfn.create_change_set(**request)["Id"]
    cfn.get_waiter("change_set_create_complete").wait(
        ChangeSetName=change_set, WaiterConfig={"Delay": 5, "MaxAttempts": 180}
    )
    plan = {
        "format": FORMAT,
        "account": ACCOUNT,
        "region": REGION,
        "parent": PARENT,
        "sourceRevision": exact,
        "newImage": image,
        "childPreview": child_preview,
        "changeSet": change_set,
        "baseline": baseline,
        "preparedAt": datetime.now(timezone.utc).isoformat(),
    }
    try:
        validate_change_set(session, plan)
    except Exception:
        for rejected in (change_set, child_preview):
            try:
                cfn.delete_change_set(ChangeSetName=rejected)
            except Exception:
                pass
        raise
    path = directory / "release-plan.json"
    write(path, plan)
    print("Canonical runner prepared and scope-checked:", image)
    print("Direct child preview:", child_preview)
    print("Parent execution change set:", change_set)
    print("Release plan:", path)
    print("No production change has been executed.")
    return path


def execute(session, path):
    plan = read(path)
    require(
        (plan.get("format"), plan.get("account"), plan.get("region"), plan.get("parent"))
        == (FORMAT, ACCOUNT, REGION, PARENT),
        "Unexpected release plan.",
    )
    before = snapshot(session)
    require(
        before["currentImage"] == plan["baseline"]["currentImage"]
        and before["projectFingerprint"] == plan["baseline"]["projectFingerprint"],
        "PROD runner changed since preparation; prepare a fresh plan.",
    )
    validate_change_set(session, plan)
    cfn = session.client("cloudformation")
    cfn.execute_change_set(ChangeSetName=plan["changeSet"])
    cfn.get_waiter("stack_update_complete").wait(
        StackName=PARENT, WaiterConfig={"Delay": 10, "MaxAttempts": 180}
    )
    after = snapshot(session)
    require(after["currentImage"] == plan["newImage"], "Runner image deployment verification failed.")
    require(
        after["projectStableFingerprint"]
        == plan["baseline"]["projectStableFingerprint"],
        "Unexpected CodeBuild project change detected.",
    )
    verification = {
        "format": FORMAT,
        "sourceRevision": plan["sourceRevision"],
        "runnerImage": plan["newImage"],
        "childPreview": plan["childPreview"],
        "verifiedAt": datetime.now(timezone.utc).isoformat(),
        "deploymentPerformed": True,
    }
    write(path.parent / "verification.json", verification)
    print("PROD canonical Terraform runner deployed and verified.")
    print("No Terraform plan/apply was started for any cluster.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="navigan")
    parser.add_argument("--revision", default="HEAD")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--prepare", action="store_true")
    modes.add_argument("--execute", type=Path, metavar="PLAN")
    args = parser.parse_args()
    os.umask(0o077)
    require(branch() == EXPECTED_BRANCH, "Use the feature/eks-upgrade-readiness checkout.")
    session = boto3.Session(profile_name=args.profile, region_name=REGION)
    if args.prepare:
        prepare(session, args.revision)
    else:
        execute(session, args.execute.resolve())


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        reason = str(error) if isinstance(error, ValueError) else type(error).__name__
        raise SystemExit("Runner release stopped: " + reason + ".") from None
