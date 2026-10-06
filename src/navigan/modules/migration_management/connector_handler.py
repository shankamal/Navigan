"""Authentication boundary for migration discovery connectors."""

import base64
import copy
import hashlib
import hmac
import json
import logging
import re
import uuid
from datetime import datetime, timezone

from pydantic import ValidationError

from navigan.shared.database import transaction
from navigan.shared.errors import ApiError

from .assessment_engine import assess
from .models import (
    SourceCatalogueReport,
    SourceInventoryReport,
)
from .repository import Repository


CONNECTOR_ID = re.compile(r"MGC-[0-9a-f]{32}")
CONNECTOR_TOKEN = re.compile(r"[A-Za-z0-9_-]{43,128}")
AUTHENTICATED_STATUSES = {"ENROLLED", "ACTIVE"}


def unauthenticated():
    return ApiError(
        401,
        "MIGRATION_CONNECTOR_UNAUTHENTICATED",
        "Migration connector authentication failed.",
    )


def authenticate(db, connector_id, headers, now=None):
    if not CONNECTOR_ID.fullmatch(connector_id or ""):
        raise unauthenticated()

    normalized_headers = {
        str(key).lower(): str(value)
        for key, value in (headers or {}).items()
    }
    authorization = normalized_headers.get("authorization", "")

    if not authorization.startswith("Bearer "):
        raise unauthenticated()

    token = authorization[7:]
    if not CONNECTOR_TOKEN.fullmatch(token):
        raise unauthenticated()

    connector = db.execute(
        "SELECT connector_id,migration_id,token_sha256,status,expires_at "
        "FROM migration_management.migration_connectors "
        "WHERE connector_id=%s FOR UPDATE",
        [connector_id],
    ).fetchone()

    supplied_hash = hashlib.sha256(token.encode()).hexdigest()
    stored_hash = (
        connector["token_sha256"]
        if connector
        else "0" * 64
    )
    token_matches = hmac.compare_digest(
        stored_hash,
        supplied_hash,
    )

    current_time = now or datetime.now(timezone.utc)
    if (
        not connector
        or connector["status"] not in AUTHENTICATED_STATUSES
        or connector["expires_at"] <= current_time
        or not token_matches
    ):
        raise unauthenticated()

    return connector

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

BASE = "/api/v1/migration-connectors"


class ConnectorPrincipal:
    def __init__(self, user_id):
        self.user_id = user_id


def response(status, body, correlation):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Correlation-ID": correlation,
        },
        "body": json.dumps(
            body,
            default=str,
            separators=(",", ":"),
        ),
    }


def assignment(db, connector, now, correlation):
    migration = db.execute(
        "SELECT migration_id,customer_id,name,description,"
        "source_platform,target_platform,source_configuration,"
        "target_configuration,migration_scope,execution_mode,"
        "status,version,created_by,updated_by,created_at,updated_at "
        "FROM migration_management.migrations "
        "WHERE migration_id=%s FOR UPDATE",
        [connector["migration_id"]],
    ).fetchone()

    if not migration:
        raise unauthenticated()

    flows = {
        "SOURCE_ENROLLMENT_PENDING": {
            "activeStatus": "INVENTORY_DISCOVERING",
            "assignmentType": "SOURCE_CATALOGUE",
            "event": "MIGRATION_INVENTORY_STARTED",
            "reason": "Source catalogue connector authenticated",
        },
        "INVENTORY_DISCOVERING": {
            "activeStatus": "INVENTORY_DISCOVERING",
            "assignmentType": "SOURCE_CATALOGUE",
        },
        "DISCOVERY_PENDING": {
            "activeStatus": "DISCOVERING",
            "assignmentType": "SOURCE_INVENTORY",
            "event": "MIGRATION_DISCOVERY_STARTED",
            "reason": "Detailed inventory connector authenticated",
        },
        "DISCOVERING": {
            "activeStatus": "DISCOVERING",
            "assignmentType": "SOURCE_INVENTORY",
        },
    }
    flow = flows.get(migration["status"])

    if not flow:
        raise ApiError(
            409,
            "MIGRATION_DISCOVERY_NOT_AVAILABLE",
            "Migration discovery is not available.",
        )

    current = migration
    if migration["status"] != flow["activeStatus"]:
        current = copy.deepcopy(migration)
        current["status"] = flow["activeStatus"]
        current["version"] += 1
        current["updated_by"] = connector["connector_id"]
        current["change_reason"] = flow["reason"]
        current["comments"] = None

        Repository(
            db,
            ConnectorPrincipal(connector["connector_id"]),
        ).save(
            current,
            migration,
            flow["event"],
            correlation,
        )

    db.execute(
        "UPDATE migration_management.migration_connectors "
        "SET status='ACTIVE',last_seen_at=%s "
        "WHERE connector_id=%s",
        [now, connector["connector_id"]],
    )

    return {
        "connectorId": connector["connector_id"],
        "migrationId": current["migration_id"],
        "migrationVersion": current["version"],
        "executionMode": current["execution_mode"],
        "assignmentType": flow["assignmentType"],
        "source": current["source_configuration"],
        "target": current["target_configuration"],
        "scope": current["migration_scope"],
        "status": current["status"],
    }

def body_of(event):
    raw = event.get("body") or ""

    if event.get("isBase64Encoded"):
        raw = base64.b64decode(
            raw,
            validate=True,
        ).decode("utf-8")

    if not raw or len(raw.encode("utf-8")) > 8 * 1024 * 1024:
        raise ApiError(
            413,
            "INVALID_ASSESSMENT_PAYLOAD",
            "Assessment payload is invalid.",
        )

    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ApiError(
            400,
            "INVALID_ASSESSMENT_PAYLOAD",
            "Assessment payload is invalid.",
        )

    return value


def submit_catalogue(
    db,
    connector,
    report,
    now,
    correlation,
):
    migration = db.execute(
        "SELECT migration_id,customer_id,name,description,"
        "source_platform,target_platform,source_configuration,"
        "target_configuration,migration_scope,execution_mode,"
        "status,version,created_by,updated_by,created_at,updated_at "
        "FROM migration_management.migrations "
        "WHERE migration_id=%s FOR UPDATE",
        [connector["migration_id"]],
    ).fetchone()

    if not migration:
        raise unauthenticated()

    if migration["status"] != "INVENTORY_DISCOVERING":
        raise ApiError(
            409,
            "MIGRATION_INVENTORY_NOT_ACTIVE",
            "Source catalogue discovery is not active.",
        )

    if migration["version"] != report.migrationVersion:
        raise ApiError(
            409,
            "STALE_MIGRATION_INVENTORY",
            "The migration configuration changed during discovery.",
        )

    catalogue = {
        "schemaVersion": report.version,
        "sourceKubernetesVersion": report.sourceKubernetesVersion,
        "nodeCount": report.nodeCount,
        "architectures": report.architectures,
        "namespaces": [
            item.model_dump(mode="json")
            for item in report.namespaces
        ],
        "sensitiveDataIncluded": False,
    }
    calculated_digest = hashlib.sha256(
        json.dumps(
            catalogue,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()

    if not hmac.compare_digest(
        calculated_digest,
        report.inventoryDigest,
    ):
        raise ApiError(
            400,
            "INVALID_INVENTORY_DIGEST",
            "Source catalogue digest validation failed.",
        )

    next_version = db.execute(
        "SELECT coalesce(max(catalogue_version),0) + 1 "
        "AS catalogue_version "
        "FROM migration_management.migration_source_catalogues "
        "WHERE migration_id=%s",
        [migration["migration_id"]],
    ).fetchone()["catalogue_version"]

    db.execute(
        "INSERT INTO migration_management.migration_source_catalogues("
        "migration_id,catalogue_version,migration_version,"
        "schema_version,observed_at,source_kubernetes_version,"
        "inventory_digest,node_count,architectures,namespaces,"
        "created_by"
        ") VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s)",
        [
            migration["migration_id"],
            next_version,
            report.migrationVersion,
            report.version,
            report.observedAt,
            report.sourceKubernetesVersion,
            report.inventoryDigest,
            report.nodeCount,
            json.dumps(report.architectures, separators=(",", ":")),
            json.dumps(
                [
                    item.model_dump(mode="json")
                    for item in report.namespaces
                ],
                separators=(",", ":"),
            ),
            connector["connector_id"],
        ],
    )

    current = copy.deepcopy(migration)
    current["source_configuration"] = {
        **current["source_configuration"],
        "kubernetesVersion": (
            report.sourceKubernetesVersion.removeprefix("v")
        ),
    }
    current["status"] = "INVENTORY_READY"
    current["version"] += 1
    current["updated_by"] = connector["connector_id"]
    current["change_reason"] = "Sanitized source catalogue received"
    current["comments"] = None

    Repository(
        db,
        ConnectorPrincipal(connector["connector_id"]),
    ).save(
        current,
        migration,
        "MIGRATION_INVENTORY_RECEIVED",
        correlation,
    )

    db.execute(
        "UPDATE migration_management.migration_connectors "
        "SET status='COMPLETED',completed_at=%s,last_seen_at=%s "
        "WHERE connector_id=%s",
        [now, now, connector["connector_id"]],
    )

    return {
        "connectorId": connector["connector_id"],
        "migrationId": migration["migration_id"],
        "catalogueVersion": next_version,
        "migrationVersion": current["version"],
        "namespaceCount": len(report.namespaces),
        "status": "INVENTORY_READY",
    }


def resolve_target_runtime(db, migration, now):
    target = migration["target_configuration"]

    target_type = target.get(
        "targetType",
        "EXISTING_CLUSTER",
    )

    if (
        target.get("platform") != "EKS"
        or target_type != "EXISTING_CLUSTER"
        or not target.get("clusterId")
    ):
        raise ApiError(
            409,
            "TARGET_CLUSTER_REQUIRED",
            "Select an existing EKS target cluster.",
        )

    cluster_id = target["clusterId"]
    cluster = db.execute(
        "SELECT cluster_id,customer_id "
        "FROM cluster_management.clusters "
        "WHERE cluster_id=%s AND customer_id=%s "
        "AND coalesce(workflow->>'ownershipStatus','') "
        "<> 'ARCHIVED'",
        [cluster_id, migration["customer_id"]],
    ).fetchone()

    if not cluster:
        raise ApiError(
            409,
            "TARGET_CLUSTER_NOT_AVAILABLE",
            "The selected EKS target cluster is not available.",
        )

    runtime = db.execute(
        "SELECT status,connector_id,source_revision,resources,"
        "warning_events,metrics,observed_at,expires_at "
        "FROM cluster_management.cluster_runtime_inventories "
        "WHERE cluster_id=%s",
        [cluster_id],
    ).fetchone()

    if not runtime:
        return {
            "clusterId": cluster_id,
            "status": "NOT_REPORTED",
            "resources": [],
            "warningEvents": [],
            "metrics": {},
            "observedAt": None,
            "expiresAt": None,
        }

    status = (
        "STALE"
        if runtime["expires_at"] <= now
        else runtime["status"]
    )

    return {
        "clusterId": cluster_id,
        "status": status,
        "resources": runtime["resources"] or [],
        "warningEvents": runtime["warning_events"] or [],
        "metrics": runtime["metrics"] or {},
        "observedAt": runtime["observed_at"],
        "expiresAt": runtime["expires_at"],
    }


def submit_source_inventory(
    db,
    connector,
    report,
    now,
    correlation,
):
    migration = db.execute(
        "SELECT migration_id,customer_id,name,description,"
        "source_platform,target_platform,source_configuration,"
        "target_configuration,migration_scope,execution_mode,"
        "status,version,created_by,updated_by,created_at,updated_at "
        "FROM migration_management.migrations "
        "WHERE migration_id=%s FOR UPDATE",
        [connector["migration_id"]],
    ).fetchone()

    if not migration:
        raise unauthenticated()

    if migration["status"] != "DISCOVERING":
        raise ApiError(
            409,
            "MIGRATION_DISCOVERY_NOT_ACTIVE",
            "Detailed source inventory discovery is not active.",
        )

    if migration["version"] != report.migrationVersion:
        raise ApiError(
            409,
            "STALE_MIGRATION_INVENTORY",
            "The migration configuration changed during discovery.",
        )

    target_runtime = resolve_target_runtime(
        db,
        migration,
        now,
    )

    next_inventory = db.execute(
        "SELECT coalesce(max(inventory_version),0) + 1 "
        "AS inventory_version "
        "FROM migration_management.migration_source_inventories "
        "WHERE migration_id=%s",
        [migration["migration_id"]],
    ).fetchone()["inventory_version"]

    db.execute(
        "INSERT INTO "
        "migration_management.migration_source_inventories("
        "migration_id,inventory_version,migration_version,"
        "schema_version,observed_at,source_kubernetes_version,"
        "inventory_digest,resource_count,resources,created_by"
        ") VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)",
        [
            migration["migration_id"],
            next_inventory,
            report.migrationVersion,
            report.schemaVersion,
            report.observedAt,
            report.sourceKubernetesVersion,
            report.inventoryDigest,
            len(report.resources),
            json.dumps(
                report.resources,
                sort_keys=True,
                separators=(",", ":"),
            ),
            connector["connector_id"],
        ],
    )

    repository = Repository(
        db,
        ConnectorPrincipal(connector["connector_id"]),
    )

    assessing = copy.deepcopy(migration)
    assessing["status"] = "ASSESSING"
    assessing["version"] += 1
    assessing["updated_by"] = connector["connector_id"]
    assessing["change_reason"] = (
        "Sanitized detailed source inventory received"
    )
    assessing["comments"] = None

    repository.save(
        assessing,
        migration,
        "MIGRATION_SOURCE_INVENTORY_RECEIVED",
        correlation,
    )

    source_inventory = {
        "schemaVersion": report.schemaVersion,
        "sourceKubernetesVersion": (
            report.sourceKubernetesVersion
        ),
        "inventoryDigest": report.inventoryDigest,
        "resources": report.resources,
        "sensitiveDataIncluded": False,
    }

    generated = assess(
        source_inventory,
        target_runtime,
        migration["target_configuration"],
    )

    next_assessment = db.execute(
        "SELECT coalesce(max(assessment_version),0) + 1 "
        "AS assessment_version "
        "FROM migration_management.migration_assessments "
        "WHERE migration_id=%s",
        [migration["migration_id"]],
    ).fetchone()["assessment_version"]

    db.execute(
        "INSERT INTO migration_management.migration_assessments("
        "migration_id,assessment_version,migration_version,"
        "report_schema_version,source_kubernetes_version,"
        "observed_at,inventory_digest,compatibility_score,"
        "contains_blockers,inventory_summary,findings,created_by"
        ") VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,"
        "%s::jsonb,%s)",
        [
            migration["migration_id"],
            next_assessment,
            report.migrationVersion,
            generated["reportSchemaVersion"],
            generated["sourceKubernetesVersion"],
            generated["observedAt"],
            generated["inventoryDigest"],
            generated["compatibilityScore"],
            generated["containsBlockers"],
            json.dumps(
                generated["inventorySummary"],
                sort_keys=True,
                separators=(",", ":"),
            ),
            json.dumps(
                generated["findings"],
                sort_keys=True,
                separators=(",", ":"),
            ),
            "NAVIGAN_ASSESSMENT_ENGINE",
        ],
    )

    completed = copy.deepcopy(assessing)
    completed["status"] = "ASSESSMENT_READY"
    completed["version"] += 1
    completed["updated_by"] = "NAVIGAN_ASSESSMENT_ENGINE"
    completed["change_reason"] = (
        "Trusted migration feasibility report generated"
    )
    completed["comments"] = None

    repository.save(
        completed,
        assessing,
        "MIGRATION_ASSESSMENT_GENERATED",
        correlation,
    )

    db.execute(
        "UPDATE migration_management.migration_connectors "
        "SET status='COMPLETED',completed_at=%s,last_seen_at=%s "
        "WHERE connector_id=%s",
        [now, now, connector["connector_id"]],
    )

    return {
        "connectorId": connector["connector_id"],
        "migrationId": migration["migration_id"],
        "inventoryVersion": next_inventory,
        "assessmentVersion": next_assessment,
        "migrationVersion": completed["version"],
        "resourceCount": len(report.resources),
        "compatibilityScore": generated["compatibilityScore"],
        "containsBlockers": generated["containsBlockers"],
        "status": "ASSESSMENT_READY",
    }

def execute(event, correlation):
    method = (
        event.get("requestContext", {})
        .get("http", {})
        .get("method", "")
    )
    path = event.get("rawPath") or ""

    assignment_match = re.fullmatch(
        BASE + r"/(MGC-[0-9a-f]{32})/assignment",
        path,
    )
    inventory_match = re.fullmatch(
        BASE + r"/(MGC-[0-9a-f]{32})/inventory",
        path,
    )
    source_inventory_match = re.fullmatch(
        BASE + r"/(MGC-[0-9a-f]{32})/source-inventory",
        path,
    )

    if assignment_match and method == "GET":
        route = "assignment"
        connector_id = assignment_match.group(1)
    elif inventory_match and method == "POST":
        route = "inventory"
        connector_id = inventory_match.group(1)
    elif source_inventory_match and method == "POST":
        route = "source_inventory"
        connector_id = source_inventory_match.group(1)
    else:
        raise ApiError(
            404,
            "ROUTE_NOT_FOUND",
            "Endpoint not found.",
        )

    headers = {
        str(key).lower(): str(value)
        for key, value in (event.get("headers") or {}).items()
    }

    if route in {"inventory", "source_inventory"} and not headers.get(
        "content-type",
        "",
    ).lower().startswith("application/json"):
        raise ApiError(
            400,
            "INVALID_CONTENT_TYPE",
            "Use application/json.",
        )

    now = datetime.now(timezone.utc)

    with transaction() as db:
        connector = authenticate(
            db,
            connector_id,
            headers,
            now,
        )

        if route == "assignment":
            return assignment(
                db,
                connector,
                now,
                correlation,
            )

        payload = body_of(event)

        if route == "inventory":
            report = SourceCatalogueReport.model_validate(payload)
            return submit_catalogue(
                db,
                connector,
                report,
                now,
                correlation,
            )

        report = SourceInventoryReport.model_validate(payload)
        return submit_source_inventory(
            db,
            connector,
            report,
            now,
            correlation,
        )


def lambda_handler(event, context):
    headers = {
        str(key).lower(): str(value)
        for key, value in (event.get("headers") or {}).items()
    }
    correlation = headers.get("x-correlation-id", "")

    if not re.fullmatch(
        r"[A-Za-z0-9._:-]{1,100}",
        correlation,
    ):
        correlation = str(uuid.uuid4())

    try:
        return response(
            200,
            execute(event, correlation),
            correlation,
        )
    except ApiError as error:
        return response(
            error.status,
            error.payload(correlation),
            correlation,
        )
    except ValidationError as validation_error:
        error = ApiError(
            400,
            "VALIDATION_ERROR",
            "Check the assessment fields.",
            {
                "fields": [
                    {
                        "field": ".".join(
                            map(str, item["loc"])
                        ),
                        "message": item["msg"],
                    }
                    for item in validation_error.errors(
                        include_url=False,
                        include_input=False,
                    )
                ]
            },
        )
        return response(
            error.status,
            error.payload(correlation),
            correlation,
        )
    except (
        ValueError,
        json.JSONDecodeError,
        UnicodeError,
    ):
        error = ApiError(
            400,
            "VALIDATION_ERROR",
            "Check the assessment fields.",
        )
        return response(
            error.status,
            error.payload(correlation),
            correlation,
        )
    except Exception:
        logger.exception(
            "Unhandled migration connector request",
            extra={"correlation_id": correlation},
        )
        error = ApiError(
            500,
            "INTERNAL_ERROR",
            "An unexpected error occurred.",
        )
        return response(
            error.status,
            error.payload(correlation),
            correlation,
        )
