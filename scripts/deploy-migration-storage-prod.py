#!/usr/bin/env python3
"""Provision only PROD migration workspace/recovery storage through scoped change sets.

Default: read-only readiness check. --apply creates and executes change sets after
checking the resource allowlist. Does not update Lambda, APIs, ECS, source hosts,
database contents, existing role trust, or the parent application stack.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import uuid

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, WaiterError

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = "905418045935"
REGION = "ap-south-1"
PARENT = "navigan-custmanagement-cfnstk"
BRANCH = "new_migration_approach_18oct26"
TABLES = ("artifact_workspaces", "workspace_artifacts", "workspace_collection_jobs")
STABLE = {"CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"}
SPECS = {
    "artifact-workspace": {
        "file": "workspace-storage.yaml",
        "resources": {"WorkspaceKey": "AWS::KMS::Key", "WorkspaceBucket": "AWS::S3::Bucket",
                      "WorkspaceBucketPolicy": "AWS::S3::BucketPolicy", "WorkspaceStoragePolicy": "AWS::IAM::Policy"},
    },
    "source-recovery": {
        "file": "recovery-storage.yaml",
        "resources": {"RecoveryBucket": "AWS::S3::Bucket", "RecoveryBucketPolicy": "AWS::S3::BucketPolicy",
                      "RecoveryStoragePolicy": "AWS::IAM::Policy"},
    },
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def check_checkout():
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    require(branch == BRANCH, f"Use the existing {BRANCH} checkout")
    paths = ["scripts/deploy-migration-storage-prod.py",
             "infrastructure/modules/migration-management/workspace-storage.yaml",
             "infrastructure/modules/migration-management/recovery-storage.yaml"]
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--", *paths], cwd=ROOT, text=True)
    require(not dirty.strip(), "Commit or review local storage-release edits before deploying; no files were changed")


def preflight(session):
    require(session.client("sts").get_caller_identity()["Account"] == ACCOUNT, "Unexpected AWS account")
    cfn = session.client("cloudformation")
    parent = cfn.describe_stacks(StackName=PARENT)["Stacks"][0]
    require(parent["StackStatus"] in STABLE, "Wait for the production parent stack to become stable")
    params = {p["ParameterKey"]: p["ParameterValue"] for p in parent.get("Parameters", [])}
    require(params.get("DatabaseName") == "navigan", "Expected PROD database navigan")
    nested = cfn.describe_stack_resource(StackName=PARENT, LogicalResourceId="MigrationManagement")["StackResourceDetail"]["PhysicalResourceId"]
    require(nested.startswith(f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/{PARENT}-MigrationManagement-"),
            "Unexpected production migration stack")
    name = cfn.describe_stack_resource(StackName=nested, LogicalResourceId="MigrationFunction")["StackResourceDetail"]["PhysicalResourceId"]
    config = session.client("lambda").get_function_configuration(FunctionName=name)
    require(config.get("FunctionArn", "").startswith(f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{PARENT}-"),
            "Unexpected production Lambda")
    require(config.get("State") == "Active" and config.get("LastUpdateStatus") == "Successful", "Wait for the production migration API to become stable")
    require(config.get("Environment", {}).get("Variables", {}).get("DB_NAME") == "navigan", "Migration API is not using PROD database")
    role = config.get("Role", "")
    require(re.fullmatch(rf"arn:aws:iam::{ACCOUNT}:role/[A-Za-z0-9+=,.@_/-]+", role), "Unexpected production API role")
    cluster = session.client("rds").describe_db_clusters(DBClusterIdentifier="aws-infra-platform-db")["DBClusters"][0]
    require(cluster["DBClusterArn"].startswith(f"arn:aws:rds:{REGION}:{ACCOUNT}:cluster:"), "Unexpected database account/region")
    require(bool(cluster.get("HttpEndpointEnabled")), "The database Data API must be available for verification")
    data = session.client("rds-data")
    # Read-only SQL. Check identity, all three tables, and every required runtime privilege.
    result = data.execute_statement(resourceArn=cluster["DBClusterArn"], secretArn=params["ApiDatabaseSecretArn"],
        database="navigan", sql="SELECT current_database() AS database_name, " + ", ".join(
            f"to_regclass('migration_management.{table}')::text AS {table}" for table in TABLES), formatRecordsAs="JSON")
    rows = json.loads(result["formattedRecords"])
    require(len(rows) == 1 and rows[0].get("database_name") == "navigan", "Database identity verification failed")
    require(all(rows[0].get(table) for table in TABLES), "PROD workspace tables are missing; apply confirmed workspace-only migrations 027/028 first")
    privileges = " AND ".join(f"has_table_privilege('navigan_api', 'migration_management.{table}', '{privilege}')"
                              for table in TABLES for privilege in ("SELECT", "INSERT", "UPDATE"))
    result = data.execute_statement(resourceArn=cluster["DBClusterArn"], secretArn=params["ApiDatabaseSecretArn"],
        database="navigan", sql=f"SELECT ({privileges}) AS runtime_grants", formatRecordsAs="JSON")
    require(json.loads(result["formattedRecords"])[0].get("runtime_grants") is True, "Workspace runtime grants are missing")
    return {"function": name, "role": role.rsplit("/", 1)[-1], "roleArn": role,
            "revision": config["RevisionId"], "nested": nested}


def describe_optional(cfn, stack):
    try:
        return cfn.describe_stacks(StackName=stack)["Stacks"][0]
    except ClientError as error:
        if error.response["Error"]["Code"] == "ValidationError" and "does not exist" in error.response["Error"].get("Message", ""):
            return None
        raise


def validate_changes(changes, allowed):
    for item in changes:
        change = item.get("ResourceChange", {})
        logical = change.get("LogicalResourceId")
        require(logical in allowed and change.get("ResourceType") == allowed[logical],
                f"Unexpected resource in storage change set: {logical}")
        require(change.get("Action") in {"Add", "Modify"}, f"Storage change set would remove/import {logical}")
        require(change.get("Replacement", "False") == "False", f"Storage replacement is not allowed: {logical}")
        require(not change.get("ChangeSetId"), "Nested stack updates are not allowed in storage change sets")


def change_set(cfn, stack, spec, template, role, directory):
    existing = describe_optional(cfn, stack)
    if existing:
        require(existing["StackStatus"] in STABLE | {"REVIEW_IN_PROGRESS"}, f"Storage stack is not stable: {stack}")
        parameters = {p["ParameterKey"]: p["ParameterValue"] for p in existing.get("Parameters", [])}
        require(parameters == {"MigrationFunctionRoleName": role}, "Existing storage stack is attached to a different role; stopping")
        if existing["StackStatus"] != "REVIEW_IN_PROGRESS":
            (directory / f"{stack}-original-template.json").write_text(json.dumps(cfn.get_template(StackName=stack)["TemplateBody"], indent=2))
        else:
            existing = None  # Resume an unexecuted CREATE change set from an earlier preparation.
    request = dict(StackName=stack, ChangeSetName="navigan-prod-storage-" + uuid.uuid4().hex[:16],
                   ChangeSetType="UPDATE" if existing else "CREATE", TemplateBody=template,
                   Parameters=[{"ParameterKey": "MigrationFunctionRoleName", "ParameterValue": role}],
                   Capabilities=["CAPABILITY_NAMED_IAM"])
    if existing and existing.get("RoleARN"):
        request["RoleARN"] = existing["RoleARN"]
    created = cfn.create_change_set(**request)
    identifier = created["Id"]
    print("Prepared change set: " + identifier, flush=True)
    try:
        cfn.get_waiter("change_set_create_complete").wait(ChangeSetName=identifier,
            WaiterConfig={"Delay": 5, "MaxAttempts": 180})
    except WaiterError:
        failed = cfn.describe_change_set(ChangeSetName=identifier)
        reason = failed.get("StatusReason", "")
        if existing and failed.get("Status") == "FAILED" and (
                "didn't contain changes" in reason or "No updates are to be performed" in reason):
            print(stack + ": no changes")
            return None
        raise RuntimeError("Storage change-set preparation failed; inspect the change set in CloudFormation") from None
    changes = []
    token = None
    while True:
        page = cfn.describe_change_set(ChangeSetName=identifier, **({"NextToken": token} if token else {}))
        changes.extend(page.get("Changes", []))
        token = page.get("NextToken")
        if not token:
            break
    validate_changes(changes, spec["resources"])
    require(bool(changes), "Prepared change set has no inspectable resource changes")
    (directory / f"{stack}-changes.json").write_text(json.dumps(changes, indent=2))
    for item in changes:
        change = item["ResourceChange"]
        print(f"  {change['Action']} {change['LogicalResourceId']} ({change['ResourceType']})")
    return {"id": identifier, "stack": stack, "create": existing is None}


def execute(cfn, plan):
    if plan is None:
        return
    cfn.execute_change_set(ChangeSetName=plan["id"])
    print("Waiting for " + plan["stack"], flush=True)
    waiter = "stack_create_complete" if plan["create"] else "stack_update_complete"
    cfn.get_waiter(waiter).wait(StackName=plan["stack"], WaiterConfig={"Delay": 10, "MaxAttempts": 180})


def verify_storage(session, suffix):
    stack = PARENT + "-" + suffix
    deployed = session.client("cloudformation").describe_stacks(StackName=stack)["Stacks"][0]
    require(deployed["StackStatus"] in STABLE, "Storage deployment did not complete")
    outputs = {o["OutputKey"]: o["OutputValue"] for o in deployed.get("Outputs", [])}
    workspace = suffix == "artifact-workspace"
    bucket = outputs["WorkspaceBucketName" if workspace else "RecoveryBucketName"]
    s3 = session.client("s3")
    s3.head_bucket(Bucket=bucket, ExpectedBucketOwner=ACCOUNT)
    block = s3.get_public_access_block(Bucket=bucket, ExpectedBucketOwner=ACCOUNT)["PublicAccessBlockConfiguration"]
    require(all(block.get(k) is True for k in ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")),
            "Storage bucket public-access protection is incomplete")
    require(s3.get_bucket_versioning(Bucket=bucket, ExpectedBucketOwner=ACCOUNT).get("Status") == "Enabled", "Versioning must be enabled")
    encryption = s3.get_bucket_encryption(Bucket=bucket, ExpectedBucketOwner=ACCOUNT)["ServerSideEncryptionConfiguration"]["Rules"]
    default = encryption[0]["ApplyServerSideEncryptionByDefault"]
    require(default["SSEAlgorithm"] == ("aws:kms" if workspace else "AES256"), "Unexpected bucket encryption")
    if workspace:
        require(outputs["WorkspaceBucketOwner"] == ACCOUNT, "Unexpected workspace owner")
        require(outputs["WorkspaceKmsKeyArn"].startswith(f"arn:aws:kms:{REGION}:{ACCOUNT}:key/"), "Unexpected workspace KMS key")
        require(default["KMSMasterKeyID"] == outputs["WorkspaceKmsKeyArn"], "Workspace encryption key does not match its output")
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="navigan")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    check_checkout()
    session = boto3.Session(profile_name=args.profile, region_name=REGION)
    # Timeouts apply to every client, including the read-only database preflight.
    original_client = session.client
    session.client = lambda service, **kw: original_client(service, config=Config(connect_timeout=10, read_timeout=60,
        retries={"max_attempts": 3, "mode": "standard"}), **kw)
    settings = preflight(session)
    print("PROD navigan: all three workspace tables and runtime grants verified")
    print("Storage permissions will attach only to: " + settings["roleArn"])
    templates = {suffix: (ROOT / "infrastructure/modules/migration-management" / spec["file"]).read_text()
                 for suffix, spec in SPECS.items()}
    if not args.apply:
        print("Readiness check passed. No AWS resources modified. Use --apply to provision the two dedicated storage stacks.")
        return 0
    directory = Path(tempfile.mkdtemp(prefix="navigan-prod-migration-storage-"))
    directory.chmod(0o700)
    print("Private deployment record: " + str(directory))
    cfn = session.client("cloudformation")
    plans = [change_set(cfn, PARENT + "-" + suffix, spec, templates[suffix], settings["role"], directory)
             for suffix, spec in SPECS.items()]
    # Both change sets must pass the scope checks before either executes.
    current = session.client("lambda").get_function_configuration(FunctionName=settings["function"])
    require(current["RevisionId"] == settings["revision"] and current["Role"] == settings["roleArn"],
            "Production API changed during preparation; rerun readiness before executing storage changes")
    for plan in plans:
        execute(cfn, plan)
    outputs = {suffix: verify_storage(session, suffix) for suffix in SPECS}
    report = {"database": "navigan", "function": settings["function"], "outputs": outputs,
              "templates": {s: hashlib.sha256(t.encode()).hexdigest() for s, t in templates.items()}}
    (directory / "storage-release.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(outputs, indent=2))
    print("PROD migration storage deployed and verified. API configuration/code and frontend are unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
