"""Trusted EventBridge callback for CodeBuild Terraform execution state."""
import json
import os
from datetime import datetime, timezone
import boto3
from navigan.shared.database import transaction
from navigan.modules.customer_management.repository import json_text

s3 = boto3.client("s3")


def lambda_handler(event, context):
    detail = event.get("detail") or {}
    build_id = detail.get("build-id")
    build_status = detail.get("build-status")
    if not build_id or not build_status:
        return {"ignored": True}
    with transaction() as db:
        row = db.execute(
            "SELECT * FROM cluster_management.clusters "
            "WHERE provider_execution_id=%s FOR UPDATE",
            [build_id],
        ).fetchone()
        if not row:
            return {"ignored": True}
        previous = row["status"]
        if previous not in {"PLAN_RUNNING", "APPLYING"}:
            return {"ignored": True}
        result = {}
        if build_status == "SUCCEEDED":
            try:
                body = s3.get_object(
                    Bucket=os.environ["TERRAFORM_ARTIFACT_BUCKET"],
                    Key=row["execution_artifact_prefix"] + "/result.json",
                )["Body"].read()
                result = json.loads(body)
            except Exception:
                build_status = "RESULT_UNAVAILABLE"
        success = build_status == "SUCCEEDED" and result.get("success") is True
        target = "PLAN_READY" if success and previous == "PLAN_RUNNING" else (
            "ACTIVE" if success and previous == "APPLYING" else "FAILED"
        )
        version = row["version"] + 1
        now = datetime.now(timezone.utc)
        plan_sha = result.get("planSha256") if previous == "PLAN_RUNNING" and success else row["plan_sha256"]
        outputs = result.get("outputs", {}) if previous == "APPLYING" and success else row["outputs"]
        workflow = dict(row["workflow"])
        workflow["lastExecution"] = {
            "buildId": build_id, "status": build_status, "completedAt": now.isoformat(),
            "errorCode": result.get("errorCode") if not success else None,
        }
        if previous == "PLAN_RUNNING" and success:
            workflow["planSummary"] = result.get("planSummary", {})
        db.execute(
            "UPDATE cluster_management.clusters SET status=%s,version=%s,plan_sha256=%s,"
            "outputs=%s::jsonb,workflow=%s::jsonb,updated_by=%s,updated_at=%s "
            "WHERE cluster_id=%s",
            [target, version, plan_sha, json_text(outputs), json_text(workflow),
             "terraform-runner", now, row["cluster_id"]],
        )
        db.execute(
            "INSERT INTO cluster_management.cluster_status_history"
            "(cluster_id,previous_status,new_status,changed_by,reason,correlation_id) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            [row["cluster_id"], previous, target, "terraform-runner",
             None if success else build_status, event.get("id", "codebuild")],
        )
        old_snapshot = {
            key: value.isoformat() if hasattr(value, "isoformat") else value
            for key, value in dict(row).items()
        }
        snapshot = dict(row)
        snapshot.update({
            "status": target, "version": version, "plan_sha256": plan_sha,
            "outputs": outputs, "workflow": workflow, "updated_by": "terraform-runner",
            "updated_at": now,
        })
        snapshot = {
            key: value.isoformat() if hasattr(value, "isoformat") else value
            for key, value in snapshot.items()
        }
        db.execute(
            "INSERT INTO cluster_management.cluster_versions"
            "(cluster_id,version,snapshot,created_by,change_reason) VALUES (%s,%s,%s::jsonb,%s,%s)",
            [row["cluster_id"], version, json_text(snapshot), "terraform-runner", build_status],
        )
        db.execute(
            "INSERT INTO cluster_management.cluster_audit_log"
            "(cluster_id,action,performed_by,correlation_id,old_value,new_value) "
            "VALUES (%s,%s,%s,%s,%s::jsonb,%s::jsonb)",
            [row["cluster_id"], "TerraformExecutionCompleted", "terraform-runner",
             event.get("id", "codebuild"), json_text(old_snapshot), json_text(snapshot)],
        )
    return {"clusterId": row["cluster_id"], "status": target}
