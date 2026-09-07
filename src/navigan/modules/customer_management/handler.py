"""API Gateway HTTP API payload v2 entry point. No JWT decoding or public function URL."""

import base64
import hashlib
import json
import logging
import re
import time
import uuid
from pydantic import ValidationError
from navigan.shared.auth import Principal
from navigan.shared.database import transaction
from navigan.shared.errors import ApiError
from .models import Action, CreateCustomer, ProviderSet, UpdateCustomer
from .repository import Repository
from .service import CustomerService
from .workflow import STATUSES, TRANSITIONS

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
BASE = "/api/v1/customers"


def parse_query(params):
    params = params or {}
    if set(params) - {"page", "pageSize", "status", "cloudProvider", "search", "sort", "createdBy"}:
        raise ApiError(400, "INVALID_QUERY", "Unknown query parameter.")
    try:
        page, size = int(params.get("page", "0")), int(params.get("pageSize", "20"))
        if page < 0 or page > 1000000 or not 1 <= size <= 100:
            raise ValueError()
    except (TypeError, ValueError):
        raise ApiError(
            400, "INVALID_PAGINATION", "page must be nonnegative and pageSize must be 1–100."
        ) from None
    sort = params.get("sort", "createdAt,desc")
    if sort not in {
        f"{field},{direction}"
        for field in ("name", "createdAt", "updatedAt", "status")
        for direction in ("asc", "desc")
    }:
        raise ApiError(400, "INVALID_SORT", "Unsupported sort field or direction.")
    if params.get("status") and params["status"] not in STATUSES:
        raise ApiError(400, "INVALID_STATUS", "Unknown customer status.")
    if any(not isinstance(v, str) or len(v) > 255 for v in params.values()):
        raise ApiError(400, "INVALID_QUERY", "Query values must be strings of at most 255 characters.")
    return {**params, "page": page, "pageSize": size, "sort": sort}


def parse_version(headers):
    raw = headers.get("if-match", "")
    if not re.fullmatch(r'(?:[1-9][0-9]{0,17}|"[1-9][0-9]{0,17}")', raw):
        raise ApiError(400, "VERSION_REQUIRED", "If-Match must contain the current positive integer version.")
    return int(raw.strip('"'))


def body_json(event):
    body = event.get("body") or "{}"
    try:
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body, validate=True).decode("utf-8")
        if len(body.encode("utf-8")) > 65536:
            raise ApiError(400, "PAYLOAD_TOO_LARGE", "Request body exceeds 64 KiB.")
        value = json.loads(body)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, UnicodeError, TypeError):
        raise ApiError(400, "INVALID_JSON", "A JSON object is required.") from None


def response(status, body, correlation, replay=False):
    headers = {
        "Content-Type": "application/json",
        "X-Correlation-ID": correlation,
        "Cache-Control": "no-store",
    }
    if isinstance(body, dict) and "version" in body:
        headers["ETag"] = f'"{body["version"]}"'
    if replay:
        headers["Idempotency-Replayed"] = "true"
    return {"statusCode": status, "headers": headers, "body": json.dumps(body, default=str)}


def resource_path(event):
    """Remove only the named API Gateway stage, leaving the resource path intact."""
    path = event.get("rawPath", "")
    stage = event.get("requestContext", {}).get("stage")
    if isinstance(stage, str) and stage and stage != "$default":
        prefix = "/" + stage
        if path == prefix + BASE or path.startswith(prefix + BASE + "/"):
            return path[len(prefix):]
    return path


def execute(event, principal, correlation, tx=transaction):
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    path = resource_path(event)
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    match = re.fullmatch(
        re.escape(BASE)
        + r"(?:/(CUS-[A-Za-z0-9-]+)(?:/(cloud-providers|submit|resubmit|review/start|approve|reject|activate|suspend|reactivate|deactivate|status-history|audit-log|reviews))?)?",
        path,
    )
    if not match:
        raise ApiError(404, "ROUTE_NOT_FOUND", "Endpoint not found.")
    customer_id, action = match.groups()
    allowed = (
        {"GET", "POST"}
        if not customer_id
        else {"GET", "PUT"}
        if not action
        else {"GET", "PUT"}
        if action == "cloud-providers"
        else {"POST"}
        if action in TRANSITIONS
        else {"GET"}
    )
    if method not in allowed:
        raise ApiError(405, "METHOD_NOT_ALLOWED", "Method not supported for this endpoint.")
    query = parse_query(event.get("queryStringParameters"))
    mutating = method in {"POST", "PUT"}
    body, version = None, None
    if mutating:
        principal.require(TRANSITIONS[action][2] if action in TRANSITIONS else "CLOUD_ENGINEER")
        if not customer_id and not principal.can_create:
            raise ApiError(403, "FORBIDDEN", "Customer onboarding entitlement is required.")
        content_type = headers.get("content-type", "application/json").split(";")[0].strip().lower()
        if content_type != "application/json":
            raise ApiError(400, "INVALID_CONTENT_TYPE", "Use application/json.")
        model = (
            CreateCustomer
            if not customer_id
            else ProviderSet
            if action == "cloud-providers"
            else Action
            if action in TRANSITIONS
            else UpdateCustomer
        )
        body = model.model_validate(body_json(event)).model_dump()
        if customer_id:
            version = parse_version(headers)
    key = headers.get("idempotency-key") if mutating else None
    if key is not None and not re.fullmatch(r"[\x21-\x7e]{1,128}", key):
        raise ApiError(400, "INVALID_IDEMPOTENCY_KEY", "Use 1–128 printable non-space ASCII characters.")
    operation = f"{method} {path}"
    fingerprint = hashlib.sha256(
        json.dumps({"body": body, "version": version}, sort_keys=True).encode()
    ).hexdigest()
    with tx() as connection:
        if not mutating:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        repository = Repository(connection, principal)
        service = CustomerService(repository, correlation)
        # Recheck scope before returning any cached result (access may have been revoked).
        if customer_id:
            repository.get(customer_id)
        if key:
            cached = repository.idempotency_get(operation, key, fingerprint)
            if cached:
                repository.get(cached["body"]["customerId"])
                return response(cached["status"], cached["body"], correlation, True)
        status = 200
        if method == "GET":
            if not customer_id:
                result = service.list(query)
            elif action == "cloud-providers":
                result = {
                    "customerId": customer_id,
                    "cloudProviders": repository.providers(customer_id),
                    "version": repository.get(customer_id)["version"],
                }
            elif action:
                result = service.records(customer_id, action, query)
            else:
                result = service.details(repository.get(customer_id))
        elif not customer_id:
            result, status = service.create(body), 201
        elif method == "PUT":
            result = service.update(customer_id, body, version, action == "cloud-providers")
        else:
            result = service.transition(customer_id, action, body, version)
        if key:
            repository.idempotency_put(operation, key, fingerprint, {"status": status, "body": result})
        return response(status, result, correlation)


def lambda_handler(event, context):
    started = time.monotonic()
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    correlation = headers.get("x-correlation-id", "")
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,100}", correlation):
        correlation = str(uuid.uuid4())
    principal = None
    try:
        principal = Principal.from_event(event)
        result = execute(event, principal, correlation)
    except ApiError as error:
        result = response(error.status, error.payload(correlation), correlation)
    except ValidationError as error:
        # Never return Pydantic's input/context fields: those can contain submitted PII or secrets.
        details = {
            "fields": [{"path": ".".join(map(str, e["loc"])), "type": e["type"]} for e in error.errors()]
        }
        result = response(
            400,
            ApiError(400, "VALIDATION_ERROR", "Invalid request fields.", details).payload(correlation),
            correlation,
        )
    except Exception as error:
        state = getattr(error, "sqlstate", None)
        if state == "23505":
            mapped = ApiError(409, "DUPLICATE_CUSTOMER", "A conflicting customer record already exists.")
        elif state in {"40001", "40P01", "55P03"}:
            mapped = ApiError(
                409, "CONCURRENT_UPDATE", "Concurrent operation detected. Retry with the latest version."
            )
        else:
            mapped = ApiError(500, "INTERNAL_ERROR", "An unexpected error occurred.")
        # Deliberately do not log exception text/SQL/parameters.
        logger.error(json.dumps({"errorType": type(error).__name__, "correlationId": correlation}))
        result = response(mapped.status, mapped.payload(correlation), correlation)
    business_metrics = {}
    customer_id = None
    if result["statusCode"] < 300:
        returned = json.loads(result["body"])
        customer_id = returned.get("customerId")
        if result["headers"].get("Idempotency-Replayed") != "true":
            path = resource_path(event)
            method = event.get("requestContext", {}).get("http", {}).get("method")
            metric = None
            if method == "POST":
                metric = (
                    "customers_created_total"
                    if path == BASE
                    else {
                        "submit": "customers_submitted_total",
                        "resubmit": "customers_submitted_total",
                        "approve": "customers_approved_total",
                        "reject": "customers_rejected_total",
                        "activate": "customers_active_total",
                        "reactivate": "customers_active_total",
                    }.get(path.rsplit("/", 1)[-1])
                )
            elif method == "PUT" and path.endswith("/cloud-providers"):
                metric = "customer_cloud_provider_changes_total"
            if metric:
                business_metrics[metric] = 1
    elapsed = round((time.monotonic() - started) * 1000, 2)
    status = result["statusCode"]
    logger.info(
        json.dumps(
            {
                "timestamp": int(time.time() * 1000),
                "userId": principal.user_id if principal else None,
                "requestId": getattr(context, "aws_request_id", None),
                "correlationId": correlation,
                "customerId": customer_id,
                "action": event.get("routeKey", "unknown"),
                "result": status,
                "latencyMs": elapsed,
            }
        )
    )
    logger.info(
        json.dumps(
            {
                "_aws": {
                    "Timestamp": int(time.time() * 1000),
                    "CloudWatchMetrics": [
                        {
                            "Namespace": "Navigan/CustomerManagement",
                            "Dimensions": [["Module"]],
                            "Metrics": [
                                {"Name": "customer_api_requests_total", "Unit": "Count"},
                                {"Name": "customer_api_errors_total", "Unit": "Count"},
                                {"Name": "customer_api_latency", "Unit": "Milliseconds"},
                                *[{"Name": name, "Unit": "Count"} for name in business_metrics],
                            ],
                        }
                    ],
                },
                "Module": "CustomerManagement",
                "customer_api_requests_total": 1,
                "customer_api_errors_total": int(status >= 400),
                "customer_api_latency": elapsed,
                **business_metrics,
            }
        )
    )
    return result
