"""One-time exchange and validation for browser tool sessions."""

import base64
import hashlib
import hmac
import json
import re
import secrets
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from navigan.shared.database import transaction
from navigan.shared.errors import ApiError

BASE = "/api/v1/tool-sessions"
SESSION = re.compile(r"^KTS-[a-f0-9]{32}$")


class ExchangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    exchangeToken: str = Field(min_length=40, max_length=100)


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
    if not raw or len(raw.encode()) > 4096:
        raise ApiError(400, "INVALID_TOOL_SESSION", "Tool session request is invalid.")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ApiError(400, "INVALID_TOOL_SESSION", "Tool session request is invalid.")
    return value


def execute(event):
    method = event.get("requestContext", {}).get("http", {}).get("method")
    match = re.fullmatch(
        re.escape(BASE) + r"/(KTS-[a-f0-9]{32})/(exchange|validate)",
        path_of(event),
    )
    if not match or method != "POST":
        raise ApiError(404, "ROUTE_NOT_FOUND", "Endpoint not found.")
    session_id, action = match.groups()
    if not SESSION.fullmatch(session_id):
        raise ApiError(404, "ROUTE_NOT_FOUND", "Endpoint not found.")
    headers = {key.lower(): value for key, value in (event.get("headers") or {}).items()}
    now = datetime.now(timezone.utc)
    with transaction() as db:
        row = db.execute(
            "SELECT * FROM cluster_management.cluster_tool_sessions "
            "WHERE session_id=%s FOR UPDATE",
            [session_id],
        ).fetchone()
        if not row or row["expires_at"] <= now or row["status"] in {
            "CLOSED",
            "EXPIRED",
            "REVOKED",
        }:
            raise ApiError(401, "TOOL_SESSION_INVALID", "Tool session is invalid.")
        if action == "exchange":
            request = ExchangeRequest.model_validate(body_of(event))
            supplied = hashlib.sha256(request.exchangeToken.encode()).hexdigest()
            if (
                row["status"] != "ISSUED"
                or row["exchange_expires_at"] <= now
                or not row["exchange_token_sha256"]
                or not hmac.compare_digest(row["exchange_token_sha256"], supplied)
            ):
                raise ApiError(401, "TOOL_SESSION_INVALID", "Tool session is invalid.")
            access_token = secrets.token_urlsafe(48)
            db.execute(
                "UPDATE cluster_management.cluster_tool_sessions "
                "SET status='ACTIVE',exchange_token_sha256=NULL,"
                "access_token_sha256=%s,activated_at=%s,last_seen_at=%s "
                "WHERE session_id=%s",
                [
                    hashlib.sha256(access_token.encode()).hexdigest(),
                    now,
                    now,
                    session_id,
                ],
            )
            return {
                "sessionId": session_id,
                "accessToken": access_token,
                "clusterId": row["cluster_id"],
                "toolCode": row["tool_code"],
                "expiresAt": row["expires_at"].isoformat(),
            }
        authorization = headers.get("authorization", "")
        if not authorization.startswith("Bearer "):
            raise ApiError(401, "TOOL_SESSION_INVALID", "Tool session is invalid.")
        supplied = hashlib.sha256(authorization[7:].encode()).hexdigest()
        if (
            row["status"] != "ACTIVE"
            or not row["access_token_sha256"]
            or not hmac.compare_digest(row["access_token_sha256"], supplied)
        ):
            raise ApiError(401, "TOOL_SESSION_INVALID", "Tool session is invalid.")
        db.execute(
            "UPDATE cluster_management.cluster_tool_sessions SET last_seen_at=%s "
            "WHERE session_id=%s",
            [now, session_id],
        )
        return {
            "sessionId": session_id,
            "clusterId": row["cluster_id"],
            "customerId": row["customer_id"],
            "userId": row["user_id"],
            "toolCode": row["tool_code"],
            "expiresAt": row["expires_at"].isoformat(),
        }


def lambda_handler(event, context):
    correlation = str(uuid.uuid4())
    try:
        return response(200, execute(event), correlation)
    except ApiError as error:
        return response(error.status, error.payload(correlation), correlation)
    except (ValidationError, ValueError, json.JSONDecodeError, UnicodeError):
        error = ApiError(400, "INVALID_TOOL_SESSION", "Tool session request is invalid.")
        return response(error.status, error.payload(correlation), correlation)
    except Exception:
        error = ApiError(500, "INTERNAL_ERROR", "An unexpected error occurred.")
        return response(error.status, error.payload(correlation), correlation)
