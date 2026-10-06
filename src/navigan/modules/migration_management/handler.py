"""JWT-protected assessment-only Migration Management API."""

import base64
import hashlib
import json
import logging
import re
import traceback
import uuid

from pydantic import ValidationError

from navigan.modules.customer_management.repository import (
    Repository as CustomerRepository,
)
from navigan.shared.access import AccessEvaluator, AccessRepository
from navigan.shared.auth import Principal
from navigan.shared.database import transaction
from navigan.shared.errors import ApiError

from .models import (
    CreateMigration,
    CreateSourceCluster,
    CreateSourceEnrollment,
    DiscoveryAction,
    MigrationAction,
    UpdateMigration,
)
from .repository import Repository
from .service import Service, TRANSITIONS


BASE = "/api/v1/migrations"
SOURCE_CLUSTERS_BASE = "/api/v1/source-clusters"
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


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
        "body": json.dumps(body, default=str),
    }


def path_of(event):
    path = event.get("rawPath", "")
    stage = event.get("requestContext", {}).get("stage")
    prefix = "/" + stage if stage and stage != "$default" else ""
    if prefix and path.startswith(prefix + "/api/v1/"):
        return path[len(prefix):]
    return path


def body_of(event):
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw, validate=True).decode()

    if len(raw.encode()) > 65536:
        raise ApiError(
            413,
            "PAYLOAD_TOO_LARGE",
            "Maximum request size is 64 KiB.",
        )

    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ApiError(
            400,
            "INVALID_JSON",
            "A JSON object is required.",
        )
    return value


def query_of(event):
    raw = dict(event.get("queryStringParameters") or {})
    allowed = {
        "page",
        "pageSize",
        "status",
        "customerId",
        "sourcePlatform",
        "targetPlatform",
        "search",
    }
    if set(raw) - allowed:
        raise ApiError(
            400,
            "INVALID_QUERY",
            "Unknown query parameter.",
        )

    try:
        page = int(raw.get("page", "0"))
        size = int(raw.get("pageSize", "20"))
        if page < 0 or not 1 <= size <= 100:
            raise ValueError()
    except ValueError:
        raise ApiError(
            400,
            "INVALID_QUERY",
            "Check pagination.",
        ) from None

    return {**raw, "page": page, "pageSize": size}


def route_of(method, path):
    if path == SOURCE_CLUSTERS_BASE:
        if method == "GET":
            return "source_cluster_list", None, None
        if method == "POST":
            return "source_cluster_create", None, None
        raise ApiError(404, "ROUTE_NOT_FOUND", "Endpoint not found.")

    if path.startswith(SOURCE_CLUSTERS_BASE + "/"):
        parts = path[len(SOURCE_CLUSTERS_BASE):].strip("/").split("/")
        identifier = parts[0]
        if not re.fullmatch(r"SRC-[a-f0-9]{32}", identifier):
            raise ApiError(404, "ROUTE_NOT_FOUND", "Endpoint not found.")
        if len(parts) == 1 and method == "GET":
            return "source_cluster_get", identifier, None
        if (
            len(parts) == 2
            and parts[1] == "enrollments"
            and method == "POST"
        ):
            return "source_cluster_enrollment", identifier, None
        raise ApiError(404, "ROUTE_NOT_FOUND", "Endpoint not found.")

    if path == BASE:
        if method == "GET":
            return "list", None, None
        if method == "POST":
            return "create", None, None
        raise ApiError(404, "ROUTE_NOT_FOUND", "Endpoint not found.")

    if not path.startswith(BASE + "/"):
        raise ApiError(404, "ROUTE_NOT_FOUND", "Endpoint not found.")

    parts = path[len(BASE):].strip("/").split("/")
    identifier = parts[0]

    if not re.fullmatch(r"MIG-[a-f0-9]{32}", identifier):
        raise ApiError(404, "ROUTE_NOT_FOUND", "Endpoint not found.")

    if len(parts) == 1 and method == "GET":
        return "get", identifier, None

    if (
        len(parts) == 2
        and parts[1] == "source-catalogue"
        and method == "GET"
    ):
        return "source_catalogue", identifier, None

    if (
        len(parts) == 2
        and parts[1] == "assessment"
        and method == "GET"
    ):
        return "assessment", identifier, None

    if len(parts) == 1 and method == "PUT":
        return "update", identifier, None

    if (
        len(parts) == 2
        and method == "POST"
        and parts[1] in TRANSITIONS
    ):
        return "action", identifier, parts[1]

    raise ApiError(404, "ROUTE_NOT_FOUND", "Endpoint not found.")


def execute(event, principal, correlation):
    method = event.get("requestContext", {}).get("http", {}).get("method")
    path = path_of(event)
    route, identifier, action = route_of(method, path)
    mutating = route in {
        "create",
        "update",
        "action",
        "source_cluster_create",
        "source_cluster_enrollment",
    }
    idempotent = mutating and route != "source_cluster_enrollment"

    headers = {
        key.lower(): value
        for key, value in (event.get("headers") or {}).items()
    }

    body = {}
    key = None
    operation = None
    fingerprint = None

    if mutating:
        if not headers.get("content-type", "").lower().startswith(
            "application/json"
        ):
            raise ApiError(
                400,
                "INVALID_CONTENT_TYPE",
                "Use application/json.",
            )

        body = body_of(event)

        if (
            identifier
            and "version" not in body
            and headers.get("if-match")
        ):
            try:
                body["version"] = int(
                    headers["if-match"].strip('"')
                )
            except ValueError:
                raise ApiError(
                    400,
                    "INVALID_VERSION",
                    "Use an integer version.",
                ) from None

        if route == "create":
            model = CreateMigration
        elif route == "update":
            model = UpdateMigration
        elif route == "source_cluster_create":
            model = CreateSourceCluster
        elif route == "source_cluster_enrollment":
            model = CreateSourceEnrollment
        elif action in {"discover", "assess"}:
            model = DiscoveryAction
        else:
            model = MigrationAction
        body = model.model_validate(body).model_dump(
            mode="json",
            exclude_none=True,
        )

        if idempotent:
            key = headers.get("idempotency-key")
            if not key or not re.fullmatch(
                r"[A-Za-z0-9._:-]{1,128}",
                key,
            ):
                raise ApiError(
                    400,
                    "IDEMPOTENCY_KEY_REQUIRED",
                    "Provide an Idempotency-Key.",
                )

            operation = method + " " + path
            fingerprint = hashlib.sha256(
                json.dumps(
                    body,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()

    with transaction() as db:
        repo = Repository(db, principal)
        access = AccessEvaluator(
            AccessRepository(db)
        ).evaluate(principal)

        if not mutating:
            access.require("migration.view")
            if route == "source_cluster_list":
                value = repo.list_source_clusters(query_of(event))
            elif route == "source_cluster_get":
                from .repository import serialize

                value = serialize(repo.get_source_cluster(identifier))
            elif route == "list":
                value = repo.list(query_of(event))
            elif route == "source_catalogue":
                value = repo.get_source_catalogue(identifier)
            elif route == "assessment":
                value = repo.get_assessment(identifier)
            else:
                from .repository import serialize

                value = serialize(repo.get(identifier))
            return response(200, value, correlation)

        customer_repo = CustomerRepository(db, principal)
        replay = (
            customer_repo.idempotency_get(
                operation,
                key,
                fingerprint,
            )
            if idempotent
            else None
        )
        if replay:
            replay_identifier = (
                replay["body"].get("migrationId")
                or replay["body"].get("sourceClusterId")
            )
            if replay_identifier:
                if replay_identifier.startswith("SRC-"):
                    repo.get_source_cluster(replay_identifier)
                else:
                    repo.get(replay_identifier)
            result = response(
                replay["status"],
                replay["body"],
                correlation,
            )
            result["headers"]["Idempotency-Replayed"] = "true"
            return result

        service = Service(repo, access, correlation)

        if route == "source_cluster_create":
            value = service.create_source_cluster(body)
            status = 201
        elif route == "source_cluster_enrollment":
            value = service.create_source_enrollment(identifier, body)
            status = 201
        elif route == "create":
            value = service.create(body)
            status = 201
        elif route == "update":
            value = service.update(identifier, body)
            status = 200
        else:
            value = service.change(identifier, action, body)
            status = 200

        if idempotent:
            customer_repo.idempotency_put(
                operation,
                key,
                fingerprint,
                {"status": status, "body": value},
            )
        return response(status, value, correlation)


def lambda_handler(event, context):
    headers = {
        key.lower(): value
        for key, value in (event.get("headers") or {}).items()
    }
    correlation = headers.get("x-correlation-id", "")
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,100}", correlation):
        correlation = str(uuid.uuid4())

    try:
        return execute(
            event,
            Principal.from_event(event),
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
            "Check the highlighted request fields.",
            {
                "fields": [
                    {
                        "field": ".".join(map(str, item["loc"])),
                        "message": item["msg"],
                    }
                    for item in validation_error.errors(
                        include_url=False
                    )
                ]
            },
        )
        return response(
            error.status,
            error.payload(correlation),
            correlation,
        )
    except (ValueError, json.JSONDecodeError, UnicodeError):
        error = ApiError(
            400,
            "VALIDATION_ERROR",
            "Check the request fields.",
        )
        return response(
            error.status,
            error.payload(correlation),
            correlation,
        )
    except Exception as error:
        logger.error(
            json.dumps(
                {
                    "correlationId": correlation,
                    "errorType": type(error).__name__,
                    "sqlState": getattr(error, "sqlstate", None),
                    "locations": [
                        {
                            "file": frame.filename.rsplit("/", 1)[-1],
                            "line": frame.lineno,
                            "function": frame.name,
                        }
                        for frame in traceback.extract_tb(
                            error.__traceback__
                        )
                    ][-8:],
                }
            )
        )
        internal = ApiError(
            500,
            "INTERNAL_ERROR",
            "An unexpected error occurred.",
        )
        return response(
            internal.status,
            internal.payload(correlation),
            correlation,
        )
