#!/usr/bin/env python3
"""Audit Navigan cluster Terraform state placement across retained S3 backends.

Read-only. The script queries Cluster Management for Terraform-bound clusters,
checks the configured/current Terraform artifact bucket first, then searches
explicit candidate retained buckets for the exact same state key. It never
copies, deletes, imports, pushes or mutates Terraform state.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import boto3
from botocore.exceptions import ClientError


def require(condition, message):
    if not condition:
        raise ValueError(message)


def state_head(s3, bucket, key):
    try:
        item = s3.head_object(Bucket=bucket, Key=key)
        return {
            "present": True,
            "versionId": item.get("VersionId"),
            "lastModified": (
                item.get("LastModified").isoformat()
                if item.get("LastModified") else None
            ),
            "size": item.get("ContentLength"),
            "etag": item.get("ETag"),
            "kmsKeyArn": item.get("SSEKMSKeyId"),
        }
    except ClientError as error:
        code = str(error.response.get("Error", {}).get("Code", ""))
        status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
            return {"present": False}
        raise


def state_versions(s3, bucket, key):
    response = s3.list_object_versions(Bucket=bucket, Prefix=key)
    result = []
    for item in response.get("Versions", []):
        if item.get("Key") == key:
            result.append({
                "versionId": item.get("VersionId"),
                "isLatest": bool(item.get("IsLatest")),
                "lastModified": (
                    item.get("LastModified").isoformat()
                    if item.get("LastModified") else None
                ),
                "size": item.get("Size"),
            })
    return result


def cluster_rows(rds, resource_arn, secret_arn, database):
    sql = """
        SELECT cluster_id, customer_id, environment_id, cluster_name,
               status, terraform_state_key, terraform_module_version
        FROM cluster_management.clusters
        WHERE terraform_state_key IS NOT NULL
          AND terraform_module_version IS NOT NULL
          AND status NOT IN ('DELETED')
        ORDER BY cluster_id
    """
    response = rds.execute_statement(
        resourceArn=resource_arn,
        secretArn=secret_arn,
        database=database,
        sql=sql,
        formatRecordsAs="JSON",
    )
    return json.loads(response.get("formattedRecords") or "[]")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="navigan")
    parser.add_argument("--region", default="ap-south-1")
    parser.add_argument("--resource-arn", required=True)
    parser.add_argument("--secret-arn", required=True)
    parser.add_argument("--database", default="navigan")
    parser.add_argument("--current-bucket", required=True)
    parser.add_argument(
        "--candidate-bucket",
        action="append",
        default=[],
        help="Retained/older Terraform artifact bucket; repeat as needed.",
    )
    parser.add_argument("--cluster-id", help="Audit one cluster only.")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    s3 = session.client("s3")
    rds = session.client("rds-data")
    account = session.client("sts").get_caller_identity()["Account"]

    rows = cluster_rows(rds, args.resource_arn, args.secret_arn, args.database)
    if args.cluster_id:
        rows = [row for row in rows if row["cluster_id"] == args.cluster_id]
        require(rows, "Requested cluster was not found or has no Terraform binding.")

    candidates = []
    for value in args.candidate_bucket:
        if value != args.current_bucket and value not in candidates:
            candidates.append(value)

    report = {
        "format": "navigan-terraform-state-audit-v1",
        "account": account,
        "region": args.region,
        "currentBucket": args.current_bucket,
        "candidateBuckets": candidates,
        "clusters": [],
        "summary": {
            "total": len(rows),
            "current": 0,
            "recoverable": 0,
            "missing": 0,
            "ambiguous": 0,
        },
    }

    for row in rows:
        key = row["terraform_state_key"]
        current = state_head(s3, args.current_bucket, key)
        findings = []
        if not current["present"]:
            for bucket in candidates:
                found = state_head(s3, bucket, key)
                if found["present"]:
                    findings.append({
                        "bucket": bucket,
                        **found,
                        "versions": state_versions(s3, bucket, key),
                    })

        if current["present"]:
            classification = "CURRENT"
            report["summary"]["current"] += 1
        elif len(findings) == 1:
            classification = "RECOVERABLE"
            report["summary"]["recoverable"] += 1
        elif len(findings) > 1:
            classification = "AMBIGUOUS"
            report["summary"]["ambiguous"] += 1
        else:
            classification = "MISSING"
            report["summary"]["missing"] += 1

        report["clusters"].append({
            "clusterId": row["cluster_id"],
            "customerId": row["customer_id"],
            "environmentId": row["environment_id"],
            "clusterName": row["cluster_name"],
            "status": row["status"],
            "terraformModuleVersion": row["terraform_module_version"],
            "stateKey": key,
            "classification": classification,
            "current": current,
            "retainedCandidates": findings,
        })

    text = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit(
            "Terraform state audit stopped: "
            + (str(error) if isinstance(error, ValueError) else type(error).__name__)
        ) from None
