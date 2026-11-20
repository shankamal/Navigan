#!/usr/bin/env python3
"""Bind one EKS cluster to module 1.1.0 after a certified node-group preview."""
import argparse
from contextlib import suppress
import hashlib
import io
import json
import re
import zipfile

import boto3


ACCOUNT = "905418045935"
REGION = "ap-south-1"
STACK = "navigan-custmanagement-cfnstk"
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def build_inputs(cb, s3, build_id):
    response = cb.batch_get_builds(ids=[build_id])["builds"]
    require(len(response) == 1, "CodeBuild execution not found.")
    build = response[0]
    require(build["buildStatus"] == "SUCCEEDED", "CodeBuild execution did not succeed.")
    env = {item["name"]: item["value"] for item in build["environment"]["environmentVariables"]}
    bucket = env["TERRAFORM_ARTIFACT_BUCKET"]
    prefix = env["NAVIGAN_ARTIFACT_PREFIX"]
    require(env["NAVIGAN_MODE"] == "plan" and env["NAVIGAN_INPUT_KEY"] == prefix + "/input.json",
            "Unexpected plan build configuration.")

    def artifact(filename):
        return s3.get_object(Bucket=bucket, Key=prefix + "/" + filename,
                             ExpectedBucketOwner=ACCOUNT)["Body"].read()

    request = json.loads(artifact("input.json"))
    result = json.loads(artifact("result.json"))
    require(request["mode"] == "plan" and request["artifactPrefix"] == prefix
            and result["mode"] == "plan" and result["success"], "Build artifacts do not match a completed plan.")
    return build, request, result, artifact


def verify_created_resources(logs, build, node_group):
    location = build["logs"]
    created = set()
    for page in logs.get_paginator("filter_log_events").paginate(
        logGroupName=location["groupName"], logStreamNames=[location["streamName"]],
    ):
        for event in page["events"]:
            for line in ANSI.sub("", event["message"]).splitlines():
                match = re.fullmatch(r"\s*# (.+) will be created\s*", line)
                if match:
                    created.add(match[1])
    index = json.dumps(node_group)
    require(created == {f"aws_eks_node_group.this[{index}]", f"aws_launch_template.node[{index}]"},
            "The two create addresses could not be verified in the build log.")
    return sorted(created)


def snapshot(row):
    return {
        key.split("_")[0] + "".join(part.title() for part in key.split("_")[1:]): value
        for key, value in row.items()
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="navigan")
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--cluster-name", required=True)
    parser.add_argument("--node-group", required=True)
    parser.add_argument("--source-build", required=True)
    parser.add_argument("--compatibility-build", required=True)
    parser.add_argument("--commit", action="store_true", help="Persist the verified cluster binding and audit entry.")
    args = parser.parse_args()

    aws = boto3.Session(profile_name=args.profile, region_name=REGION)
    identity = aws.client("sts").get_caller_identity()
    require(identity["Account"] == ACCOUNT, "Unexpected AWS account.")
    cb, s3 = aws.client("codebuild"), aws.client("s3")
    old_build, old, old_result, _ = build_inputs(cb, s3, args.source_build)
    new_build, new, result, artifact = build_inputs(cb, s3, args.compatibility_build)
    expected = dict(old, executionId=new["executionId"], artifactPrefix=new["artifactPrefix"],
                    terraformModuleVersion="1.1.0", approvedPlanArtifactKey=None, approvedPlanSha256=None)
    require(new == expected and old["terraformModuleVersion"] == "1.0.0"
            and new["clusterName"] == args.cluster_name and new["platform"] == "EKS"
            and not new["configuration"].get("systemNodeGroupMigration")
            and old["executionId"] != new["executionId"]
            and old_result["certification"]["status"] == "FAILED",
            "Compatibility input is not the expected replay of the failed plan.")
    require(old_build["projectName"] == new_build["projectName"]
            and old_build["environment"]["image"] == new_build["environment"]["image"],
            "Compatibility build used a different runner.")
    cfn = aws.client("cloudformation")
    stack = cfn.describe_stacks(StackName=STACK)["Stacks"][0]
    params = {item["ParameterKey"]: item["ParameterValue"] for item in stack["Parameters"]}
    project = cb.batch_get_projects(names=[new_build["projectName"]])["projects"][0]
    require(project["environment"]["image"] == params["TerraformRunnerImageUri"]
            == new_build["environment"]["image"], "Production runner changed after the compatibility plan.")
    actions = result["planSummary"]["actions"]
    require(result["certification"]["status"] == "PASSED" and not result["securityScan"]["findings"]
            and actions.get("create") == 2 and not (actions.keys() - {"create", "no-op", "read"}),
            "Compatibility plan must contain two creates and no updates, deletes or replacements.")
    created = verify_created_resources(aws.client("logs"), new_build, args.node_group)
    plan = artifact("terraform.tfplan")
    require(hashlib.sha256(plan).hexdigest() == result["planSha256"], "Saved compatibility plan hash mismatch.")
    with zipfile.ZipFile(io.BytesIO(plan)) as archive:
        prior = json.loads(archive.read("tfstate-prev"))

    db_arn = aws.client("rds").describe_db_clusters(
        DBClusterIdentifier="aws-infra-platform-db",
    )["DBClusters"][0]["DBClusterArn"]
    api = aws.client("rds-data")
    db = {"resourceArn": db_arn, "secretArn": params["ApiDatabaseSecretArn"]}
    transaction = api.begin_transaction(**db, database="navigan")["transactionId"]

    def query(sql, *, rows=False, **values):
        parameters = [
            {"name": name, "value": {"longValue" if isinstance(value, int) else "stringValue": value}}
            for name, value in values.items()
        ]
        response = api.execute_statement(
            **db, database="navigan", transactionId=transaction, sql=sql,
            parameters=parameters, formatRecordsAs="JSON" if rows else "NONE",
        )
        return json.loads(response["formattedRecords"]) if rows else response.get("numberOfRecordsUpdated")

    committed = False
    try:
        query("SET LOCAL lock_timeout = '5s'")
        selected = query("""
            SELECT to_jsonb(k)::text AS cluster, r.node_group::text AS node_group
            FROM cluster_management.clusters k
            JOIN cluster_management.cluster_node_group_requests r USING (cluster_id)
            WHERE k.cluster_id = :cluster AND k.cluster_name = :name
              AND k.status = 'ACTIVE' AND k.terraform_module_version = '1.0.0'
              AND r.request_id = :request AND r.status = 'PLAN_READY'
              AND r.provider_execution_id = :source
              AND r.plan_sha256 = :failed_hash
              AND r.workflow->'certification'->>'status' = 'FAILED'
              AND NOT EXISTS (
                  SELECT 1 FROM cluster_management.cluster_node_group_requests active
                  WHERE active.cluster_id = k.cluster_id
                    AND active.status IN ('PLAN_RUNNING', 'APPLYING')
              )
              AND NOT EXISTS (
                  SELECT 1 FROM cluster_management.upgrade_plans active
                  WHERE active.cluster_id = k.cluster_id AND active.status = 'EXECUTING'
              )
            FOR UPDATE OF k, r
        """, rows=True, cluster=new["clusterId"], name=args.cluster_name, request=args.request_id,
             source=args.source_build, failed_hash=old_result["planSha256"])
        require(len(selected) == 1, "The failed request or cluster binding changed, or an execution is active.")
        cluster = json.loads(selected[0]["cluster"])
        group = json.loads(selected[0]["node_group"])
        config = {**cluster["configuration"], "nodeGroups": [*cluster["configuration"].get("nodeGroups", []), group]}
        state = new["state"]
        pinned = cluster["workflow"].get("terraformBackend") or {}
        require(group["name"] == args.node_group and config == new["configuration"]
                and cluster["customer_id"] == new["customerId"]
                and cluster["environment_id"] == new["environmentId"]
                and cluster["environment_approved_version"] == new["environmentApprovedVersion"]
                and cluster["provisioning_role_arn"] == new["provisioningRoleArn"]
                and cluster["external_id_secret_arn"] == new["externalIdSecretArn"]
                and cluster["terraform_state_key"] == state["key"]
                and all(pinned.get(field, state[field]) == state[field] for field in ("key", "bucket", "region", "kmsKeyArn")),
                "Current desired state or Terraform binding differs from the validated input.")
        live = json.loads(s3.get_object(Bucket=state["bucket"], Key=state["key"],
                                       ExpectedBucketOwner=ACCOUNT)["Body"].read())
        require(prior["lineage"] and live["lineage"] == prior["lineage"] and live["serial"] == prior["serial"],
                "Terraform state changed after the compatibility plan. Regenerate the compatibility plan.")
        if args.commit:
            actor = "aws:" + hashlib.sha256(identity["Arn"].encode()).hexdigest()
            require(query("""
                UPDATE cluster_management.clusters
                SET terraform_module_version = '1.1.0', version = version + 1,
                    updated_by = :actor, updated_at = now()
                WHERE cluster_id = :cluster AND terraform_module_version = '1.0.0' AND version = :version
            """, actor=actor, cluster=new["clusterId"], version=cluster["version"]) == 1,
                    "Expected exactly one cluster binding update.")
            updated = json.loads(query("""
                SELECT to_jsonb(k)::text AS cluster FROM cluster_management.clusters k WHERE cluster_id = :cluster
            """, rows=True, cluster=new["clusterId"])[0]["cluster"])
            query("""
                INSERT INTO cluster_management.cluster_versions
                    (cluster_id, version, snapshot, created_by, change_reason)
                VALUES (:cluster, :version, CAST(:payload AS jsonb), :actor, 'Certified Terraform module binding recovery')
            """, cluster=new["clusterId"], version=updated["version"], payload=json.dumps(snapshot(updated)), actor=actor)
            query("""
                INSERT INTO cluster_management.cluster_audit_log
                    (cluster_id, action, performed_by, correlation_id, old_value, new_value)
                VALUES (:cluster, 'ClusterTerraformModuleBindingUpdated', :actor, :build,
                        CAST(:old_value AS jsonb), CAST(:new_value AS jsonb))
            """, cluster=new["clusterId"], actor=actor, build=args.compatibility_build,
                  old_value=json.dumps({"terraformModuleVersion": "1.0.0", "version": cluster["version"]}),
                  new_value=json.dumps({"terraformModuleVersion": "1.1.0", "version": updated["version"],
                                        "compatibilityBuild": args.compatibility_build, "requestId": args.request_id,
                                        "stateSerial": prior["serial"]}))
            api.commit_transaction(**db, transactionId=transaction)
            committed = True
        print(json.dumps({
            "cluster": args.cluster_name, "creates": created, "stateSerial": prior["serial"],
            "binding": "1.1.0" if committed else "1.0.0", "verifiedCandidate": "1.1.0",
            "bindingCommitted": committed,
        }, indent=2))
    finally:
        if not committed:
            with suppress(Exception):
                api.rollback_transaction(**db, transactionId=transaction)


if __name__ == "__main__":
    main()
