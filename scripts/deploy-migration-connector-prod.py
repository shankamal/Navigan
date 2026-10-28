#!/usr/bin/env python3
"""Promote only the PROD connector API's source-only assessment implementation.

Default is read-only. --prepare creates an unexecuted scoped CloudFormation
plan with private rollback files. --execute PLAN rechecks the production revision.
Source pods, registrations, credentials, IAM, database, frontend and migration
API are unchanged. Existing pending connector submissions can resume on retry.
"""
from __future__ import annotations

import argparse
import ast
import base64
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request
import uuid
import zipfile

import boto3

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("migration_api_release", ROOT / "scripts/deploy-migration-api-prod.py")
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)
ACCOUNT, REGION, PARENT = api.ACCOUNT, api.REGION, api.PARENT
FUNCTION = "MigrationConnectorFunction"
FLAG = "MIGRATION_SOURCE_FIRST_ENABLED"
MODULES = ("connector_handler.py", "assessment_engine.py", "models.py", "deployment_sources.py")
PREFIX = "navigan/modules/migration_management/"
require = api.require


def code_hash(content):
    return base64.b64encode(hashlib.sha256(content).digest()).decode()


def package_connector(original, directory, source=ROOT):
    replacements = {PREFIX + name: (source / "src" / PREFIX / name).read_bytes() for name in MODULES}
    for name, content in replacements.items():
        ast.parse(content, filename=name)
    require(b"source_only=source_only" in replacements[PREFIX + "connector_handler.py"], "Source-only submission handling is missing")
    require(b"source_only=False" in replacements[PREFIX + "assessment_engine.py"], "Source-only assessment engine is missing")
    target = directory / "MigrationConnectorFunction-updated.zip"
    with zipfile.ZipFile(original) as old:
        names = old.namelist()
        require(len(names) == len(set(names)), "Original connector ZIP contains duplicate members")
        require(all(PREFIX + name in names for name in ("connector_handler.py", "assessment_engine.py", "models.py")), "Unexpected connector package layout")
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as new:
            for entry in old.infolist():
                if entry.filename.startswith(PREFIX) and entry.filename.endswith(".pyc") and any(
                    Path(entry.filename).name.startswith(name[:-3] + ".") or Path(entry.filename).name == name + "c"
                    for name in MODULES
                ):
                    continue
                content = replacements.pop(entry.filename, None)
                new.writestr(entry, old.read(entry.filename) if content is None else content)
            for name, content in sorted(replacements.items()):
                new.writestr(name, content)
    with zipfile.ZipFile(target) as package:
        require(sum(entry.file_size for entry in package.infolist()) <= 250 * 1024 * 1024, "Lambda uncompressed package limit exceeded")
    return target


def connector_template(original, config, code):
    result = copy.deepcopy(original)
    resource = result["Resources"].get(FUNCTION, {})
    require(resource.get("Type") == "AWS::Lambda::Function", "Connector Lambda is absent from processed template")
    props = resource["Properties"]
    require(props.get("Handler") == "navigan.modules.migration_management.connector_handler.lambda_handler", "Unexpected connector handler")
    variables = dict(config.get("Environment", {}).get("Variables", {}))
    require(variables.get("DB_NAME") == "navigan", "Connector must use production database navigan")
    variables[FLAG] = "true"
    props["Code"] = code
    props["Environment"] = {"Variables": variables}
    return result


def unchanged_dependency(change, before, after):
    logical = change.get("LogicalResourceId")
    old = before["Resources"].get(logical)
    if not old or old != after["Resources"].get(logical) or old.get("Type") != change.get("ResourceType"):
        return False
    if change.get("Action") != "Modify" or change.get("Replacement", "False") != "False" or change.get("ChangeSetId"):
        return False
    props = old.get("Properties", {})
    if old["Type"] == "AWS::ApiGatewayV2::Integration":
        return logical == "MigrationConnectorIntegration" and props.get("IntegrationType") == "AWS_PROXY" and api.references(props.get("IntegrationUri"), FUNCTION)
    if old["Type"] == "AWS::Lambda::Permission":
        return props.get("Action") == "lambda:InvokeFunction" and props.get("Principal") == "apigateway.amazonaws.com" and api.references(props.get("FunctionName"), FUNCTION)
    return False


def validate_children(changes, before, after, config, code):
    expected = dict(config.get("Environment", {}).get("Variables", {}))
    expected[FLAG] = "true"
    require(after["Resources"][FUNCTION]["Properties"].get("Environment") == {"Variables": expected}, "Connector environment changed outside source-first flag")
    require(after["Resources"][FUNCTION]["Properties"].get("Code") == code, "Connector package reference changed")
    require(all(before["Resources"].get(key) == after["Resources"].get(key) for key in set(before["Resources"]) | set(after["Resources"]) if key != FUNCTION), "Unrelated template resource changed")
    original = before["Resources"][FUNCTION]
    proposed = copy.deepcopy(after["Resources"][FUNCTION])
    for key in ("Code", "Environment"):
        if key in original["Properties"]:
            proposed["Properties"][key] = original["Properties"][key]
        else:
            proposed["Properties"].pop(key, None)
    require(proposed == original, "Connector properties outside code/environment changed")
    found = False
    for item in changes:
        change = item.get("ResourceChange", {})
        if change.get("LogicalResourceId") == FUNCTION:
            require(change.get("ResourceType") == "AWS::Lambda::Function" and change.get("Action") == "Modify" and change.get("Replacement", "False") == "False" and not change.get("ChangeSetId"), "Connector recreation/replacement rejected")
            found = True
        else:
            require(unchanged_dependency(change, before, after), "Unexpected connector release change: " + str(change.get("LogicalResourceId")))
        print(f"  Modify {change['LogicalResourceId']} ({change['ResourceType']})")
    require(found, "Connector code change was not found")


def inspect_plan(cfn, identifier, nested, config, code):
    root = cfn.describe_change_set(ChangeSetName=identifier)
    require(root.get("StackName") == PARENT and root.get("Status") == "CREATE_COMPLETE" and root.get("ExecutionStatus") == "AVAILABLE", "Connector change set is not executable")
    changes = api.all_items(cfn, "describe_change_set", "Changes", ChangeSetName=identifier)
    require(len(changes) == 1, "Parent must change only MigrationManagement")
    change = changes[0].get("ResourceChange", {})
    require(change.get("LogicalResourceId") == "MigrationManagement" and change.get("ResourceType") == "AWS::CloudFormation::Stack" and change.get("Action") == "Modify" and change.get("Replacement", "False") == "False" and change.get("ChangeSetId"), "Unexpected parent change")
    child_id = change["ChangeSetId"]
    child = cfn.describe_change_set(ChangeSetName=child_id)
    require(child.get("StackId") == nested, "Unexpected nested stack")
    before = api.body(cfn.get_template(StackName=nested, TemplateStage="Processed")["TemplateBody"])
    after = api.body(cfn.get_template(StackName=nested, ChangeSetName=child_id, TemplateStage="Processed")["TemplateBody"])
    validate_children(api.all_items(cfn, "describe_change_set", "Changes", ChangeSetName=child_id), before, after, config, code)


def live_connector(session, nested):
    name = session.client("cloudformation").describe_stack_resource(StackName=nested, LogicalResourceId=FUNCTION)["StackResourceDetail"]["PhysicalResourceId"]
    config = session.client("lambda").get_function_configuration(FunctionName=name)
    require(config["FunctionArn"].startswith(f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:") and config.get("State") == "Active" and config.get("LastUpdateStatus") == "Successful", "Connector Lambda must be active and stable in the expected account")
    require(config.get("Handler") == "navigan.modules.migration_management.connector_handler.lambda_handler" and config.get("Runtime") == "python3.12" and config.get("PackageType", "Zip") == "Zip", "Unexpected connector runtime/handler/package")
    require(config.get("Environment", {}).get("Variables", {}).get("DB_NAME") == "navigan", "Unexpected connector database")
    return name, config


def execute(session, path):
    plan = json.loads(path.read_text())
    require(plan.get("format") == "prod-connector-v1" and plan.get("account") == ACCOUNT and plan.get("region") == REGION, "Invalid connector release plan")
    require(session.client("sts").get_caller_identity()["Account"] == ACCOUNT, "Unexpected AWS account")
    cfn = session.client("cloudformation")
    parent = cfn.describe_stacks(StackName=PARENT)["Stacks"][0]
    require(parent["StackStatus"] in api.storage.STABLE and api.stamp(parent) == plan["parentStamp"], "Parent stack changed after preparation")
    nested = cfn.describe_stack_resource(StackName=PARENT, LogicalResourceId="MigrationManagement")["StackResourceDetail"]["PhysicalResourceId"]
    require(nested == plan["nested"], "Migration stack identity changed")
    name, config = live_connector(session, nested)
    require(name == plan["function"] and config["RevisionId"] == plan["revision"] and config["CodeSha256"] == plan["originalCodeSha256"], "Connector changed after preparation")
    inspect_plan(cfn, plan["changeSet"], nested, config, plan["code"])
    cfn.execute_change_set(ChangeSetName=plan["changeSet"])
    print("Waiting for scoped PROD connector API update", flush=True)
    cfn.get_waiter("stack_update_complete").wait(StackName=PARENT, WaiterConfig={"Delay": 10, "MaxAttempts": 180})
    _, config = live_connector(session, nested)
    require(config["CodeSha256"] == plan["newCodeSha256"] and config["Environment"]["Variables"].get(FLAG) == "true", "Connector deployment verification failed")
    print("PROD connector API deployed. Existing source pods will retry pending reports automatically. Refresh discovery status; authenticated workflow verification remains required.")


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="navigan")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--execute", type=Path, metavar="PLAN")
    args = parser.parse_args()
    session = boto3.Session(profile_name=args.profile, region_name=REGION)
    if args.execute:
        execute(session, args.execute)
        return
    api.check_checkout()
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--", "scripts/deploy-migration-connector-prod.py"], cwd=ROOT, text=True)
    require(not dirty.strip(), "Commit/review local connector release script edits first")
    settings = api.storage.preflight(session)
    workspace = api.storage.verify_storage(session, "artifact-workspace")
    cfn = session.client("cloudformation")
    parent = cfn.describe_stacks(StackName=PARENT)["Stacks"][0]
    name, config = live_connector(session, settings["nested"])
    root = api.body(cfn.get_template(StackName=PARENT, TemplateStage="Processed")["TemplateBody"])
    child = api.body(cfn.get_template(StackName=settings["nested"], TemplateStage="Processed")["TemplateBody"])
    connector_template(child, config, {})
    print("PROD connector API and database verified; only connector code and source-first flag will change")
    if not args.prepare:
        print("Read-only check passed. Use --prepare to create an unexecuted connector release plan.")
        return
    directory = Path(tempfile.mkdtemp(prefix="navigan-prod-migration-connector-"))
    directory.chmod(0o700)
    print("Private rollback/release record: " + str(directory), flush=True)
    for filename, value in (("parent-original-template.json", root), ("connector-original-template.json", child), ("connector-original-configuration.json", config)):
        (directory / filename).write_text(json.dumps(value, indent=2, default=str))
    deployed = session.client("lambda").get_function(FunctionName=name)
    require(deployed["Configuration"]["RevisionId"] == config["RevisionId"], "Connector changed before package download")
    original = directory / "MigrationConnectorFunction-original.zip"
    with urllib.request.urlopen(deployed["Code"]["Location"], timeout=60) as response, original.open("wb") as stream:
        shutil.copyfileobj(response, stream)
    require(code_hash(original.read_bytes()) == config["CodeSha256"], "Original connector package checksum mismatch")
    package = package_connector(original, directory)
    code, _ = api.upload(session, workspace, directory, "migration-connector.zip", package.read_bytes())
    updated = connector_template(child, config, code)
    _, child_url = api.upload(session, workspace, directory, "connector-template.json", json.dumps(updated).encode())
    updated_root = api.parent_template(root, child_url)
    _, root_url = api.upload(session, workspace, directory, "connector-parent-template.json", json.dumps(updated_root).encode())
    (directory / "connector-updated-template.json").write_text(json.dumps(updated, indent=2))
    request = dict(StackName=PARENT, ChangeSetName="navigan-prod-connector-" + uuid.uuid4().hex[:16], ChangeSetType="UPDATE", TemplateURL=root_url, IncludeNestedStacks=True,
        Capabilities=["CAPABILITY_NAMED_IAM", "CAPABILITY_AUTO_EXPAND"], Parameters=[{"ParameterKey": p["ParameterKey"], "UsePreviousValue": True} for p in parent.get("Parameters", [])])
    if parent.get("RoleARN"):
        request["RoleARN"] = parent["RoleARN"]
    identifier = cfn.create_change_set(**request)["Id"]
    print("Prepared change set: " + identifier, flush=True)
    cfn.get_waiter("change_set_create_complete").wait(ChangeSetName=identifier, WaiterConfig={"Delay": 5, "MaxAttempts": 180})
    inspect_plan(cfn, identifier, settings["nested"], config, code)
    plan = {"format": "prod-connector-v1", "account": ACCOUNT, "region": REGION, "nested": settings["nested"], "function": name,
        "revision": config["RevisionId"], "originalCodeSha256": config["CodeSha256"], "newCodeSha256": code_hash(package.read_bytes()),
        "parentStamp": api.stamp(parent), "changeSet": identifier, "code": code}
    path = directory / "release-plan.json"
    path.write_text(json.dumps(plan, indent=2))
    print("Scoped connector change set validated; not executed. Release plan: " + str(path))


if __name__ == "__main__":
    main()
