"""Runs the real Lambda entry point and real PostgreSQL, without repository mocks."""

import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
import pytest
import psycopg
from navigan.modules.customer_management.handler import lambda_handler

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("DATABASE_URL"), reason="Set DATABASE_URL to a migrated disposable PostgreSQL database"
    ),
]


def request(
    method,
    path="",
    body=None,
    actor="maker",
    role="CLOUD_ENGINEER",
    version=None,
    key=None,
    customer_ids=None,
    platform=False,
    create=True,
    query=None,
):
    headers = {"Content-Type": "application/json"}
    if version is not None:
        headers["If-Match"] = str(version)
    if key:
        headers["Idempotency-Key"] = key
    event = {
        "version": "2.0",
        "rawPath": "/api/v1/customers" + path,
        "headers": headers,
        "body": json.dumps(body or {}),
        "queryStringParameters": query,
        "requestContext": {
            "http": {"method": method},
            "authorizer": {
                "jwt": {
                    "claims": {
                        "sub": actor,
                        "roles": [role],
                        "customer_ids": customer_ids or [],
                        "platform_scope": str(platform).lower(),
                        "customer_create": str(create).lower(),
                    }
                }
            },
        },
    }
    result = lambda_handler(event, SimpleNamespace(aws_request_id="integration"))
    return result["statusCode"], json.loads(result["body"]), result["headers"]


def create_customer(**kwargs):
    body = {
        "name": "Customer " + uuid.uuid4().hex,
        "cloudProviders": ["OCI"],
        "contacts": [{"type": "PRIMARY", "name": "Demo Contact", "email": "demo@example.com"}],
    }
    body.update(kwargs.pop("body", {}))
    status, customer, _ = request("POST", body=body, **kwargs)
    assert status == 201, customer
    return customer


def act(customer, action, **body):
    engineer = action in {"submit", "resubmit"}
    status, value, _ = request(
        "POST",
        "/" + customer["customerId"] + "/" + action,
        body=body,
        actor="maker" if engineer else "architect",
        role="CLOUD_ENGINEER" if engineer else "PLATFORM_ARCHITECT",
        platform=not engineer,
        version=customer["version"],
    )
    assert status == 200, value
    return value


def test_complete_onboarding_and_terminal_state():
    customer = create_customer(body={"cloudProviders": ["AWS", "AZURE"]})
    cid = customer["customerId"]
    status, customer, _ = request(
        "PUT", f"/{cid}/cloud-providers", {"cloudProviders": ["AWS", "AZURE", "OCI"]}, version=1
    )
    assert status == 200
    for action in ["submit", "review/start", "approve", "activate", "suspend", "reactivate", "deactivate"]:
        customer = act(customer, action, reason="Integration test")
    assert customer["status"] == "DEACTIVATED"
    status, history, _ = request("GET", f"/{cid}/status-history")
    assert status == 200 and history["pagination"]["totalElements"] == 8
    assert history["history"][0]["fromStatus"] is None
    status, _, _ = request(
        "POST",
        f"/{cid}/reactivate",
        role="PLATFORM_ARCHITECT",
        actor="architect",
        platform=True,
        version=customer["version"],
    )
    assert status == 422
    with psycopg.connect(os.environ["DATABASE_URL"]) as db:
        assert (
            db.execute("SELECT count(*) FROM platform.event_outbox WHERE customer_id=%s", [cid]).fetchone()[0]
            == 9
        )


def test_rejection_correction_preserves_reviews():
    customer = act(act(create_customer(), "submit"), "review/start")
    cid = customer["customerId"]
    status, _, _ = request(
        "PUT", f"/{cid}/cloud-providers", {"cloudProviders": ["AWS"]}, version=customer["version"]
    )
    assert status == 422
    customer = act(customer, "reject", reason="Select correct providers", comments="Please confirm OCI")
    status, customer, _ = request(
        "PUT", f"/{cid}/cloud-providers", {"cloudProviders": ["OCI", "AWS"]}, version=customer["version"]
    )
    assert status == 200
    customer = act(act(act(customer, "resubmit"), "review/start"), "approve")
    assert customer["reviewCycle"] == 2
    status, reviews, _ = request("GET", f"/{cid}/reviews")
    assert status == 200 and len(reviews["items"]) == 4
    assert any(r["rejectionReason"] == "Select correct providers" for r in reviews["items"])


def test_customer_scope_all_routes_and_listing():
    customer = create_customer()
    cid = customer["customerId"]
    for suffix in ["", "/cloud-providers", "/status-history", "/audit-log", "/reviews"]:
        status, _, _ = request("GET", f"/{cid}{suffix}", actor="outsider", create=False)
        assert status == 404
    status, result, _ = request("GET", actor="outsider", create=False, query={"search": cid})
    assert status == 200 and not result["items"]
    status, _, _ = request(
        "PUT", f"/{cid}", body={"name": "No access"}, actor="outsider", create=False, version=1
    )
    assert status == 404
    status, _, _ = request("GET", f"/{cid}", actor="scoped", role="SERVICE", customer_ids=[cid], create=False)
    assert status == 200
    status, _, _ = request("POST", body={"name": "Denied"}, actor="scoped", role="SERVICE")
    assert status == 403
    status, _, _ = request("GET", f"/{cid}/audit-log")
    assert status == 403


def test_idempotent_create_conflict_and_authorization():
    key = uuid.uuid4().hex
    body = {"name": "Idempotent " + uuid.uuid4().hex, "cloudProviders": ["OCI"]}
    first = request("POST", body=body, key=key)
    replay = request("POST", body=body, key=key)
    assert first[0] == replay[0] == 201 and first[1] == replay[1]
    assert replay[2]["Idempotency-Replayed"] == "true"
    assert request("POST", body={**body, "name": "different"}, key=key)[0] == 409
    assert request("POST", body=body, key=key, create=False)[0] == 403


def test_action_idempotency_stale_version_and_no_duplicate_history():
    customer = create_customer()
    cid = customer["customerId"]
    key = uuid.uuid4().hex
    first = request("POST", f"/{cid}/submit", version=1, key=key)
    assert first[0] == 200
    assert request("POST", f"/{cid}/submit", version=1, key=key)[1] == first[1]
    assert request("POST", f"/{cid}/submit", version=2, key=key)[0] == 409
    assert request("GET", f"/{cid}/status-history")[1]["pagination"]["totalElements"] == 2
    status, _, _ = request(
        "POST", f"/{cid}/review/start", version=1, actor="architect", role="PLATFORM_ARCHITECT", platform=True
    )
    assert status == 409


def test_atomic_provider_replacement_and_validation():
    customer = create_customer()
    cid = customer["customerId"]
    status, _, _ = request("PUT", f"/{cid}/cloud-providers", {"cloudProviders": ["AWS", "BOGUS"]}, version=1)
    assert status == 422
    assert request("GET", f"/{cid}/cloud-providers")[1]["cloudProviders"] == ["OCI"]
    assert request("GET", f"/{cid}")[1]["version"] == 1
    assert request("PUT", f"/{cid}", {"name": "Updated"}, version=7)[0] == 409
    assert request("PUT", f"/{cid}", {"name": "Updated"})[0] == 400


def test_draft_submission_and_duplicate_name():
    customer = create_customer(body={"contacts": [], "cloudProviders": []})
    assert request("POST", f"/{customer['customerId']}/submit", version=1)[0] == 422
    assert request("POST", body={"name": " " + customer["name"].upper() + " "})[0] == 409


def test_concurrent_updates_one_winner():
    customer = create_customer()
    cid = customer["customerId"]

    def update(i):
        return request("PUT", f"/{cid}", {"name": "Concurrent " + uuid.uuid4().hex}, version=1)[0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update, range(2)))
    assert sorted(results) == [200, 409]
    assert request("GET", f"/{cid}")[1]["version"] == 2


def test_concurrent_idempotency_one_customer():
    body = {"name": "Concurrent create " + uuid.uuid4().hex}
    key = uuid.uuid4().hex
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: request("POST", body=body, key=key), range(2)))
    assert [r[0] for r in results] == [201, 201]
    assert results[0][1]["customerId"] == results[1][1]["customerId"]


def test_audit_immutability_and_redaction():
    customer = create_customer()
    cid = customer["customerId"]
    status, log, _ = request(
        "GET", f"/{cid}/audit-log", actor="architect", role="PLATFORM_ARCHITECT", platform=True
    )
    assert status == 200 and "demo@example.com" not in json.dumps(log)
    with psycopg.connect(os.environ["DATABASE_URL"]) as db:
        with pytest.raises(psycopg.errors.RaiseException):
            db.execute(
                "UPDATE customer_management.customer_audit_log SET action='TAMPER' WHERE customer_id=%s",
                [cid],
            )
        db.rollback()


def test_search_provider_filter_and_stable_pagination():
    customer = create_customer(body={"cloudProviders": ["AWS", "OCI"]})
    status, result, _ = request(
        "GET",
        query={
            "search": customer["customerId"],
            "cloudProvider": "AWS",
            "status": "DRAFT",
            "pageSize": "1",
            "sort": "name,asc",
        },
    )
    assert status == 200 and result["pagination"]["totalElements"] == 1
    assert result["items"][0]["customerId"] == customer["customerId"]


def test_runtime_database_roles():
    with psycopg.connect(os.environ["DATABASE_URL"]) as db:
        db.execute((Path(__file__).resolve().parents[1] / "database/bootstrap/roles.sql").read_text())
        db.commit()
        db.execute("SET ROLE navigan_api")
        assert db.execute("SELECT count(*) FROM customer_management.customers").fetchone()[0] >= 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute("DELETE FROM customer_management.customers")
        db.rollback()
        db.execute("SET ROLE navigan_events")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute("SELECT * FROM customer_management.customer_contacts")
        db.rollback()


def test_dependency_veto_rolls_back():
    from navigan.modules.customer_management.repository import Repository
    from navigan.modules.customer_management.service import CustomerService
    from navigan.shared.auth import Principal
    from navigan.shared.database import transaction
    from navigan.shared.errors import ApiError

    customer = create_customer()
    cid = customer["customerId"]

    class Dependencies:
        def has_dependencies(self, customer_id, provider):
            return provider == "OCI"

    principal = Principal("maker", frozenset({"CLOUD_ENGINEER"}), frozenset(), False, True)
    with pytest.raises(ApiError) as error:
        with transaction() as db:
            service = CustomerService(Repository(db, principal), "veto", Dependencies())
            service.update(cid, {"cloudProviders": ["AWS"]}, 1, providers=True)
    assert error.value.code == "PROVIDER_HAS_DEPENDENCIES"
    assert request("GET", f"/{cid}/cloud-providers")[1]["cloudProviders"] == ["OCI"]
    assert request("GET", f"/{cid}")[1]["version"] == 1


def test_runtime_role_full_write_path(monkeypatch):
    from navigan.shared import database
    from psycopg.rows import dict_row

    with psycopg.connect(os.environ["DATABASE_URL"]) as db:
        db.execute((Path(__file__).resolve().parents[1] / "database/bootstrap/roles.sql").read_text())

    def restricted_connect(secret_env="DB_SECRET_ARN"):
        db = psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)
        db.execute("SET ROLE navigan_api")
        return db

    monkeypatch.setattr(database, "connect", restricted_connect)
    customer = create_customer(key=uuid.uuid4().hex)
    cid = customer["customerId"]
    status, customer, _ = request(
        "PUT",
        f"/{cid}",
        {"name": "Restricted " + uuid.uuid4().hex, "contacts": [{"type": "PRIMARY", "name": "Primary"}]},
        version=customer["version"],
    )
    assert status == 200
    for action in ["submit", "review/start", "approve", "activate"]:
        customer = act(customer, action)
    assert customer["status"] == "ACTIVE"


def test_inactive_provider_cannot_be_submitted():
    code = "TEST_" + uuid.uuid4().hex.upper()
    with psycopg.connect(os.environ["DATABASE_URL"]) as db:
        db.execute(
            "INSERT INTO customer_management.cloud_providers(provider_code,provider_name) VALUES (%s,%s)",
            [code, "Configured future provider"],
        )
    customer = create_customer(body={"cloudProviders": [code]})
    with psycopg.connect(os.environ["DATABASE_URL"]) as db:
        db.execute(
            "UPDATE customer_management.cloud_providers SET active=false WHERE provider_code=%s", [code]
        )
    assert request("POST", f"/{customer['customerId']}/submit", version=1)[0] == 422


def test_outbox_partial_failure_and_publisher_role(monkeypatch):
    import boto3
    from navigan.shared import outbox, database
    from psycopg.rows import dict_row

    with psycopg.connect(os.environ["DATABASE_URL"]) as db:
        db.execute((Path(__file__).resolve().parents[1] / "database/bootstrap/roles.sql").read_text())
        # Disposable test DB only; isolate worker assertions from prior test events.
        db.execute("UPDATE platform.event_outbox SET published_at=now() WHERE published_at IS NULL")
    create_customer()
    create_customer()

    def restricted_connect(secret_env="DB_SECRET_ARN"):
        db = psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)
        db.execute("SET ROLE navigan_events")
        return db

    monkeypatch.setattr(database, "connect", restricted_connect)

    class Events:
        def put_events(self, Entries):
            assert len(Entries) == 2
            assert all("contacts" not in json.loads(e["Detail"]) for e in Entries)
            return {"Entries": [{"EventId": "ok"}, {"ErrorCode": "InternalFailure"}], "FailedEntryCount": 1}

    def events_client(service, *, config):
        assert service == "events"
        assert config.connect_timeout == config.read_timeout == 3
        assert config.retries["total_max_attempts"] == 1
        return Events()

    monkeypatch.setattr(boto3, "client", events_client)
    monkeypatch.setenv("EVENT_BUS_NAME", "test")
    assert outbox.lambda_handler({}, None) == {"published": 1, "failed": 1}
    with psycopg.connect(os.environ["DATABASE_URL"]) as db:
        assert (
            db.execute(
                "SELECT count(*) FROM platform.event_outbox WHERE published_at IS NULL AND last_error='InternalFailure'"
            ).fetchone()[0]
            == 1
        )
