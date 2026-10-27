#!/usr/bin/env python3
"""Prepare a PROD task changing only API origin/path; execute its saved plan.

Copies the actual running task, never the stale CloudFormation task. No image
build/push, feature-flag change or CloudFormation update. --prepare registers a
candidate but leaves the service unchanged. --rollback restores the saved task.
Private records retain the existing CloudFormation drift for SAM reconciliation.
"""
import argparse
import copy
from datetime import datetime, timezone, timedelta
import importlib.util
from pathlib import Path
import re
import tempfile

import boto3


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


front = load("frontend_release", "deploy-frontend-prod.py")
parity = load("frontend_domain_parity", "validate-api-domain-parity.py")
domain = parity.release
require, read, write, fingerprint = domain.require, domain.read, domain.write, domain.fingerprint
FORMAT = "navigan-frontend-api-domain-v1"
STACK = "navigan-frontend"
KEYS = ("NAVIGAN_API_ORIGIN", "NAVIGAN_API_BASE_PATH")
NEW = {KEYS[0]: "https://api.navigan.click", KEYS[1]: "/api/v1"}
# AWS's documented Mumbai Fargate agent repository, not an application image:
# https://docs.aws.amazon.com/guardduty/latest/ug/ecs-runtime-agent-ecr-image-uri.html
GUARDDUTY_REPOSITORY = "251508486986.dkr.ecr.ap-south-1.amazonaws.com/aws-guardduty-agent-fargate"


def task_arn(value):
    require(bool(re.fullmatch(r"arn:aws:ecs:" + re.escape(front.REGION + ":" + front.ACCOUNT)
            + r":task-definition/" + re.escape(front.FAMILY) + r":[1-9][0-9]*", value)), "Unexpected frontend task identity.")


def original_request(ecs, described):
    accepted = ecs.meta.service_model.operation_model("RegisterTaskDefinition").input_shape.members
    return front.task_request(described["taskDefinition"], described.get("tags", []), accepted)


def service_config(service):
    # Preserve all settings, including future fields, except runtime status and
    # deployment history. The task reference is verified separately per phase.
    dynamic = {"deployments", "events", "taskSets", "runningCount", "pendingCount", "taskDefinition", "status"}
    return {key: value for key, value in service.items() if key not in dynamic}


def candidate_request(original, old_url):
    result = copy.deepcopy(original)
    container = front.container(result)
    env = front.environment(container)
    require(env.get("NODE_ENV", "production") == "production", "Expected the production frontend runtime.")
    require(env.get(KEYS[0], "").rstrip("/") + env.get(KEYS[1], "") == old_url,
            "Running frontend is not using the captured original PROD API URL.")
    require(not any(item.get("name") in KEYS for item in container.get("secrets", [])), "API URL settings cannot also be secret overrides.")
    require(all(key in env for key in KEYS), "Both API settings must be explicit in the current task.")
    for item in container["environment"]:
        if item["name"] in NEW:
            item["value"] = NEW[item["name"]]
    require(all(re.fullmatch(r".+@sha256:[a-f0-9]{64}", c.get("image", "")) for c in result["containerDefinitions"]),
            "All existing container images must be digest-pinned before this configuration-only rollout.")
    require(bool(re.fullmatch(re.escape(front.IMAGE_PREFIX) + r"@sha256:[a-f0-9]{64}", container["image"])), "Unexpected frontend image repository/digest.")
    return front.normalize(result)


def domain_gate(session, path, *, authenticated):
    plan, old, new = parity.targets(path, front.ACCOUNT, front.REGION)
    require(plan["environment"] == "prod" and new == NEW[KEYS[0]] + NEW[KEYS[1]], "Expected the verified PROD domain plan.")
    if authenticated:
        evidence = read(path.parent / "authenticated-verification.json")
        require(evidence.get("environment") == "prod" and evidence.get("changeSet") == plan["changeSet"]
                and evidence.get("passed") is True and len(evidence.get("requests", [])) == len(parity.ENDPOINTS)
                and {row.get("endpoint") for row in evidence["requests"]} == set(parity.ENDPOINTS)
                and all(row.get("passed") is True and row.get("sameJson") is True
                    and row.get("existing", {}).get("status") == row.get("custom", {}).get("status") == 200
                    for row in evidence["requests"]), "Matching successful PROD authenticated summary evidence is required.")
        observed = datetime.fromisoformat(evidence["observedAt"])
        require(observed.utcoffset() is not None and timedelta(0) <= datetime.now(timezone.utc) - observed < timedelta(hours=24),
                "Authenticated evidence must be from the last 24 hours; rerun the parity check.")
    domain.verify(session, path, front.ACCOUNT, front.REGION)
    return old


def cfn_state(session):
    cfn = session.client("cloudformation")
    stack = cfn.describe_stacks(StackName=STACK)["Stacks"][0]
    require(stack["StackId"].startswith(f"arn:aws:cloudformation:{front.REGION}:{front.ACCOUNT}:stack/{STACK}/")
            and stack["StackStatus"] in {"CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"}, "Frontend stack is not the expected stable stack.")
    resources = domain.audit.pages(cfn, "list_stack_resources", "StackResourceSummaries", StackName=stack["StackId"])
    ids = {row["LogicalResourceId"]: row["PhysicalResourceId"] for row in resources}
    require(ids.get("Cluster") == front.CLUSTER and ids.get("Service", "").rsplit("/", 1)[-1] == front.SERVICE,
            "Captured CloudFormation stack does not own the expected Navigan frontend service.")
    return {"stack": stack, "resources": resources,
            "template": cfn.get_template(StackName=stack["StackId"], TemplateStage="Original")}


def check_cfn(session, baseline):
    current = cfn_state(session)
    for key in ("stack", "template"):
        require(fingerprint(current[key]) == fingerprint(baseline[key]), "Frontend CloudFormation state changed since capture.")
    require(fingerprint(sorted(current["resources"], key=lambda row: row["LogicalResourceId"]))
            == fingerprint(sorted(baseline["resources"], key=lambda row: row["LogicalResourceId"])), "Frontend resource identities changed since capture.")


def check_service(session, baseline, expected_task, *, stable=True):
    service = front.read_service(session.client("ecs"))
    require(service["taskDefinition"] == expected_task and (not stable or front.stable(service)),
            "Frontend baseline/revision or rollout state changed; inspect before retrying.")
    require(fingerprint(service_config(service)) == fingerprint(service_config(baseline["service"])), "Frontend service configuration changed since capture.")
    require(service.get("deploymentConfiguration", {}).get("minimumHealthyPercent") == 100
            and service.get("deploymentConfiguration", {}).get("maximumPercent", 0) >= 200
            and service.get("deploymentConfiguration", {}).get("strategy", "ROLLING") == "ROLLING",
            "Expected the existing rolling configuration with start-before-stop capacity.")
    check_cfn(session, baseline)
    return service


def guardduty_configuration(session):
    """Read ECS's AWS-managed activation flag and the exact cluster's scope tag.

    These settings prove managed-agent provenance when ECS omits its image
    metadata. They are recorded and compared, never enabled/disabled here.
    """
    ecs = session.client("ecs")
    settings, token = [], None
    while True:
        page = ecs.list_account_settings(name="guardDutyActivate", effectiveSettings=True,
            **({"nextToken": token} if token else {}))
        settings.extend(page.get("settings", []))
        token = page.get("nextToken")
        if not token:
            break
    require(len(settings) == 1 and settings[0].get("name") == "guardDutyActivate"
            and settings[0].get("value") in {"enabled", "disabled", "on", "off"}
            and settings[0].get("type", "aws_managed") in {"aws_managed", "aws-managed"},
            "Cannot independently establish the AWS-managed GuardDuty account setting.")
    result = ecs.describe_clusters(clusters=[front.CLUSTER], include=["TAGS"])
    clusters = result.get("clusters", [])
    arn = f"arn:aws:ecs:{front.REGION}:{front.ACCOUNT}:cluster/{front.CLUSTER}"
    require(not result.get("failures") and len(clusters) == 1 and clusters[0].get("clusterArn") == arn,
            "Cannot establish GuardDuty scope on the exact frontend cluster.")
    tags = [tag["value"] for tag in clusters[0].get("tags", []) if tag.get("key") == "GuardDutyManaged"]
    require(len(tags) <= 1, "Duplicate GuardDuty scope tags require review.")
    return {"clusterArn": arn, "accountValue": settings[0]["value"],
            "settingType": "aws_managed", "clusterTag": tags[0] if tags else None}


def has_captured_agent(baseline):
    declared = {c["name"] for c in baseline["task"]["taskDefinition"]["containerDefinitions"]}
    return any(c.get("name", "").startswith("aws-guardduty-agent-") and c["name"] not in declared
        for task in baseline.get("runningTasks", {}).get("tasks", []) for c in task.get("containers", []))


def agent_states(tasks):
    return [c.get("lastStatus", "UNKNOWN") for task in tasks for c in task.get("containers", [])
            if c.get("name", "").startswith("aws-guardduty-agent-")]


def managed_agent_expected(proof):
    return bool(proof) and proof["accountValue"] in {"enabled", "on"} and proof["clusterTag"] != "false"


def runtime_overrides(item, definition, *, guardduty_proof=None):
    """Recognize a proven AWS-injected agent without copying its overrides."""
    declared = {c["name"] for c in definition["containerDefinitions"]}
    containers = item.get("containers", [])
    names = [c.get("name") for c in containers]
    require(all(isinstance(name, str) and name for name in names) and len(names) == len(set(names))
            and declared <= set(names), "Runtime container identities differ from the registered task.")
    injected = [c for c in containers if c["name"] not in declared]
    require(len(injected) <= 1, "Unexpected extra runtime containers require review.")
    for agent in injected:
        proof = (guardduty_proof or {}).get("settingType") == "aws_managed"
        image, digest = agent.get("image"), agent.get("imageDigest")
        require(item.get("launchType") == "FARGATE"
                and re.fullmatch(r"aws-guardduty-agent-[A-Za-z0-9_-]+", agent["name"])
                and (re.fullmatch(re.escape(GUARDDUTY_REPOSITORY) + r"(?::[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}|@sha256:[a-f0-9]{64})", image) if image else proof)
                and (re.fullmatch(r"sha256:[a-f0-9]{64}", digest) if digest else proof)
                and agent.get("lastStatus") in ({"RUNNING", "STOPPED", "PENDING"} if proof else {"RUNNING"}),
                "Injected-agent identity is not established by regional image metadata or AWS-managed configuration.")
    overrides = item.get("overrides", {})
    require(not any(value for key, value in overrides.items() if key != "containerOverrides"),
            "Task-level runtime overrides require review before copying this task.")
    rows = overrides.get("containerOverrides", [])
    row_names = [row.get("name") for row in rows]
    require(len(row_names) == len(set(row_names)) and set(row_names) <= set(names), "Unexpected or duplicate container override identity.")
    for row in rows:
        if row["name"] in declared:
            require(not any(value for key, value in row.items() if key != "name"),
                    "Application container runtime overrides require review before copying this task.")
        else:
            require(set(row) <= {"name", "environment", "memory"}, "Unexpected GuardDuty runtime override fields require review.")
            require("memory" not in row or (type(row["memory"]) is int and row["memory"] > 0), "Invalid GuardDuty memory override.")
            env = row.get("environment", [])
            require(isinstance(env, list) and all(set(v) == {"name", "value"} and isinstance(v["name"], str)
                    and bool(v["name"]) and isinstance(v["value"], str) for v in env)
                    and len({v["name"] for v in env}) == len(env), "Invalid GuardDuty environment override shape.")
    return bool(injected)


def captured_guardduty(baseline, proof=None):
    result = baseline.get("runningTasks", {})
    tasks = result.get("tasks", [])
    require(not result.get("failures") and len(tasks) == baseline["service"]["runningCount"] and bool(tasks),
            "Capture requires the complete running-task metadata.")
    require(all(item["taskDefinitionArn"] == baseline["service"]["taskDefinition"] for item in tasks), "Captured running task identity differs.")
    coverage = [runtime_overrides(item, baseline["task"]["taskDefinition"], guardduty_proof=proof) for item in tasks]
    require(all(value == coverage[0] for value in coverage), "Mixed GuardDuty agent presence requires review.")
    return coverage[0]


def running(session, task, digests, count, *, guardduty_required=False, guardduty_proof=None, guardduty_running_required=False):
    ecs = session.client("ecs")
    arns = []
    for page in ecs.get_paginator("list_tasks").paginate(cluster=front.CLUSTER, serviceName=front.SERVICE, desiredStatus="RUNNING"):
        arns.extend(page["taskArns"])
    require(len(arns) == count and bool(arns), "Unexpected number of running frontend tasks.")
    tasks = []
    for offset in range(0, len(arns), 100):
        result = ecs.describe_tasks(cluster=front.CLUSTER, tasks=arns[offset:offset + 100])
        require(not result.get("failures"), "Could not read all running frontend tasks.")
        tasks.extend(result["tasks"])
    require(len(tasks) == count, "Running task inventory is incomplete.")
    definition = task_state(session, task)
    for item in tasks:
        require(item["taskDefinitionArn"] == task and item.get("lastStatus") == "RUNNING" and item.get("healthStatus") == "HEALTHY",
                "An unexpected or unhealthy frontend task is running.")
        present = runtime_overrides(item, definition, guardduty_proof=guardduty_proof)
        require(not guardduty_required or (guardduty_proof is not None and not managed_agent_expected(guardduty_proof)) or present,
                "The previously present GuardDuty runtime agent is missing; inspect security monitoring.")
        require(not guardduty_running_required or (present and all(state == "RUNNING" for state in agent_states([item]))),
                "GuardDuty agent regressed from its running baseline; inspect security monitoring.")
        container = next((c for c in item["containers"] if c["name"] == front.CONTAINER), {})
        require(container.get("imageDigest") in digests, "Running frontend image digest differs from the retained image.")
    return agent_states(tasks)


def task_state(session, arn):
    task_arn(arn)
    ecs = session.client("ecs")
    described = ecs.describe_task_definition(taskDefinition=arn, include=["TAGS"])
    require(described["taskDefinition"].get("taskDefinitionArn") == arn and described["taskDefinition"].get("status") == "ACTIVE", "Frontend task is not the expected active revision.")
    return original_request(ecs, described)


def prepare(session, capture, domain_path):
    baseline = read(capture / "frontend-capture.json")
    old_url = domain_gate(session, domain_path, authenticated=True)
    ecs = session.client("ecs")
    previous = baseline["service"]["taskDefinition"]
    original = original_request(ecs, baseline["task"])
    candidate = candidate_request(original, old_url)
    service = check_service(session, baseline, previous)
    require(task_state(session, previous) == original, "Original task configuration changed since capture.")
    image = front.container(original)["image"]
    digests = front.runtime_digests(session.client("ecr"), image.split("@", 1)[1])
    proof = guardduty_configuration(session) if has_captured_agent(baseline) else None
    guardduty = captured_guardduty(baseline, proof)
    states = agent_states(baseline["runningTasks"]["tasks"])
    running_required = bool(states) and all(state == "RUNNING" for state in states) and managed_agent_expected(proof)
    running(session, previous, digests, service["desiredCount"], guardduty_required=guardduty,
            guardduty_proof=proof, guardduty_running_required=running_required)
    directory = Path(tempfile.mkdtemp(prefix="navigan-frontend-api-release-"))
    directory.chmod(0o700)
    write(directory / "baseline.json", baseline)
    write(directory / "candidate-task-request.json", candidate)
    print("Private frontend API release record: " + str(directory), flush=True)
    plan = {"format": FORMAT, "account": front.ACCOUNT, "region": front.REGION, "previousTask": previous,
            "domainPlan": str(domain_path), "originalHash": fingerprint(original), "candidateHash": fingerprint(candidate),
            "oldUrl": old_url, "image": image, "runtimeDigests": digests, "guardDutyRequired": guardduty,
            "guardDutyConfiguration": proof, "guardDutyRunningRequired": running_required, "baselineAgentStates": states}
    # Registration does not update the service. Save its identity before any
    # follow-up validation so an interrupted preview remains inspectable.
    registered = ecs.register_task_definition(**candidate)["taskDefinition"]["taskDefinitionArn"]
    plan["nextTask"] = registered
    path = directory / "release-plan.json"
    write(path, plan)
    task_arn(registered)
    require(registered != previous and task_state(session, registered) == candidate, "Registered candidate differs from the exact two-setting preview.")
    check_service(session, baseline, previous)
    print("Candidate registered: " + registered, flush=True)
    print("Scope verified: only NAVIGAN_API_ORIGIN and NAVIGAN_API_BASE_PATH change; running image and all other task/service settings retained.")
    print("Frontend service unchanged. Rollback task: " + previous)
    if guardduty:
        print("GuardDuty managed settings retained; baseline agent states: " + ", ".join(states) + ". Agent overrides are not copied.")
        if not running_required:
            print("The existing GuardDuty agent is not running. Monitoring health remains a separate open item.")
    print("Existing CloudFormation task/image drift is recorded, not reconciled by this release.")
    print("Release plan: " + str(path))


def load_plan(session, path):
    plan, baseline = read(path), read(path.parent / "baseline.json")
    require(plan.get("format") == FORMAT and plan.get("account") == front.ACCOUNT and plan.get("region") == front.REGION,
            "Invalid PROD frontend API plan.")
    task_arn(plan["previousTask"])
    task_arn(plan["nextTask"])
    require(plan["previousTask"] == baseline["service"]["taskDefinition"] and plan["nextTask"] != plan["previousTask"], "Invalid previous/candidate task binding.")
    proof = guardduty_configuration(session) if has_captured_agent(baseline) else None
    require(proof == plan.get("guardDutyConfiguration"), "GuardDuty managed configuration changed since preparation.")
    require(plan.get("guardDutyRequired") is captured_guardduty(baseline, proof), "Plan does not retain captured GuardDuty agent presence.")
    states = agent_states(baseline["runningTasks"]["tasks"])
    require(plan.get("baselineAgentStates") == states and plan.get("guardDutyRunningRequired") is (bool(states) and all(state == "RUNNING" for state in states) and managed_agent_expected(proof)),
            "Plan does not retain the captured GuardDuty agent state.")
    original = original_request(session.client("ecs"), baseline["task"])
    expected = candidate_request(original, plan["oldUrl"])
    require(fingerprint(original) == plan["originalHash"] and fingerprint(expected) == plan["candidateHash"]
            and front.container(original)["image"] == plan["image"], "Private plan/baseline differs from the exact two-setting release.")
    require(task_state(session, plan["previousTask"]) == original and task_state(session, plan["nextTask"]) == expected,
            "Saved task configurations differ from their live definitions.")
    digests = front.runtime_digests(session.client("ecr"), plan["image"].split("@", 1)[1])
    require(digests == plan["runtimeDigests"], "Retained image manifest changed.")
    return plan, baseline


def verify(session, path, *, rolled_back=False):
    plan, baseline = load_plan(session, path)
    target = plan["previousTask"] if rolled_back else plan["nextTask"]
    if not rolled_back:
        require(domain_gate(session, Path(plan["domainPlan"]), authenticated=False) == plan["oldUrl"], "Domain plan API target differs.")
    service = check_service(session, baseline, target)
    states = running(session, target, plan["runtimeDigests"], service["desiredCount"], guardduty_required=plan["guardDutyRequired"],
        guardduty_proof=plan["guardDutyConfiguration"], guardduty_running_required=plan["guardDutyRunningRequired"])
    for endpoint in ("/healthz", "/login"):
        require(domain.probe(front.APP_URL + endpoint) == 200, "Frontend public health/login HTTP check failed.")
    write(path.parent / ("rollback-verification.json" if rolled_back else "verification.json"), {
        "verifiedAt": datetime.now(timezone.utc).isoformat(), "task": target, "image": plan["image"],
        "apiUrl": plan["oldUrl"] if rolled_back else NEW[KEYS[0]] + NEW[KEYS[1]],
        "frontendConfigurationVerified": True, "authenticatedBrowserAcceptance": False,
        "cloudFormationDriftPending": True, "guardDutyPresencePreserved": bool(states) if plan["guardDutyRequired"] else True,
        "guardDutyConfigurationUnchanged": True, "guardDutyAgentStates": states,
        "guardDutyMonitoringAcceptance": False})
    print("PROD frontend API " + ("rollback" if rolled_back else "configuration") + " verified: " + target)
    print("Running image preserved; health/login HTTP checks passed. Fresh authenticated browser checks remain required.")
    if plan["guardDutyRequired"] and (not states or any(state != "RUNNING" for state in states)):
        print("GuardDuty agent states: " + (", ".join(states) or "not present in the current monitoring scope") + ". Existing monitoring health remains an open item.")


def execute(session, path, *, rollback=False):
    plan, baseline = load_plan(session, path)
    journal = path.parent / ("rollback-request.json" if rollback else "execution.json")
    require(not journal.exists(), "Execution already requested; inspect AWS/journal or use --verify. Do not repeat execution.")
    current = plan["nextTask"] if rollback else plan["previousTask"]
    target = plan["previousTask"] if rollback else plan["nextTask"]
    if not rollback:
        require(not (path.parent / "rollback-request.json").exists(), "A rollback has already been requested for this release.")
        require(domain_gate(session, Path(plan["domainPlan"]), authenticated=True) == plan["oldUrl"], "Domain plan API target differs.")
    service = check_service(session, baseline, current, stable=not rollback)
    if not rollback:
        running(session, current, plan["runtimeDigests"], service["desiredCount"], guardduty_required=plan["guardDutyRequired"],
            guardduty_proof=plan["guardDutyConfiguration"], guardduty_running_required=plan["guardDutyRunningRequired"])
    write(journal, {"requestedAt": datetime.now(timezone.utc).isoformat(), "task": target, "previousTask": current})
    session.client("ecs").update_service(cluster=front.CLUSTER, service=front.SERVICE, taskDefinition=target)
    print("Updating only Navigan frontend task reference; saved prior task: " + current, flush=True)
    session.client("ecs").get_waiter("services_stable").wait(cluster=front.CLUSTER, services=[front.SERVICE], WaiterConfig={"Delay": 10, "MaxAttempts": 120})
    verify(session, path, rolled_back=rollback)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="navigan")
    parser.add_argument("--region", required=True)
    parser.add_argument("--expected-account", required=True)
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--domain-plan", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--execute", type=Path)
    mode.add_argument("--verify", type=Path)
    mode.add_argument("--rollback", type=Path)
    args = parser.parse_args()
    require(args.region == front.REGION and args.expected_account == front.ACCOUNT, "Expected the existing PROD account/region.")
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    require(session.client("sts").get_caller_identity()["Account"] == args.expected_account, "Unexpected AWS account.")
    if args.prepare:
        require(args.capture is not None and args.domain_plan is not None, "Preparation requires the frontend capture and verified PROD domain plan.")
        prepare(session, args.capture.resolve(), args.domain_plan.resolve())
    else:
        require(args.capture is None and args.domain_plan is None, "Resume targets come from the saved release plan only.")
        path = (args.execute or args.verify or args.rollback).resolve()
        if args.verify:
            verify(session, path, rolled_back=(path.parent / "rollback-request.json").exists())
        else:
            execute(session, path, rollback=bool(args.rollback))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        message = str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__
        raise SystemExit("Frontend API release stopped: " + message + ". Keep private records local; inspect before retrying.")
