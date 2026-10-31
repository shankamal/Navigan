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
    r"^customers/(CUS-[A-Za-z0-9_-]{1,128})/migrations/(MIG-[a-f0-9]{32})/"
    r"(?:(workspaces)/(AWS-[a-f0-9]{32})/|(recovery)/(REC-[a-f0-9]{32})/).+$")


def proposed_root(assessment):
    def segment(name, identifier, prefix, fallback):
        if not re.fullmatch(prefix+r"-[a-f0-9]{32}",identifier):
            raise ValueError("INVALID_ARTIFACT_IDENTITY")
        name=unicodedata.normalize("NFKD",name or fallback).encode("ascii","ignore").decode().lower()
        slug=re.sub(r"[^a-z0-9]+","-",name).strip("-")[:48].rstrip("-") or fallback
        return slug+"--"+identifier.split("-",1)[1][:12]
    return ("navigan/customers/"+segment(assessment.get("customer_name"),assessment["customer_id"],"CUS","customer")+
            "/migrations/"+segment(assessment.get("name"),assessment["migration_id"],"MIG","migration")+"/")


def error_code(error):
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
            "buckets": sorted({workspace, env.get("MIGRATION_RECOVERY_BUCKET")} - {None, ""})}


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
    return {"assessments":migrations, **json.loads(response["formattedRecords"])[0]}


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
            item = {k:v for k,v in binding.items() if k!="secretArn"}
            plan["environments"][environment] = item
            proxy = next((p for p in proxies if p.get("Endpoint")==binding["proxyHost"]),None)
            if proxy:
                targets = [t for page in rds.get_paginator("describe_db_proxy_targets").paginate(DBProxyName=proxy["DBProxyName"])
                           for t in page.get("Targets",[])]
                item["proxy"]={"name":proxy["DBProxyName"],"status":proxy["Status"],
                               "targets":[{"type":t.get("Type"),"health":t.get("TargetHealth",{})} for t in targets]}
            else:
                item["proxy"]={"errorCode":"PROXY_ENDPOINT_NOT_FOUND"}
            inventory = database_inventory(session,binding,cluster)
            item["inventory"]=inventory
            roots={}
            for assessment in inventory["assessments"]:
                root=proposed_root(assessment)
                identity=(assessment["customer_id"],assessment["migration_id"])
                if root in roots and roots[root]!=identity:
                    raise ValueError("ARTIFACT_PREFIX_COLLISION")
                roots[root]=identity
                assessment["proposedArtifactRoot"]=root
            ids = {(m["customer_id"],m["migration_id"]) for m in inventory["assessments"]}
            for bucket in binding["buckets"]:
                known.setdefault(bucket,set()).update(ids)
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
                "proxy":item.get("proxy"), **{k:v for k,v in item.get("inventory",{}).items() if k!="assessments"},
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
