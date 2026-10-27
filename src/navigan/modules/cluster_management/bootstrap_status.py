"""Reconcile registered installer completion during bootstrap detail polling.

Installer builds run in customer accounts and are not covered by the platform's
Terraform EventBridge rule. Read the exact recorded build through the existing
customer provisioning role, then recheck ownership under locks before writing.
"""

from datetime import datetime, timezone
import json
import logging

from .connector_installation import ConnectorInstaller


logger = logging.getLogger(__name__)
FAILURES = {
    "FAILED": "INSTALLER_BUILD_FAILED",
    "FAULT": "INSTALLER_BUILD_FAULT",
    "STOPPED": "INSTALLER_BUILD_STOPPED",
    "TIMED_OUT": "INSTALLER_BUILD_TIMED_OUT",
}


def registered_connector(repo, cluster, bootstrap, *, lock=False):
    return repo.db.execute(
        "SELECT connector_id,installation_execution_id,status "
        "FROM cluster_management.cluster_connectors "
        "WHERE cluster_id=%s AND connector_id=%s AND installation_execution_id=%s "
        "AND status IN ('ENROLLED','ACTIVE','STALE')"
        + (" FOR UPDATE" if lock else ""),
        [cluster["cluster_id"], bootstrap.get("connectorId"), bootstrap.get("executionId")],
    ).fetchone()


def refresh_installer_status(repo, cluster, correlation, installer=None):
    bootstrap = (cluster.get("workflow") or {}).get("platformBootstrap") or {}
    if (
        cluster.get("status") != "BOOTSTRAPPING"
        or not bootstrap.get("executionId")
        or not bootstrap.get("connectorId")
        or bootstrap.get("installerStatus") == "SUCCEEDED"
    ):
        return cluster
    if not registered_connector(repo, cluster, bootstrap):
        return cluster
    try:
        _, environment = repo.pinned_environment_snapshot(
            cluster["environment_id"], cluster["environment_approved_version"]
        )
        result = (installer or ConnectorInstaller()).inspect_status(
            cluster, environment, bootstrap["executionId"]
        )
    except Exception as error:
        # A lookup failure is not evidence that installation failed. Keep the
        # prior lifecycle state and never log credentials or AWS error payloads.
        logger.warning(
            "Installer state could not be verified.",
            extra={"clusterId": cluster["cluster_id"], "errorType": type(error).__name__},
        )
        return cluster
    build_status = result.get("status")
    if (
        result.get("executionId") != bootstrap["executionId"]
        or build_status not in {*FAILURES, "SUCCEEDED"}
    ):
        return cluster

    # Cluster-first lock order matches connector enrollment/restart. A build
    # observed before another restart must never fail the newer installation.
    current = repo.get(cluster["cluster_id"], lock=True)
    current_bootstrap = (current.get("workflow") or {}).get("platformBootstrap") or {}
    if (
        current.get("status") != "BOOTSTRAPPING"
        or any(current_bootstrap.get(key) != bootstrap.get(key)
               for key in ("connectorId", "executionId"))
        or current_bootstrap.get("installerStatus") == "SUCCEEDED"
        or not registered_connector(repo, current, current_bootstrap, lock=True)
    ):
        return current

    now = datetime.now(timezone.utc)
    failed = build_status in FAILURES
    failure_code = FAILURES.get(build_status)
    workflow = dict(current.get("workflow") or {})
    workflow["platformBootstrap"] = {
        **current_bootstrap,
        "installerStatus": build_status,
        "installerCompletedAt": now.isoformat(),
        **({"status": "FAILED", "failureCode": failure_code,
            "failedAt": now.isoformat()} if failed else {}),
    }
    updated = {**current, "workflow": workflow, "version": current["version"] + 1,
               "status": "BOOTSTRAP_FAILED" if failed else current["status"],
               "updated_by": "platform-bootstrap", "updated_at": now}
    repo.db.execute(
        "UPDATE cluster_management.cluster_connectors "
        "SET installation_status=%s,installation_failure_code=%s,"
        "installation_completed_at=coalesce(installation_completed_at,%s) "
        "WHERE cluster_id=%s AND connector_id=%s AND installation_execution_id=%s",
        ["FAILED" if failed else "SUCCEEDED", failure_code, now,
         current["cluster_id"], bootstrap["connectorId"], bootstrap["executionId"]],
    )
    repo.save(updated)
    snapshot = {
        key: value.isoformat() if hasattr(value, "isoformat") else value
        for key, value in updated.items()
    }
    repo.db.execute(
        "INSERT INTO cluster_management.cluster_versions"
        "(cluster_id,version,snapshot,created_by,change_reason) VALUES (%s,%s,%s::jsonb,%s,%s)",
        [current["cluster_id"], updated["version"], json.dumps(snapshot),
         "platform-bootstrap", "Installer execution " + build_status],
    )
    if failed:
        repo.db.execute(
            "INSERT INTO cluster_management.cluster_status_history"
            "(cluster_id,previous_status,new_status,changed_by,reason,correlation_id) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            [current["cluster_id"], current["status"], updated["status"],
             "platform-bootstrap", failure_code, correlation],
        )
    repo.db.execute(
        "INSERT INTO cluster_management.cluster_audit_log"
        "(cluster_id,action,performed_by,correlation_id,new_value) VALUES (%s,%s,%s,%s,%s::jsonb)",
        [current["cluster_id"], "PlatformInstallerExecutionCompleted", "platform-bootstrap",
         correlation, json.dumps({"executionId": bootstrap["executionId"],
                                  "connectorId": bootstrap["connectorId"],
                                  "installerStatus": build_status,
                                  "status": updated["status"], "failureCode": failure_code})],
    )
    # Installer success never activates a cluster: existing connector telemetry
    # still must prove the required platform components are healthy.
    return updated
