#!/usr/bin/env python3
"""Prepare or execute a scoped PROD release for read-only EKS upgrade evidence.

The release changes only the existing ClusterFunction package and adds the
JWT-protected GET /api/v1/clusters/{clusterId}/upgrade-readiness route. It
does not invoke EKS mutation APIs, change the frontend, or update a customer
IAM role. Existing customer roles need the separately reviewed read policy.
"""
from __future__ import annotations

import argparse
import ast
import base64
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import urllib.request
import uuid
import zipfile

import boto3


ROOT = Path(__file__).resolve().parents[1]
ROUTE_KEY = "GET /api/v1/clusters/{clusterId}/upgrade-readiness"
ROUTE_LOGICAL = "NaviganProdEksUpgradeReadinessRoute"
FORMAT = "navigan-eks-upgrade-readiness-prod-v1"


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


summary = load("upgrade_readiness_summary_support", "deploy-summary-apis-prod.py")
support = summary.support
ACCOUNT, REGION, PARENT = summary.ACCOUNT, summary.REGION, summary.PARENT
require = summary.require


def digest(value):
    return hashlib.sha256(value).hexdigest()


def code_hash(value):
    return base64.b64encode(hashlib.sha256(value).digest()).decode()


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, default=str))


def stamp(stack):
    return support.stamp(stack)


def check_checkout(expected_branch):
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"], cwd=ROOT, text=True
    ).strip()
    require(branch == expected_branch, f"Check out the exact release source branch {expected_branch}")
    paths = [
        "scripts/deploy-eks-upgrade-readiness-prod.py",
        "src/navigan/modules/cluster_management/handler.py",
        "src/navigan/modules/cluster_management/upgrade_readiness.py",
        "infrastructure/modules/cluster-management/template.yaml",
    ]
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain", "--", *paths], cwd=ROOT, text=True
    )
    require(not dirty.strip(), "Commit the reviewed upgrade-readiness release sources first")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def patch_handler(original):
    newline = "\r\n" if "\r\n" in original else "\n"
    result = original.replace("\r\n", "\n")
    markers = (
        "from .upgrade_readiness import EksUpgradeDiscovery",
        '        "upgrade-readiness",',
        '                elif action == "upgrade-readiness":',
        "                    value = EksUpgradeDiscovery().discover(row, environment)",
    )
    present = [result.count(marker) for marker in markers]
    if all(count == 1 for count in present):
        ast.parse(result)
        return original
    require(not any(present), "Partially installed upgrade-readiness handler rejected")
    insertions = (
        (
            "from .tool_access import resolve_tool_access\n",
            "from .tool_access import resolve_tool_access\n"
            "from .upgrade_readiness import EksUpgradeDiscovery\n",
        ),
        (
            '        "platform-components",\n',
            '        "platform-components",\n        "upgrade-readiness",\n',
        ),
        (
            '                elif action == "platform-components":\n'
            "                    value = repo.platform_components(identifier)\n",
            '                elif action == "platform-components":\n'
            "                    value = repo.platform_components(identifier)\n"
            '                elif action == "upgrade-readiness":\n'
            "                    _, environment = repo.pinned_environment_snapshot(\n"
            '                        row["environment_id"], row["environment_approved_version"]\n'
            "                    )\n"
            "                    value = EksUpgradeDiscovery().discover(row, environment)\n",
        ),
    )
    for before, after in insertions:
        require(result.count(before) == 1, "Unexpected deployed Cluster handler contract")
        result = result.replace(before, after, 1)
    require(
        all(result.count(marker) == 1 for marker in markers),
        "Upgrade-readiness handler patch is incomplete",
    )
    ast.parse(result)
    return result if newline == "\n" else result.replace("\n", "\r\n")


def package(original, destination):
    prefix = "navigan/modules/cluster_management/"
    handler = prefix + "handler.py"
    discovery = prefix + "upgrade_readiness.py"
    with zipfile.ZipFile(original) as old:
        require(handler in old.namelist(), "Unexpected deployed ClusterFunction package")
        require(len(old.namelist()) == len(set(old.namelist())), "Duplicate ZIP members rejected")
        replacement = patch_handler(old.read(handler).decode()).encode()
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as new:
            for entry in old.infolist():
                if entry.filename == discovery:
                    continue
                if entry.filename.endswith(".pyc") and (
                    "/cluster_management/handler." in entry.filename
                    or "/cluster_management/upgrade_readiness." in entry.filename
                ):
                    continue
                new.writestr(entry, replacement if entry.filename == handler else old.read(entry.filename))
            new.writestr(discovery, (ROOT / "src" / discovery).read_bytes())
    with zipfile.ZipFile(destination) as updated:
        require(
            sum(item.file_size for item in updated.infolist()) <= 250 * 1024 * 1024,
            "Updated ClusterFunction package is too large",
        )
    return destination


def preflight(session):
    parent, root, records = summary.preflight(session)
    record = next(item for item in records if item["resource"] == "clusters")
    gateway = session.client("apigatewayv2")
    routes = support.all_items(gateway, "get_routes", "Items", ApiId=record["api"])
    current = [item for item in routes if item["RouteKey"] == ROUTE_KEY]
    require(len(current) <= 1, "Duplicate production upgrade-readiness routes")
    if current:
        reference = record["reference"]
        require(
            all(
                current[0].get(key, [] if key == "AuthorizationScopes" else None)
                == reference.get(key, [] if key == "AuthorizationScopes" else None)
                for key in ("AuthorizationType", "AuthorizerId", "AuthorizationScopes", "Target")
            ),
            "Existing upgrade-readiness route protection differs from the Cluster API",
        )
    record["routePresent"] = bool(current)
    return parent, root, record


def validate_delta(before, after, function_logical, route_was_present):
    require(before.keys() == after.keys(), "Nested template settings changed")
    require(
        all(before[key] == after[key] for key in before if key != "Resources"),
        "Nested template settings changed",
    )
    old, new = before["Resources"], after["Resources"]
    require(set(old) <= set(new), "Cluster resource deletion rejected")
    allowed_additions = set() if route_was_present else {ROUTE_LOGICAL}
    require(set(new) - set(old) == allowed_additions, "Unexpected Cluster resource addition")
    for key in old:
        if key == function_logical:
            expected = copy.deepcopy(old[key])
            expected["Properties"]["Code"] = new[key]["Properties"]["Code"]
            require(expected == new[key], "Only ClusterFunction code may change")
        else:
            require(old[key] == new[key], "Unrelated Cluster resource changed: " + key)


def proposed_child(record, code):
    before = record["before"]
    after = copy.deepcopy(before)
    function = record["functionLogical"]
    after["Resources"][function]["Properties"]["Code"] = code
    if not record["routePresent"]:
        reference = record["reference"]
        after["Resources"][ROUTE_LOGICAL] = {
            "Type": "AWS::ApiGatewayV2::Route",
            "Properties": {
                "ApiId": record["api"],
                "RouteKey": ROUTE_KEY,
                "Target": reference["Target"],
                "AuthorizationType": reference["AuthorizationType"],
                "AuthorizerId": reference["AuthorizerId"],
                "AuthorizationScopes": reference.get("AuthorizationScopes", []),
            },
        }
    validate_delta(before, after, function, record["routePresent"])
    return after


def inspect_change_set(cfn, identifier, saved):
    root = cfn.describe_change_set(ChangeSetName=identifier)
    require(
        root["StackName"] == PARENT
        and root["Status"] == "CREATE_COMPLETE"
        and root["ExecutionStatus"] == "AVAILABLE",
        "Prepared production change set is unavailable",
    )
    changes = support.all_items(cfn, "describe_change_set", "Changes", ChangeSetName=identifier)
    require(len(changes) == 1, "Only ClusterManagement may change")
    change = changes[0]["ResourceChange"]
    require(
        change["LogicalResourceId"] == "ClusterManagement"
        and change["ResourceType"] == "AWS::CloudFormation::Stack"
        and change["Action"] == "Modify"
        and change.get("Replacement", "False") == "False"
        and change.get("ChangeSetId"),
        "Unexpected production root change",
    )
    child_id = change["ChangeSetId"]
    child = cfn.describe_change_set(ChangeSetName=child_id)
    require(child["StackId"] == saved["stack"], "Wrong nested Cluster stack")
    before = support.body(
        cfn.get_template(StackName=saved["stack"], TemplateStage="Processed")["TemplateBody"]
    )
    after = support.body(
        cfn.get_template(
            StackName=saved["stack"], ChangeSetName=child_id, TemplateStage="Processed"
        )["TemplateBody"]
    )
    require(digest(json.dumps(after, sort_keys=True).encode()) == saved["templateHash"], "Prepared template changed")
    validate_delta(before, after, saved["functionLogical"], saved["routePresent"])
    nested = support.all_items(cfn, "describe_change_set", "Changes", ChangeSetName=child_id)
    allowed = {saved["functionLogical"], saved["integrationLogical"]} | (
        set() if saved["routePresent"] else {ROUTE_LOGICAL}
    )
    require({item["ResourceChange"]["LogicalResourceId"] for item in nested} <= allowed, "Unrelated nested change")
    require(saved["functionLogical"] in {item["ResourceChange"]["LogicalResourceId"] for item in nested}, "ClusterFunction update missing")
    for item in nested:
        value = item["ResourceChange"]
        require(value.get("Replacement", "False") == "False", "Resource replacement rejected")
        if value["LogicalResourceId"] == saved["functionLogical"]:
            require(value["Action"] == "Modify", "ClusterFunction must be modified in place")
        elif value["LogicalResourceId"] == saved["integrationLogical"]:
            require(
                value["Action"] == "Modify"
                and value["ResourceType"] == "AWS::ApiGatewayV2::Integration"
                and before["Resources"][value["LogicalResourceId"]]
                == after["Resources"][value["LogicalResourceId"]]
                and support.references(
                    before["Resources"][value["LogicalResourceId"]],
                    saved["functionLogical"],
                ),
                "Only the unchanged Cluster integration dependency may refresh",
            )
        else:
            require(value["Action"] == "Add", "Upgrade-readiness route must be an addition")


def signature(record):
    return {
        key: record[key]
        for key in (
            "stack",
            "stackStamp",
            "function",
            "functionLogical",
            "integrationLogical",
            "revision",
            "oldSha",
            "api",
            "routePresent",
        )
    }


def prepare(session, revision):
    parent, root, record = preflight(session)
    workspace = support.storage.verify_storage(session, "artifact-workspace")
    directory = Path(tempfile.mkdtemp(prefix="navigan-prod-eks-upgrade-"))
    directory.chmod(0o700)
    print("Private rollback/release record: " + str(directory), flush=True)
    deployed = session.client("lambda").get_function(FunctionName=record["function"])
    require(deployed["Configuration"]["RevisionId"] == record["revision"], "ClusterFunction changed during preparation")
    original = directory / "ClusterFunction-original.zip"
    with urllib.request.urlopen(deployed["Code"]["Location"], timeout=60) as stream:
        original.write_bytes(stream.read())
    require(code_hash(original.read_bytes()) == record["oldSha"], "Original ClusterFunction checksum mismatch")
    updated = package(original, directory / "ClusterFunction-updated.zip")
    code, _ = support.upload(session, workspace, directory, "eks-upgrade-readiness.zip", updated.read_bytes())
    child = proposed_child(record, code)
    dump(directory / "cluster-original-template.json", record["before"])
    dump(directory / "cluster-updated-template.json", child)
    _, child_url = support.upload(
        session,
        workspace,
        directory,
        "eks-upgrade-readiness-cluster-template.json",
        json.dumps(child).encode(),
    )
    updated_root = copy.deepcopy(root)
    updated_root["Resources"]["ClusterManagement"]["Properties"]["TemplateURL"] = child_url
    _, root_url = support.upload(
        session,
        workspace,
        directory,
        "eks-upgrade-readiness-parent-template.json",
        json.dumps(updated_root).encode(),
    )
    cfn = session.client("cloudformation")
    request = {
        "StackName": PARENT,
        "ChangeSetName": "navigan-prod-eks-upgrade-" + uuid.uuid4().hex[:16],
        "ChangeSetType": "UPDATE",
        "TemplateURL": root_url,
        "IncludeNestedStacks": True,
        "Capabilities": ["CAPABILITY_NAMED_IAM", "CAPABILITY_AUTO_EXPAND"],
        "Parameters": [
            {"ParameterKey": item["ParameterKey"], "UsePreviousValue": True}
            for item in parent.get("Parameters", [])
        ],
    }
    if parent.get("RoleARN"):
        request["RoleARN"] = parent["RoleARN"]
    identifier = cfn.create_change_set(**request)["Id"]
    cfn.get_waiter("change_set_create_complete").wait(
        ChangeSetName=identifier, WaiterConfig={"Delay": 5, "MaxAttempts": 180}
    )
    saved = {
        **signature(record),
        "templateHash": digest(json.dumps(child, sort_keys=True).encode()),
        "newSha": code_hash(updated.read_bytes()),
    }
    inspect_change_set(cfn, identifier, saved)
    plan = directory / "release-plan.json"
    dump(
        plan,
        {
            "format": FORMAT,
            "account": ACCOUNT,
            "region": REGION,
            "revision": revision,
            "parentStamp": stamp(parent),
            "changeSet": identifier,
            "release": saved,
        },
    )
    print("Scoped PROD backend release prepared; NOT executed. Release plan: " + str(plan))


def execute(session, plan_path):
    plan = json.loads(plan_path.read_text())
    require(
        (plan.get("format"), plan.get("account"), plan.get("region"))
        == (FORMAT, ACCOUNT, REGION),
        "Wrong upgrade-readiness release plan",
    )
    parent, _, current = preflight(session)
    saved = plan["release"]
    require(stamp(parent) == plan["parentStamp"], "Production parent stack changed; prepare again")
    require(signature(current) == {key: saved[key] for key in signature(current)}, "Cluster API changed; prepare again")
    cfn = session.client("cloudformation")
    inspect_change_set(cfn, plan["changeSet"], saved)
    cfn.execute_change_set(ChangeSetName=plan["changeSet"])
    print("Waiting for the scoped Cluster API deployment", flush=True)
    cfn.get_waiter("stack_update_complete").wait(
        StackName=PARENT, WaiterConfig={"Delay": 10, "MaxAttempts": 180}
    )
    _, _, deployed = preflight(session)
    require(deployed["oldSha"] == saved["newSha"], "Deployed ClusterFunction checksum differs")
    require(deployed["routePresent"], "Protected upgrade-readiness route was not deployed")
    print("PROD read-only EKS upgrade-readiness API deployed and verified. Frontend unchanged.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="navigan")
    parser.add_argument("--source-branch", default="feature/eks-upgrade-readiness")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--execute", type=Path, metavar="PLAN")
    args = parser.parse_args()
    revision = check_checkout(args.source_branch)
    session = boto3.Session(profile_name=args.profile, region_name=REGION)
    require(session.client("sts").get_caller_identity()["Account"] == ACCOUNT, "Wrong AWS account")
    if args.execute:
        execute(session, args.execute)
    else:
        prepare(session, revision)


if __name__ == "__main__":
    main()
