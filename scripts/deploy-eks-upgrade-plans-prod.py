#!/usr/bin/env python3
"""Prepare or execute the scoped PROD backend release for governed EKS plans.

The database migration and customer-role execution policy are separate, explicit
prerequisites. This release changes only the existing ClusterFunction package
and four JWT-protected upgrade-plan routes. It never invokes an EKS update API.
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
BASELINE_TREE = "64be8680772f165939d738a0d7dd9abaf60341e4"
FORMAT = "navigan-eks-upgrade-plans-prod-v1"
ROUTES = {
    "ListClusterUpgradePlansRoute": "GET /api/v1/clusters/{clusterId}/upgrade-plans",
    "CreateClusterUpgradePlanRoute": "POST /api/v1/clusters/{clusterId}/upgrade-plans",
    "GetClusterUpgradePlanRoute": "GET /api/v1/clusters/{clusterId}/upgrade-plans/{planId}",
    "ClusterUpgradePlanActionRoute": "POST /api/v1/clusters/{clusterId}/upgrade-plans/{planId}/{upgradeAction}",
}


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = load("upgrade_plan_readiness_support", "deploy-eks-upgrade-readiness-prod.py")
summary = base.summary
support = base.support
ACCOUNT, REGION, PARENT = base.ACCOUNT, base.REGION, base.PARENT
require = base.require


def digest(value):
    return hashlib.sha256(value).hexdigest()


def code_hash(value):
    return base64.b64encode(hashlib.sha256(value).digest()).decode()


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, default=str))


def git_source(tree, path):
    return subprocess.check_output(["git", "show", f"{tree}:{path}"], cwd=ROOT)


def semantic(source):
    return ast.dump(ast.parse(source.decode()), include_attributes=False)


def handler_baselines(source):
    values = {semantic(source)}
    repository_order = (
        b"from .bootstrap_status import refresh_installer_status\n"
        b"from .tool_access import resolve_tool_access\n"
        b"from .upgrade_readiness import EksUpgradeDiscovery\n"
    )
    legacy_order = (
        b"from .tool_access import resolve_tool_access\n"
        b"from .bootstrap_status import refresh_installer_status\n"
        b"from .upgrade_readiness import EksUpgradeDiscovery\n"
    )
    deployed_readiness_order = (
        b"from .tool_access import resolve_tool_access\n"
        b"from .upgrade_readiness import EksUpgradeDiscovery\n"
        b"from .bootstrap_status import refresh_installer_status\n"
    )
    if repository_order in source:
        values.add(semantic(source.replace(repository_order, legacy_order, 1)))
        values.add(semantic(source.replace(repository_order, deployed_readiness_order, 1)))
    return values


def check_checkout(expected_branch):
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    require(branch == expected_branch, f"Check out the exact release source branch {expected_branch}")
    paths = [
        "scripts/deploy-eks-upgrade-plans-prod.py",
        "src/navigan/modules/cluster_management/handler.py",
        "src/navigan/modules/cluster_management/models.py",
        "src/navigan/modules/cluster_management/upgrade_readiness.py",
        "src/navigan/modules/cluster_management/upgrade_plans.py",
        "infrastructure/modules/cluster-management/template.yaml",
    ]
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--", *paths], cwd=ROOT, text=True)
    require(not dirty.strip(), "Commit the reviewed EKS upgrade-plan release sources first")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def package(original, destination):
    prefix = "navigan/modules/cluster_management/"
    managed = {
        prefix + "handler.py": "src/navigan/modules/cluster_management/handler.py",
        prefix + "models.py": "src/navigan/modules/cluster_management/models.py",
        prefix + "upgrade_readiness.py": "src/navigan/modules/cluster_management/upgrade_readiness.py",
    }
    new_module = prefix + "upgrade_plans.py"
    with zipfile.ZipFile(original) as old:
        names = old.namelist()
        require(len(names) == len(set(names)), "Duplicate ZIP members rejected")
        for member, path in managed.items():
            require(member in names, f"Deployed ClusterFunction is missing {member}")
            baseline = git_source(BASELINE_TREE, path)
            actual = semantic(old.read(member))
            allowed = handler_baselines(baseline) if member.endswith("handler.py") else {semantic(baseline)}
            require(actual in allowed, f"Deployed {member} differs from the reviewed production baseline")
        require(
            new_module not in names, "Upgrade-plan module is already present; prepare from a fresh baseline"
        )
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as new:
            for entry in old.infolist():
                if entry.filename.endswith(".pyc") and any(
                    f"/{name}." in entry.filename
                    for name in ("handler", "models", "upgrade_readiness", "upgrade_plans")
                ):
                    continue
                source = managed.get(entry.filename)
                new.writestr(entry, (ROOT / source).read_bytes() if source else old.read(entry.filename))
            new.writestr(new_module, (ROOT / "src" / new_module).read_bytes())
    with zipfile.ZipFile(destination) as updated:
        require(
            sum(item.file_size for item in updated.infolist()) <= 250 * 1024 * 1024,
            "Updated ClusterFunction package is too large",
        )
    return destination


def verify_database(session, parent):
    params = {item["ParameterKey"]: item["ParameterValue"] for item in parent.get("Parameters", [])}
    require(params.get("DatabaseName") == "navigan", "Expected PROD database navigan")
    cluster = session.client("rds").describe_db_clusters(DBClusterIdentifier="aws-infra-platform-db")[
        "DBClusters"
    ][0]
    result = session.client("rds-data").execute_statement(
        resourceArn=cluster["DBClusterArn"],
        secretArn=params["ApiDatabaseSecretArn"],
        database="navigan",
        sql=(
            "SELECT to_regclass('cluster_management.upgrade_plans')::text AS table_name, "
            "has_table_privilege('navigan_api','cluster_management.upgrade_plans',"
            "'SELECT,INSERT,UPDATE') AS runtime_grants"
        ),
        formatRecordsAs="JSON",
    )
    rows = json.loads(result["formattedRecords"])
    require(
        len(rows) == 1 and rows[0].get("table_name") and rows[0].get("runtime_grants") is True,
        "Apply confirmed scoped migration 029 before preparing the backend release",
    )


def preflight(session):
    parent, root, record = base.preflight(session)
    verify_database(session, parent)
    gateway = session.client("apigatewayv2")
    existing = {
        item["RouteKey"]: item
        for item in support.all_items(gateway, "get_routes", "Items", ApiId=record["api"])
    }
    presence = {}
    for logical, route_key in ROUTES.items():
        route = existing.get(route_key)
        presence[logical] = bool(route)
        if route:
            reference = record["reference"]
            require(
                all(
                    route.get(key, [] if key == "AuthorizationScopes" else None)
                    == reference.get(key, [] if key == "AuthorizationScopes" else None)
                    for key in ("AuthorizationType", "AuthorizerId", "AuthorizationScopes", "Target")
                ),
                f"Existing route protection differs for {route_key}",
            )
    record["planRoutePresence"] = presence
    return parent, root, record


def validate_delta(before, after, function_logical, presence):
    require(before.keys() == after.keys(), "Nested template settings changed")
    require(
        all(before[key] == after[key] for key in before if key != "Resources"),
        "Nested template settings changed",
    )
    old, new = before["Resources"], after["Resources"]
    require(set(old) <= set(new), "Cluster resource deletion rejected")
    additions = {logical for logical in ROUTES if not presence[logical]}
    require(set(new) - set(old) == additions, "Unexpected Cluster resource addition")
    for key in old:
        if key == function_logical:
            expected = copy.deepcopy(old[key])
            expected["Properties"]["Code"] = new[key]["Properties"]["Code"]
            require(expected == new[key], "Only ClusterFunction code may change")
        else:
            require(old[key] == new[key], "Unrelated Cluster resource changed: " + key)


def proposed_child(record, code):
    after = copy.deepcopy(record["before"])
    function = record["functionLogical"]
    after["Resources"][function]["Properties"]["Code"] = code
    reference = record["reference"]
    for logical, route_key in ROUTES.items():
        if not record["planRoutePresence"][logical]:
            after["Resources"][logical] = {
                "Type": "AWS::ApiGatewayV2::Route",
                "Properties": {
                    "ApiId": record["api"],
                    "RouteKey": route_key,
                    "Target": reference["Target"],
                    "AuthorizationType": reference["AuthorizationType"],
                    "AuthorizerId": reference["AuthorizerId"],
                    "AuthorizationScopes": reference.get("AuthorizationScopes", []),
                },
            }
    validate_delta(record["before"], after, function, record["planRoutePresence"])
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
        cfn.get_template(StackName=saved["stack"], ChangeSetName=child_id, TemplateStage="Processed")[
            "TemplateBody"
        ]
    )
    require(
        digest(json.dumps(after, sort_keys=True).encode()) == saved["templateHash"],
        "Prepared template changed",
    )
    validate_delta(before, after, saved["functionLogical"], saved["planRoutePresence"])
    nested = support.all_items(cfn, "describe_change_set", "Changes", ChangeSetName=child_id)
    allowed = {saved["functionLogical"], saved["integrationLogical"]} | {
        logical for logical in ROUTES if not saved["planRoutePresence"][logical]
    }
    logical_ids = {item["ResourceChange"]["LogicalResourceId"] for item in nested}
    require(logical_ids <= allowed, "Unrelated nested change")
    require(saved["functionLogical"] in logical_ids, "ClusterFunction update missing")
    for item in nested:
        value = item["ResourceChange"]
        require(value.get("Replacement", "False") == "False", "Resource replacement rejected")
        logical = value["LogicalResourceId"]
        if logical == saved["functionLogical"]:
            require(
                value["Action"] == "Modify" and value["ResourceType"] == "AWS::Lambda::Function",
                "ClusterFunction must be modified in place",
            )
        elif logical == saved["integrationLogical"]:
            require(
                value["Action"] == "Modify"
                and value["ResourceType"] == "AWS::ApiGatewayV2::Integration"
                and before["Resources"][logical] == after["Resources"][logical]
                and support.references(before["Resources"][logical], saved["functionLogical"]),
                "Only the unchanged Cluster integration dependency may refresh",
            )
        else:
            require(
                logical in ROUTES
                and value["Action"] == "Add"
                and value["ResourceType"] == "AWS::ApiGatewayV2::Route",
                "Upgrade-plan routes must be protected additions",
            )


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
            "planRoutePresence",
        )
    }


def prepare(session, revision):
    parent, root, record = preflight(session)
    workspace = support.storage.verify_storage(session, "artifact-workspace")
    directory = Path(tempfile.mkdtemp(prefix="navigan-prod-eks-plans-"))
    directory.chmod(0o700)
    print("Private rollback/release record: " + str(directory), flush=True)
    deployed = session.client("lambda").get_function(FunctionName=record["function"])
    require(
        deployed["Configuration"]["RevisionId"] == record["revision"],
        "ClusterFunction changed during preparation",
    )
    original = directory / "ClusterFunction-original.zip"
    with urllib.request.urlopen(deployed["Code"]["Location"], timeout=60) as stream:
        original.write_bytes(stream.read())
    require(
        code_hash(original.read_bytes()) == record["oldSha"], "Original ClusterFunction checksum mismatch"
    )
    updated = package(original, directory / "ClusterFunction-updated.zip")
    code, _ = support.upload(session, workspace, directory, "eks-upgrade-plans.zip", updated.read_bytes())
    child = proposed_child(record, code)
    _, child_url = support.upload(
        session, workspace, directory, "eks-upgrade-plans-cluster-template.json", json.dumps(child).encode()
    )
    updated_root = copy.deepcopy(root)
    updated_root["Resources"]["ClusterManagement"]["Properties"]["TemplateURL"] = child_url
    _, root_url = support.upload(
        session,
        workspace,
        directory,
        "eks-upgrade-plans-parent-template.json",
        json.dumps(updated_root).encode(),
    )
    cfn = session.client("cloudformation")
    request = {
        "StackName": PARENT,
        "ChangeSetName": "navigan-prod-eks-plans-" + uuid.uuid4().hex[:16],
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
            "parentStamp": base.stamp(parent),
            "changeSet": identifier,
            "release": saved,
        },
    )
    print("Scoped PROD EKS plan API release prepared; NOT executed. Release plan: " + str(plan))


def execute(session, plan_path):
    plan = json.loads(plan_path.read_text())
    require(
        (plan.get("format"), plan.get("account"), plan.get("region")) == (FORMAT, ACCOUNT, REGION),
        "Wrong EKS upgrade-plan release plan",
    )
    parent, _, current = preflight(session)
    saved = plan["release"]
    require(base.stamp(parent) == plan["parentStamp"], "Production parent stack changed; prepare again")
    require(
        signature(current) == {key: saved[key] for key in signature(current)},
        "Cluster API changed; prepare again",
    )
    cfn = session.client("cloudformation")
    inspect_change_set(cfn, plan["changeSet"], saved)
    cfn.execute_change_set(ChangeSetName=plan["changeSet"])
    print("Waiting for the scoped Cluster API deployment", flush=True)
    cfn.get_waiter("stack_update_complete").wait(
        StackName=PARENT, WaiterConfig={"Delay": 10, "MaxAttempts": 180}
    )
    _, _, deployed = preflight(session)
    require(deployed["oldSha"] == saved["newSha"], "Deployed ClusterFunction checksum differs")
    require(all(deployed["planRoutePresence"].values()), "Protected upgrade-plan routes were not deployed")
    print("PROD governed EKS upgrade-plan API deployed and verified. No EKS upgrade was started.")


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
    execute(session, args.execute) if args.execute else prepare(session, revision)


if __name__ == "__main__":
    main()
