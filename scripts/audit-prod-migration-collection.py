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


def collect(session, migration):
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
        return {"schedule": rule["State"], "targetMatchesWorker": any(
            v.get("Arn") == function["FunctionArn"] for v in target),
            "workerState": function.get("State"), "lastUpdate": function.get("LastUpdateStatus"),
            "lastTwoHours": metrics}

    def images():
        outputs, parameters = stack("workspace-images")
        ecs = session.client("ecs")
        response = ecs.describe_services(cluster=parameters["ClusterArn"], services=[outputs["WorkerServiceName"]])
        if response.get("failures") or len(response.get("services", [])) != 1:
            return {"errorCode": "IMAGE_SERVICE_NOT_FOUND"}
        service = response["services"][0]
        return {"desired": service["desiredCount"], "running": service["runningCount"],
                "pending": service["pendingCount"], "deployments": [
                    {key: v.get(key) for key in ("status", "rolloutState", "failedTasks")}
                    for v in service.get("deployments", [])],
                "events": [v["message"][:300] for v in service.get("events", [])[:3]]}

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
                rows.append({"workspaceId": workspace, **counts})
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
    args = parser.parse_args()
    if not re.fullmatch(r"MIG-[a-f0-9]{32}", args.migration):
        parser.error("Use the exact migration ID from its page URL")
    session = boto3.Session(profile_name=args.profile, region_name=REGION)
    print(json.dumps(collect(session, args.migration), indent=2, default=str))


if __name__ == "__main__":
    main()
