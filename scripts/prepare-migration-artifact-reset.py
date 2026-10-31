#!/usr/bin/env python3
"""Prepare a private, read-only inventory for resetting DEV and PROD artifacts.

No deletion, job cancellation, service update or database mutation is performed.
Only migration workspace/recovery object versions are candidates; unrelated keys
and customer, assessment, inventory and scope records are preserved.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import unicodedata

import boto3

ACCOUNT = "905418045935"
REGION = "ap-south-1"
CLUSTER = "aws-infra-platform-db"
ENVIRONMENTS = {"dev": ("navigan-ashok-dev", "navigan_dev"),
                "prod": ("navigan-custmanagement-cfnstk", "navigan")}
LEGACY_OBJECT = re.compile(
    r"^customers/(CUS-[A-Za-z0-9_-]{1,128})/migrations/(MIG-[A-Za-z0-9_-]{1,128})/"
    r"(?:(workspaces)/(AWS-[a-f0-9]{32})/|(recovery)/(REC-[a-f0-9]{32})/).+$")


def proposed_root(assessment):
    def segment(name, identifier, prefix, fallback):
        if not isinstance(identifier,str) or not re.fullmatch(prefix+r"-[A-Za-z0-9_-]{1,124}",identifier):
            raise ValueError("INVALID_ARTIFACT_IDENTITY")
        name=unicodedata.normalize("NFKD",name or fallback).encode("ascii","ignore").decode().lower()
        slug=re.sub(r"[^a-z0-9]+","-",name).strip("-")[:48].rstrip("-") or fallback
        # Seeded/demo IDs predate UUID IDs. Keep their full identity in metadata
        # and use a stable hash suffix instead of silently dropping the tenant.
        suffix=(identifier.split("-",1)[1][:12] if re.fullmatch(prefix+r"-[a-f0-9]{32}",identifier)
                else hashlib.sha256(identifier.encode()).hexdigest()[:12])
        return slug+"--"+suffix
    return ("navigan/customers/"+segment(assessment.get("customer_name"),assessment["customer_id"],"CUS","customer")+
            "/migrations/"+segment(assessment.get("name"),assessment["migration_id"],"MIG","migration")+"/")


def error_code(error):
    if isinstance(error,ValueError) and str(error) in {
        "INVALID_ARTIFACT_IDENTITY","ARTIFACT_PREFIX_COLLISION","DATABASE_IDENTITY_MISMATCH",
        "FUNCTION_IDENTITY_MISMATCH","WORKSPACE_STORAGE_IDENTITY_MISMATCH"}:
        return str(error)
    return (getattr(error, "response", {}) or {}).get("Error", {}).get("Code", type(error).__name__)


def settings(session, parent, database):
    cfn = session.client("cloudformation")
    stack = cfn.describe_stacks(StackName=parent)["Stacks"][0]
    parameters = {p["ParameterKey"]: p["ParameterValue"] for p in stack.get("Parameters", [])}
    nested = cfn.describe_stack_resource(StackName=parent, LogicalResourceId="MigrationManagement")["StackResourceDetail"]["PhysicalResourceId"]
    function = cfn.describe_stack_resource(StackName=nested, LogicalResourceId="MigrationFunction")["StackResourceDetail"]["PhysicalResourceId"]
    config = session.client("lambda").get_function_configuration(FunctionName=function)
    env = config.get("Environment", {}).get("Variables", {})
    if env.get("DB_NAME") != database or parameters.get("DatabaseName") != database:
        raise ValueError("DATABASE_IDENTITY_MISMATCH")
    if not config.get("FunctionArn", "").startswith(f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{parent}-"):
        raise ValueError("FUNCTION_IDENTITY_MISMATCH")
    workspace = env.get("MIGRATION_WORKSPACE_BUCKET")
    if not workspace or env.get("MIGRATION_WORKSPACE_BUCKET_OWNER") != ACCOUNT:
        raise ValueError("WORKSPACE_STORAGE_IDENTITY_MISMATCH")
    return {"parent": parent, "database": database, "function": function,
            "proxyHost": env.get("DB_PROXY_HOST"), "secretArn": env["DB_SECRET_ARN"],
            "network":{key:config.get("VpcConfig",{}).get(key,[]) for key in ("SubnetIds","SecurityGroupIds")},
            "comparisonValues":{key:env.get(key) for key in ("DB_NAME","DB_PROXY_HOST","DB_PORT","DB_SECRET_ARN",
                "MIGRATION_WORKSPACE_BUCKET","MIGRATION_WORKSPACE_KMS_KEY","MIGRATION_WORKSPACE_BUCKET_OWNER")},
            "buckets": sorted({workspace, env.get("MIGRATION_RECOVERY_BUCKET")} - {None, ""})}


def connection_inventory(rds, host, cluster, proxies, instances):
    host=(host or "").lower().rstrip(".")
    for field,kind in (("Endpoint","AURORA_WRITER"),("ReaderEndpoint","AURORA_READER")):
        if cluster.get(field,"").lower().rstrip(".")==host and host:
            return {"kind":kind,"host":host,"status":cluster["Status"],"writable":field=="Endpoint"}
    for instance in instances:
        if instance.get("Endpoint",{}).get("Address","").lower().rstrip(".")==host and host:
            return {"kind":"RDS_INSTANCE","host":host,"status":instance["DBInstanceStatus"],
                    "instance":instance["DBInstanceIdentifier"]}
    proxy=next((p for p in proxies if p.get("Endpoint","").lower().rstrip(".")==host and host),None)
    if proxy:
        targets=[t for page in rds.get_paginator("describe_db_proxy_targets").paginate(DBProxyName=proxy["DBProxyName"])
                 for t in page.get("Targets",[])]
        return {"kind":"RDS_PROXY","host":host,"name":proxy["DBProxyName"],"status":proxy["Status"],
                "targets":[{"type":t.get("Type"),"health":t.get("TargetHealth",{})} for t in targets]}
    return {"kind":"UNRESOLVED","host":host,"status":"NOT_CLASSIFIED",
            "note":"No direct cluster/instance/default-proxy match; this does not establish a connection failure."}


def collector_inventory(session,binding):
    if "comparisonValues" not in binding:
        return {"status":"NOT_INSPECTED"}
    expected=binding["comparisonValues"]
    network=binding["network"]
    def compare(env,actual_network):
        differences=[key for key,value in expected.items()
                     if (str(env.get(key) or "5432") if key=="DB_PORT" else env.get(key))!=
                        (str(value or "5432") if key=="DB_PORT" else value)]
        return {"runtimeDifferences":differences,
                "networkMatchesApi":all(sorted(actual_network.get(key,[]))==sorted(value) for key,value in network.items())}
    cfn=session.client("cloudformation")
    def companion(suffix):
        stack=cfn.describe_stacks(StackName=binding["parent"]+suffix)["Stacks"][0]
        return ({v["OutputKey"]:v["OutputValue"] for v in stack.get("Outputs",[])},
                {v["ParameterKey"]:v["ParameterValue"] for v in stack.get("Parameters",[])})
    results={}
    try:
        outputs,_=companion("-workspace-repositories")
        config=session.client("lambda").get_function_configuration(FunctionName=outputs["WorkerName"])
        results["repository"]=compare(config.get("Environment",{}).get("Variables",{}),config.get("VpcConfig",{}))
    except Exception as error:
        results["repository"]={"errorCode":error_code(error)}
    try:
        outputs,params=companion("-workspace-images")
        ecs=session.client("ecs")
        response=ecs.describe_services(cluster=params["ClusterArn"],services=[outputs["WorkerServiceName"]])
        service=response["services"][0]
        task=ecs.describe_task_definition(taskDefinition=service["taskDefinition"])["taskDefinition"]
        containers=[c for c in task["containerDefinitions"] if c["name"]=="collector"]
        if len(containers)!=1:
            raise ValueError()
        env={v["name"]:v["value"] for v in containers[0].get("environment",[])}
        net=service["networkConfiguration"]["awsvpcConfiguration"]
        results["images"]=compare(env,{"SubnetIds":net["subnets"],"SecurityGroupIds":net["securityGroups"]})
    except Exception as error:
        results["images"]={"errorCode":error_code(error)}
    return results


def database_inventory(session, binding, cluster):
    data = session.client("rds-data")
    base = dict(resourceArn=cluster["DBClusterArn"], secretArn=binding["secretArn"],
                database=binding["database"], formatRecordsAs="JSON")
    # Read only identifiers, names, saved scopes and aggregate collection state.
    # Do not capture delivery configuration, credentials, manifests or file bodies.
    migrations = []
    cursor = ""
    while True:
        response = data.execute_statement(**base, sql=
            "SELECT m.migration_id,m.customer_id,m.name,m.version,md5(m.migration_scope::text) AS scope_fingerprint,c.name AS customer_name "
            "FROM migration_management.migrations m JOIN customer_management.customers c USING(customer_id) "
            "WHERE m.migration_id>:cursor ORDER BY m.migration_id LIMIT 200",
            parameters=[{"name":"cursor", "value":{"stringValue":cursor}}])
        rows = json.loads(response["formattedRecords"])
        migrations.extend(rows)
        if len(rows) < 200:
            break
        cursor = rows[-1]["migration_id"]
    response = data.execute_statement(**base, sql=
        "SELECT (SELECT count(*) FROM migration_management.artifact_workspaces) AS workspaces,"
        "(SELECT count(*) FROM migration_management.workspace_artifacts) AS artifacts,"
        "(SELECT count(*) FROM migration_management.workspace_collection_jobs) AS collection_jobs,"
        "(SELECT count(*) FROM migration_management.workspace_collection_jobs WHERE status IN ('QUEUED','RUNNING')) AS active_collection_jobs,"
        "(SELECT count(*) FROM migration_management.source_clusters s "
        "CROSS JOIN LATERAL jsonb_each(COALESCE(s.delivery_configuration->'artifactRecovery','{}'::jsonb)) r "
        "CROSS JOIN LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(r.value)='array' THEN r.value ELSE '[]'::jsonb END) j "
        "WHERE j->>'status'='RECOVERING') AS active_source_recoveries")
    aggregates=json.loads(response["formattedRecords"])[0]
    response=data.execute_statement(**base,sql=
        "SELECT s.source_cluster_id,r.key AS migration_id,j->>'jobId' AS job_id,"
        "j->>'phase' AS phase,j->>'createdAt' AS created_at,j->>'commandId' AS command_id,"
        "j->>'managedInstanceId' AS managed_instance_id,"
        "s.delivery_configuration->>'accountId' AS source_account,"
        "s.delivery_configuration->>'region' AS source_region "
        "FROM migration_management.source_clusters s "
        "CROSS JOIN LATERAL jsonb_each(COALESCE(s.delivery_configuration->'artifactRecovery','{}'::jsonb)) r "
        "CROSS JOIN LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(r.value)='array' THEN r.value ELSE '[]'::jsonb END) j "
        "WHERE j->>'status'='RECOVERING'")
    recoveries=json.loads(response["formattedRecords"])
    for job in recoveries:
        if job.get("source_account") not in (None,"",ACCOUNT):
            job["commandStatus"]="CROSS_ACCOUNT_CHECK_REQUIRED"
            continue
        try:
            invocation=session.client("ssm",region_name=job.get("source_region") or REGION).get_command_invocation(
                CommandId=job["command_id"],InstanceId=job["managed_instance_id"])
            job["commandStatus"]=invocation["Status"]
        except Exception as error:
            job["commandStatus"]="STATUS_UNAVAILABLE"
            job["errorCode"]=error_code(error)
    return {"assessments":migrations, **aggregates,"sourceRecoveryDetails":recoveries}


def bucket_inventory(session, bucket, known_assessments):
    s3 = session.client("s3")
    versioning = s3.get_bucket_versioning(Bucket=bucket, ExpectedBucketOwner=ACCOUNT).get("Status", "Disabled")
    candidates, preserved = [], []
    for page in s3.get_paginator("list_object_versions").paginate(
            Bucket=bucket, Prefix="customers/", ExpectedBucketOwner=ACCOUNT):
        for field in ("Versions", "DeleteMarkers"):
            for obj in page.get(field, []):
                key = obj["Key"]
                match = LEGACY_OBJECT.fullmatch(key)
                record = {"key":key, "versionId":obj["VersionId"], "bytes":obj.get("Size",0),
                          "deleteMarker":field=="DeleteMarkers"}
                if match and (match[1],match[2]) in known_assessments:
                    candidates.append({**record,"customerId":match[1],"migrationId":match[2]})
                else:
                    preserved.append(record)
    uploads = []
    for page in s3.get_paginator("list_multipart_uploads").paginate(
            Bucket=bucket, Prefix="customers/", ExpectedBucketOwner=ACCOUNT):
        for upload in page.get("Uploads", []):
            match = LEGACY_OBJECT.fullmatch(upload["Key"])
            if match and (match[1],match[2]) in known_assessments:
                uploads.append({"key":upload["Key"],"uploadId":upload["UploadId"]})
    return {"bucket":bucket,"versioning":versioning,"candidateVersions":candidates,
            "candidateUploads":uploads,"preservedVersions":preserved}


def prepare(session):
    if session.client("sts").get_caller_identity()["Account"] != ACCOUNT:
        raise RuntimeError("Unexpected AWS account")
    rds = session.client("rds")
    cluster = rds.describe_db_clusters(DBClusterIdentifier=CLUSTER)["DBClusters"][0]
    if not cluster["DBClusterArn"].startswith(f"arn:aws:rds:{REGION}:{ACCOUNT}:cluster:"):
        raise RuntimeError("Unexpected database cluster")
    proxies = [p for page in rds.get_paginator("describe_db_proxies").paginate() for p in page["DBProxies"]]
    instances=[]
    for member in cluster.get("DBClusterMembers",[]):
        try:
            instances.extend(rds.describe_db_instances(DBInstanceIdentifier=member["DBInstanceIdentifier"])["DBInstances"])
        except Exception:
            pass  # Endpoint classification remains UNRESOLVED, never a false availability claim.
    plan = {"schemaVersion":1,"kind":"MIGRATION_ARTIFACT_RESET_INVENTORY","readOnly":True,
            "account":ACCOUNT,"region":REGION,"createdAt":datetime.now(timezone.utc).isoformat(),
            "scope":"ALL_MIGRATION_ASSESSMENTS_DEV_AND_PROD", "deletionMode":"EXACT_OBJECT_VERSIONS_ONLY",
            "proposedLayout":{"version":2,"inventoryFolder":"inventories/inventory-<version>--<utc>/",
                "workspaceFolder":"workspaces/workspace--<full-workspace-uuid>/",
                "folders":["repository-files","container-images","source-recovery","exports","reports"],
                "prefixesPersistedAtCreation":True,"status":"PROPOSED_NOT_DEPLOYED"},
            "databaseCluster":{"identifier":CLUSTER,"status":cluster["Status"]},
            "environments":{},"buckets":[],"blockers":[],"readyToDelete":False}
    known = {}
    for environment,(parent,database) in ENVIRONMENTS.items():
        try:
            binding = settings(session,parent,database)
            item = {k:v for k,v in binding.items() if k not in {"secretArn","comparisonValues"}}
            plan["environments"][environment] = item
            try:
                item["databaseConnection"]=connection_inventory(rds,binding["proxyHost"],cluster,proxies,instances)
            except Exception as error:
                item["databaseConnection"]={"errorCode":error_code(error)}
            item["collectors"]=collector_inventory(session,binding)
            inventory = database_inventory(session,binding,cluster)
            item["inventory"]=inventory
            ids = {(m["customer_id"],m["migration_id"]) for m in inventory["assessments"]}
            for bucket in binding["buckets"]:
                known.setdefault(bucket,set()).update(ids)
            roots={}
            for assessment in inventory["assessments"]:
                try:
                    root=proposed_root(assessment)
                except ValueError as error:
                    assessment["namingErrorCode"]=error_code(error)
                    plan["blockers"].append(environment+": proposed naming failed for "+assessment["migration_id"])
                    continue
                identity=(assessment["customer_id"],assessment["migration_id"])
                if root in roots and roots[root]!=identity:
                    raise ValueError("ARTIFACT_PREFIX_COLLISION")
                roots[root]=identity
                assessment["proposedArtifactRoot"]=root
            if inventory["active_collection_jobs"] or inventory["active_source_recoveries"]:
                plan["blockers"].append(environment+": existing collection/recovery jobs must be reconciled and writers paused")
        except Exception as error:
            plan["environments"].setdefault(environment,{})["errorCode"]=error_code(error)
            plan["blockers"].append(environment+": database/runtime inventory incomplete")
    for bucket,assessments in sorted(known.items()):
        try:
            plan["buckets"].append(bucket_inventory(session,bucket,assessments))
        except Exception as error:
            plan["buckets"].append({"bucket":bucket,"errorCode":error_code(error)})
            plan["blockers"].append(bucket+": object-version inventory incomplete")
    plan["blockers"].append("Deletion requires a reviewed inventory, quiesced writers, fresh metadata checks and the new collection layout deployed")
    return plan


def summary(plan):
    return {"readOnly":True,"scope":plan["scope"],"databaseCluster":plan["databaseCluster"],
            "environments":{name:{"database":item.get("database"),"errorCode":item.get("errorCode"),
                "databaseConnection":item.get("databaseConnection"), "collectors":item.get("collectors"),
                **{k:v for k,v in item.get("inventory",{}).items() if k not in {"assessments","sourceRecoveryDetails"}},
                "sourceRecoveryDetails":[{k:v for k,v in job.items() if k in {
                    "source_cluster_id","migration_id","job_id","phase","created_at","commandStatus","errorCode"}}
                    for job in item.get("inventory",{}).get("sourceRecoveryDetails",[])],
                "namingErrors":[{"migrationId":m["migration_id"],"code":m["namingErrorCode"]}
                    for m in item.get("inventory",{}).get("assessments",[]) if m.get("namingErrorCode")],
                "assessmentCount":len(item.get("inventory",{}).get("assessments",[]))}
                for name,item in plan["environments"].items()},
            "buckets":[{"bucket":b["bucket"],"errorCode":b.get("errorCode"),
                "candidateVersions":len(b.get("candidateVersions",[])),
                "candidateBytes":sum(v["bytes"] for v in b.get("candidateVersions",[])),
                "candidateUploads":len(b.get("candidateUploads",[])),
                "preservedVersions":len(b.get("preservedVersions",[]))} for b in plan["buckets"]],
            "readyToDelete":False,"blockers":plan["blockers"]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile",default="navigan")
    args=parser.parse_args()
    session=boto3.Session(profile_name=args.profile,region_name=REGION)
    plan=prepare(session)
    directory=Path(tempfile.mkdtemp(prefix="navigan-artifact-reset-",dir="/var/tmp"))
    os.chmod(directory,0o700)
    path=directory/"reset-inventory.json"
    path.write_text(json.dumps(plan,indent=2,default=str))
    path.chmod(0o600)
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    print(json.dumps({**summary(plan),"privateInventory":str(path),"sha256":digest},indent=2,default=str))
    print("Inventory only. No objects, object versions, jobs or database records changed.")


if __name__=="__main__":
    main()
