#!/usr/bin/env python3
"""Synchronize deployed PROD API packages into the existing DEV SAM stack.

One-time baseline reconciliation, separate from normal selective source builds.
Reuses verified live ZIPs; only the missing runner guard needs an image overlay.
DEV parameters, roles, database, network, routes and Terraform module stay intact.
--prepare stages artifacts and unexecuted previews; --apply also executes the
parent update. No PROD writes, DB commands, ECS updates or cluster provisioning.
"""

from __future__ import annotations

import argparse
import ast
import base64
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from types import SimpleNamespace
import urllib.parse
import urllib.request
import uuid

import boto3

import release_common as common
import release_dev_target as target

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT, REGION = "905418045935", "ap-south-1"
DEV, PROD = "navigan-ashok-dev", "navigan-custmanagement-cfnstk"
FORMAT = "navigan-dev-runtime-sync-v1"
MODULES = {
    "AccessManagement",
    "ClusterManagement",
    "CustomerManagement",
    "EnvironmentManagement",
    "MigrationManagement",
}
CONFIG_KEYS = (
    "FunctionArn",
    "FunctionName",
    "Role",
    "Handler",
    "Runtime",
    "Timeout",
    "MemorySize",
    "Environment",
    "VpcConfig",
    "Layers",
    "Architectures",
    "TracingConfig",
    "KMSKeyArn",
    "DeadLetterConfig",
    "FileSystemConfigs",
    "EphemeralStorage",
    "SnapStart",
    "LoggingConfig",
)
require = common.require


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit = load("dev_sync_audit", "audit-cluster-bootstrap-runtime.py")
patch = load("dev_sync_patch", "cluster-bootstrap-patch.py")
refs = load("dev_sync_references", "cluster-bootstrap-reference-proof.py")


def fingerprint(value):
    return common.sha(common.canonical(value))


def parameters(stack):
    return {p["ParameterKey"]: p["ParameterValue"] for p in stack.get("Parameters", [])}


def context():
    return SimpleNamespace(
        require=require,
        ACCOUNT=ACCOUNT,
        REGION=REGION,
        PARENT=DEV,
        parameters=parameters,
        audit=audit,
        stamp=lambda s: str(s.get("LastUpdatedTime") or s["CreationTime"]),
    )


def zip_hash(raw):
    return base64.b64encode(hashlib.sha256(raw).digest()).decode()


def configuration(cfg):
    return {k: cfg.get(k) for k in CONFIG_KEYS}


def state_signature(state):
    return fingerprint(
        {"stamp": target.stamp(state), "config": {p: configuration(c) for p, c in state["functions"].items()}}
    )


def captured(directory, environment):
    directory = Path(directory)
    summary = common.read(directory / "summary.json")
    parent = DEV if environment == "dev" else PROD
    require(
        (summary.get("environment"), summary.get("account"), summary.get("region"), summary.get("stackName"))
        == (environment, ACCOUNT, REGION, parent),
        "Bootstrap capture belongs to another target.",
    )
    require(isinstance(summary.get("runnerInspection"), dict), "Bootstrap capture needs runner inspection.")
    for name in ("ClusterFunction", "StatusFunction"):
        cfg = common.read(directory / (name + "-config.json"))
        require(
            zip_hash((directory / (name + ".zip")).read_bytes())
            == cfg["CodeSha256"]
            == summary["functions"][name]["codeSha256"],
            "Captured package checksum mismatch.",
        )
        require(
            cfg["Environment"]["Variables"]["DB_NAME"]
            == ("navigan_dev" if environment == "dev" else "navigan"),
            "Capture database identity mismatch.",
        )
    require(
        common.sha((directory / "runner/runner.py").read_bytes())
        == summary["runnerInspection"]["runnerSha256"],
        "Captured runner checksum mismatch.",
    )
    return summary


def fetch_package(lam, name, cfg):
    response = lam.get_function(FunctionName=name)
    current = response["Configuration"]
    require(
        current["RevisionId"] == cfg["RevisionId"] and current["CodeSha256"] == cfg["CodeSha256"],
        "Lambda changed while capturing its package.",
    )
    with urllib.request.urlopen(response["Code"]["Location"], timeout=90) as stream:
        raw = stream.read()
    require(zip_hash(raw) == cfg["CodeSha256"], "Downloaded ZIP checksum mismatch.")
    common.unzip(raw)
    return raw


def prod_functions(session, dev):
    """Read only corresponding application functions; never infer PROD names."""
    cfn, lam = session.client("cloudformation"), session.client("lambda")
    root = cfn.describe_stacks(StackName=PROD)["Stacks"][0]
    audit.validate_stack(root, ACCOUNT, REGION)
    require(parameters(root).get("DatabaseName") == "navigan", "PROD database identity mismatch.")
    result = {}
    for module in sorted(MODULES):
        child_id = cfn.describe_stack_resource(StackName=root["StackId"], LogicalResourceId=module)[
            "StackResourceDetail"
        ]["PhysicalResourceId"]
        child = cfn.describe_stacks(StackName=child_id)["Stacks"][0]
        audit.validate_stack(child, ACCOUNT, REGION, root["StackId"])
        for path in sorted(dev["functions"]):
            if not path.startswith("root/" + module + "/"):
                continue
            logical = path.rsplit("/", 1)[1]
            physical = cfn.describe_stack_resource(StackName=child_id, LogicalResourceId=logical)[
                "StackResourceDetail"
            ]["PhysicalResourceId"]
            cfg = lam.get_function_configuration(FunctionName=physical)
            old = dev["functions"][path]
            require(
                cfg.get("State") == "Active"
                and cfg.get("LastUpdateStatus") == "Successful"
                and cfg.get("Environment", {}).get("Variables", {}).get("DB_NAME") == "navigan",
                "PROD application Lambda is not stable or has another database.",
            )
            require(
                cfg.get("PackageType", "Zip") == "Zip"
                and cfg.get("Runtime") == old.get("Runtime")
                and cfg.get("Handler") == old.get("Handler")
                and cfg.get("Architectures", ["x86_64"]) == old.get("Architectures", ["x86_64"]),
                "DEV/PROD Lambda execution contracts differ.",
            )
            require(
                [v["Arn"] for v in cfg.get("Layers", [])] == [v["Arn"] for v in old.get("Layers", [])],
                "DEV/PROD external Lambda layers differ; package-only synchronization is insufficient.",
            )
            result[path] = cfg
    require(set(result) == set(dev["functions"]), "Unexpected application module/function set.")
    return result


def expected_environment(state, prod):
    """Only two confirmed missing settings; preserve DEV values/allowlists."""
    cluster = state["functions"]["root/ClusterManagement/ClusterFunction"]["Environment"]["Variables"]
    url = cluster.get("PLATFORM_TOOLS_BASE_URL", "")
    parsed = urllib.parse.urlsplit(url)
    require(
        parsed.scheme in {"https", "http"}
        and parsed.netloc
        and parsed.path.rstrip("/") == "/tools"
        and not parsed.query
        and not parsed.fragment
        and not parsed.username
        and not parsed.password,
        "DEV ClusterFunction has no usable existing tools URL; inspect its gateway configuration.",
    )
    if parsed.scheme == "http":
        require(parsed.hostname in {"localhost", "127.0.0.1"}, "Non-local DEV gateway must use HTTPS.")
    result = {}
    path = "root/ClusterManagement/StatusFunction"
    old = state["functions"][path]["Environment"]["Variables"].get("PLATFORM_TOOLS_BASE_URL")
    require(old in (None, "", url), "DEV StatusFunction tools URL conflicts with the existing DEV gateway.")
    if old != url:
        template = audit.template_body(state["stacks"]["root/ClusterManagement"]["processed"])
        binding = template["Resources"]["ClusterFunction"]["Properties"]["Environment"]["Variables"][
            "PLATFORM_TOOLS_BASE_URL"
        ]
        require(
            binding == url or binding == {"Ref": "PlatformToolsBaseUrl"},
            "Unknown DEV tools URL template binding.",
        )
        result[path] = {"PLATFORM_TOOLS_BASE_URL": {"value": url, "binding": binding}}
    path = "root/MigrationManagement/MigrationConnectorFunction"
    flag = prod[path]["Environment"]["Variables"].get("MIGRATION_SOURCE_FIRST_ENABLED")
    require(flag == "true", "PROD source-first flag differs from the reviewed requirement.")
    old = state["functions"][path]["Environment"]["Variables"].get("MIGRATION_SOURCE_FIRST_ENABLED")
    require(old in (None, "", "true"), "DEV explicitly disables source-first; inspect its configuration.")
    if old != "true":
        result[path] = {"MIGRATION_SOURCE_FIRST_ENABLED": {"value": "true", "binding": "true"}}
    return result


def runner_sources(dev_capture, prod_capture):
    """Validate the local patch before downloading/staging cloud artifacts."""
    old = (dev_capture / "runner/runner.py").read_text()
    if "system_node_findings" in audit.function_names(old):
        return old, old
    prod_source = (prod_capture / "runner/runner.py").read_text()
    proposed = patch.patch_runner(old, desired=prod_source)
    prod_guard = next(
        n
        for n in ast.parse(prod_source).body
        if isinstance(n, ast.FunctionDef) and n.name == "system_node_findings"
    )
    guard = next(
        n
        for n in ast.parse(proposed).body
        if isinstance(n, ast.FunctionDef) and n.name == "system_node_findings"
    )
    require(patch.same(guard, prod_guard), "Guard implementation differs from the captured PROD fix.")
    module = dev_capture / "runner/aws-eks"
    require(
        all((module / name).is_file() for name in ("main.tf", "variables.tf", "outputs.tf", "versions.tf")),
        "Captured DEV Terraform module is incomplete.",
    )
    main = (module / "main.tf").read_text()
    require(
        all(
            key in main
            for key in (
                '"navigan.io/platform-services"',
                '"navigan.io/system-only"',
                '"SYSTEM"',
                '"NO_SCHEDULE"',
            )
        )
        and "purpose" in (module / "variables.tf").read_text(),
        "DEV Terraform module lacks the protected-node labels/taint contract.",
    )
    return old, proposed


def guard_overlay(session, directory, dev_capture, prod_capture, image):
    """Add the tested guard to DEV's runner; retain every Terraform file."""
    old, proposed = runner_sources(dev_capture, prod_capture)
    if old == proposed:
        print("Runner guard already present; retaining the DEV image.", flush=True)
        return image
    observed = directory / "runner-base-verification"
    observed.mkdir()
    audit.inspect_runner(session, image, ACCOUNT, REGION, observed)
    require(
        (observed / "runner/runner.py").read_text() == old,
        "Captured DEV runner differs from the actual pinned base image.",
    )
    module = dev_capture / "runner/aws-eks"
    stage = directory / "guard-build"
    stage.mkdir()
    (stage / "runner.py").write_text(proposed)
    # Private host umask must not make the image's Python file unreadable to
    # the base image's existing non-root user. No USER/config override is needed.
    (stage / "Dockerfile").write_text(f"FROM {image}\nCOPY --chmod=0644 runner.py /app/runner.py\n")
    registry = f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com"
    repository = "navigan-terraform-runner"
    ecr = session.client("ecr")
    ecr.describe_repositories(repositoryNames=[repository])
    with tempfile.TemporaryDirectory(prefix="dev-sync-ecr-", dir=directory) as authdir:
        auth = ecr.get_authorization_token(registryIds=[ACCOUNT])["authorizationData"]
        entry = next(a for a in auth if a["proxyEndpoint"] == "https://" + registry)
        user, password = base64.b64decode(entry["authorizationToken"]).split(b":", 1)
        require(user == b"AWS", "Unexpected ECR auth identity.")
        docker = ["docker", "--config", authdir]
        log = directory / "runner-build.log"
        common.run(
            [*docker, "login", "--username", "AWS", "--password-stdin", registry], ROOT, log, data=password
        )
        tag = registry + "/" + repository + ":dev-guard-" + uuid.uuid4().hex
        print("Runner: building only the missing guard; DEV Terraform files retained...", flush=True)
        common.run(
            [*docker, "build", "--platform", "linux/amd64", "--network", "none", "-t", tag, str(stage)],
            ROOT,
            log,
        )
        common.run([*docker, "push", tag], ROOT, log)
    digest = ecr.describe_images(repositoryName=repository, imageIds=[{"imageTag": tag.rsplit(":", 1)[1]}])[
        "imageDetails"
    ][0]["imageDigest"]
    require(re.fullmatch(r"sha256:[a-f0-9]{64}", digest), "Invalid pushed runner digest.")
    pinned = registry + "/" + repository + "@" + digest
    check = directory / "guard-verification"
    check.mkdir()
    audit.inspect_runner(session, pinned, ACCOUNT, REGION, check)
    require(
        (check / "runner/runner.py").read_text() == proposed, "Built runner differs from the guard overlay."
    )
    require(
        {p.name: p.read_bytes() for p in module.iterdir() if p.is_file()}
        == {p.name: p.read_bytes() for p in (check / "runner/aws-eks").iterdir() if p.is_file()},
        "Runner overlay changed DEV Terraform files.",
    )
    return pinned


def desired_templates(state, codes, settings):
    root = copy.deepcopy(audit.template_body(state["stacks"]["root"]["processed"]))
    children = {}
    for path in sorted(set(codes) | set(settings)):
        module, logical = path.split("/")[1:]
        child = children.setdefault(
            module, copy.deepcopy(audit.template_body(state["stacks"]["root/" + module]["processed"]))
        )
        resource = child["Resources"][logical]
        require(
            resource["Type"] == "AWS::Lambda::Function", "Only processed Lambda resources may be patched."
        )
        if path in codes:
            resource["Properties"]["Code"] = codes[path]
        if path in settings:
            # Updating Environment replaces the entire Lambda map. Preserve live
            # DEV additions and matching SAM bindings, including private refs.
            record = state["stacks"]["root/" + module]
            variables = resource["Properties"].setdefault("Environment", {}).setdefault("Variables", {})
            live = state["functions"][path]["Environment"]["Variables"]
            variables.update({k: v for k, v in live.items() if k not in variables})
            for key in list(variables):
                if key not in live:
                    del variables[key]
                else:
                    require(
                        resolve_binding(variables[key], record) == live[key],
                        "Existing DEV runtime/template environment drift requires review: "
                        + path
                        + "/"
                        + key,
                    )
        for key, item in settings.get(path, {}).items():
            resource["Properties"].setdefault("Environment", {}).setdefault("Variables", {})[key] = item[
                "binding"
            ]
    return root, children


def resolve_binding(value, record):
    if isinstance(value, (str, int, float, bool)):
        return str(value).lower() if isinstance(value, bool) else str(value)
    require(isinstance(value, dict), "Unknown environment binding.")
    params = parameters(record["stack"])
    physical = {r["LogicalResourceId"]: r["PhysicalResourceId"] for r in record["resources"]}
    pseudo = {
        "AWS::Region": REGION,
        "AWS::AccountId": ACCOUNT,
        "AWS::Partition": "aws",
        "AWS::URLSuffix": "amazonaws.com",
        "AWS::StackId": record["stack"]["StackId"],
        "AWS::StackName": record["stack"]["StackName"],
    }
    if set(value) == {"Ref"}:
        name = value["Ref"]
        values = {**params, **physical, **pseudo}
        require(name in values and values[name] != "****", "Unknown or redacted environment reference.")
        return values[name]
    if set(value) == {"Fn::GetAtt"}:
        parts = value["Fn::GetAtt"]
        parts = parts.split(".", 1) if isinstance(parts, str) else parts
        require(
            isinstance(parts, list) and len(parts) == 2 and parts[0] in physical and parts[1] == "Arn",
            "Unknown environment attribute.",
        )
        resource = audit.template_body(record["processed"])["Resources"][parts[0]]
        if physical[parts[0]].startswith("arn:"):
            return physical[parts[0]]
        kind = resource["Type"]
        if kind == "AWS::KMS::Key":
            return f"arn:aws:kms:{REGION}:{ACCOUNT}:key/" + physical[parts[0]]
        if kind == "AWS::S3::Bucket":
            return "arn:aws:s3:::" + physical[parts[0]]
        if kind == "AWS::CodeBuild::Project":
            return f"arn:aws:codebuild:{REGION}:{ACCOUNT}:project/" + physical[parts[0]]
        require(False, "Unknown environment ARN binding.")
    if set(value) == {"Fn::Sub"}:
        sub = value["Fn::Sub"]
        text, bindings = (sub, {}) if isinstance(sub, str) else sub

        def replace(match):
            key = match[1]
            if key in bindings:
                return resolve_binding(bindings[key], record)
            return resolve_binding({"Fn::GetAtt": key.split(".", 1)} if "." in key else {"Ref": key}, record)

        return re.sub(r"\$\{([^}]+)\}", replace, text)
    require(False, "Unsupported DEV environment binding; inspect before updating the entire map.")


def arguments(stack, image=None):
    return [
        {
            "ParameterKey": p["ParameterKey"],
            **(
                {"ParameterValue": image}
                if image is not None and p["ParameterKey"] == "TerraformRunnerImageUri"
                else {"UsePreviousValue": True}
            ),
        }
        for p in stack.get("Parameters", [])
    ]


def preview(cfn, stack, url, image=None):
    request = {
        "StackName": stack["StackId"],
        "ChangeSetName": "dev-runtime-sync-" + uuid.uuid4().hex[:12],
        "ChangeSetType": "UPDATE",
        "TemplateURL": url,
        "IncludeNestedStacks": False,
        "Capabilities": ["CAPABILITY_NAMED_IAM", "CAPABILITY_AUTO_EXPAND"],
        "Parameters": arguments(stack, image),
    }
    if stack.get("RoleARN"):
        request["RoleARN"] = stack["RoleARN"]
    identifier = cfn.create_change_set(**request)["Id"]
    try:
        cfn.get_waiter("change_set_create_complete").wait(
            ChangeSetName=identifier, WaiterConfig={"Delay": 5, "MaxAttempts": 180}
        )
    except Exception:
        meta = cfn.describe_change_set(ChangeSetName=identifier)
        reason = meta.get("StatusReason", "").lower()
        require(
            meta.get("Status") == "FAILED"
            and (
                reason.startswith("the submitted information didn't contain changes")
                or reason.startswith("no updates are to be performed")
            ),
            "Change-set creation failed; inspect the saved record.",
        )
    return identifier


def inspect_preview(cfn, state, plan, module, identifier):
    key = "root" if module == "root" else "root/" + module
    record = state["stacks"][key]
    meta = cfn.describe_change_set(ChangeSetName=identifier)
    require(
        meta["StackId"] == record["stack"]["StackId"]
        and meta.get("IncludeNestedStacks") is False
        and not meta.get("ParentChangeSetId"),
        "Preview is not independent or targets another stack.",
    )
    wanted = parameters(record["stack"])
    if module in {"root", "ClusterManagement"}:
        wanted["TerraformRunnerImageUri"] = plan["newImage"]
    chosen = {
        p["ParameterKey"]: p.get("ParameterValue", parameters(record["stack"]).get(p["ParameterKey"]))
        for p in meta.get("Parameters", [])
    }
    require(chosen == wanted, "Preview changes unrelated DEV parameters.")
    rows = common.pages(cfn, "describe_change_set", "Changes", ChangeSetName=identifier)
    if meta.get("Status") == "FAILED":
        reason = meta.get("StatusReason", "").lower()
        require(
            not rows
            and (
                reason.startswith("the submitted information didn't contain changes")
                or reason.startswith("no updates are to be performed")
            ),
            "Preview failed for a reason other than no changes.",
        )
        require(
            module not in plan["children"] and module != "root",
            "An intended change unexpectedly has no changes.",
        )
        return
    require(
        meta.get("Status") == "CREATE_COMPLETE" and meta.get("ExecutionStatus") == "AVAILABLE",
        "Preview is not available.",
    )
    after = audit.template_body(
        cfn.get_template(
            StackName=record["stack"]["StackId"], ChangeSetName=identifier, TemplateStage="Processed"
        )["TemplateBody"]
    )
    require(
        fingerprint(after) == plan["templateHashes"][module],
        "Prepared template differs from the scoped overlay.",
    )
    before = audit.template_body(record["processed"])
    seen = set()
    changes = {r["ResourceChange"]["LogicalResourceId"]: r["ResourceChange"] for r in rows}
    for logical, row in changes.items():
        seen.add(logical)
        require(
            row.get("Action") == "Modify" and not row.get("ChangeSetId"),
            "Add/delete/import/nested precomputation is outside DEV synchronization.",
        )
        path = "root/" + module + "/" + logical
        if module == "root":
            require(
                row.get("ResourceType") == "AWS::CloudFormation::Stack"
                and row.get("Replacement") == "False"
                and logical in plan["previews"],
                "Parent affects an unverified resource.",
            )
            continue
        if path in plan["expectedFunctions"]:
            fields = ({"Code"} if path in plan["codes"] else set()) | (
                {"Environment"} if path in plan["settings"] else set()
            )
            require(
                row.get("ResourceType") == "AWS::Lambda::Function"
                and row.get("Replacement") == "False"
                and row.get("Details")
                and all(
                    d.get("Target", {}).get("Attribute") == "Properties"
                    and d["Target"].get("Name") in fields
                    and d["Target"].get("RequiresRecreation") == "Never"
                    for d in row["Details"]
                ),
                "Lambda preview changes more than the intended code/settings.",
            )
        elif module == "ClusterManagement" and logical == "TerraformProject":
            require(
                row.get("ResourceType") == "AWS::CodeBuild::Project"
                and row.get("Replacement") == "False"
                and row.get("Details")
                and all(
                    d.get("Target", {}).get("Name") == "Environment"
                    and d["Target"].get("RequiresRecreation") == "Never"
                    for d in row["Details"]
                ),
                "Unexpected runner project change.",
            )
        else:
            require(
                before["Resources"].get(logical) == after["Resources"].get(logical),
                "Dependency resource definition changed.",
            )
            require(
                row.get("ResourceType")
                in {
                    "AWS::ApiGatewayV2::Integration",
                    "AWS::ApiGatewayV2::Route",
                    "AWS::Events::Rule",
                    "AWS::Lambda::Permission",
                }
                and row.get("Replacement") in {"False", "Conditional"}
                and row.get("Details"),
                "Unverified dependency replacement.",
            )
            for detail in row["Details"]:
                producer = (detail.get("CausingEntity") or "").split(".", 1)[0]
                require(
                    detail.get("Evaluation") == "Dynamic"
                    and detail.get("ChangeSource") == "ResourceAttribute"
                    and detail.get("Target", {}).get("Attribute") == "Properties"
                    and producer in changes
                    and changes[producer].get("Replacement") == "False"
                    and changes[producer].get("Action") == "Modify",
                    "Dependency does not refer to a stable modified resource.",
                )
    if module in plan["children"]:
        wanted_functions = {
            p.rsplit("/", 1)[1] for p in plan["expectedFunctions"] if p.startswith("root/" + module + "/")
        }
        require(wanted_functions <= seen, "Concrete preview omits intended functions.")
    if module == "root":
        require(set(plan["children"]) <= seen, "Parent preview omits an intended module.")


def api_snapshot(session, api_id):
    api = session.client("apigatewayv2")
    result = {}
    for operation, name, key in (
        ("get_routes", "routes", "RouteId"),
        ("get_integrations", "integrations", "IntegrationId"),
        ("get_authorizers", "authorizers", "AuthorizerId"),
    ):
        result[name] = sorted(common.pages(api, operation, "Items", ApiId=api_id), key=lambda r: r[key])
    return result


def verify_inputs(session, directory, plan):
    state = target.snapshot(session, ACCOUNT, REGION)
    baseline = common.read(directory / "dev-state.json")
    require(
        state_signature(state) == plan["baselineSignature"],
        "DEV changed after preparation; inspect before executing.",
    )
    prod = prod_functions(session, state)
    require(
        fingerprint({p: (c["RevisionId"], c["CodeSha256"]) for p, c in prod.items()})
        == plan["prodSignature"],
        "PROD artifacts changed after preparation; prepare a fresh synchronization plan.",
    )
    cfn = session.client("cloudformation")
    for module, identifier in plan["previews"].items():
        inspect_preview(cfn, baseline, plan, module, identifier)
    inspect_preview(cfn, baseline, plan, "root", plan["changeSet"])
    require(
        api_snapshot(session, state["apiId"]) == common.read(directory / "api-before.json"),
        "DEV API bindings changed after preparation.",
    )
    return state


def upload(session, bucket, filename, raw):
    return common.put_content(
        session.client("s3"), bucket, "dev-runtime-sync/" + common.sha(raw) + "/" + filename, raw, ACCOUNT
    )


def artifact_code(item):
    bucket, key = common.s3_location(item)
    return {"S3Bucket": bucket, "S3Key": key, "S3ObjectVersion": item["versionId"]}


def artifact_url(item):
    bucket, key = common.s3_location(item)
    return f"https://{bucket}.s3.{REGION}.amazonaws.com/{urllib.parse.quote(key, safe='/')}?versionId={urllib.parse.quote(item['versionId'], safe='')}"


def prepare(session, args):
    dev_capture, prod_capture = args.dev_capture.resolve(), args.prod_capture.resolve()
    dev_summary, prod_summary = captured(dev_capture, "dev"), captured(prod_capture, "prod")
    runner_sources(dev_capture, prod_capture)
    print("Runner patch preflight passed; existing DEV normalization retained where present.", flush=True)
    directory = common.workspace("navigan-dev-runtime-sync-")
    print("Private DEV synchronization record: " + str(directory), flush=True)
    state = target.snapshot(session, ACCOUNT, REGION)
    prod = prod_functions(session, state)
    for name in ("ClusterFunction", "StatusFunction"):
        path = "root/ClusterManagement/" + name
        require(
            state["functions"][path]["CodeSha256"] == dev_summary["functions"][name]["codeSha256"]
            and prod[path]["CodeSha256"] == prod_summary["functions"][name]["codeSha256"],
            "Bootstrap packages changed since capture.",
        )
    cluster = state["stacks"]["root/ClusterManagement"]
    image = parameters(state["stacks"]["root"]["stack"])["TerraformRunnerImageUri"]
    require(
        image
        == parameters(cluster["stack"])["TerraformRunnerImageUri"]
        == dev_summary["runnerInspection"]["resolvedImage"],
        "DEV runner parameter changed since capture.",
    )
    require(
        re.fullmatch(
            rf"{ACCOUNT}\.dkr\.ecr\.{REGION}\.amazonaws\.com/navigan-terraform-runner@sha256:[a-f0-9]{{64}}",
            image,
        ),
        "DEV runner is not pinned in its existing repository.",
    )
    project = next(
        r["PhysicalResourceId"] for r in cluster["resources"] if r["LogicalResourceId"] == "TerraformProject"
    )
    live_project = session.client("codebuild").batch_get_projects(names=[project])["projects"][0]
    require(
        live_project["environment"]["image"] == image, "DEV CodeBuild image differs from its SAM parameter."
    )
    bucket = common.read(args.config)["artifactBucket"]
    common.verify_registry(session, bucket, ACCOUNT, REGION)
    common.write(directory / "dev-state.json", state)
    common.write(directory / "api-before.json", api_snapshot(session, state["apiId"]))
    common.write(directory / "project-before.json", live_project)
    settings = expected_environment(state, prod)
    packages, expected = {}, {}
    lam = session.client("lambda")
    for path, old in sorted(state["functions"].items()):
        candidate = prod[path]
        if candidate["CodeSha256"] == old["CodeSha256"]:
            continue
        filename = path.replace("/", "-") + ".zip"
        rollback = fetch_package(lam, old["FunctionName"], old)
        (directory / ("rollback-" + filename)).write_bytes(rollback)
        raw = fetch_package(lam, candidate["FunctionName"], candidate)
        packages[path] = artifact_code(upload(session, bucket, filename, raw))
        expected[path] = candidate["CodeSha256"]
        print("API package staged: " + path.removeprefix("root/"), flush=True)
    new_image = guard_overlay(session, directory, dev_capture, prod_capture, image)
    root, children = desired_templates(state, packages, settings)
    # Changing the runner parameter affects only the existing ClusterManagement binding.
    owners = {k for k, r in root["Resources"].items() if '"Ref": "TerraformRunnerImageUri"' in json.dumps(r)}
    require(owners == {"ClusterManagement"}, "Runner parameter has unexpected owners.")
    require(
        audit.template_body(cluster["processed"])["Resources"]["TerraformProject"]["Properties"][
            "Environment"
        ]["Image"]
        == {"Ref": "TerraformRunnerImageUri"},
        "Unexpected runner image binding.",
    )
    if new_image != image:
        children.setdefault("ClusterManagement", copy.deepcopy(audit.template_body(cluster["processed"])))
    if not children:
        print(
            "API packages, scoped settings and runner guard already match; no deployment needed.", flush=True
        )
        return None
    plan = {
        "format": FORMAT,
        "account": ACCOUNT,
        "region": REGION,
        "parent": DEV,
        "directory": str(directory),
        "baselineSignature": state_signature(state),
        "prodSignature": fingerprint({p: (c["RevisionId"], c["CodeSha256"]) for p, c in prod.items()}),
        "codes": packages,
        "settings": settings,
        "expectedFunctions": sorted(set(packages) | set(settings)),
        "expectedCodeHashes": expected,
        "newImage": new_image,
        "oldImage": image,
        "children": sorted(children),
        "templateHashes": {},
        "previews": {},
        "project": project,
    }
    cfn = session.client("cloudformation")
    reference_saved = {"rootTemplate": root, "root": state["stacks"]["root"]["stack"]}
    for logical, resource in root["Resources"].items():
        if resource["Type"] != "AWS::CloudFormation::Stack":
            continue
        record = state["stacks"]["root/" + logical]
        template = children.get(logical, audit.template_body(record["processed"]))
        refs.resolve_inputs(
            context(),
            cfn,
            reference_saved,
            {"newImage": new_image},
            logical=logical,
            child=record["stack"],
            child_template=template,
        )
        # Stage unchanged siblings too: this pins the exact captured template and
        # proves a no-op, rather than trusting an old mutable TemplateURL.
        item = upload(session, bucket, logical + ".json", common.canonical(template))
        url = artifact_url(item)
        if logical in children:
            root["Resources"][logical]["Properties"]["TemplateURL"] = url
        else:
            # Verify the actual source URL that the preserved parent will use.
            url = resource["Properties"]["TemplateURL"]
        plan["templateHashes"][logical] = fingerprint(template)
        identifier = preview(cfn, record["stack"], url, new_image if logical == "ClusterManagement" else None)
        plan["previews"][logical] = identifier
        inspect_preview(cfn, state, plan, logical, identifier)
        print("SAM module preview verified: " + logical, flush=True)
    root_item = upload(session, bucket, "root.json", common.canonical(root))
    plan["templateHashes"]["root"] = fingerprint(root)
    common.write(directory / "proposed-root.json", root)
    for logical, template in children.items():
        common.write(directory / (logical + "-proposed.json"), template)
    require(
        state_signature(target.snapshot(session, ACCOUNT, REGION)) == plan["baselineSignature"],
        "DEV changed during preparation.",
    )
    plan["changeSet"] = preview(cfn, state["stacks"]["root"]["stack"], artifact_url(root_item), new_image)
    inspect_preview(cfn, state, plan, "root", plan["changeSet"])
    path = directory / "release-plan.json"
    common.write(path, plan)
    verify_inputs(session, directory, plan)
    print(
        f"Prepared: {len(packages)} API packages, {len(settings)} scoped configuration fixes, runner guard overlay.",
        flush=True,
    )
    print("No deployment yet. Plan: " + str(path), flush=True)
    return path


def read_plan(path):
    path = path.resolve()
    plan = common.read(path)
    require(
        (
            plan.get("format"),
            plan.get("account"),
            plan.get("region"),
            plan.get("parent"),
            plan.get("directory"),
        )
        == (FORMAT, ACCOUNT, REGION, DEV, str(path.parent)),
        "Not a DEV synchronization plan.",
    )
    return path, plan


def verify(session, path):
    path, plan = read_plan(path)
    baseline = common.read(path.parent / "dev-state.json")
    state = target.snapshot(session, ACCOUNT, REGION)
    old_ids = {
        p: sorted((r["LogicalResourceId"], r["PhysicalResourceId"]) for r in v["resources"])
        for p, v in baseline["stacks"].items()
    }
    ids = {
        p: sorted((r["LogicalResourceId"], r["PhysicalResourceId"]) for r in v["resources"])
        for p, v in state["stacks"].items()
    }
    require(
        ids == old_ids and state["roles"] == baseline["roles"],
        "DEV physical identities or IAM policies changed.",
    )
    for module, wanted_hash in plan["templateHashes"].items():
        key = "root" if module == "root" else "root/" + module
        record = state["stacks"][key]
        require(
            fingerprint(audit.template_body(record["processed"])) == wanted_hash,
            "Deployed template differs: " + module,
        )
        wanted_params = parameters(baseline["stacks"][key]["stack"])
        if module in {"root", "ClusterManagement"}:
            wanted_params["TerraformRunnerImageUri"] = plan["newImage"]
        require(parameters(record["stack"]) == wanted_params, "Unrelated DEV parameters changed.")
    for name, old in baseline["functions"].items():
        new = state["functions"][name]
        expected = copy.deepcopy(old)
        for key, value in plan["settings"].get(name, {}).items():
            expected["Environment"]["Variables"][key] = value["value"]
        require(
            configuration(new) == configuration(expected)
            and new["CodeSha256"] == plan["expectedCodeHashes"].get(name, old["CodeSha256"]),
            "API code/config verification failed: " + name,
        )
    project = session.client("codebuild").batch_get_projects(names=[plan["project"]])["projects"][0]
    expected_project = common.read(path.parent / "project-before.json")
    expected_project["environment"]["image"] = plan["newImage"]
    for item in (project, expected_project):
        item.pop("lastModified", None)
    require(
        fingerprint(project) == fingerprint(expected_project),
        "Unrelated DEV CodeBuild configuration changed.",
    )
    require(
        api_snapshot(session, state["apiId"]) == common.read(path.parent / "api-before.json"),
        "DEV API routes/integrations/authorizers changed.",
    )
    common.write(
        path.parent / "verification.json",
        {
            "verifiedAt": datetime.now(timezone.utc).isoformat(),
            "apiPackages": len(plan["codes"]),
            "configurationFixes": len(plan["settings"]),
            "runnerImage": plan["newImage"],
            "authenticatedWorkflowAcceptance": "PENDING",
        },
    )
    print(
        "DEV runtime sync verified: API packages, two scoped settings and protected runner guard. DEV bindings retained.",
        flush=True,
    )
    print(
        "Database, collectors, frontend and existing customer clusters were not deployed. Browser/workflow acceptance remains required.",
        flush=True,
    )


def execute(session, path):
    path, plan = read_plan(path)
    journal = path.parent / "execution.json"
    require(
        not journal.exists(),
        "Execution was already requested; use --verify or inspect the saved execution record.",
    )
    verify_inputs(session, path.parent, plan)
    cfn = session.client("cloudformation")
    common.write(
        journal, {"requestedAt": datetime.now(timezone.utc).isoformat(), "changeSet": plan["changeSet"]}
    )
    print("Executing the DEV parent SAM/CloudFormation update...", flush=True)
    cfn.execute_change_set(
        ChangeSetName=plan["changeSet"], ClientRequestToken="dev-runtime-sync-" + uuid.uuid4().hex
    )
    cfn.get_waiter("stack_update_complete").wait(
        StackName=DEV, WaiterConfig={"Delay": 10, "MaxAttempts": 180}
    )
    verify(session, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="navigan")
    parser.add_argument("--config", type=Path, default=ROOT / ".navigan-release/dev.json")
    parser.add_argument("--dev-capture", type=Path)
    parser.add_argument("--prod-capture", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--execute", type=Path)
    mode.add_argument("--verify", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    require(
        subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
        == "new_migration_approach_18oct26",
        "Use the existing migration branch.",
    )
    session = boto3.Session(profile_name=args.profile, region_name=REGION)
    require(session.client("sts").get_caller_identity()["Account"] == ACCOUNT, "Unexpected AWS account.")
    if args.verify:
        verify(session, args.verify)
    elif args.execute:
        execute(session, args.execute)
    else:
        require(args.dev_capture and args.prod_capture, "Both existing bootstrap captures are required.")
        path = prepare(session, args)
        if args.apply and path is not None:
            execute(session, path)


def failure_reason(error):
    if isinstance(error, common.ReleaseError):
        return str(error)
    # Only expose static messages generated by our validation helpers. Generic
    # ValueErrors/SDK exceptions can contain private values or signed URLs.
    trace = error.__traceback__
    while trace is not None and trace.tb_next is not None:
        trace = trace.tb_next
    if trace is not None and trace.tb_frame.f_code in {patch.require.__code__, audit.require.__code__}:
        return str(error)
    return type(error).__name__


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        message = failure_reason(error)
        raise SystemExit(
            "DEV synchronization stopped: " + message + ". Keep private records local."
        ) from None
