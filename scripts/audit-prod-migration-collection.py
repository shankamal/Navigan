#!/usr/bin/env python3
"""Read-only PROD collection evidence. Never starts jobs, reads secrets or changes S3 keys."""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import re

import boto3

ACCOUNT = "905418045935"
REGION = "ap-south-1"
PARENT = "navigan-custmanagement-cfnstk"


def safe_error(error):
    return getattr(error, "response", {}).get("Error", {}).get("Code", type(error).__name__)


def log_failures(session, group):
    """Paginated, bounded evidence; never print exception messages or command output."""
    logs = session.client("logs")
    start = int((datetime.now(timezone.utc) - timedelta(hours=2)).timestamp() * 1000)
    token = None
    counts = Counter()
    examples = []
    for _ in range(20):
        page = logs.filter_log_events(logGroupName=group, startTime=start, limit=50,
            filterPattern='?failed ?FAILED ?ERROR ?Exception ?"Task timed out"',
            **({"nextToken": token} if token else {}))
        for event in page.get("events", []):
            message = event.get("message", "")
            try:
                data, _ = json.JSONDecoder().raw_decode(message[message.index("{"):])
            except (ValueError, TypeError):
                data = {}
            if not isinstance(data, dict):
                data = {}
            if data.get("status") in {"failed", "FAILED"}:
                summary = {k: data[k] for k in ("stage", "status", "errorType", "sqlState", "awsErrorCode", "code")
                           if isinstance(data.get(k), str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", data[k])}
                summary["locations"] = [{k: f[k] for k in ("file", "line", "function") if k in f}
                    for f in data.get("locations", []) if isinstance(f, dict)][-3:]
            else:
                error = re.search(r"\[ERROR\]\s+([A-Za-z][A-Za-z0-9_.]*)", message)
                if not error and "Task timed out" not in message:
                    continue
                summary = {"errorType": error.group(1) if error else "TaskTimedOut"}
            identity = json.dumps(summary, sort_keys=True)
            counts[identity] += 1
            if len(examples) < 5 and not any(v["failure"] == summary for v in examples):
                examples.append({"timestamp":event.get("timestamp"), "failure":summary})
        next_token = page.get("nextToken")
        if not next_token or next_token == token:
            return {"group":group,"failures":examples,"matchedEvents":sum(counts.values()),"truncated":False}
        token = next_token
    return {"group":group,"failures":examples,"matchedEvents":sum(counts.values()),"truncated":True}


def collect(session, migration, include_logs=False):
    if session.client("sts").get_caller_identity()["Account"] != ACCOUNT:
        raise RuntimeError("Expected PROD account " + ACCOUNT)
    cfn = session.client("cloudformation")
    result = {"environment": "prod", "migrationId": migration, "readOnly": True}

    def section(name, action):
        try:
            result[name] = action()
        except Exception as error:
            result[name] = {"errorCode": safe_error(error)}

    def stack(suffix):
        item = cfn.describe_stacks(StackName=PARENT + "-" + suffix)["Stacks"][0]
        outputs = {v["OutputKey"]: v["OutputValue"] for v in item.get("Outputs", [])}
        parameters = {v["ParameterKey"]: v["ParameterValue"] for v in item.get("Parameters", [])}
        return outputs, parameters

    def repository():
        outputs, _ = stack("workspace-repositories")
        name = outputs["WorkerName"]
        function = session.client("lambda").get_function_configuration(FunctionName=name)
        events = session.client("events")
        rule = events.describe_rule(Name=outputs["ScheduleName"])
        target = events.list_targets_by_rule(Rule=outputs["ScheduleName"]).get("Targets", [])
        now = datetime.now(timezone.utc)
        metrics = {}
        for metric in ("Invocations", "Errors", "Throttles"):
            data = session.client("cloudwatch").get_metric_statistics(
                Namespace="AWS/Lambda", MetricName=metric,
                Dimensions=[{"Name": "FunctionName", "Value": name}],
                StartTime=now - timedelta(hours=2), EndTime=now,
                Period=3600, Statistics=["Sum"])
            metrics[metric] = sum(v["Sum"] for v in data.get("Datapoints", []))
        result = {"schedule": rule["State"], "targetMatchesWorker": any(
            v.get("Arn") == function["FunctionArn"] for v in target),
            "workerState": function.get("State"), "lastUpdate": function.get("LastUpdateStatus"),
            "lastTwoHours": metrics}
        if include_logs:
            group = function.get("LoggingConfig", {}).get("LogGroup") or "/aws/lambda/" + name
            try:
                result["recentFailures"] = log_failures(session, group)
            except Exception as error:
                result["recentFailures"] = {"errorCode":safe_error(error)}
        return result

    def images():
        outputs, parameters = stack("workspace-images")
        ecs = session.client("ecs")
        response = ecs.describe_services(cluster=parameters["ClusterArn"], services=[outputs["WorkerServiceName"]])
        if response.get("failures") or len(response.get("services", [])) != 1:
            return {"errorCode": "IMAGE_SERVICE_NOT_FOUND"}
        service = response["services"][0]
        result = {"desired": service["desiredCount"], "running": service["runningCount"],
                "pending": service["pendingCount"], "deployments": [
                    {key: v.get(key) for key in ("status", "rolloutState", "failedTasks")}
                    for v in service.get("deployments", [])],
                "events": [v["message"][:300] for v in service.get("events", [])[:3]]}
        if include_logs:
            try:
                task = ecs.describe_task_definition(taskDefinition=service["taskDefinition"])["taskDefinition"]
                groups = {c.get("logConfiguration", {}).get("options", {}).get("awslogs-group")
                          for c in task["containerDefinitions"]}
                result["recentFailures"] = [log_failures(session, group) for group in sorted(groups - {None})]
            except Exception as error:
                result["recentFailures"] = {"errorCode":safe_error(error)}
        return result

    def source():
        commands = session.client("ssm").list_commands(MaxResults=50)
        matches = [v for v in commands.get("Commands", [])
                   if v.get("Comment") == "Recover source artifact without changing workloads"]
        return {"scope": "Latest 50 commands in this AWS account; not yet bound to this migration",
                "commands": [{key: v.get(key) for key in ("CommandId", "Status", "RequestedDateTime")}
                             for v in matches[:5]], "additionalCommandsExist": bool(commands.get("NextToken"))}

    def storage():
        outputs, _ = stack("artifact-workspace")
        bucket = outputs["WorkspaceBucketName"]
        s3 = session.client("s3")
        customers = s3.list_objects_v2(Bucket=bucket, Prefix="customers/", Delimiter="/",
                                      MaxKeys=1000, ExpectedBucketOwner=ACCOUNT)
        rows = []
        truncated = bool(customers.get("IsTruncated"))
        prefixes = customers.get("CommonPrefixes", [])
        truncated |= len(prefixes) > 100
        for customer in prefixes[:100]:
            prefix = customer["Prefix"] + "migrations/" + migration + "/workspaces/"
            page = s3.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=1000, ExpectedBucketOwner=ACCOUNT)
            truncated |= bool(page.get("IsTruncated"))
            grouped = {}
            for item in page.get("Contents", []):
                parts = item["Key"][len(prefix):].split("/", 1)
                if len(parts) != 2:
                    continue
                group = grouped.setdefault(parts[0], {"folders": Counter(), "objects": 0, "bytes": 0})
                group["objects"] += 1
                group["bytes"] += item["Size"]
                group["folders"][parts[1].split("/", 1)[0]] += 1
            for workspace, counts in grouped.items():
                rows.append({"workspaceId": workspace, "s3Uri": "s3://" + bucket + "/" + prefix + workspace + "/", **counts})
        return {"bucket": bucket, "workspaces": rows, "listingTruncated": truncated,
                "note": "S3 objects only; queue/database states are separate. No objects or object versions changed."}

    for name, action in (("repositoryCollector", repository), ("imageCollector", images),
                         ("recentSourceRecovery", source), ("workspaceStorage", storage)):
        section(name, action)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="navigan")
    parser.add_argument("--migration", required=True)
    parser.add_argument("--logs", action="store_true", help="Include paginated, redacted worker error summaries")
    args = parser.parse_args()
    if not re.fullmatch(r"MIG-[a-f0-9]{32}", args.migration):
        parser.error("Use the exact migration ID from its page URL")
    session = boto3.Session(profile_name=args.profile, region_name=REGION)
    print(json.dumps(collect(session, args.migration, include_logs=args.logs), indent=2, default=str))


if __name__ == "__main__":
    main()
