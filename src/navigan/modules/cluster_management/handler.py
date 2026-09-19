"""JWT-protected Cluster Management API. Terraform executions are asynchronous."""
import base64
import hashlib
import json
import logging
import os
import re
import traceback
import uuid
import secrets
import boto3
from pydantic import ValidationError
from navigan.shared.access import AccessEvaluator, AccessRepository
from navigan.shared.auth import Principal
from navigan.shared.database import transaction
from navigan.shared.errors import ApiError
from navigan.modules.customer_management.repository import Repository as CustomerRepository
from .models import (
    CreateCluster,
    UpdateCluster,
    Action,
    KubernetesAccessAssignment,
    RevokeKubernetesAccess,
    ConnectorInstallationRequest,
    CreateNodeGroupRequest,
    NodeGroupRequestAction,
    SystemNodeGroupMigration,
    GitHubAuthorizationRequest,
    CompleteGitHubAuthorization,
)
from .repository import Repository, serialize
from .service import Service, TRANSITIONS
from .connector_installation import ConnectorInstaller

BASE = "/api/v1/clusters"
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
SECRET_VALUE = re.compile(
    r"(?i)(external[_ -]?id|secret|string|token|password)\s*[:=]\s*\S+"
)


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


def _user_attributes(user):
    return {
        item.get("Name"): item.get("Value")
        for item in user.get("Attributes", [])
        if item.get("Name") and item.get("Value")
    }


def identity_subjects():
    """Return a bounded Cognito directory without exposing provider internals."""
    pool_id = os.environ["IDENTITY_USER_POOL_ID"]
    client = boto3.client("cognito-idp")
    users, groups = [], []
    token = None
    for _ in range(10):
        request = {"UserPoolId": pool_id, "Limit": 60}
        if token:
            request["PaginationToken"] = token
        page = client.list_users(**request)
        for user in page.get("Users", []):
            attributes = _user_attributes(user)
            subject_id = attributes.get("sub")
            if not subject_id:
                continue
            email = attributes.get("email")
            aliases = [
                value
                for value in [
                    attributes.get("name"),
                    attributes.get("preferred_username"),
                    attributes.get("given_name"),
                    attributes.get("family_name"),
                    email,
                    user.get("Username"),
                ]
                if value
            ]
            display_name = (
                attributes.get("name")
                or attributes.get("preferred_username")
                or " ".join(
                    part
                    for part in [
                        attributes.get("given_name"),
                        attributes.get("family_name"),
                    ]
                    if part
                )
                or email
                or user.get("Username")
            )
            users.append(
                {
                    "type": "USER",
                    "id": subject_id,
                    "displayName": display_name,
                    "email": email,
                    "username": user.get("Username"),
                    "aliases": list(dict.fromkeys(aliases)),
                    "enabled": bool(user.get("Enabled", False)),
                    "status": user.get("UserStatus"),
                }
            )
        token = page.get("PaginationToken")
        if not token:
            break
    next_token = None
    for _ in range(10):
        request = {"UserPoolId": pool_id, "Limit": 60}
        if next_token:
            request["NextToken"] = next_token
        page = client.list_groups(**request)
        groups.extend(
            {
                "type": "GROUP",
                "id": group["GroupName"],
                "displayName": group["GroupName"],
                "description": group.get("Description"),
                "aliases": [group["GroupName"], group.get("Description")]
                if group.get("Description")
                else [group["GroupName"]],
            }
            for group in page.get("Groups", [])
        )
        next_token = page.get("NextToken")
        if not next_token:
            break
    return {
        "users": sorted(users, key=lambda item: (item["displayName"] or "").lower()),
        "groups": sorted(groups, key=lambda item: item["displayName"].lower()),
        "truncated": bool(token or next_token),
    }


def validate_identity_subject(subject_type, subject_id):
    directory = identity_subjects()
    collection = directory["users"] if subject_type == "USER" else directory["groups"]
    subject = next((item for item in collection if item["id"] == subject_id), None)
    if not subject:
        raise ApiError(
            422,
            "IDENTITY_SUBJECT_NOT_FOUND",
            "Select an active user or group from the configured identity provider.",
        )
    if subject_type == "USER" and not subject["enabled"]:
        raise ApiError(
            422,
            "IDENTITY_USER_DISABLED",
            "Access cannot be assigned to a disabled user.",
        )
    return subject


def execution_logs(row):
    build_id = row.get("provider_execution_id")
    if not build_id:
        return {"status": row["status"], "events": [], "complete": True}
    workflow = row.get("workflow") or {}
    execution = workflow.get("currentExecution") or workflow.get("lastExecution") or {}
    operation = execution.get("mode")
    if not operation and row.get("execution_artifact_prefix"):
        try:
            body = boto3.client("s3").get_object(
                Bucket=os.environ["TERRAFORM_ARTIFACT_BUCKET"],
                Key=row["execution_artifact_prefix"] + "/input.json",
            )["Body"].read()
            operation = json.loads(body).get("mode")
        except Exception:
            logger.info(
                "Execution operation metadata is unavailable.",
                extra={"clusterId": row["cluster_id"], "buildId": build_id},
            )
    project, _, stream = build_id.partition(":")
    if not project or not stream:
        return {
            "status": row["status"], "operation": operation,
            "events": [], "complete": True,
        }
    provider_status = None
    try:
        builds = boto3.client("codebuild").batch_get_builds(ids=[build_id]).get(
            "builds", []
        )
        if builds:
            provider_status = builds[0].get("buildStatus")
    except Exception:
        logger.info(
            "Live CodeBuild status is unavailable.",
            extra={"clusterId": row["cluster_id"], "buildId": build_id},
        )
    running_statuses = {"IN_PROGRESS"}
    complete = (
        provider_status not in running_statuses
        if provider_status
        else row["status"] not in {
            "PLAN_RUNNING", "APPLYING", "STOPPING", "STARTING", "DELETING"
        }
    )
    result = boto3.client("logs").get_log_events(
        logGroupName=f"/aws/codebuild/{project}",
        logStreamName=stream,
        startFromHead=False,
        limit=200,
    )
    events = []
    for event in result.get("events", []):
        message = ANSI_ESCAPE.sub("", str(event.get("message", ""))).strip()
        message = SECRET_VALUE.sub(r"\1=[REDACTED]", message)
        if message:
            events.append(
                {
                    "timestamp": int(event.get("timestamp", 0)),
                    "message": message[:4000],
                }
            )
    return {
        "status": provider_status or row["status"],
        "requestStatus": row["status"],
        "operation": operation,
        "executionId": build_id,
        "errorCode": (workflow.get("lastExecution") or {}).get("errorCode"),
        "events": events[-200:],
        "complete": complete,
    }


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
    create_access = (
        method == "POST" and len(parts) == 3
        and parts[1:] == ["access", "assignments"]
    )
    revoke_access = (
        method == "POST" and len(parts) == 5
        and parts[1] == "access" and parts[2] == "assignments"
        and re.fullmatch(r"KAA-[A-Fa-f0-9]{32}", parts[3] or "")
        and parts[4] == "revoke"
    )
    access_subjects = (
        method == "GET" and len(parts) == 3
        and parts[1:] == ["access", "subjects"]
    )
    access_namespaces = (
        method == "GET" and len(parts) == 3
        and parts[1:] == ["access", "namespaces"]
    )
    install_connector = (
        method == "POST" and len(parts) == 3
        and parts[1:] == ["connector", "install"]
    )
    node_group_requests = len(parts) == 2 and parts[1] == "node-groups"
    audit_log = len(parts) == 2 and parts[1] == "audit-log"
    node_group_execution_logs = (
        method == "GET"
        and len(parts) == 4
        and parts[1] == "node-groups"
        and re.fullmatch(r"KNG-[a-f0-9]{32}", parts[2] or "")
        and parts[3] == "execution-logs"
    )
    create_node_group_request = method == "POST" and node_group_requests
    migrate_system_node_group = (
        method == "POST"
        and len(parts) == 2
        and parts[1] == "migrate-system-node-group"
    )
    begin_github_authorization = (
        method == "POST"
        and len(parts) == 3
        and parts[1:] == ["github", "authorize"]
    )
    complete_github_authorization = (
        method == "POST"
        and len(parts) == 3
        and parts[1:] == ["github", "complete"]
    )
    node_group_action = (
        method == "POST"
        and len(parts) == 4
        and parts[1] == "node-groups"
        and re.fullmatch(r"KNG-[a-f0-9]{32}", parts[2] or "")
        and parts[3] in {"submit", "approve", "reject", "apply", "retry"}
    )
    read_actions = {"execution-logs", "identity", "access"}
    read = method == "GET" and (
        len(parts) <= 1
        or (len(parts) == 2 and action in read_actions)
        or access_subjects
        or access_namespaces
        or node_group_requests
        or audit_log
        or node_group_execution_logs
    )
    write = (
        (method == "POST" and (
            not parts or action in {*TRANSITIONS, "plan", "apply", "stop", "start", "delete"}
        ))
        or (method == "PUT" and len(parts) == 1)
        or create_access
        or revoke_access
        or install_connector
        or create_node_group_request
        or migrate_system_node_group
        or begin_github_authorization
        or complete_github_authorization
        or node_group_action
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
        model = (
            KubernetesAccessAssignment
            if create_access
            else RevokeKubernetesAccess
            if revoke_access
            else ConnectorInstallationRequest
            if install_connector
            else CreateNodeGroupRequest
            if create_node_group_request
            else SystemNodeGroupMigration
            if migrate_system_node_group
            else GitHubAuthorizationRequest
            if begin_github_authorization
            else CompleteGitHubAuthorization
            if complete_github_authorization
            else NodeGroupRequestAction
            if node_group_action
            else CreateCluster
            if not identifier
            else UpdateCluster
            if method == "PUT"
            else Action
        )
        body = model.model_validate(body).model_dump(exclude_none=True)
        key = headers.get("idempotency-key")
        if not key or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", key):
            raise ApiError(400, "IDEMPOTENCY_KEY_REQUIRED", "Provide an Idempotency-Key.")
    with transaction() as db:
        repo = Repository(db, principal)
        access = AccessEvaluator(AccessRepository(db)).evaluate(principal)
        if read:
            if not identifier:
                value = repo.list(query_of(event), access)
            else:
                row = repo.get(identifier)
                if action == "execution-logs":
                    value = execution_logs(row)
                elif action == "identity":
                    access.require("cluster.identity.view")
                    value = repo.identity(identifier)
                elif action == "access":
                    access.require("cluster.access.view")
                    value = repo.kubernetes_access(identifier)
                elif access_subjects:
                    access.require("cluster.access.manage")
                    value = {
                        "clusterId": identifier,
                        "customerId": row["customer_id"],
                        **identity_subjects(),
                    }
                elif access_namespaces:
                    access.require("cluster.access.manage")
                    value = repo.kubernetes_namespaces(identifier)
                elif node_group_requests:
                    value = repo.node_group_requests(identifier)
                elif node_group_execution_logs:
                    access.require("cluster.logs.view")
                    value = execution_logs(
                        repo.get_node_group_request(identifier, parts[2])
                    )
                elif audit_log:
                    if not (
                        access.has("cluster.audit.view")
                        or access.has("audit.platform.view")
                    ):
                        raise ApiError(
                            403, "FORBIDDEN", "This operation is not permitted."
                        )
                    value = repo.audit_log(identifier)
                else:
                    value = serialize(row, access)
            return response(200, value, correlation)
        if install_connector:
            access.require("cluster.access.manage")
            row = repo.get(identifier)
            if row["version"] != body["version"]:
                raise ApiError(409, "CONCURRENT_UPDATE", "Reload the latest cluster request.")
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
            token = secrets.token_urlsafe(32)
            value = repo.request_connector_install(
                identifier,
                token,
                body["reason"],
                correlation,
                ConnectorInstaller(),
            )
            customer_repo.idempotency_put(
                operation, key, fingerprint, {"status": 202, "body": value}
            )
            return response(202, value, correlation)
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
        if create_access:
            access.require("cluster.access.manage")
            validate_identity_subject(body["subjectType"], body["subjectId"])
            value = repo.create_kubernetes_access(identifier, body, correlation)
            status = 201
        elif revoke_access:
            access.require("cluster.access.manage")
            value = repo.revoke_kubernetes_access(
                identifier, parts[3], body, correlation
            )
            status = 200
        elif create_node_group_request:
            value = Service(repo, correlation).create_node_group_request(
                identifier, body
            )
            status = 201
        elif migrate_system_node_group:
            access.require("cluster.apply")
            value = Service(repo, correlation).migrate_system_node_group(
                identifier, body
            )
            status = 202
        elif begin_github_authorization:
            access.require("cluster.approve")
            value = Service(repo, correlation).begin_github_authorization(
                identifier, body
            )
            status = 200
        elif complete_github_authorization:
            access.require("cluster.approve")
            value = Service(repo, correlation).complete_github_authorization(
                identifier, body
            )
            status = 200
        elif node_group_action:
            value = Service(repo, correlation).change_node_group_request(
                identifier, parts[2], parts[3], body
            )
            status = 202 if parts[3] in {"approve", "apply"} else 200
        else:
            service = Service(repo, correlation)
            value = service.create(body) if not identifier else service.change(identifier, action or "update", body)
            status = 201 if not identifier else 202 if action in {
            "approve", "plan", "apply", "stop", "start", "delete"
            } else 200
        customer_repo.idempotency_put(operation, key, fingerprint, {"status": status, "body": value})
        return response(status, value, correlation)


def lambda_handler(event, context):
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    correlation = headers.get("x-correlation-id") or str(uuid.uuid4())
    try:
        return execute(event, Principal.from_event(event), correlation)
    except ApiError as error:
        return response(error.status, error.payload(correlation), correlation)
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
                    for item in validation_error.errors(include_url=False)
                ]
            },
        )
        return response(error.status, error.payload(correlation), correlation)
    except (ValueError, json.JSONDecodeError, UnicodeError):
        error = ApiError(400, "VALIDATION_ERROR", "Check the request fields.")
        return response(error.status, error.payload(correlation), correlation)
    except Exception as error:
        logger.error(json.dumps({
            "correlationId": correlation,
            "errorType": type(error).__name__,
            "sqlState": getattr(error, "sqlstate", None),
            "locations": [
                {
                    "file": frame.filename.rsplit("/", 1)[-1],
                    "line": frame.lineno,
                    "function": frame.name,
                }
                for frame in traceback.extract_tb(error.__traceback__)
            ][-8:],
        }))
        error = ApiError(500, "INTERNAL_ERROR", "An unexpected error occurred.")
        return response(error.status, error.payload(correlation), correlation)
