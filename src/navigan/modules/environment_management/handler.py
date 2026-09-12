"""Explicit HTTP API v2 routes; all authorization derives from verified JWT claims."""

from navigan.shared.diagnostics import emit, phase, invocation

emit("environment_module_import", "started")
import base64
import hashlib
import json
import re
import uuid
from datetime import datetime
from pydantic import ValidationError
from navigan.shared.auth import Principal
from navigan.shared.database import transaction
from navigan.shared.errors import ApiError
from .configuration import DISTRIBUTIONS, schema
from .models import (
    CreateEnvironment,
    UpdateEnvironment,
    Action,
    AwsDiscoveryRequest,
    BlueprintReadinessRequest,
    CreateBootstrapRemediation,
    BootstrapRemediationDecision,
)
from .repository import Repository, serialize
from .service import Service, TRANSITIONS
from .discovery import discover_aws
from .readiness import assess_eks_blueprints
from .remediation import BootstrapRemediationService

emit("environment_module_import", "completed")
BASE = "/api/v1/environments"


def resource_path(event):
    path = event.get("rawPath", "")
    stage = event.get("requestContext", {}).get("stage")
    prefix = "/" + stage if stage and stage != "$default" else ""
    if prefix and (path == prefix + BASE or path.startswith(prefix + BASE + "/")):
        path = path[len(prefix) :]
    return path


def response(status, body, correlation):
    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-store",
        "X-Correlation-ID": correlation,
    }
    if isinstance(body, dict) and body.get("version"):
        headers["ETag"] = str(body["version"])
    return {
        "statusCode": status,
        "headers": headers,
        "body": json.dumps(body, default=lambda v: v.isoformat()),
    }


def query_params(params):
    query = dict(params or {})
    allowed = {
        "page",
        "pageSize",
        "sort",
        "customerId",
        "customerName",
        "cloudProvider",
        "kubernetesDistribution",
        "environmentName",
        "environmentType",
        "status",
        "approvedStatus",
        "region",
        "createdBy",
        "createdFrom",
        "createdTo",
        "search",
    }
    if set(query) - allowed or any(not isinstance(v, str) or len(v) > 200 for v in query.values()):
        raise ApiError(400, "INVALID_QUERY", "Unknown or invalid query parameter.")
    try:
        query["page"] = int(query.get("page", "0"))
        query["pageSize"] = int(query.get("pageSize", "20"))
        if not 0 <= query["page"] <= 1000000 or not 1 <= query["pageSize"] <= 100:
            raise ValueError()
        for name in ["createdFrom", "createdTo"]:
            if query.get(name):
                date = datetime.fromisoformat(query[name].replace("Z", "+00:00"))
                if date.tzinfo is None:
                    raise ValueError()
    except ValueError:
        raise ApiError(400, "INVALID_QUERY", "Check pagination and ISO timestamps with timezone.") from None
    query.setdefault("sort", "createdAt,desc")
    if query["sort"] not in {
        f"{f},{d}" for f in ["environmentName", "createdAt", "updatedAt", "status"] for d in ["asc", "desc"]
    }:
        raise ApiError(400, "INVALID_QUERY", "Unsupported sort.")
    return query


def remediation_query_params(params):
    query = dict(params or {})
    allowed = {"page", "pageSize", "status", "customerId", "search"}
    if set(query) - allowed or any(not isinstance(v, str) or len(v) > 200 for v in query.values()):
        raise ApiError(400, "INVALID_QUERY", "Unknown or invalid query parameter.")
    try:
        query["page"] = int(query.get("page", "0"))
        query["pageSize"] = int(query.get("pageSize", "20"))
        if not 0 <= query["page"] <= 1000000 or not 1 <= query["pageSize"] <= 100:
            raise ValueError()
    except ValueError:
        raise ApiError(400, "INVALID_QUERY", "Check pagination values.") from None
    statuses = {
        "REQUESTED",
        "APPROVED",
        "REJECTED",
        "PLAN_RUNNING",
        "PLAN_READY",
        "APPLY_RUNNING",
        "COMPLETED",
        "FAILED",
    }
    if query.get("status") and query["status"] not in statuses:
        raise ApiError(400, "INVALID_QUERY", "Unsupported remediation status.")
    return query


def body_json(event):
    try:
        raw = event.get("body") or "{}"
        if len(raw) > 90000:
            raise ApiError(413, "PAYLOAD_TOO_LARGE", "Maximum request size is 64 KiB.")
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw, validate=True).decode()
        if len(raw.encode()) > 65536:
            raise ApiError(413, "PAYLOAD_TOO_LARGE", "Maximum request size is 64 KiB.")
        body = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(body, dict):
            raise ValueError()
        return body
    except (ValueError, UnicodeError):
        raise ApiError(400, "INVALID_JSON", "A valid JSON object is required.") from None


def execute(event, principal, correlation, tx=transaction):
    method = event.get("requestContext", {}).get("http", {}).get("method")
    path = resource_path(event)
    suffix = path[len(BASE) :] if path == BASE or path.startswith(BASE + "/") else None
    if suffix is None:
        raise ApiError(404, "ROUTE_NOT_FOUND", "Endpoint not found.")
    parts = suffix.strip("/").split("/") if suffix else []
    if method == "GET" and len(parts) == 3 and parts[0] == "configuration-schemas":
        return response(200, schema(parts[1], parts[2]), correlation)
    if method == "GET" and parts == ["metadata"]:
        with tx() as db:
            types = db.execute(
                "SELECT code FROM environment_management.environment_types WHERE active ORDER BY display_order,code"
            ).fetchall()
        return response(
            200,
            {
                "environmentTypes": [r["code"] for r in types],
                "distributions": [
                    {"cloudProvider": p, "kubernetesDistribution": d, "schemaVersions": ["1.0"]}
                    for p, d in DISTRIBUTIONS.items()
                ],
            },
            correlation,
        )
    if method == "POST" and parts == ["discover", "aws"]:
        headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
        if not headers.get("content-type", "").lower().startswith("application/json"):
            raise ApiError(400, "INVALID_CONTENT_TYPE", "Use application/json.")
        body = AwsDiscoveryRequest.model_validate(body_json(event)).model_dump()
        principal.require("CLOUD_ENGINEER")
        with tx() as db:
            Repository(db, principal).validate_parent(body["customerId"], "AWS", active=True)
        with phase("environment_aws_discovery"):
            return response(200, discover_aws(body), correlation)
    if method == "POST" and parts == ["blueprint-readiness"]:
        headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
        if not headers.get("content-type", "").lower().startswith("application/json"):
            raise ApiError(400, "INVALID_CONTENT_TYPE", "Use application/json.")
        body = BlueprintReadinessRequest.model_validate(body_json(event))
        principal.require("CLOUD_ENGINEER")
        if body.kubernetesDistribution != "EKS":
            raise ApiError(422, "READINESS_UNSUPPORTED", "Blueprint readiness currently supports EKS.")
        with phase("environment_blueprint_readiness"):
            return response(200, assess_eks_blueprints(body.configuration), correlation)
    if parts and parts[0] == "bootstrap-remediations":
        headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
        request_id = parts[1] if len(parts) > 1 else None
        decision = parts[2] if len(parts) > 2 else None
        if request_id and not re.fullmatch(r"BRQ-[A-Fa-f0-9]{32}", request_id):
            raise ApiError(404, "ROUTE_NOT_FOUND", "Endpoint not found.")
        if (
            (method == "POST" and not request_id and len(parts) == 1)
            or (method == "POST" and request_id and decision in {"approve", "reject"} and len(parts) == 3)
        ):
            if not headers.get("content-type", "").lower().startswith("application/json"):
                raise ApiError(400, "INVALID_CONTENT_TYPE", "Use application/json.")
            key = headers.get("idempotency-key")
            if not key or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", key):
                raise ApiError(400, "IDEMPOTENCY_KEY_REQUIRED", "Provide an Idempotency-Key.")
            raw = body_json(event)
            model = CreateBootstrapRemediation if not request_id else BootstrapRemediationDecision
            body = model.model_validate(raw).model_dump(exclude_none=True)
            operation = method + " " + path
            fingerprint = hashlib.sha256(
                json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            with tx() as db:
                repo = Repository(db, principal)
                replay = repo.customers.idempotency_get(operation, key, fingerprint)
                if replay:
                    result = response(replay["status"], replay["body"], correlation)
                    result["headers"]["Idempotency-Replayed"] = "true"
                    return result
                service = BootstrapRemediationService(repo, correlation)
                value = (
                    service.create(body)
                    if not request_id
                    else service.decide(request_id, decision, body)
                )
                status = 201 if not request_id else 200
                repo.customers.idempotency_put(
                    operation, key, fingerprint, {"status": status, "body": value}
                )
                return response(status, value, correlation)
        if method == "GET" and not request_id and len(parts) == 1:
            with tx() as db:
                db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                return response(
                    200,
                    BootstrapRemediationService(Repository(db, principal), correlation).list(
                        remediation_query_params(event.get("queryStringParameters"))
                    ),
                    correlation,
                )
        if method == "GET" and request_id and len(parts) == 2:
            with tx() as db:
                db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                return response(
                    200,
                    BootstrapRemediationService(Repository(db, principal), correlation).get(request_id),
                    correlation,
                )
        raise ApiError(404, "ROUTE_NOT_FOUND", "Endpoint not found.")
    identifier = parts[0] if parts else None
    if identifier and not re.fullmatch(r"ENV-[A-Za-z0-9-]{1,46}", identifier):
        raise ApiError(404, "ROUTE_NOT_FOUND", "Endpoint not found.")
    action = "/".join(parts[1:]) if identifier else ""
    is_read = method == "GET" and (
        not action
        or action in {"versions", "status-history", "reviews", "audit-log"}
        or re.fullmatch(r"versions/[1-9][0-9]{0,17}", action)
    )
    is_write = (
        (method == "POST" and ((not identifier and not action) or action in TRANSITIONS))
        or (method == "PUT" and identifier and not action)
        or (method == "PATCH" and action == "status")
    )
    if not is_read and not is_write:
        raise ApiError(404, "ROUTE_NOT_FOUND", "Endpoint not found.")
    query = query_params(event.get("queryStringParameters"))
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    body = {}
    if is_write:
        if not headers.get("content-type", "").lower().startswith("application/json"):
            raise ApiError(400, "INVALID_CONTENT_TYPE", "Use application/json.")
        body = body_json(event)
        if identifier and "version" not in body and headers.get("if-match"):
            try:
                body["version"] = int(headers["if-match"].strip('"'))
            except ValueError:
                raise ApiError(400, "INVALID_VERSION", "Use an integer version.") from None
        model = CreateEnvironment if not identifier else UpdateEnvironment if method == "PUT" else Action
        body = model.model_validate(body).model_dump(exclude_none=True)
        if identifier and headers.get("if-match") and headers["if-match"].strip('"') != str(body["version"]):
            raise ApiError(400, "INVALID_VERSION", "Version and If-Match must agree.")
        if method == "PATCH":
            action = {"SUSPENDED": "suspend", "DEACTIVATED": "deactivate", "ACTIVE": "reactivate"}.get(
                body.get("status")
            )
            if not action:
                raise ApiError(400, "INVALID_STATUS_TRANSITION", "Select SUSPENDED, ACTIVE or DEACTIVATED.")
        key = headers.get("idempotency-key")
        if not key or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", key):
            raise ApiError(400, "IDEMPOTENCY_KEY_REQUIRED", "Provide an Idempotency-Key for every write.")
    with tx() as db:
        if is_read:
            db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        repo = Repository(db, principal)
        if is_read:
            if not identifier:
                result = repo.list(query)
            elif not action:
                result = serialize(repo.get(identifier))
            else:
                if action == "audit-log":
                    principal.require("PLATFORM_ARCHITECT")
                result = repo.records(
                    identifier,
                    action.split("/")[0],
                    query["page"],
                    query["pageSize"],
                    int(action.split("/")[1]) if action.startswith("versions/") else None,
                )
            return response(200, result, correlation)
        # Check current scope even on an idempotent replay. Mutations recheck role and workflow.
        if identifier:
            repo.get(identifier)
        else:
            repo.customers.get(body["customerId"])
        if not identifier:
            principal.require("CLOUD_ENGINEER")
        else:
            required_role = TRANSITIONS[action][2] if action in TRANSITIONS else None
            if required_role == "ENVIRONMENT_AUTHOR":
                principal.require("CLOUD_ENGINEER")
            else:
                principal.require(required_role or "CLOUD_ENGINEER")
        operation = method + " " + path
        fingerprint = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        replay = repo.customers.idempotency_get(operation, key, fingerprint)
        if replay:
            result = response(replay["status"], replay["body"], correlation)
            result["headers"]["Idempotency-Replayed"] = "true"
            return result
        service = Service(repo, correlation)
        with phase("environment_" + ("create" if not identifier else action or "update")):
            value = (
                service.create(body)
                if not identifier
                else service.change(identifier, action or "update", body)
            )
        status = 201 if not identifier else 200
        repo.customers.idempotency_put(operation, key, fingerprint, {"status": status, "body": value})
        return response(status, value, correlation)


@invocation
def lambda_handler(event, context):
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    correlation = headers.get("x-correlation-id", "")
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,100}", correlation):
        correlation = str(uuid.uuid4())
    try:
        with phase("environment_identity_validation", correlationId=correlation):
            principal = Principal.from_event(event)
        with phase("environment_operation", correlationId=correlation):
            return execute(event, principal, correlation)
    except ApiError as error:
        return response(error.status, error.payload(correlation), correlation)
    except ValidationError as error:
        return response(
            400,
            ApiError(
                400,
                "VALIDATION_ERROR",
                "Check the request fields.",
                {
                    "fields": [
                        {"field": ".".join(map(str, e["loc"])), "message": e["type"]} for e in error.errors()
                    ]
                },
            ).payload(correlation),
            correlation,
        )
    except Exception as error:
        state = getattr(error, "sqlstate", None)
        if state == "23505":
            mapped = ApiError(
                409,
                "DUPLICATE_ENVIRONMENT",
                "An environment with this name already exists for the customer and provider.",
            )
        elif state in {"40001", "40P01", "55P03"}:
            mapped = ApiError(409, "CONCURRENT_UPDATE", "Concurrent update; reload and retry.")
        elif state == "23503":
            mapped = ApiError(
                409, "DEPENDENCY_CHANGED", "A related customer or provider changed; reload and retry."
            )
        else:
            mapped = ApiError(
                500,
                "INTERNAL_ERROR",
                "An unexpected error occurred. Use the reference to locate diagnostic logs.",
            )
        return response(mapped.status, mapped.payload(correlation), correlation)
