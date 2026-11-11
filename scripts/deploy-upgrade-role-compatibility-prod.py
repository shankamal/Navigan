#!/usr/bin/env python3
"""Scoped CloudFormation release: restore legacy Cloud Engineer upgrade planning.

Patch only the role catalogue entry in the existing Access and Cluster packages.
Preserve every other deployed module and all infrastructure properties.
"""
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
spec = importlib.util.spec_from_file_location("role_release_support", ROOT / "scripts/deploy-migration-api-prod.py")
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)
ACCOUNT, REGION, PARENT = support.ACCOUNT, support.REGION, support.PARENT
FORMAT = "navigan-upgrade-role-compatibility-v1"
TARGETS = {"AccessManagement": "AccessFunction", "ClusterManagement": "ClusterFunction"}
MEMBER = "navigan/shared/access.py"
require = support.require


def patch_access(source):
    tree = ast.parse(source)
    assignments = [n for n in tree.body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "LEGACY_ROLE_PRIVILEGES" for t in n.targets)]
    require(len(assignments) == 1 and isinstance(assignments[0].value, ast.Dict), "Unexpected role catalogue")
    catalogue = assignments[0].value
    matches = [v for k, v in zip(catalogue.keys, catalogue.values)
               if isinstance(k, ast.Constant) and k.value == "CLOUD_ENGINEER"]
    require(len(matches) == 1, "Missing unique Cloud Engineer role")
    call = matches[0]
    require(isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            and call.func.id == "frozenset" and len(call.args) == 1
            and isinstance(call.args[0], ast.Set), "Unexpected Cloud Engineer privileges")
    values = call.args[0]
    require(all(isinstance(n, ast.Constant) and isinstance(n.value, str) for n in values.elts), "Nonliteral role privileges")
    privileges = {n.value for n in values.elts}
    require({"cluster.create", "cluster.submit", "cluster.view"} <= privileges, "Unexpected maker role")
    if "cluster.upgrade.plan" in privileges:
        return source
    last = values.elts[-1]
    lines = source.splitlines(keepends=True)
    lines.insert(last.end_lineno, ' ' * last.col_offset + '"cluster.upgrade.plan",\n')
    patched = "".join(lines)
    values.elts.append(ast.Constant(value="cluster.upgrade.plan"))
    require(ast.dump(tree, include_attributes=False) == ast.dump(ast.parse(patched), include_attributes=False),
            "Patch changed more than the maker privilege")
    return patched


def package(original, destination):
    with zipfile.ZipFile(original) as old:
        require(len(old.namelist()) == len(set(old.namelist())) and MEMBER in old.namelist(), "Invalid Lambda archive")
        source = old.read(MEMBER).decode()
        patched = patch_access(source).encode()
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as new:
            for entry in old.infolist():
                if entry.filename.endswith(".pyc") and entry.filename.startswith("navigan/shared/") and "access." in entry.filename:
                    continue
                new.writestr(entry, patched if entry.filename == MEMBER else old.read(entry.filename))
    return destination


def sha(data):
    return base64.b64encode(hashlib.sha256(data).digest()).decode()


def snapshot(session):
    require(session.client("sts").get_caller_identity()["Account"] == ACCOUNT, "Unexpected account")
    cfn = session.client("cloudformation")
    parent = cfn.describe_stacks(StackName=PARENT)["Stacks"][0]
    require(parent["StackStatus"] in {"CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"}, "Production stack not stable")
    root = support.body(cfn.get_template(StackName=PARENT, TemplateStage="Processed")["TemplateBody"])
    records = {}
    for logical, function_logical in TARGETS.items():
        child = cfn.describe_stack_resource(StackName=PARENT, LogicalResourceId=logical)["StackResourceDetail"]["PhysicalResourceId"]
        fn = cfn.describe_stack_resource(StackName=child, LogicalResourceId=function_logical)["StackResourceDetail"]["PhysicalResourceId"]
        config = session.client("lambda").get_function_configuration(FunctionName=fn)
        require(config["FunctionArn"].startswith(f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{PARENT}-"), "Unexpected function")
        require(config.get("State") == "Active" and config.get("LastUpdateStatus") == "Successful", "Function not stable")
        records[logical] = {"stack": child, "function": fn, "revision": config["RevisionId"], "oldSha": config["CodeSha256"],
                            "before": support.body(cfn.get_template(StackName=child, TemplateStage="Processed")["TemplateBody"])}
    return parent, root, records


def inspect(cfn, identifier, plan):
    changes = cfn.describe_change_set(ChangeSetName=identifier)
    require(changes["Status"] == "CREATE_COMPLETE", "Change set not ready")
    require(not changes.get("NextToken"), "Unexpected paginated root change set")
    root_changes = changes.get("Changes", [])
    require(bool(root_changes), "Empty change set")
    for item in root_changes:
        change = item["ResourceChange"]
        logical = change["LogicalResourceId"]
        require(logical in TARGETS and change["Action"] == "Modify" and change.get("Replacement") == "False"
                and change["ResourceType"] == "AWS::CloudFormation::Stack" and change.get("ChangeSetId"), "Unrelated root change")
        record = plan["releases"][logical]
        fn = TARGETS[logical]
        nested = cfn.describe_change_set(ChangeSetName=change["ChangeSetId"])
        require(nested["Status"] == "CREATE_COMPLETE" and not nested.get("NextToken"), "Nested change set incomplete")
        for child in nested.get("Changes", []):
            rc = child["ResourceChange"]
            require(rc["Action"] == "Modify" and rc.get("Replacement", "False") == "False", "Unexpected resource replacement")
            if rc["LogicalResourceId"] == fn:
                require(rc["ResourceType"] == "AWS::Lambda::Function", "Wrong function type")
                continue
            # Only unchanged API dependents may be reevaluated by CloudFormation.
            resource = record["before"]["Resources"].get(rc["LogicalResourceId"], {})
            props = resource.get("Properties", {})
            kind = resource.get("Type")
            integration = fn.replace("Function", "Integration")
            allowed = (
                kind == "AWS::ApiGatewayV2::Integration"
                and rc["LogicalResourceId"] == integration
                and props.get("IntegrationType") == "AWS_PROXY"
                and support.references(props.get("IntegrationUri"), fn)
            ) or (
                kind == "AWS::ApiGatewayV2::Route" and props.get("AuthorizationType") == "JWT"
                and bool(props.get("AuthorizerId")) and support.references(props.get("Target"), integration)
            ) or (
                kind == "AWS::Lambda::Permission" and props.get("Action") == "lambda:InvokeFunction"
                and props.get("Principal") == "apigateway.amazonaws.com"
                and support.references(props.get("FunctionName"), fn)
            )
            require(allowed and kind == rc["ResourceType"] and not rc.get("ChangeSetId"), "Unrelated nested change")


def prepare(session):
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    require(branch == "feature/eks-upgrade-readiness", "Check out feature/eks-upgrade-readiness")
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--",
        "scripts/deploy-upgrade-role-compatibility-prod.py", "src/navigan/shared/access.py"], cwd=ROOT, text=True)
    require(not dirty.strip(), "Commit reviewed authorization release sources first")
    parent, root, records = snapshot(session)
    workspace = support.storage.verify_storage(session, "artifact-workspace")
    directory = Path(tempfile.mkdtemp(prefix="navigan-prod-upgrade-roles-"))
    directory.chmod(0o700)
    proposed = copy.deepcopy(root)
    for logical, record in records.items():
        deployed = session.client("lambda").get_function(FunctionName=record["function"])
        require(deployed["Configuration"]["RevisionId"] == record["revision"], "Function changed during preparation")
        original = directory / (logical + "-original.zip")
        with urllib.request.urlopen(deployed["Code"]["Location"], timeout=60) as stream:
            original.write_bytes(stream.read())
        require(sha(original.read_bytes()) == record["oldSha"], "Original archive checksum mismatch")
        updated = package(original, directory / (logical + "-updated.zip"))
        record["newSha"] = sha(updated.read_bytes())
        code, _ = support.upload(session, workspace, directory, logical + ".zip", updated.read_bytes())
        after = copy.deepcopy(record["before"])
        after["Resources"][TARGETS[logical]]["Properties"]["Code"] = code
        _, url = support.upload(session, workspace, directory, logical + ".json", json.dumps(after).encode())
        proposed["Resources"][logical]["Properties"]["TemplateURL"] = url
    _, url = support.upload(session, workspace, directory, "upgrade-roles-parent.json", json.dumps(proposed).encode())
    cfn = session.client("cloudformation")
    change = cfn.create_change_set(StackName=PARENT, ChangeSetName="navigan-prod-upgrade-roles-" + uuid.uuid4().hex[:16],
        ChangeSetType="UPDATE", TemplateURL=url, IncludeNestedStacks=True,
        Capabilities=["CAPABILITY_NAMED_IAM", "CAPABILITY_AUTO_EXPAND"],
        Parameters=[{"ParameterKey": p["ParameterKey"], "UsePreviousValue": True} for p in parent.get("Parameters", [])])["Id"]
    cfn.get_waiter("change_set_create_complete").wait(ChangeSetName=change)
    plan = {"format": FORMAT, "account": ACCOUNT, "region": REGION, "parentStamp": support.stamp(parent),
            "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "changeSet": change, "releases": records}
    inspect(cfn, change, plan)
    path = directory / "release-plan.json"
    path.write_text(json.dumps(plan, indent=2))
    print("Scoped upgrade-role compatibility release prepared; NOT executed. Release plan: " + str(path), flush=True)


def execute(session, path):
    plan = json.loads(path.read_text())
    require((plan.get("format"), plan.get("account"), plan.get("region")) == (FORMAT, ACCOUNT, REGION), "Wrong release plan")
    parent, _, records = snapshot(session)
    require(support.stamp(parent) == plan["parentStamp"], "Parent stack changed; prepare again")
    for logical, current in records.items():
        saved = plan["releases"][logical]
        require(all(current[k] == saved[k] for k in ("stack", "function", "revision", "oldSha", "before")), "Function changed; prepare again")
    cfn = session.client("cloudformation")
    inspect(cfn, plan["changeSet"], plan)
    cfn.execute_change_set(ChangeSetName=plan["changeSet"])
    print("Waiting for the scoped authorization deployment", flush=True)
    cfn.get_waiter("stack_update_complete").wait(StackName=PARENT, WaiterConfig={"Delay": 10, "MaxAttempts": 180})
    _, _, deployed = snapshot(session)
    for logical, current in deployed.items():
        require(current["oldSha"] == plan["releases"][logical]["newSha"], "Deployed checksum differs")
    print("PROD legacy Cloud Engineer upgrade planning deployed and checksums verified. No upgrade started.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="navigan")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prepare", action="store_true")
    group.add_argument("--execute", type=Path)
    args = parser.parse_args()
    session = boto3.Session(profile_name=args.profile, region_name=REGION)
    execute(session, args.execute) if args.execute else prepare(session)
