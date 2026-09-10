"""JWT-protected Cluster Management API. Terraform executions are asynchronous."""
import base64
import hashlib
import json
import re
import uuid
from pydantic import ValidationError
from navigan.shared.auth import Principal
from navigan.shared.database import transaction
from navigan.shared.errors import ApiError
from navigan.modules.customer_management.repository import Repository as CustomerRepository
from .models import CreateCluster, UpdateCluster, Action
from .repository import Repository, serialize
from .service import Service, TRANSITIONS

BASE = "/api/v1/clusters"


def response(status, body, correlation):
    headers = {
        "Content-Type": "application/json", "Cache-Control": "no-store",
        "X-Correlation-ID": correlation,
    }
    if isinstance(body, dict) and body.get("version"):
        headers["ETag"] = str(body["version"])
    return {"statusCode": status, "headers": headers, "body": json.dumps(body, default=str)}


def path_of(event):
    path = event.get("rawPath", "")
    stage = event.get("requestContext", {}).get("stage")
    prefix = "/" + stage if stage and stage != "$default" else ""
    return path[len(prefix):] if prefix and path.startswith(prefix + BASE) else path


def body_of(event):
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw, validate=True).decode()
    if len(raw.encode()) > 65536:
        raise ApiError(413, "PAYLOAD_TOO_LARGE", "Maximum request size is 64 KiB.")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ApiError(400, "INVALID_JSON", "A JSON object is required.")
    return value


def query_of(event):
    raw = dict(event.get("queryStringParameters") or {})
    allowed = {"page", "pageSize", "status", "environmentId", "customerId", "platform", "search"}
    if set(raw) - allowed:
        raise ApiError(400, "INVALID_QUERY", "Unknown query parameter.")
    try:
        page, size = int(raw.get("page", "0")), int(raw.get("pageSize", "20"))
        if page < 0 or not 1 <= size <= 100:
            raise ValueError()
    except ValueError:
        raise ApiError(400, "INVALID_QUERY", "Check pagination.") from None
    return {**raw, "page": page, "pageSize": size}


def execute(event, principal, correlation):
    method = event.get("requestContext", {}).get("http", {}).get("method")
    path = path_of(event)
    if path != BASE and not path.startswith(BASE + "/"):
        raise ApiError(404, "ROUTE_NOT_FOUND", "Endpoint not found.")
    parts = path[len(BASE):].strip("/").split("/") if path != BASE else []
    identifier = parts[0] if parts else None
    if identifier and not re.fullmatch(r"CLU-[A-Za-z0-9-]{1,46}", identifier):
        raise ApiError(404, "ROUTE_NOT_FOUND", "Endpoint not found.")
    action = parts[1] if len(parts) == 2 else ""
    read = method == "GET" and len(parts) <= 1
    write = (
        (method == "POST" and (not parts or action in {*TRANSITIONS, "plan", "apply"}))
        or (method == "PUT" and len(parts) == 1)
    )
    if not read and not write:
        raise ApiError(404, "ROUTE_NOT_FOUND", "Endpoint not found.")
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    body = {}
    if write:
        if not headers.get("content-type", "").lower().startswith("application/json"):
            raise ApiError(400, "INVALID_CONTENT_TYPE", "Use application/json.")
        body = body_of(event)
        if identifier and "version" not in body and headers.get("if-match"):
            try:
                body["version"] = int(headers["if-match"].strip('"'))
            except ValueError:
                raise ApiError(400, "INVALID_VERSION", "Use an integer version.") from None
        model = CreateCluster if not identifier else UpdateCluster if method == "PUT" else Action
        body = model.model_validate(body).model_dump(exclude_none=True)
        key = headers.get("idempotency-key")
        if not key or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", key):
            raise ApiError(400, "IDEMPOTENCY_KEY_REQUIRED", "Provide an Idempotency-Key.")
    with transaction() as db:
        repo = Repository(db, principal)
        if read:
            value = repo.list(query_of(event)) if not identifier else serialize(repo.get(identifier))
            return response(200, value, correlation)
        operation = method + " " + path
        fingerprint = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        customer_repo = CustomerRepository(db, principal)
        replay = customer_repo.idempotency_get(operation, key, fingerprint)
        if replay:
            result = response(replay["status"], replay["body"], correlation)
            result["headers"]["Idempotency-Replayed"] = "true"
            return result
        service = Service(repo, correlation)
        value = service.create(body) if not identifier else service.change(identifier, action or "update", body)
        status = 201 if not identifier else 202 if action in {"approve", "plan", "apply"} else 200
        customer_repo.idempotency_put(operation, key, fingerprint, {"status": status, "body": value})
        return response(status, value, correlation)


def lambda_handler(event, context):
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    correlation = headers.get("x-correlation-id") or str(uuid.uuid4())
    try:
        return execute(event, Principal.from_event(event), correlation)
    except ApiError as error:
        return response(error.status, error.payload(correlation), correlation)
    except (ValidationError, ValueError, json.JSONDecodeError, UnicodeError):
        error = ApiError(400, "VALIDATION_ERROR", "Check the request fields.")
        return response(error.status, error.payload(correlation), correlation)
    except Exception:
        error = ApiError(500, "INTERNAL_ERROR", "An unexpected error occurred.")
        return response(error.status, error.payload(correlation), correlation)
