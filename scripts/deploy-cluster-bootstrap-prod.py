#!/usr/bin/env python3
"""Release only bootstrap prevention to PROD using captured live packages.

--prepare builds/pushes an overlay runner and stages a scoped CloudFormation
change set. --apply additionally executes it after strict scope checks.
--execute PLAN resumes an unchanged prepared release. Existing clusters are not
reprovisioned and no installer build is started. Private records stay local.
With --preview-change-set, a verified concrete child preview permits replanning
the parent without unresolved nested previews. The rejected hierarchy and the
diagnostic child preview are never executed.
"""
from __future__ import annotations

import argparse
import base64
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
from urllib.parse import quote
import uuid

import boto3

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT, REGION, PARENT = "905418045935", "ap-south-1", "navigan-custmanagement-cfnstk"
FUNCTIONS = ("ClusterFunction", "StatusFunction")
FORMAT = "navigan-bootstrap-prod-v1"
CONFIG_KEYS = ("FunctionArn", "FunctionName", "Role", "Handler", "Runtime", "Timeout", "MemorySize",
               "Environment", "VpcConfig", "Layers", "Architectures", "TracingConfig", "KMSKeyArn",
               "DeadLetterConfig", "FileSystemConfigs", "EphemeralStorage", "SnapStart", "LoggingConfig")


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit = load("bootstrap_runtime_audit", "audit-cluster-bootstrap-runtime.py")
patch = load("bootstrap_runtime_patch", "cluster-bootstrap-patch.py")
storage = load("bootstrap_storage", "deploy-migration-storage-prod.py")
references = load("bootstrap_reference_proof", "cluster-bootstrap-reference-proof.py")
require = patch.require


def read(path):
    return json.loads(path.read_text())


def digest(value):
    return hashlib.sha256(value).hexdigest()


def fingerprint(value):
    return digest(json.dumps(value, sort_keys=True, default=str).encode())


def code_hash(path):
    return base64.b64encode(hashlib.sha256(path.read_bytes()).digest()).decode()


def stamp(stack):
    return str(stack.get("LastUpdatedTime") or stack["CreationTime"])


def baseline(directory):
    summary = read(directory / "summary.json")
    require((summary.get("environment"), summary.get("account"), summary.get("region"), summary.get("stackName"))
            == ("prod", ACCOUNT, REGION, PARENT), "Capture is not the requested production deployment.")
    require(isinstance(summary.get("runnerInspection"), dict), "Capture must include --inspect-runner.")
    root, child = read(directory / "root-stack.json"), read(directory / "cluster-stack.json")
    audit.validate_stack(root, ACCOUNT, REGION)
    audit.validate_stack(child, ACCOUNT, REGION, root["StackId"])
    configs = {name: read(directory / (name + "-config.json")) for name in FUNCTIONS}
    for name, config in configs.items():
        require(config["CodeSha256"] == code_hash(directory / (name + ".zip")), "Captured ZIP checksum mismatch.")
        require(config.get("Environment", {}).get("Variables", {}).get("DB_NAME") == "navigan", "Not PROD database.")
    project = read(directory / "terraform-project.json")
    image = project["environment"]["image"]
    require(image == summary["runnerInspection"]["resolvedImage"] and
            re.fullmatch(rf"{ACCOUNT}\.dkr\.ecr\.{REGION}\.amazonaws\.com/navigan-terraform-runner@sha256:[a-f0-9]{{64}}", image),
            "Expected the captured immutable production runner image.")
    runner = directory / "runner"
    require(digest((runner / "runner.py").read_bytes()) == summary["runnerInspection"]["runnerSha256"],
            "Captured runner checksum mismatch.")
    return {"directory": directory, "summary": summary, "root": root, "child": child, "configs": configs,
            "project": project, "image": image, "rootTemplate": read(directory / "root-template.json"),
            "childTemplate": read(directory / "cluster-template.json")}


def parameters(stack):
    return {item["ParameterKey"]: item.get("ParameterValue") for item in stack.get("Parameters", [])}


def preflight(session, saved):
    require(session.client("sts").get_caller_identity()["Account"] == ACCOUNT, "Wrong AWS account.")
    cfn = session.client("cloudformation")
    for key, logical in (("root", None), ("child", "ClusterManagement")):
        old = saved[key]
        stack = cfn.describe_stacks(StackName=PARENT if key == "root" else old["StackId"])["Stacks"][0]
        audit.validate_stack(stack, ACCOUNT, REGION, saved["root"]["StackId"] if logical else None)
        require(stack["StackId"] == old["StackId"] and stamp(stack) == stamp(old), "Stack changed since capture; rerun audit.")
        require(parameters(stack).get("DatabaseName") == "navigan", "Not the PROD database.")
        require(parameters(stack).get("TerraformRunnerImageUri") == saved["image"], "Runner parameter differs from captured project.")
        actual = audit.template_body(cfn.get_template(StackName=stack["StackId"], TemplateStage="Processed")["TemplateBody"])
        require(fingerprint(actual) == fingerprint(saved[key + "Template"]), "Processed template changed since capture.")
    child_id = cfn.describe_stack_resource(StackName=PARENT, LogicalResourceId="ClusterManagement")["StackResourceDetail"]["PhysicalResourceId"]
    require(child_id == saved["child"]["StackId"], "Cluster nested stack changed.")
    resources = saved["rootTemplate"]["Resources"]
    require(resources["ClusterManagement"]["Properties"]["Parameters"]["TerraformRunnerImageUri"] == {"Ref": "TerraformRunnerImageUri"},
            "Unexpected root runner parameter binding.")
    references = {key for key, resource in resources.items() if '"Ref": "TerraformRunnerImageUri"' in json.dumps(resource)}
    require(references == {"ClusterManagement"}, "Runner parameter affects resources outside ClusterManagement.")
    require(saved["childTemplate"]["Resources"]["TerraformProject"]["Properties"]["Environment"]["Image"]
            == {"Ref": "TerraformRunnerImageUri"}, "Unexpected CodeBuild runner parameter binding.")
    for logical, old in saved["configs"].items():
        physical = cfn.describe_stack_resource(StackName=child_id, LogicalResourceId=logical)["StackResourceDetail"]["PhysicalResourceId"]
        require(physical == old["FunctionName"], "Lambda binding changed.")
        config = session.client("lambda").get_function_configuration(FunctionName=physical)
        require(config.get("State") == "Active" and config.get("LastUpdateStatus") == "Successful", "Lambda is not stable.")
        require(config["RevisionId"] == old["RevisionId"] and config["CodeSha256"] == old["CodeSha256"], "Lambda changed since capture.")
        require(all(config.get(k) == old.get(k) for k in CONFIG_KEYS), "Lambda configuration changed since capture.")
    project_name = cfn.describe_stack_resource(StackName=child_id, LogicalResourceId="TerraformProject")["StackResourceDetail"]["PhysicalResourceId"]
    require(project_name == saved["project"]["name"], "Terraform project binding changed.")
    response = session.client("codebuild").batch_get_projects(names=[project_name])
    require(not response.get("projectsNotFound") and len(response.get("projects", [])) == 1, "Terraform project missing.")
    require(fingerprint(response["projects"][0]) == fingerprint(saved["project"]), "Terraform project changed since capture.")


def docker_login(session, config):
    registry = f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com"
    auth = session.client("ecr").get_authorization_token(registryIds=[ACCOUNT])["authorizationData"]
    item = next((a for a in auth if a["proxyEndpoint"] == "https://" + registry), None)
    require(item, "Unexpected ECR registry.")
    username, password = base64.b64decode(item["authorizationToken"]).split(b":", 1)
    require(username == b"AWS", "Unexpected ECR identity.")
    audit.docker(config, "login", "--username", "AWS", "--password-stdin", registry, payload=password)


def runner_overlay(session, saved, directory):
    print("Verifying the deployed runner image and preparing a narrow overlay...", flush=True)
    observed = directory / "base-verification"
    observed.mkdir(mode=0o700)
    audit.inspect_runner(session, saved["image"], ACCOUNT, REGION, observed)
    captured = saved["directory"] / "runner"
    live = observed / "runner"
    require((captured / "runner.py").read_bytes() == (live / "runner.py").read_bytes(), "Runner capture differs from the base image.")
    require({p.name for p in (captured / "aws-eks").iterdir()} == {p.name for p in (live / "aws-eks").iterdir()}, "Module capture members differ.")
    for path in (captured / "aws-eks").iterdir():
        require(path.is_file() and path.read_bytes() == (live / "aws-eks" / path.name).read_bytes(), "Module capture differs from the base image.")
    context = directory / "runner-build"
    context.mkdir(mode=0o700)
    (context / "runner.py").write_text(patch.patch_runner((captured / "runner.py").read_text()))
    main, variables = patch.patch_module((captured / "aws-eks/main.tf").read_text(), (captured / "aws-eks/variables.tf").read_text())
    (context / "main.tf").write_text(main)
    (context / "variables.tf").write_text(variables)
    (context / "Dockerfile").write_text(
        f"FROM {saved['image']}\nUSER root\n"
        "COPY runner.py /app/runner.py\nCOPY main.tf /app/modules/aws-eks/main.tf\n"
        "COPY variables.tf /app/modules/aws-eks/variables.tf\n"
        "RUN terraform fmt /app/modules/aws-eks/main.tf /app/modules/aws-eks/variables.tf "
        "&& terraform fmt -check /app/modules/aws-eks/main.tf /app/modules/aws-eks/variables.tf\nUSER navigan\n")
    repository = "navigan-terraform-runner"
    ecr = session.client("ecr")
    ecr.describe_repositories(repositoryNames=[repository])
    tag = "bootstrap-fix-" + uuid.uuid4().hex
    image = f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/{repository}:{tag}"
    with tempfile.TemporaryDirectory(prefix="navigan-bootstrap-ecr-") as config:
        docker_login(session, Path(config))
        print("Building the overlay; existing runner dependencies and unrelated behavior are retained.", flush=True)
        audit.docker(Path(config), "build", "--platform", "linux/amd64", "--network", "none", "--tag", image, str(context))
        audit.docker(Path(config), "push", image)
    records = ecr.describe_images(repositoryName=repository, imageIds=[{"imageTag": tag}])["imageDetails"]
    require(len(records) == 1 and re.fullmatch(r"sha256:[a-f0-9]{64}", records[0]["imageDigest"]), "Pushed image digest unavailable.")
    pinned = image.rsplit(":", 1)[0] + "@" + records[0]["imageDigest"]
    check = directory / "overlay-verification"
    check.mkdir(mode=0o700)
    report = audit.inspect_runner(session, pinned, ACCOUNT, REGION, check)
    require(report["protectedPoolGuardPresent"], "Built runner guard missing.")
    require((check / "runner/runner.py").read_bytes() == (context / "runner.py").read_bytes(), "Built runner differs from prepared overlay.")
    for name in ("main.tf", "variables.tf"):
        require(audit.hcl_tokens((check / "runner/aws-eks" / name).read_text()) == audit.hcl_tokens((context / name).read_text()), "Built module differs from prepared overlay.")
    for path in (captured / "aws-eks").iterdir():
        if path.name not in {"main.tf", "variables.tf"}:
            require(path.read_bytes() == (check / "runner/aws-eks" / path.name).read_bytes(), "Unrelated module file changed.")
    print("Overlay verified: " + pinned, flush=True)
    return pinned


def proposed_templates(saved, codes, child_url=None):
    child = copy.deepcopy(saved["childTemplate"])
    for name in FUNCTIONS:
        require(child["Resources"][name]["Type"] == "AWS::Lambda::Function", "Expected Lambda resource.")
        child["Resources"][name]["Properties"]["Code"] = codes[name]
    root = copy.deepcopy(saved["rootTemplate"])
    if child_url is not None:
        root["Resources"]["ClusterManagement"]["Properties"]["TemplateURL"] = child_url
    return root, child


def validate_templates(saved, root, child):
    expected_root = copy.deepcopy(saved["rootTemplate"])
    expected_root["Resources"]["ClusterManagement"]["Properties"]["TemplateURL"] = root["Resources"]["ClusterManagement"]["Properties"]["TemplateURL"]
    require(expected_root == root, "Unrelated root template changes rejected.")
    expected_child = copy.deepcopy(saved["childTemplate"])
    for name in FUNCTIONS:
        code = child["Resources"][name]["Properties"]["Code"]
        require(set(code) == {"S3Bucket", "S3Key", "S3ObjectVersion"} and code["S3ObjectVersion"] not in (None, "", "null"), "Versioned Lambda code required.")
        expected_child["Resources"][name]["Properties"]["Code"] = code
    require(expected_child == child, "Only the two Lambda Code properties may change in the child template.")


def items(client, operation, key, **kwargs):
    result, token = [], None
    while True:
        response = getattr(client, operation)(**kwargs, **({"NextToken": token} if token else {}))
        result.extend(response.get(key, []))
        token = response.get("NextToken")
        if not token:
            return result


def proof_context():
    return SimpleNamespace(require=require, ACCOUNT=ACCOUNT, REGION=REGION, PARENT=PARENT,
                           parameters=parameters, stamp=stamp, audit=audit, FUNCTIONS=FUNCTIONS,
                           items=items, fingerprint=fingerprint)


def inspect_change_set(cfn, saved, plan, reference_proof=None):
    if reference_proof is not None:
        require(reference_proof.get("releaseChangeSet") == plan["changeSet"]
                and reference_proof.get("childHash") == plan["childHash"]
                and reference_proof.get("newImage") == plan["newImage"]
                and reference_proof.get("snapshot") and reference_proof.get("inputs"), "Reference proof belongs to another release.")
    root = cfn.describe_change_set(ChangeSetName=plan["changeSet"])
    require(root["StackId"] == saved["root"]["StackId"] and root["Status"] == "CREATE_COMPLETE"
            and root["ExecutionStatus"] == "AVAILABLE", "Change set is unavailable or targets another stack.")
    chosen = parameters(root)
    require(chosen.get("TerraformRunnerImageUri") == plan["newImage"], "Prepared runner parameter changed.")
    old_parameters = parameters(saved["root"])
    require(set(chosen) == set(old_parameters) and all(
        chosen[key] == value for key, value in old_parameters.items() if key != "TerraformRunnerImageUri"),
        "Unrelated root parameter changes rejected.")
    changes = items(cfn, "describe_change_set", "Changes", ChangeSetName=plan["changeSet"])
    require(len(changes) == 1, "Only ClusterManagement may change in the root stack.")
    change = changes[0]["ResourceChange"]
    require((change["LogicalResourceId"], change["ResourceType"], change["Action"], change.get("Replacement"))
            == ("ClusterManagement", "AWS::CloudFormation::Stack", "Modify", "False") and change.get("ChangeSetId"),
            "Unexpected root change or replacement.")
    child_id = change["ChangeSetId"]
    child_meta = cfn.describe_change_set(ChangeSetName=child_id)
    require(child_meta["StackId"] == saved["child"]["StackId"], "Wrong nested change-set target.")
    root_template = audit.template_body(cfn.get_template(StackName=saved["root"]["StackId"], ChangeSetName=plan["changeSet"], TemplateStage="Processed")["TemplateBody"])
    child_template = audit.template_body(cfn.get_template(StackName=saved["child"]["StackId"], ChangeSetName=child_id, TemplateStage="Processed")["TemplateBody"])
    require(fingerprint(root_template) == plan["rootHash"] and fingerprint(child_template) == plan["childHash"], "Prepared templates changed.")
    validate_templates(saved, root_template, child_template)
    seen = set()
    for entry in items(cfn, "describe_change_set", "Changes", ChangeSetName=child_id):
        resource = entry["ResourceChange"]
        logical, kind = resource["LogicalResourceId"], resource["ResourceType"]
        if logical in FUNCTIONS:
            require(resource["Action"] == "Modify" and resource.get("Replacement") == "False" and not resource.get("ChangeSetId"), "Lambda creation/deletion/replacement rejected.")
            require(kind == "AWS::Lambda::Function", "Unexpected function resource type.")
            allowed_property = "Code"
        elif logical == "TerraformProject":
            require(resource["Action"] == "Modify" and resource.get("Replacement") == "False" and not resource.get("ChangeSetId"), "Project creation/deletion/replacement rejected.")
            require(kind == "AWS::CodeBuild::Project", "Unexpected runner project type.")
            allowed_property = "Environment"
        else:
            if reference_proof is not None:
                references.dependency(proof_context(), resource, saved["childTemplate"]["Resources"], child_template["Resources"], concrete=False)
            else:
                require(resource["Action"] == "Modify" and resource.get("Replacement") == "False" and not resource.get("ChangeSetId"), "Resource creation/deletion/replacement rejected.")
                require(kind in {"AWS::ApiGatewayV2::Integration", "AWS::ApiGatewayV2::Route", "AWS::Lambda::Permission"}
                        and saved["childTemplate"]["Resources"].get(logical) == child_template["Resources"].get(logical),
                        "Unrelated resource change rejected: " + logical)
                text = json.dumps(child_template["Resources"][logical])
                require(any(name in text for name in FUNCTIONS), "Unrelated dependency change rejected: " + logical)
            allowed_property = None
        if allowed_property:
            require(resource.get("Details") and all(
                detail.get("Target", {}).get("Attribute") == "Properties"
                and detail.get("Target", {}).get("Name") == allowed_property
                for detail in resource["Details"]), "Unrelated property change rejected: " + logical)
        seen.add(logical)
        suffix = "; independent binding/ARN proof verified" if reference_proof is not None and logical not in {*FUNCTIONS, "TerraformProject"} else ""
        print(f"  Modify {logical} ({kind}); reported replacement={resource.get('Replacement')}{suffix}", flush=True)
    require(set(FUNCTIONS) | {"TerraformProject"} <= seen, "Expected both Lambda code changes and runner project update.")


def upload(session, workspace, name, data):
    key = "deployment-packages/prod-cluster-bootstrap/" + digest(data) + "/" + name
    response = session.client("s3").put_object(Bucket=workspace["WorkspaceBucketName"], Key=key, Body=data,
        ExpectedBucketOwner=ACCOUNT, ServerSideEncryption="aws:kms", SSEKMSKeyId=workspace["WorkspaceKmsKeyArn"])
    version = response.get("VersionId")
    require(version not in (None, "", "null"), "Versioned deployment storage is required.")
    code = {"S3Bucket": workspace["WorkspaceBucketName"], "S3Key": key, "S3ObjectVersion": version}
    url = f"https://{workspace['WorkspaceBucketName']}.s3.{REGION}.amazonaws.com/{key}?versionId={quote(version, safe='')}"
    return code, url


def prepare(session, capture):
    saved = baseline(capture)
    preflight(session, saved)
    directory = Path(tempfile.mkdtemp(prefix="navigan-bootstrap-release-"))
    print("Private release record: " + str(directory), flush=True)
    snapshot = directory / "baseline"
    shutil.copytree(capture, snapshot)
    saved = baseline(snapshot)
    for name in FUNCTIONS:
        patch.patch_package(snapshot / (name + ".zip"), directory / (name + "-updated.zip"), polling=name == "ClusterFunction")
    # Patch validation precedes ECR uploads and any CloudFormation mutation.
    workspace = storage.verify_storage(session, "artifact-workspace")
    image = runner_overlay(session, saved, directory)
    preflight(session, saved)
    codes = {name: upload(session, workspace, name + ".zip", (directory / (name + "-updated.zip")).read_bytes())[0] for name in FUNCTIONS}
    _, child = proposed_templates(saved, codes)
    _, child_url = upload(session, workspace, "cluster-template.json", json.dumps(child).encode())
    root, child = proposed_templates(saved, codes, child_url)
    validate_templates(saved, root, child)
    audit.write_json(directory / "root-updated-template.json", root)
    audit.write_json(directory / "cluster-updated-template.json", child)
    _, root_url = upload(session, workspace, "root-template.json", json.dumps(root).encode())
    preflight(session, saved)
    cfn = session.client("cloudformation")
    request = {"StackName": PARENT, "ChangeSetName": "navigan-bootstrap-" + uuid.uuid4().hex[:16],
               "ChangeSetType": "UPDATE", "TemplateURL": root_url, "IncludeNestedStacks": True,
               "Capabilities": ["CAPABILITY_NAMED_IAM", "CAPABILITY_AUTO_EXPAND"],
               "Parameters": [{"ParameterKey": item["ParameterKey"], **(
                   {"ParameterValue": image} if item["ParameterKey"] == "TerraformRunnerImageUri" else {"UsePreviousValue": True})}
                   for item in saved["root"].get("Parameters", [])]}
    if saved["root"].get("RoleARN"):
        request["RoleARN"] = saved["root"]["RoleARN"]
    identifier = cfn.create_change_set(**request)["Id"]
    plan = {"format": FORMAT, "account": ACCOUNT, "region": REGION, "parent": PARENT,
            "baseline": str(snapshot), "changeSet": identifier, "newImage": image,
            "rootHash": fingerprint(root), "childHash": fingerprint(child),
            "newCodeHashes": {name: code_hash(directory / (name + "-updated.zip")) for name in FUNCTIONS}}
    path = directory / "release-plan.json"
    audit.write_json(path, plan)
    print("Prepared change set: " + identifier, flush=True)
    cfn.get_waiter("change_set_create_complete").wait(ChangeSetName=identifier, WaiterConfig={"Delay": 5, "MaxAttempts": 180})
    inspect_change_set(cfn, saved, plan)
    print("Prepared and scope-checked; release plan: " + str(path), flush=True)
    return path


def execute(session, path, preview_change_set=None):
    plan = read(path)
    require((plan.get("format"), plan.get("account"), plan.get("region"), plan.get("parent")) == (FORMAT, ACCOUNT, REGION, PARENT), "Unexpected release plan.")
    require(re.fullmatch(rf"{ACCOUNT}\.dkr\.ecr\.{REGION}\.amazonaws\.com/navigan-terraform-runner@sha256:[a-f0-9]{{64}}", plan["newImage"]), "Unexpected runner target.")
    saved = baseline(Path(plan["baseline"]))
    preflight(session, saved)
    cfn = session.client("cloudformation")
    proof = references.verify(proof_context(), session, saved, plan, preview_change_set) if preview_change_set else None
    if proof is not None:
        audit.write_json(path.parent / "reference-proof.json", proof)
        print("Concrete preview and unchanged parent parameter/API/ARN identities verified.", flush=True)
        print("Reviewing the original hierarchy for context only; it will not be executed.", flush=True)
    inspect_change_set(cfn, saved, plan, reference_proof=proof)
    preflight(session, saved)
    execution_id = plan["changeSet"]
    if proof is not None:
        execution_id = references.parent_plan(proof_context(), session, saved, plan, path.parent)
        preflight(session, saved)
        references.unchanged(proof_context(), session, saved, plan, proof)
        references.inspect_parent(proof_context(), cfn, saved, plan, execution_id)
    cfn.execute_change_set(ChangeSetName=execution_id)
    print("Executing the scoped bootstrap release...", flush=True)
    cfn.get_waiter("stack_update_complete").wait(StackName=PARENT, WaiterConfig={"Delay": 10, "MaxAttempts": 180})
    for key in ("root", "child"):
        stack = cfn.describe_stacks(StackName=saved[key]["StackId"])["Stacks"][0]
        require(stack["StackStatus"] == "UPDATE_COMPLETE", "Stack update did not complete successfully.")
        require(parameters(stack).get("TerraformRunnerImageUri") == plan["newImage"], "Runner parameter verification failed.")
        actual = audit.template_body(cfn.get_template(StackName=stack["StackId"], TemplateStage="Processed")["TemplateBody"])
        require(fingerprint(actual) == plan[key + "Hash"], "Deployed template differs from scoped plan.")
    for name, old in saved["configs"].items():
        config = session.client("lambda").get_function_configuration(FunctionName=old["FunctionName"])
        require(config["CodeSha256"] == plan["newCodeHashes"][name] and config.get("State") == "Active"
                and config.get("LastUpdateStatus") == "Successful", "Deployed Lambda package verification failed.")
        require(all(config.get(k) == old.get(k) for k in CONFIG_KEYS), "Unrelated Lambda configuration changed.")
    current = session.client("codebuild").batch_get_projects(names=[saved["project"]["name"]])["projects"][0]
    old_project = copy.deepcopy(saved["project"])
    old_project["environment"]["image"] = plan["newImage"]
    old_project.pop("lastModified", None)
    current.pop("lastModified", None)
    require(fingerprint(current) == fingerprint(old_project), "Unrelated CodeBuild project configuration changed.")
    if proof is not None:
        references.after_deployment(proof_context(), session, saved, proof)
    audit.write_json(path.parent / "verification.json", {"verifiedAt": datetime.now(timezone.utc).isoformat(),
        "changeSet": execution_id, "sourceChangeSet": plan["changeSet"],
        "previewChangeSet": preview_change_set, "runnerImage": plan["newImage"], "codeHashes": plan["newCodeHashes"]})
    print("PROD bootstrap release verified: two Lambda packages and the pinned runner updated. Existing clusters were not reprovisioned. A fresh-cluster acceptance test is now required.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="navigan")
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--preview-change-set", help="With --execute, independently verify a concrete child-stack preview and unchanged nested references")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--prepare", action="store_true")
    modes.add_argument("--apply", action="store_true")
    modes.add_argument("--execute", type=Path, metavar="PLAN")
    args = parser.parse_args()
    require(not args.preview_change_set or args.execute, "--preview-change-set requires --execute PLAN.")
    os.umask(0o077)
    require(subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip() == "new_migration_approach_18oct26", "Use the existing project feature-branch checkout.")
    paths = ["scripts/deploy-cluster-bootstrap-prod.py", "scripts/cluster-bootstrap-patch.py", "scripts/cluster-bootstrap-reference-proof.py", "scripts/audit-cluster-bootstrap-runtime.py",
             "scripts/deploy-migration-storage-prod.py", "src/navigan/modules/cluster_management/connector_installation.py",
             "src/navigan/modules/cluster_management/bootstrap_status.py", "provisioning/runner/runner.py"]
    require(not subprocess.check_output(["git", "status", "--porcelain", "--", *paths], cwd=ROOT, text=True).strip(), "Release inputs have local changes; preserve and review them before deployment.")
    session = boto3.Session(profile_name=args.profile, region_name=REGION)
    if args.execute:
        execute(session, args.execute.resolve(), args.preview_change_set)
    else:
        require(args.capture is not None, "--capture is required for preparation.")
        path = prepare(session, args.capture.resolve())
        if args.apply:
            execute(session, path)
        else:
            print("NOT executed. Resume with --execute " + str(path), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        reason = str(error) if type(error) is ValueError else type(error).__name__
        code = getattr(error, "response", {}).get("Error", {}).get("Code", "")
        if re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", code):
            reason += ": " + code
        raise SystemExit("Release stopped: " + reason + ". Keep the private release record local.") from None
