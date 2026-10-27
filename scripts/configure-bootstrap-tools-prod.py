#!/usr/bin/env python3
"""Bind the existing PROD tools URL to automatic bootstrap through CloudFormation.

--prepare stages checked, unexecuted previews. --apply also executes the parent.
--execute PLAN resumes an unchanged prepared plan. Only StatusFunction's tools
URL is added; no code, image, feature flag, permission or customer resource edits.
Private capture/rollback records remain local. Child/no-op previews never execute.
"""
import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import uuid

import boto3

import importlib.util
spec = importlib.util.spec_from_file_location("bootstrap_tools_release", Path(__file__).with_name("deploy-cluster-bootstrap-prod.py"))
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
require = h.require
URL = "https://navigan.click/tools"
KEY = "PLATFORM_TOOLS_BASE_URL"
FORMAT = "navigan-bootstrap-tools-prod-v1"


def saved_capture(directory):
    summary = h.read(directory / "summary.json")
    require((summary.get("environment"), summary.get("account"), summary.get("region"), summary.get("stackName"))
            == ("prod", h.ACCOUNT, h.REGION, h.PARENT), "Unexpected PROD capture.")
    saved = {"directory": directory, "summary": summary,
             "root": h.read(directory / "root-stack.json"), "child": h.read(directory / "cluster-stack.json"),
             "rootTemplate": h.read(directory / "root-template.json"), "childTemplate": h.read(directory / "cluster-template.json"),
             "configs": {name: h.read(directory / (name + "-config.json")) for name in h.FUNCTIONS},
             "project": h.read(directory / "terraform-project.json")}
    saved["image"] = saved["project"]["environment"]["image"]
    for name, config in saved["configs"].items():
        require(h.code_hash(directory / (name + ".zip")) == config["CodeSha256"], "Capture ZIP checksum mismatch.")
    return saved


def desired(saved, child_url=None):
    live = saved["configs"]["ClusterFunction"]["Environment"]["Variables"]
    require(live.get(KEY) == URL and all(live.get(key) == "true" for key in (
        "PLATFORM_TOOLS_GATEWAY_ENABLED", "PLATFORM_TOOLS_TUNNEL_ENABLED")), "Existing PROD gateway is not enabled at the expected URL.")
    require(h.parameters(saved["root"]).get("PlatformToolsBaseUrl") == URL
            and h.parameters(saved["child"]).get("PlatformToolsBaseUrl") == URL,
            "Existing parent/child tools URL parameters differ from the verified gateway.")
    current = saved["childTemplate"]
    require(current["Resources"]["StatusFunction"]["Type"] == "AWS::Lambda::Function", "Expected processed Lambda resource.")
    cluster_env = current["Resources"]["ClusterFunction"]["Properties"]["Environment"]["Variables"]
    require(cluster_env.get(KEY) == {"Ref": "PlatformToolsBaseUrl"}, "Existing tools URL is not the expected parameter binding.")
    status_env = saved["configs"]["StatusFunction"]["Environment"]["Variables"]
    require(not status_env.get(KEY), "StatusFunction already has a tools URL; inspect rather than overwrite it.")
    child = copy.deepcopy(current)
    variables = child["Resources"]["StatusFunction"]["Properties"]["Environment"]["Variables"]
    require(not variables.get(KEY), "StatusFunction template already has a tools URL binding.")
    variables[KEY] = copy.deepcopy(cluster_env[KEY])
    root = copy.deepcopy(saved["rootTemplate"])
    if child_url:
        root["Resources"]["ClusterManagement"]["Properties"]["TemplateURL"] = child_url
    return root, child


def validate_templates(saved, root, child):
    expected_root, expected_child = desired(saved)
    expected_root["Resources"]["ClusterManagement"]["Properties"]["TemplateURL"] = root["Resources"]["ClusterManagement"]["Properties"]["TemplateURL"]
    require(root == expected_root and child == expected_child, "Only the StatusFunction tools URL and parent template pointer may change.")


def create_preview(cfn, stack, *, body=None, url=None):
    request = {"StackName": stack["StackId"], "ChangeSetName": "bootstrap-tools-" + uuid.uuid4().hex[:12],
               "ChangeSetType": "UPDATE", "IncludeNestedStacks": False,
               "Capabilities": ["CAPABILITY_NAMED_IAM", "CAPABILITY_AUTO_EXPAND"],
               "Parameters": [{"ParameterKey": item["ParameterKey"], "UsePreviousValue": True} for item in stack.get("Parameters", [])]}
    if body is not None:
        text = json.dumps(body)
        require(len(text.encode()) <= 51200, "Parent template exceeds inline limit.")
        request["TemplateBody"] = text
    else:
        request["TemplateURL"] = url
    if stack.get("RoleARN"):
        request["RoleARN"] = stack["RoleARN"]
    identifier = cfn.create_change_set(**request)["Id"]
    print("Prepared unexecuted preview: " + identifier, flush=True)
    cfn.get_waiter("change_set_create_complete").wait(ChangeSetName=identifier, WaiterConfig={"Delay": 5, "MaxAttempts": 180})
    return identifier


def verify_child(session, saved, plan):
    cfn = session.client("cloudformation")
    identifier = plan["preview"]
    meta = cfn.describe_change_set(ChangeSetName=identifier)
    require(meta.get("StackId") == saved["child"]["StackId"] and meta.get("Status") == "CREATE_COMPLETE"
            and meta.get("ExecutionStatus") == "AVAILABLE" and meta.get("IncludeNestedStacks") is False
            and not meta.get("ParentChangeSetId"), "Child preview is not independent and available.")
    inputs = h.references.resolve_inputs(h.proof_context(), cfn, saved, plan)
    previous, chosen = h.parameters(saved["child"]), {}
    for item in meta.get("Parameters", []):
        key = item["ParameterKey"]
        require(key not in chosen, "Duplicate child parameter.")
        if item.get("UsePreviousValue"):
            require(key in previous and item.get("ParameterValue") in (None, previous[key]), "Changed previous-value binding.")
            chosen[key] = previous[key]
        else:
            chosen[key] = item.get("ParameterValue")
    require(chosen == inputs["parameters"] == previous, "Child preview changes existing parameters.")
    child = h.audit.template_body(cfn.get_template(StackName=saved["child"]["StackId"], ChangeSetName=identifier, TemplateStage="Processed")["TemplateBody"])
    root = h.read(Path(plan["directory"]) / "root-updated-template.json")
    validate_templates(saved, root, child)
    require(h.fingerprint(child) == plan["childHash"] and h.fingerprint(root) == plan["rootHash"], "Prepared templates changed.")
    rows = h.items(cfn, "describe_change_set", "Changes", ChangeSetName=identifier)
    seen = set()
    for entry in rows:
        row = entry["ResourceChange"]
        logical = row.get("LogicalResourceId")
        require(logical not in seen, "Duplicate child resource.")
        seen.add(logical)
        if logical == "StatusFunction":
            details = row.get("Details") or []
            require((row.get("ResourceType"), row.get("Action"), row.get("Replacement")) == ("AWS::Lambda::Function", "Modify", "False")
                    and not row.get("ChangeSetId") and details and all(
                        item.get("Target", {}).get("Attribute") == "Properties" and item["Target"].get("Name") == "Environment"
                        and item["Target"].get("RequiresRecreation") == "Never" for item in details),
                    "StatusFunction preview includes a replacement or another property.")
        else:
            require(logical in {"BuildStateRule", "BuildStatePermission"}, "Unexpected resource in tools configuration preview.")
            h.references.dependency(h.proof_context(), row, saved["childTemplate"]["Resources"], child["Resources"], concrete=True)
    require("StatusFunction" in seen, "Preview omits the intended URL change.")
    return {"inputs": inputs, "snapshot": h.references.snapshot(h.proof_context(), session, saved, inputs)}


def prepare(session):
    directory = Path(tempfile.mkdtemp(prefix="navigan-bootstrap-tools-"))
    print("Private configuration release record: " + str(directory), flush=True)
    capture = directory / "baseline"
    capture.mkdir(mode=0o700)
    args = SimpleNamespace(expected_account=h.ACCOUNT, region=h.REGION, stack_name=h.PARENT,
                           expected_database="navigan", environment="prod", inspect_runner=False)
    h.audit.capture(session, args, capture)
    saved = saved_capture(capture)
    h.preflight(session, saved)
    _, child = desired(saved)
    workspace = h.storage.verify_storage(session, "artifact-workspace")
    _, child_url = h.upload(session, workspace, "bootstrap-tools-template.json", json.dumps(child).encode())
    root, child = desired(saved, child_url)
    validate_templates(saved, root, child)
    h.audit.write_json(directory / "root-updated-template.json", root)
    h.audit.write_json(directory / "cluster-updated-template.json", child)
    h.preflight(session, saved)
    cfn = session.client("cloudformation")
    preview = create_preview(cfn, saved["child"], url=child_url)
    plan = {"format": FORMAT, "directory": str(directory), "account": h.ACCOUNT, "region": h.REGION, "parent": h.PARENT,
            "newImage": saved["image"], "childHash": h.fingerprint(child), "rootHash": h.fingerprint(root), "preview": preview}
    proof = verify_child(session, saved, plan)
    h.preflight(session, saved)
    parent = create_preview(cfn, saved["root"], body=root)
    plan["changeSet"] = parent
    path = directory / "release-plan.json"
    h.audit.write_json(path, plan)
    h.audit.write_json(directory / "reference-proof.json", proof)
    siblings = h.references.inspect_parent(h.proof_context(), cfn, saved, plan, parent)
    h.audit.write_json(directory / "sibling-noop-proof.json", siblings)
    print("Configuration scope verified: StatusFunction tools URL only. Plan: " + str(path), flush=True)
    return path


def verify_after(session, saved, plan, proof, siblings):
    cfn = session.client("cloudformation")
    for key in ("root", "child"):
        stack = cfn.describe_stacks(StackName=saved[key]["StackId"])["Stacks"][0]
        require(stack["StackStatus"] == "UPDATE_COMPLETE" and h.parameters(stack) == h.parameters(saved[key]), "Stack status or parameters changed unexpectedly.")
        actual = h.audit.template_body(cfn.get_template(StackName=stack["StackId"], TemplateStage="Processed")["TemplateBody"])
        require(h.fingerprint(actual) == plan[key + "Hash"], "Deployed template differs from the reviewed configuration.")
    for name, old in saved["configs"].items():
        actual = session.client("lambda").get_function_configuration(FunctionName=old["FunctionName"])
        expected = copy.deepcopy(old)
        if name == "StatusFunction":
            expected["Environment"]["Variables"][KEY] = URL
        require(actual.get("State") == "Active" and actual.get("LastUpdateStatus") == "Successful" and actual["CodeSha256"] == old["CodeSha256"]
                and all(actual.get(key) == expected.get(key) for key in h.CONFIG_KEYS), "Unexpected Lambda code or configuration after deployment.")
    current = session.client("codebuild").batch_get_projects(names=[saved["project"]["name"]])["projects"]
    require(len(current) == 1 and h.fingerprint(current[0]) == h.fingerprint(saved["project"]), "Terraform project changed during URL-only deployment.")
    h.references.after_deployment(h.proof_context(), session, saved, proof)
    h.references.siblings_after(h.proof_context(), cfn, saved, siblings)


def execute(session, path):
    path = path.resolve()
    plan = h.read(path)
    require((plan.get("format"), plan.get("account"), plan.get("region"), plan.get("parent"), plan.get("directory"))
            == (FORMAT, h.ACCOUNT, h.REGION, h.PARENT, str(path.parent)), "Unexpected configuration plan.")
    journal = path.parent / "execution.json"
    require(not journal.exists(), "Execution was already requested; inspect execution.json and AWS before retrying.")
    saved = saved_capture(path.parent / "baseline")
    require(plan["newImage"] == saved["image"], "Runner image must remain unchanged.")
    h.preflight(session, saved)
    proof = verify_child(session, saved, plan)
    require(h.fingerprint(proof) == h.fingerprint(h.read(path.parent / "reference-proof.json")), "API, callback or physical identity drift since preparation.")
    siblings = h.read(path.parent / "sibling-noop-proof.json")
    cfn = session.client("cloudformation")
    h.references.inspect_parent(h.proof_context(), cfn, saved, plan, plan["changeSet"], module_proofs=siblings)
    h.preflight(session, saved)
    require(h.fingerprint(verify_child(session, saved, plan)) == h.fingerprint(proof), "Reference proof changed during final preflight.")
    h.audit.write_json(journal, {"changeSet": plan["changeSet"], "requestedAt": datetime.now(timezone.utc).isoformat()})
    cfn.execute_change_set(ChangeSetName=plan["changeSet"])
    print("Executing parent configuration update: StatusFunction tools URL only...", flush=True)
    cfn.get_waiter("stack_update_complete").wait(StackName=h.PARENT, WaiterConfig={"Delay": 10, "MaxAttempts": 180})
    verify_after(session, saved, plan, proof, siblings)
    h.audit.write_json(path.parent / "verification.json", {"changeSet": plan["changeSet"], "verifiedAt": datetime.now(timezone.utc).isoformat(), "toolsBaseUrl": URL})
    print("PROD automatic-bootstrap tools URL verified. Existing GitOps repositories require their own scoped URL repair.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="navigan")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--execute", type=Path)
    args = parser.parse_args()
    session = boto3.Session(profile_name=args.profile, region_name=h.REGION)
    path = args.execute or prepare(session)
    if args.apply or args.execute:
        execute(session, path)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        message = str(error) if isinstance(error, (ValueError, FileNotFoundError)) else type(error).__name__
        raise SystemExit("Configuration release stopped: " + message + ". Keep the private record local.")
