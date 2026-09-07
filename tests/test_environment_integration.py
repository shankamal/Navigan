"""Real PostgreSQL + Lambda tests; no repository mocks or cloud provisioning."""

import json
import os
import uuid
from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
import pytest
import psycopg
from navigan.modules.environment_management.handler import lambda_handler
from test_environment import example
from test_integration import create_customer, act

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="Requires migrated disposable PostgreSQL"),
]


def call(
    method, path="", body=None, role="CLOUD_ENGINEER", actor="maker", platform=True, key=None, query=None
):
    event = {
        "rawPath": "/v1/api/v1/environments" + path,
        "headers": {"Content-Type": "application/json", "Idempotency-Key": key or str(uuid.uuid4())},
        "body": json.dumps(body or {}),
        "queryStringParameters": query,
        "requestContext": {
            "stage": "v1",
            "http": {"method": method},
            "authorizer": {
                "jwt": {
                    "claims": {
                        "sub": actor,
                        "roles": json.dumps([role]),
                        "customer_ids": "[]",
                        "platform_scope": str(platform).lower(),
                        "customer_create": "true",
                    }
                }
            },
        },
    }
    result = lambda_handler(event, SimpleNamespace(aws_request_id="environment-integration"))
    return result["statusCode"], json.loads(result["body"]), result["headers"]


def parent(provider):
    customer = create_customer(body={"cloudProviders": [provider]})
    for action in ["submit", "review/start", "approve", "activate"]:
        customer = act(customer, action)
    return customer


def create(provider="AWS", dist="EKS", configuration=None):
    customer = parent(provider)
    body = {
        "customerId": customer["customerId"],
        "cloudProvider": provider,
        "kubernetesDistribution": dist,
        "environmentName": "Prod-" + uuid.uuid4().hex,
        "environmentType": "PROD",
        "configuration": configuration or {},
    }
    status, row, _ = call("POST", body=body)
    assert status == 201, row
    return row, body


@pytest.mark.parametrize("provider,dist", [("AWS", "EKS"), ("AZURE", "AKS"), ("GCP", "GKE"), ("OCI", "OKE")])
def test_full_lifecycle_and_approved_version(provider, dist):
    row, _ = create(provider, dist, example(dist))
    identifier = row["environmentId"]
    for action in [
        "submit",
        "review",
        "reject",
        "resubmit",
        "review",
        "approve",
        "activate",
        "suspend",
        "reactivate",
        "deactivate",
    ]:
        role = "CLOUD_ENGINEER" if action in {"submit", "resubmit"} else "PLATFORM_ARCHITECT"
        status, row, _ = call(
            "POST",
            f"/{identifier}/{action}",
            {"version": row["version"], "reason": "Integration review", "comments": "Checked"},
            role=role,
        )
        assert status == 200, row
    assert row["status"] == "DEACTIVATED"
    status, approved, _ = call("GET", f"/{identifier}/versions/{row['approvedVersion']}")
    assert status == 200 and approved["status"] == "APPROVED"
    assert approved["configuration"] == example(dist)
    status, history, _ = call("GET", f"/{identifier}/status-history")
    assert status == 200 and history["pagination"]["totalElements"] == 11
    assert call("PUT", "/" + identifier, {"version": row["version"], "description": "blocked"})[0] == 409


def test_draft_rejection_scope_idempotency_and_conflict():
    row, body = create()
    identifier = row["environmentId"]
    assert call("POST", f"/{identifier}/submit", {"version": 1})[0] == 422
    assert call("GET", "/" + identifier, platform=False, actor="outsider")[0] == 404
    assert call("GET", f"/{identifier}/versions", platform=False, actor="outsider")[0] == 404
    assert call("GET", f"/{identifier}/audit-log")[0] == 403
    key = str(uuid.uuid4())
    body["environmentName"] = "Unique-" + key
    first = call("POST", body=body, key=key)
    retry = call("POST", body=body, key=key)
    assert first[0] == retry[0] == 201 and first[1] == retry[1]
    assert retry[2]["Idempotency-Replayed"] == "true"
    assert call("POST", body={**body, "description": "different"}, key=key)[0] == 409
    assert call("POST", body={**body, "environmentName": body["environmentName"].upper()})[0] == 409
    assert call("PUT", "/" + identifier, {"version": 99, "description": "stale"})[0] == 409


def test_concurrent_update_single_winner():
    row, _ = create()
    identifier = row["environmentId"]

    def update(i):
        return call("PUT", "/" + identifier, {"version": 1, "description": str(i)})[0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update, [1, 2]))
    assert sorted(results) == [200, 409]


def test_history_immutability_restricted_role_and_provider_dependency():
    row, _ = create()
    identifier = row["environmentId"]
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as db:
        db.execute(Path("database/bootstrap/roles.sql").read_text())
        with pytest.raises(psycopg.Error):
            db.execute(
                "DELETE FROM environment_management.environment_versions WHERE environment_id=%s",
                [identifier],
            )
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            db.execute(
                "DELETE FROM customer_management.customer_cloud_providers WHERE customer_id=%s",
                [row["customerId"]],
            )
        db.execute("SET ROLE navigan_api")
        assert db.execute(
            "SELECT environment_id FROM environment_management.environments WHERE environment_id=%s",
            [identifier],
        ).fetchone()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute(
                "DELETE FROM environment_management.environments WHERE environment_id=%s", [identifier]
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute("UPDATE environment_management.environment_audit_log SET action=action")


def test_filters_versions_and_patch():
    row, _ = create("GCP", "GKE", example("GKE"))
    identifier = row["environmentId"]
    status, rows, _ = call(
        "GET", query={"customerId": row["customerId"], "cloudProvider": "GCP", "page": "0", "pageSize": "1"}
    )
    assert status == 200 and rows["items"][0]["environmentId"] == identifier
    assert (
        call("GET", query={"customerId": row["customerId"]}, platform=False, actor="outsider")[1]["items"]
        == []
    )
    assert call("GET", f"/{identifier}/versions/1")[1]["customerName"]
    assert (
        call("PATCH", f"/{identifier}/status", {"status": "ACTIVE", "version": 1}, role="PLATFORM_ARCHITECT")[
            0
        ]
        == 409
    )
