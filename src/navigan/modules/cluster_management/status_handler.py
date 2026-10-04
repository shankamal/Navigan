"""Trusted EventBridge callback for CodeBuild Terraform execution state."""
import json
import logging
import os
import secrets
from datetime import datetime, timezone
import boto3
from navigan.shared.database import transaction
from navigan.shared.auth import Principal
from navigan.modules.customer_management.repository import json_text
from navigan.modules.cluster_management.connector_installation import ConnectorInstaller
from navigan.modules.cluster_management.repository import Repository

s3 = boto3.client("s3")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def normalize_build_id(value):
    """Convert the EventBridge CodeBuild ARN to the ID returned by StartBuild."""
    marker = ":build/"
    return value.split(marker, 1)[1] if marker in value else value


def handle_node_group_execution(db, request, build_id, build_status, event):
    previous = request["status"]
    if previous not in {"PLAN_RUNNING", "APPLYING"}:
        return {"ignored": True, "reason": "request_not_running"}
    result = {}
    if build_status == "SUCCEEDED":
        try:
            body = s3.get_object(
                Bucket=os.environ["TERRAFORM_ARTIFACT_BUCKET"],
                Key=request["execution_artifact_prefix"] + "/result.json",
            )["Body"].read()
            result = json.loads(body)
        except Exception:
            build_status = "RESULT_UNAVAILABLE"
    success = build_status == "SUCCEEDED" and result.get("success") is True
    target = (
        "PLAN_READY"
        if previous == "PLAN_RUNNING" and success
        else "ACTIVE"
        if previous == "APPLYING" and success
        else "FAILED"
    )
    now = datetime.now(timezone.utc)
    workflow = dict(request["workflow"])
    workflow["lastExecution"] = {
        "mode": "plan" if previous == "PLAN_RUNNING" else "apply",
        "buildId": build_id,
        "status": build_status,
        "completedAt": now.isoformat(),
        "errorCode": result.get("errorCode") if not success else None,
    }
    workflow.pop("currentExecution", None)
    if previous == "PLAN_RUNNING" and success:
        workflow["planSummary"] = result.get("planSummary", {})
        workflow["validation"] = result.get("validation", {})
        workflow["securityScan"] = result.get("securityScan", {})
        workflow["certification"] = result.get("certification", {})
    plan_sha = (
        result.get("planSha256")
        if previous == "PLAN_RUNNING" and success
        else request["plan_sha256"]
    )
    db.execute(
        "UPDATE cluster_management.cluster_node_group_requests "
        "SET status=%s,version=%s,plan_sha256=%s,workflow=%s::jsonb,"
        "updated_by='terraform-runner',updated_at=%s WHERE request_id=%s",
        [
            target,
            request["version"] + 1,
            plan_sha,
            json_text(workflow),
            now,
            request["request_id"],
        ],
    )
    if previous == "APPLYING" and success:
        configuration = dict(request["cluster_configuration"])
        groups = list(configuration.get("nodeGroups", []))
        if not any(
            item.get("name") == request["node_group"]["name"]
            for item in groups
            if isinstance(item, dict)
        ):
            groups.append(request["node_group"])
        configuration["nodeGroups"] = groups
        cluster_version = request["cluster_version"] + 1
        db.execute(
            "UPDATE cluster_management.clusters "
            "SET configuration=%s::jsonb,version=%s,updated_by=%s,updated_at=%s "
            "WHERE cluster_id=%s",
            [
                json_text(configuration),
                cluster_version,
                "terraform-runner",
                now,
                request["cluster_id"],
            ],
        )
        snapshot = {
            "clusterId": request["cluster_id"],
            "configuration": configuration,
            "status": request["cluster_status"],
            "version": cluster_version,
            "updatedBy": "terraform-runner",
            "updatedAt": now.isoformat(),
        }
        db.execute(
            "INSERT INTO cluster_management.cluster_versions"
            "(cluster_id,version,snapshot,created_by,change_reason) "
            "VALUES (%s,%s,%s::jsonb,%s,%s)",
            [
                request["cluster_id"],
                cluster_version,
                json_text(snapshot),
                "terraform-runner",
                "Application node group provisioned",
            ],
        )
    db.execute(
        "INSERT INTO cluster_management.cluster_audit_log"
        "(cluster_id,action,performed_by,correlation_id,new_value) "
        "VALUES (%s,%s,%s,%s,%s::jsonb)",
        [
            request["cluster_id"],
            "ClusterNodeGroupTerraformExecutionCompleted",
            "terraform-runner",
            event.get("id", "codebuild"),
            json_text(
                {
                    "requestId": request["request_id"],
                    "status": target,
                    "buildStatus": build_status,
                }
            ),
        ],
    )
    return {
        "clusterId": request["cluster_id"],
        "requestId": request["request_id"],
        "status": target,
    }


def lambda_handler(event, context):
    detail = event.get("detail") or {}
    raw_build_id = detail.get("build-id")
    build_status = detail.get("build-status")
    if not raw_build_id or not build_status:
        logger.info("Ignoring CodeBuild event without build ID or status.")
        return {"ignored": True}
    build_id = normalize_build_id(raw_build_id)
    with transaction() as db:
        row = db.execute(
            "SELECT * FROM cluster_management.clusters "
            "WHERE provider_execution_id=%s FOR UPDATE",
            [build_id],
        ).fetchone()
        if not row:
            request = db.execute(
                "SELECT r.*,k.configuration AS cluster_configuration,"
                "k.version AS cluster_version,k.status AS cluster_status "
                "FROM cluster_management.cluster_node_group_requests r "
                "JOIN cluster_management.clusters k USING(cluster_id) "
                "WHERE r.provider_execution_id=%s FOR UPDATE OF r,k",
                [build_id],
            ).fetchone()
            if request:
                return handle_node_group_execution(
                    db, request, build_id, build_status, event
                )
            logger.info(
                "Ignoring unregistered CodeBuild execution.",
                extra={"buildId": build_id, "rawBuildId": raw_build_id},
            )
            return {"ignored": True, "reason": "execution_not_registered"}
        previous = row["status"]
        if previous not in {"PLAN_RUNNING", "APPLYING", "STOPPING", "STARTING", "DELETING"}:
            logger.info(
                "Ignoring completion for a request that is no longer running.",
                extra={"buildId": build_id, "clusterId": row["cluster_id"], "status": previous},
            )
            return {"ignored": True, "reason": "request_not_running"}
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
        current_execution = dict(row["workflow"]).get("currentExecution", {})
        migration_apply = (
            previous == "APPLYING"
            and current_execution.get("kind") == "SYSTEM_NODE_GROUP_MIGRATION"
        )
        successful_targets = {
            "PLAN_RUNNING": "PLAN_READY",
            "APPLYING": "ACTIVE" if migration_apply else "BOOTSTRAPPING",
            "STOPPING": "STOPPED",
            "STARTING": "ACTIVE",
            "DELETING": "DELETED",
        }
        target = successful_targets[previous] if success else "FAILED"
        version = row["version"] + 1
        now = datetime.now(timezone.utc)
        plan_sha = result.get("planSha256") if previous == "PLAN_RUNNING" and success else row["plan_sha256"]
        outputs = (
            {}
            if previous == "DELETING" and success
            else result.get("outputs", {})
            if previous in {"APPLYING", "STARTING"} and success
            else row["outputs"]
        )
        workflow = dict(row["workflow"])
        workflow["lastExecution"] = {
            "mode": current_execution.get("mode"),
            "buildId": build_id, "status": build_status, "completedAt": now.isoformat(),
            "errorCode": result.get("errorCode") if not success else None,
        }
        workflow.pop("currentExecution", None)
        if previous == "PLAN_RUNNING" and success:
            workflow["planSummary"] = result.get("planSummary", {})
            workflow["validation"] = result.get("validation", {})
            workflow["securityScan"] = result.get("securityScan", {})
            workflow["certification"] = result.get("certification", {})
        configuration = dict(row["configuration"])
        if migration_apply and success:
            migration = dict(configuration.get("systemNodeGroupMigration") or {})
            migration.update(
                {
                    "status": "COMPLETED",
                    "completedAt": now.isoformat(),
                }
            )
            configuration["systemNodeGroupMigration"] = migration
        db.execute(
            "UPDATE cluster_management.clusters SET status=%s,version=%s,plan_sha256=%s,"
            "outputs=%s::jsonb,workflow=%s::jsonb,configuration=%s::jsonb,"
            "updated_by=%s,updated_at=%s "
            "WHERE cluster_id=%s",
            [target, version, plan_sha, json_text(outputs), json_text(workflow),
             json_text(configuration),
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
            "outputs": outputs, "workflow": workflow, "configuration": configuration,
            "updated_by": "terraform-runner",
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
        if previous == "APPLYING" and success and not migration_apply:
            principal = Principal(
                user_id="platform-bootstrap",
                roles=frozenset({"SERVICE"}),
                customer_ids=frozenset({row["customer_id"]}),
                platform_scope=True,
            )
            repo = Repository(db, principal)
            try:
                installation = repo.request_connector_install(
                    row["cluster_id"],
                    secrets.token_urlsafe(32),
                    "Automatic platform bootstrap after cluster provisioning",
                    event.get("id", "codebuild"),
                    ConnectorInstaller(),
                )
                workflow["platformBootstrap"] = {
                    "status": "RUNNING",
                    "connectorId": installation["connectorId"],
                    "executionId": installation["executionId"],
                    "startedAt": now.isoformat(),
                }
                db.execute(
                    "UPDATE cluster_management.clusters "
                    "SET workflow=%s::jsonb,updated_at=%s WHERE cluster_id=%s",
                    [json_text(workflow), now, row["cluster_id"]],
                )
            except Exception as error:
                target = "BOOTSTRAP_FAILED"
                failure_code = type(error).__name__
                workflow["platformBootstrap"] = {
                    "status": "FAILED",
                    "failureCode": failure_code,
                    "failedAt": now.isoformat(),
                }
                db.execute(
                    "UPDATE cluster_management.cluster_connectors "
                    "SET installation_status='FAILED',installation_failure_code=%s,"
                    "installation_completed_at=%s "
                    "WHERE cluster_id=%s AND status='ENROLLED'",
                    [failure_code, now, row["cluster_id"]],
                )
                db.execute(
                    "UPDATE cluster_management.clusters "
                    "SET status=%s,workflow=%s::jsonb,updated_by=%s,updated_at=%s "
                    "WHERE cluster_id=%s",
                    [
                        target,
                        json_text(workflow),
                        "platform-bootstrap",
                        now,
                        row["cluster_id"],
                    ],
                )
                db.execute(
                    "INSERT INTO cluster_management.cluster_status_history"
                    "(cluster_id,previous_status,new_status,changed_by,reason,correlation_id) "
                    "VALUES (%s,'BOOTSTRAPPING','BOOTSTRAP_FAILED',%s,%s,%s)",
                    [
                        row["cluster_id"],
                        "platform-bootstrap",
                        failure_code,
                        event.get("id", "codebuild"),
                    ],
                )
                logger.exception(
                    "Automatic connector bootstrap failed.",
                    extra={
                        "clusterId": row["cluster_id"],
                        "failureCode": failure_code,
                    },
                )
    return {"clusterId": row["cluster_id"], "status": target}
