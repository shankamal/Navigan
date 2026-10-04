"""Read-only effective-access endpoint used during the additive migration."""

import json
import logging
import re
import uuid

from navigan.shared.access import AccessEvaluator, AccessRepository
from navigan.shared.auth import Principal
from navigan.shared.database import transaction
from navigan.shared.errors import ApiError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
BASE = "/api/v1/access/me"


def response(status, body, correlation):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
            "X-Correlation-ID": correlation,
        },
        "body": json.dumps(body),
    }


def resource_path(event):
    path = event.get("rawPath", "")
    stage = event.get("requestContext", {}).get("stage")
    if isinstance(stage, str) and stage and stage != "$default":
        prefix = "/" + stage
        if path == prefix + BASE:
            return path[len(prefix):]
    return path


def serialize(access):
    grouped = {}
    for scope in access.scopes:
        entry = grouped.setdefault(
            scope.scope_type,
            {"type": scope.scope_type},
        )
        if scope.scope_type == "CUSTOMER":
            entry.setdefault("customerIds", []).append(scope.customer_id)
        elif scope.scope_type == "RESOURCE":
            entry.setdefault("resources", []).append(
                {
                    "customerId": scope.customer_id,
                    "resourceType": scope.resource_type,
                    "resourceId": scope.resource_id,
                }
            )
    scopes = []
    for entry in grouped.values():
        if "customerIds" in entry:
            entry["customerIds"] = sorted(set(entry["customerIds"]))
        scopes.append(entry)
    privileges = sorted(access.privileges)
    return {
        "user": {
            "userId": access.user_id,
            "displayName": access.display_name,
        },
        "authorizationRevision": access.authorization_revision,
        "privileges": privileges,
        "scopes": sorted(scopes, key=lambda item: item["type"]),
        "source": access.source,
        "menuCapabilities": {
            "hasPlatformScope": any(scope.scope_type == "PLATFORM" for scope in access.scopes),
            "canReviewRequests": any(
                code.endswith(".review") or code.endswith(".approve") for code in privileges
            ),
            "canManageAccess": any(
                code in {"user.manage", "role.manage", "assignment.manage", "scope.manage"}
                for code in privileges
            ),
        },
    }


def execute(event, principal, tx=transaction):
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    if resource_path(event) != BASE:
        raise ApiError(404, "ROUTE_NOT_FOUND", "Endpoint not found.")
    if method != "GET":
        raise ApiError(405, "METHOD_NOT_ALLOWED", "Method not supported for this endpoint.")
    with tx() as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        access = AccessEvaluator(AccessRepository(connection)).evaluate(principal)
        return serialize(access)


def lambda_handler(event, context):
    headers = {key.lower(): value for key, value in (event.get("headers") or {}).items()}
    correlation = headers.get("x-correlation-id", "")
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,100}", correlation):
        correlation = str(uuid.uuid4())
    principal = None
    try:
        principal = Principal.from_event(event)
        result = response(200, execute(event, principal), correlation)
    except ApiError as error:
        result = response(error.status, error.payload(correlation), correlation)
    except Exception as error:
        logger.error(
            json.dumps(
                {
                    "errorType": type(error).__name__,
                    "correlationId": correlation,
                    "userId": principal.user_id if principal else None,
                }
            )
        )
        mapped = ApiError(500, "INTERNAL_ERROR", "An unexpected error occurred.")
        result = response(mapped.status, mapped.payload(correlation), correlation)
    return result
