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
    if isinstance(error, ValueError) and str(error) in {
        "INVALID_WORKSPACE_ARTIFACTS", "INVALID_WORKSPACE_JOBS", "INVALID_WORKSPACE_NAMESPACES"
    }:
        return str(error)
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


def workspace_comparison(session, migration, selected_workspace=None):
    """Read scoped metadata through Data API; never load secrets or artifact bodies."""
    cfn = session.client("cloudformation")
    parent = cfn.describe_stacks(StackName=PARENT)["Stacks"][0]
    parameters = {p["ParameterKey"]: p["ParameterValue"] for p in parent.get("Parameters", [])}
    nested = cfn.describe_stack_resource(StackName=PARENT, LogicalResourceId="MigrationManagement")["StackResourceDetail"]["PhysicalResourceId"]
    function = cfn.describe_stack_resource(StackName=nested, LogicalResourceId="MigrationFunction")["StackResourceDetail"]["PhysicalResourceId"]
    config = session.client("lambda").get_function_configuration(FunctionName=function)
    env = config.get("Environment", {}).get("Variables", {})
    if parameters.get("DatabaseName") != "navigan" or env.get("DB_NAME") != "navigan":
        raise RuntimeError("PROD_DATABASE_IDENTITY_MISMATCH")
    if not config.get("FunctionArn", "").startswith(f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{PARENT}-"):
        raise RuntimeError("PROD_FUNCTION_IDENTITY_MISMATCH")
    cluster = session.client("rds").describe_db_clusters(DBClusterIdentifier="aws-infra-platform-db")["DBClusters"][0]
    if not cluster["DBClusterArn"].startswith(f"arn:aws:rds:{REGION}:{ACCOUNT}:cluster:"):
        raise RuntimeError("PROD_CLUSTER_IDENTITY_MISMATCH")
    response = session.client("rds-data").execute_statement(
        resourceArn=cluster["DBClusterArn"], secretArn=env["DB_SECRET_ARN"], database="navigan",
        formatRecordsAs="JSON", parameters=[{"name": "migration", "value": {"stringValue": migration}}],
        sql="""SELECT w.workspace_id,w.inventory_version,w.source_cluster_id,w.namespaces,w.status,
          w.created_at,w.manifest->>'storageLayoutVersion' AS layout_version,
          w.manifest->'storage'->>'prefix' AS storage_prefix,
          w.inventory_digest=(SELECT i.inventory_digest FROM migration_management.migration_source_inventories i
            WHERE i.migration_id=w.migration_id ORDER BY i.inventory_version DESC LIMIT 1) AS matches_latest_digest,
          (SELECT COALESCE(jsonb_agg(jsonb_build_object('kind',a.kind,'status',a.status,
            'stored',a.object_key IS NOT NULL,'bytes',COALESCE(a.size_bytes,0))), '[]'::jsonb)
            FROM migration_management.workspace_artifacts a WHERE a.workspace_id=w.workspace_id) AS artifacts,
          (SELECT COALESCE(jsonb_agg(jsonb_build_object('kind',a.kind,'status',j.status,'attempts',j.attempts,
            'errorCode',j.error_code,'updatedAt',j.updated_at)), '[]'::jsonb)
            FROM migration_management.workspace_collection_jobs j
            JOIN migration_management.workspace_artifacts a ON a.workspace_id=j.workspace_id AND a.artifact_id=j.artifact_id
            WHERE j.workspace_id=w.workspace_id) AS jobs
          FROM migration_management.artifact_workspaces w
          WHERE w.migration_id=:migration ORDER BY w.inventory_version DESC,w.created_at DESC LIMIT 51""")
    return summarize_workspaces(json.loads(response["formattedRecords"]), selected_workspace)


def json_array(value, field):
    # Data API formattedRecords encodes PostgreSQL jsonb columns as strings.
    # Decode those columns separately from the outer result-set JSON.
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            raise ValueError("INVALID_WORKSPACE_" + field.upper()) from None
    expected = str if field == "namespaces" else dict
    if not isinstance(value, list) or not all(isinstance(item, expected) for item in value):
        raise ValueError("INVALID_WORKSPACE_" + field.upper())
    return value


def summarize_workspaces(rows, selected_workspace=None):
    summaries = []
    for row in rows[:50]:
        row = {**row, **{field: json_array(row.get(field, []), field)
                        for field in ("artifacts", "jobs", "namespaces")}}
        categories = {key: {"total": 0, "saved": 0, "storedObjects": 0, "bytes": 0, "states": {}, "jobs": {}}
                      for key in ("repositoryFiles", "containerImages", "sourceRecovery", "other")}

        def category(kind):
            return ("containerImages" if kind == "IMAGE" else "sourceRecovery"
                    if kind in {"LIVE_DEFINITION", "HELM_RELEASE"} else "repositoryFiles"
                    if kind == "REPOSITORY_DEFINITION" else "other")

        for artifact in row.get("artifacts", []):
            group = categories[category(artifact["kind"])]
            group["total"] += 1
            group["saved"] += artifact["status"] == "COLLECTED"
            group["storedObjects"] += bool(artifact.get("stored"))
            group["bytes"] += artifact.get("bytes", 0)
            state = artifact["status"]
            group["states"][state] = group["states"].get(state, 0) + 1
        failures = []
        for job in row.get("jobs", []):
            group = categories[category(job["kind"])]["jobs"]
            group[job["status"]] = group.get(job["status"], 0) + 1
            code = job.get("errorCode")
            if code and re.fullmatch(r"[A-Z0-9_]{1,120}", code):
                failures.append({key: job.get(key) for key in ("kind", "status", "attempts", "errorCode", "updatedAt")})
        summaries.append({key: row.get(key) for key in ("workspace_id", "inventory_version", "source_cluster_id",
            "namespaces", "status", "created_at", "layout_version", "storage_prefix", "matches_latest_digest")} |
            {"categories": categories, "recentJobFailures": sorted(failures, key=lambda j: str(j.get("updatedAt") or ""), reverse=True)[:5]})
    selected = next((w for w in summaries if w["workspace_id"] == selected_workspace), None) if selected_workspace else next(iter(summaries), None)
    return {"workspaces": summaries, "truncated": len(rows) > 50,
            "selectedWorkspace": selected["workspace_id"] if selected else None,
            "selectedWorkspaceFound": selected is not None,
            "note": "Counts are database artifact mappings and job states, not S3 folder counts. No jobs started or records changed. Same digest alone does not establish same scope/source/version."}


def collect(session, migration, include_logs=False, compare_workspaces=False, selected_workspace=None):
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
    if compare_workspaces:
        section("workspaceComparison", lambda: workspace_comparison(session, migration, selected_workspace))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="navigan")
    parser.add_argument("--migration", required=True)
    parser.add_argument("--logs", action="store_true", help="Include paginated, redacted worker error summaries")
    parser.add_argument("--compare-workspaces", action="store_true", help="Read scoped PROD database counts and job states for old/current snapshots")
    parser.add_argument("--workspace", help="Identify the selected snapshot in the comparison")
    args = parser.parse_args()
    if not re.fullmatch(r"MIG-[a-f0-9]{32}", args.migration):
        parser.error("Use the exact migration ID from its page URL")
    if args.workspace and (not args.compare_workspaces or not re.fullmatch(r"AWS-[a-f0-9]{32}", args.workspace)):
        parser.error("Use --compare-workspaces and the exact AWS- workspace ID")
    session = boto3.Session(profile_name=args.profile, region_name=REGION)
    print(json.dumps(collect(session, args.migration, include_logs=args.logs,
        compare_workspaces=args.compare_workspaces, selected_workspace=args.workspace), indent=2, default=str))


if __name__ == "__main__":
    main()
