"""Credential-protected ingress for outbound-only in-cluster connectors."""

import base64
import hashlib
import hmac
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from navigan.shared.database import transaction
from navigan.shared.errors import ApiError
from .github_app import GitHubApp

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
BASE = "/api/v1/connectors"
CONNECTOR = re.compile(r"^KCC-[a-f0-9]{32}$")
NAMESPACE = r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$"


class NamespaceItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    name: str = Field(max_length=253, pattern=NAMESPACE)


class NamespaceInventory(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    revision: int = Field(gt=0)
    namespaces: list[NamespaceItem] = Field(max_length=1000)


class PlatformComponentItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    code: str = Field(max_length=80, pattern=r"^[a-z0-9-]+$")
    status: str = Field(pattern=r"^(READY|PROGRESSING|DEGRADED|MISSING)$")
    version: str | None = Field(default=None, max_length=100)
    syncStatus: str | None = Field(default=None, max_length=40)
    healthStatus: str | None = Field(default=None, max_length=40)


class RuntimeResourceItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    kind: str = Field(pattern=r"^(Node|Deployment|StatefulSet|DaemonSet|Pod|Service)$")
    namespace: str | None = Field(default=None, max_length=253)
    name: str = Field(min_length=1, max_length=253)
    status: str = Field(min_length=1, max_length=40)
    ready: int = Field(ge=0, le=100000)
    desired: int = Field(ge=0, le=100000)
    restarts: int = Field(ge=0, le=1000000)


class WarningEventItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    namespace: str | None = Field(default=None, max_length=253)
    reason: str = Field(min_length=1, max_length=100)
    resourceKind: str | None = Field(default=None, max_length=100)
    resourceName: str | None = Field(default=None, max_length=253)
    message: str = Field(max_length=500)
    count: int = Field(ge=1, le=1000000)
    lastObservedAt: str | None = Field(default=None, max_length=50)


class RuntimeInventory(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    resources: list[RuntimeResourceItem] = Field(max_length=1000)
    warningEvents: list[WarningEventItem] = Field(max_length=100)
    metrics: dict[str, int] = Field(default_factory=dict)


class PlatformComponentInventory(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    revision: int = Field(gt=0)
    components: list[PlatformComponentItem] = Field(min_length=1, max_length=100)
    runtime: RuntimeInventory | None = None


class ReconciliationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    assignmentId: str = Field(pattern=r"^KAA-[a-f0-9]{32}$")
    status: str = Field(pattern=r"^(APPLIED|FAILED)$")
    errorCode: str | None = Field(default=None, max_length=100, pattern=r"^[A-Z0-9_]+$")


class ReconciliationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    revision: int = Field(gt=0)
    results: list[ReconciliationResult] = Field(max_length=1000)


class ToolTunnelStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    status: str = Field(pattern=r"^(CONNECTED|DISCONNECTED)$")
    gatewayInstanceId: str = Field(
        min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$"
    )


def response(status, body, correlation):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
            "X-Correlation-ID": correlation,
        },
        "body": json.dumps(body, default=str),
    }


def path_of(event):
    path = event.get("rawPath", "")
    stage = event.get("requestContext", {}).get("stage")
    prefix = "/" + stage if stage and stage != "$default" else ""
    return path[len(prefix):] if prefix and path.startswith(prefix + BASE) else path


def body_of(event):
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw, validate=True).decode()
    if not raw or len(raw.encode()) > 262144:
        raise ApiError(413, "INVALID_CONNECTOR_PAYLOAD", "Connector payload is invalid.")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ApiError(400, "INVALID_CONNECTOR_PAYLOAD", "Connector payload is invalid.")
    return value


def authenticate(db, connector_id, headers):
    authorization = headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        raise ApiError(401, "CONNECTOR_UNAUTHENTICATED", "Connector authentication failed.")
    token = authorization[7:]
    if not re.fullmatch(r"[A-Za-z0-9_-]{40,100}", token):
        raise ApiError(401, "CONNECTOR_UNAUTHENTICATED", "Connector authentication failed.")
    connector = db.execute(
        "SELECT connector_id,cluster_id,token_sha256,status "
        "FROM cluster_management.cluster_connectors "
        "WHERE connector_id=%s FOR UPDATE",
        [connector_id],
    ).fetchone()
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    if (
        not connector
        or connector["status"] == "REVOKED"
        or not hmac.compare_digest(connector["token_sha256"], token_hash)
    ):
        raise ApiError(401, "CONNECTOR_UNAUTHENTICATED", "Connector authentication failed.")
    return connector


def desired_access(db, connector, now):
    rows = db.execute(
        "SELECT a.assignment_id,a.subject_type,a.subject_id,a.namespace,"
        "p.profile_code,p.scope_type,p.permissions,a.created_at "
        "FROM access_management.kubernetes_access_assignments a "
        "JOIN access_management.kubernetes_access_profiles p ON p.profile_id=a.profile_id "
        "WHERE a.cluster_id=%s AND a.status IN ('PENDING','ACTIVE') "
        "AND a.valid_from<=%s AND (a.valid_until IS NULL OR a.valid_until>%s) "
        "AND p.status='ACTIVE' ORDER BY a.assignment_id",
        [connector["cluster_id"], now, now],
    ).fetchall()
    revision_row = db.execute(
        "SELECT greatest("
        "coalesce(max(extract(epoch from created_at) * 1000)::bigint,1),"
        "coalesce(max(extract(epoch from revoked_at) * 1000)::bigint,1)"
        ") AS revision "
        "FROM access_management.kubernetes_access_assignments WHERE cluster_id=%s",
        [connector["cluster_id"]],
    ).fetchone()
    return {
        "revision": max(1, revision_row["revision"] if revision_row else 1),
        "assignments": [
            {
                "assignmentId": row["assignment_id"],
                "subjectType": row["subject_type"],
                "subjectId": row["subject_id"],
                "profileCode": row["profile_code"],
                "scopeType": row["scope_type"],
                "namespace": row["namespace"],
                "rules": row["permissions"],
            }
            for row in rows
        ],
    }


def github_repository_credentials(db, connector, github_app=None):
    repository = db.execute(
        "SELECT r.repository_url,r.repository_name,c.installation_id "
        "FROM cluster_management.cluster_system_repositories r "
        "JOIN cluster_management.github_app_connections c "
        "ON c.connection_id=r.connection_id "
        "WHERE r.cluster_id=%s AND r.status='ACTIVE' AND c.status='ACTIVE'",
        [connector["cluster_id"]],
    ).fetchone()
    if not repository or not repository.get("installation_id"):
        raise ApiError(
            409,
            "SYSTEM_REPOSITORY_NOT_READY",
            "The cluster system repository connection is not active.",
        )
    credential = (github_app or GitHubApp()).repository_token(
        repository["installation_id"], repository["repository_name"]
    )
    return {
        "repositoryUrl": repository["repository_url"],
        "username": "x-access-token",
        "token": credential["token"],
        "expiresAt": credential["expiresAt"],
    }


def record_reconciliation(db, connector, report, now, correlation):
    applied = [item.assignmentId for item in report.results if item.status == "APPLIED"]
    failed = [item for item in report.results if item.status == "FAILED"]
    if applied:
        db.execute(
            "UPDATE access_management.kubernetes_access_assignments SET status='ACTIVE' "
            "WHERE cluster_id=%s AND assignment_id=ANY(%s) AND status='PENDING'",
            [connector["cluster_id"], applied],
        )
    reconciliation_id = "KAR-" + uuid.uuid4().hex
    db.execute(
        "INSERT INTO cluster_management.cluster_access_reconciliations"
        "(reconciliation_id,cluster_id,idempotency_key,desired_revision,status,"
        "execution_id,initiated_by,started_at,completed_at,failure_code,result) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) "
        "ON CONFLICT(cluster_id,idempotency_key) DO UPDATE SET "
        "status=excluded.status,execution_id=excluded.execution_id,"
        "completed_at=excluded.completed_at,failure_code=excluded.failure_code,"
        "result=excluded.result",
        [
            reconciliation_id,
            connector["cluster_id"],
            f"{connector['connector_id']}:{report.revision}",
            report.revision,
            "FAILED" if failed else "SUCCEEDED",
            connector["connector_id"],
            connector["connector_id"],
            now,
            now,
            "ASSIGNMENT_RECONCILIATION_FAILED" if failed else None,
            json.dumps({"results": [item.model_dump() for item in report.results]}),
        ],
    )
    db.execute(
        "UPDATE cluster_management.cluster_connectors SET status='ACTIVE',last_seen_at=%s "
        "WHERE connector_id=%s",
        [now, connector["connector_id"]],
    )
    db.execute(
        "INSERT INTO cluster_management.cluster_audit_log"
        "(cluster_id,action,performed_by,correlation_id,new_value) "
        "VALUES (%s,'KubernetesAccessReconciled',%s,%s,%s::jsonb)",
        [
            connector["cluster_id"],
            connector["connector_id"],
            correlation,
            json.dumps({
                "revision": report.revision,
                "appliedCount": len(applied),
                "failedCount": len(failed),
            }),
        ],
    )
    if not failed:
        complete_platform_bootstrap(db, connector, now, correlation)
    return {
        "connectorId": connector["connector_id"],
        "status": "ACCEPTED",
        "revision": report.revision,
        "appliedCount": len(applied),
        "failedCount": len(failed),
    }


def complete_platform_bootstrap(db, connector, now, correlation):
    inventory = db.execute(
        "SELECT status FROM cluster_management.cluster_namespace_inventories "
        "WHERE cluster_id=%s",
        [connector["cluster_id"]],
    ).fetchone()
    if not inventory or inventory["status"] != "READY":
        return
    namespace_count = db.execute(
        "SELECT count(*) AS namespace_count "
        "FROM cluster_management.cluster_namespaces WHERE cluster_id=%s",
        [connector["cluster_id"]],
    ).fetchone()["namespace_count"]
    cluster = db.execute(
        "SELECT * FROM cluster_management.clusters "
        "WHERE cluster_id=%s FOR UPDATE",
        [connector["cluster_id"]],
    ).fetchone()
    if not cluster or cluster["status"] != "BOOTSTRAPPING":
        return
    configuration = cluster.get("configuration") or {}
    baseline = configuration.get("platformBaseline") or {}
    if baseline.get("readinessContract") == "PLATFORM_COMPONENTS_V1":
        required = required_platform_components(baseline)
        component_rows = db.execute(
            "SELECT component_code,status "
            "FROM cluster_management.cluster_platform_components "
            "WHERE cluster_id=%s",
            [connector["cluster_id"]],
        ).fetchall()
        component_status = {
            row["component_code"]: row["status"] for row in component_rows
        }
        if any(component_status.get(code) != "READY" for code in required):
            return
    workflow = dict(cluster["workflow"])
    workflow["platformBootstrap"] = {
        **workflow.get("platformBootstrap", {}),
        "status": "READY",
        "connectorId": connector["connector_id"],
        "namespaceCount": namespace_count,
        "completedAt": now.isoformat(),
    }
    next_version = cluster["version"] + 1
    db.execute(
        "UPDATE cluster_management.clusters "
        "SET status='ACTIVE',version=%s,workflow=%s::jsonb,"
        "updated_by=%s,updated_at=%s WHERE cluster_id=%s",
        [
            next_version,
            json.dumps(workflow),
            "platform-bootstrap",
            now,
            connector["cluster_id"],
        ],
    )
    snapshot = {
        key: value.isoformat() if hasattr(value, "isoformat") else value
        for key, value in dict(cluster).items()
    }
    snapshot.update(
        {
            "status": "ACTIVE",
            "version": next_version,
            "workflow": workflow,
            "updated_by": "platform-bootstrap",
            "updated_at": now.isoformat(),
        }
    )
    db.execute(
        "INSERT INTO cluster_management.cluster_versions"
        "(cluster_id,version,snapshot,created_by,change_reason) "
        "VALUES (%s,%s,%s::jsonb,%s,%s)",
        [
            connector["cluster_id"],
            next_version,
            json.dumps(snapshot),
            "platform-bootstrap",
            "Connector inventory and access reconciliation completed platform bootstrap",
        ],
    )
    db.execute(
        "INSERT INTO cluster_management.cluster_status_history"
        "(cluster_id,previous_status,new_status,changed_by,reason,correlation_id) "
        "VALUES (%s,'BOOTSTRAPPING','ACTIVE',%s,%s,%s)",
        [
            connector["cluster_id"],
            "platform-bootstrap",
            "Verified connector inventory and Kubernetes access reconciliation",
            correlation,
        ],
    )
    db.execute(
        "INSERT INTO cluster_management.cluster_audit_log"
        "(cluster_id,action,performed_by,correlation_id,new_value) "
        "VALUES (%s,'ClusterPlatformBootstrapCompleted',%s,%s,%s::jsonb)",
        [
            connector["cluster_id"],
            connector["connector_id"],
            correlation,
            json.dumps(
                {
                    "connectorId": connector["connector_id"],
                    "namespaceCount": namespace_count,
                    "status": "READY",
                }
            ),
        ],
    )


def required_platform_components(baseline):
    """Resolve the blocking component set for current and legacy baselines."""
    configured = baseline.get("requiredComponents")
    if isinstance(configured, list) and configured:
        return {code for code in configured if isinstance(code, str)}
    components = {
        code for code in baseline.get("components", []) if isinstance(code, str)
    }
    if "navigan-connector" in components:
        components.remove("navigan-connector")
        components.add("connector")
    return components


def execute(event, correlation):
    method = event.get("requestContext", {}).get("http", {}).get("method")
    path = path_of(event)
    inventory_match = re.fullmatch(
        re.escape(BASE) + r"/(KCC-[a-f0-9]{32})/inventory/namespaces",
        path,
    )
    desired_match = re.fullmatch(
        re.escape(BASE) + r"/(KCC-[a-f0-9]{32})/access/desired",
        path,
    )
    status_match = re.fullmatch(
        re.escape(BASE) + r"/(KCC-[a-f0-9]{32})/access/status",
        path,
    )
    components_match = re.fullmatch(
        re.escape(BASE) + r"/(KCC-[a-f0-9]{32})/inventory/platform-components",
        path,
    )
    credentials_match = re.fullmatch(
        re.escape(BASE) + r"/(KCC-[a-f0-9]{32})/github/credentials",
        path,
    )
    tools_authorize_match = re.fullmatch(
        re.escape(BASE) + r"/(KCC-[a-f0-9]{32})/tools/authorize",
        path,
    )
    tools_status_match = re.fullmatch(
        re.escape(BASE) + r"/(KCC-[a-f0-9]{32})/tools/status",
        path,
    )
    match = (
        inventory_match
        or desired_match
        or status_match
        or components_match
        or credentials_match
        or tools_authorize_match
        or tools_status_match
    )
    if not match or (
        inventory_match and method != "POST"
        or desired_match and method != "GET"
        or status_match and method != "POST"
        or components_match and method != "POST"
        or credentials_match and method != "GET"
        or tools_authorize_match and method != "GET"
        or tools_status_match and method != "POST"
    ):
        raise ApiError(404, "ROUTE_NOT_FOUND", "Endpoint not found.")
    connector_id = match.group(1)
    headers = {key.lower(): value for key, value in (event.get("headers") or {}).items()}
    if method == "POST" and not headers.get("content-type", "").lower().startswith("application/json"):
        raise ApiError(400, "INVALID_CONTENT_TYPE", "Use application/json.")
    inventory = NamespaceInventory.model_validate(body_of(event)) if inventory_match else None
    components = (
        PlatformComponentInventory.model_validate(body_of(event))
        if components_match
        else None
    )
    report = ReconciliationReport.model_validate(body_of(event)) if status_match else None
    tunnel_status = (
        ToolTunnelStatus.model_validate(body_of(event))
        if tools_status_match
        else None
    )
    now = datetime.now(timezone.utc)
    with transaction() as db:
        connector = authenticate(db, connector_id, headers)
        if tools_authorize_match:
            return {
                "connectorId": connector_id,
                "clusterId": connector["cluster_id"],
                "status": "AUTHORIZED",
            }
        if tools_status_match:
            expires_at = now + timedelta(minutes=2)
            db.execute(
                "INSERT INTO cluster_management.cluster_tool_tunnels"
                "(cluster_id,connector_id,status,gateway_instance_id,connected_at,"
                "last_seen_at,expires_at,updated_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT(cluster_id) DO UPDATE SET "
                "connector_id=excluded.connector_id,status=excluded.status,"
                "gateway_instance_id=excluded.gateway_instance_id,"
                "connected_at=CASE WHEN excluded.status='CONNECTED' "
                "THEN coalesce(cluster_tool_tunnels.connected_at,excluded.connected_at) "
                "ELSE cluster_tool_tunnels.connected_at END,"
                "last_seen_at=excluded.last_seen_at,expires_at=excluded.expires_at,"
                "updated_at=excluded.updated_at",
                [
                    connector["cluster_id"],
                    connector_id,
                    tunnel_status.status,
                    tunnel_status.gatewayInstanceId,
                    now if tunnel_status.status == "CONNECTED" else None,
                    now,
                    expires_at,
                    now,
                ],
            )
            return {
                "connectorId": connector_id,
                "clusterId": connector["cluster_id"],
                "status": tunnel_status.status,
                "expiresAt": expires_at.isoformat(),
            }
        if credentials_match:
            return github_repository_credentials(db, connector)
        if desired_match:
            return desired_access(db, connector, now)
        if status_match:
            return record_reconciliation(db, connector, report, now, correlation)
        if components_match:
            current = db.execute(
                "SELECT source_revision "
                "FROM cluster_management.cluster_platform_component_inventories "
                "WHERE cluster_id=%s FOR UPDATE",
                [connector["cluster_id"]],
            ).fetchone()
            if current and components.revision <= current["source_revision"]:
                raise ApiError(
                    409,
                    "STALE_CONNECTOR_REVISION",
                    "A newer platform component inventory is already stored.",
                )
            codes = [item.code for item in components.components]
            if len(codes) != len(set(codes)):
                raise ApiError(
                    422,
                    "DUPLICATE_PLATFORM_COMPONENT",
                    "Platform component codes must be unique.",
                )
            for item in components.components:
                db.execute(
                    "INSERT INTO cluster_management.cluster_platform_components"
                    "(cluster_id,component_code,status,version,sync_status,"
                    "health_status,observed_at,source_revision) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT(cluster_id,component_code) DO UPDATE SET "
                    "status=excluded.status,version=excluded.version,"
                    "sync_status=excluded.sync_status,"
                    "health_status=excluded.health_status,"
                    "observed_at=excluded.observed_at,"
                    "source_revision=excluded.source_revision",
                    [
                        connector["cluster_id"],
                        item.code,
                        item.status,
                        item.version,
                        item.syncStatus,
                        item.healthStatus,
                        now,
                        components.revision,
                    ],
                )
            overall = (
                "READY"
                if all(item.status == "READY" for item in components.components)
                else "DEGRADED"
            )
            db.execute(
                "INSERT INTO cluster_management.cluster_platform_component_inventories"
                "(cluster_id,connector_id,source_revision,status,observed_at,updated_at) "
                "VALUES (%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT(cluster_id) DO UPDATE SET "
                "connector_id=excluded.connector_id,"
                "source_revision=excluded.source_revision,status=excluded.status,"
                "observed_at=excluded.observed_at,updated_at=excluded.updated_at",
                [
                    connector["cluster_id"],
                    connector_id,
                    components.revision,
                    overall,
                    now,
                    now,
                ],
            )
            db.execute(
                "UPDATE cluster_management.cluster_connectors "
                "SET status='ACTIVE',last_seen_at=%s WHERE connector_id=%s",
                [now, connector_id],
            )
            if components.runtime:
                current_runtime = db.execute(
                    "SELECT source_revision "
                    "FROM cluster_management.cluster_runtime_inventories "
                    "WHERE cluster_id=%s FOR UPDATE",
                    [connector["cluster_id"]],
                ).fetchone()
                if (
                    not current_runtime
                    or components.revision > current_runtime["source_revision"]
                ):
                    runtime = components.runtime
                    degraded = any(
                        item.kind != "Service"
                        and (
                            item.ready < item.desired
                            or item.status in {"Failed", "Unknown"}
                        )
                        for item in runtime.resources
                    )
                    db.execute(
                        "INSERT INTO cluster_management.cluster_runtime_inventories"
                        "(cluster_id,connector_id,source_revision,status,resources,"
                        "warning_events,metrics,observed_at,expires_at,updated_at) "
                        "VALUES (%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,"
                        "%s + interval '10 minutes',%s) "
                        "ON CONFLICT(cluster_id) DO UPDATE SET "
                        "connector_id=excluded.connector_id,"
                        "source_revision=excluded.source_revision,"
                        "status=excluded.status,resources=excluded.resources,"
                        "warning_events=excluded.warning_events,"
                        "metrics=excluded.metrics,observed_at=excluded.observed_at,"
                        "expires_at=excluded.expires_at,updated_at=excluded.updated_at",
                        [
                            connector["cluster_id"],
                            connector_id,
                            components.revision,
                            "DEGRADED" if degraded else "READY",
                            json.dumps(
                                [item.model_dump() for item in runtime.resources]
                            ),
                            json.dumps(
                                [
                                    item.model_dump()
                                    for item in runtime.warningEvents
                                ]
                            ),
                            json.dumps(runtime.metrics),
                            now,
                            now,
                            now,
                        ],
                    )
            complete_platform_bootstrap(db, connector, now, correlation)
            return {
                "connectorId": connector_id,
                "status": "ACCEPTED",
                "revision": components.revision,
                "componentCount": len(components.components),
                "overallStatus": overall,
                "runtimeResourceCount": (
                    len(components.runtime.resources) if components.runtime else 0
                ),
            }
        state = db.execute(
            "SELECT source_revision FROM cluster_management.cluster_namespace_inventories "
            "WHERE cluster_id=%s FOR UPDATE",
            [connector["cluster_id"]],
        ).fetchone()
        if state and inventory.revision <= state["source_revision"]:
            raise ApiError(409, "STALE_CONNECTOR_REVISION", "A newer inventory is already stored.")
        names = sorted({item.name for item in inventory.namespaces})
        existing = db.execute(
            "SELECT namespace FROM cluster_management.cluster_namespaces "
            "WHERE cluster_id=%s ORDER BY namespace",
            [connector["cluster_id"]],
        ).fetchall()
        changed = names != [row["namespace"] for row in existing]
        if changed:
            db.execute(
                "DELETE FROM cluster_management.cluster_namespaces WHERE cluster_id=%s",
                [connector["cluster_id"]],
            )
            for name in names:
                db.execute(
                    "INSERT INTO cluster_management.cluster_namespaces"
                    "(cluster_id,namespace,is_system,labels,source_revision,observed_at) "
                    "VALUES (%s,%s,%s,'{}'::jsonb,%s,%s)",
                    [
                        connector["cluster_id"],
                        name,
                        name == "default" or name == "kube-public"
                        or name == "kube-node-lease" or name.startswith("kube-"),
                        inventory.revision,
                        now,
                    ],
                )
        else:
            db.execute(
                "UPDATE cluster_management.cluster_namespaces "
                "SET source_revision=%s,observed_at=%s WHERE cluster_id=%s",
                [inventory.revision, now, connector["cluster_id"]],
            )
        db.execute(
            "INSERT INTO cluster_management.cluster_namespace_inventories"
            "(cluster_id,status,source,source_revision,connector_id,observed_at,expires_at,updated_at) "
            "VALUES (%s,'READY','IN_CLUSTER_CONNECTOR',%s,%s,%s,%s + interval '10 minutes',%s) "
            "ON CONFLICT(cluster_id) DO UPDATE SET status='READY',"
            "source_revision=excluded.source_revision,connector_id=excluded.connector_id,"
            "observed_at=excluded.observed_at,expires_at=excluded.expires_at,"
            "failure_code=NULL,updated_at=excluded.updated_at",
            [
                connector["cluster_id"], inventory.revision, connector_id,
                now, now, now,
            ],
        )
        db.execute(
            "UPDATE cluster_management.cluster_connectors "
            "SET status='ACTIVE',last_seen_at=%s,installation_status='SUCCEEDED',"
            "installation_completed_at=coalesce(installation_completed_at,%s),"
            "installation_failure_code=NULL WHERE connector_id=%s",
            [now, now, connector_id],
        )
        if changed:
            db.execute(
                "INSERT INTO cluster_management.cluster_audit_log"
                "(cluster_id,action,performed_by,correlation_id,new_value) "
                "VALUES (%s,'ClusterNamespaceInventoryChanged',%s,%s,%s::jsonb)",
                [
                    connector["cluster_id"],
                    connector_id,
                    correlation,
                    json.dumps({
                        "connectorId": connector_id,
                        "revision": inventory.revision,
                        "namespaceCount": len(names),
                    }),
                ],
            )
    return {
        "connectorId": connector_id,
        "status": "ACCEPTED",
        "revision": inventory.revision,
        "namespaceCount": len(names),
        "observedAt": now.isoformat(),
    }


def lambda_handler(event, context):
    correlation = str(uuid.uuid4())
    try:
        return response(202, execute(event, correlation), correlation)
    except ApiError as error:
        return response(error.status, error.payload(correlation), correlation)
    except (ValidationError, ValueError, json.JSONDecodeError, UnicodeError):
        error = ApiError(400, "INVALID_CONNECTOR_PAYLOAD", "Connector payload is invalid.")
        return response(error.status, error.payload(correlation), correlation)
    except Exception as error:
        logger.error(json.dumps({
            "correlationId": correlation,
            "errorType": type(error).__name__,
        }))
        mapped = ApiError(500, "INTERNAL_ERROR", "An unexpected error occurred.")
        return response(mapped.status, mapped.payload(correlation), correlation)
