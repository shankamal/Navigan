"""Planning round-trip through the real Lambda and disposable PostgreSQL."""

import json
import os
import uuid
from types import SimpleNamespace

import psycopg
import pytest

from navigan.modules.migration_management.handler import lambda_handler
from test_integration import create_customer
from test_migration_service import create_body
from test_migration_planning import draft

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="Requires migrated disposable PostgreSQL"),
]


def call(method, path, body=None, version=None, key=None):
    headers = {"Content-Type": "application/json", "Idempotency-Key": key or str(uuid.uuid4())}
    if version:
        headers["If-Match"] = str(version)
    event = {
        "rawPath": "/api/v1/migrations" + path,
        "headers": headers,
        "body": json.dumps(body or {}),
        "requestContext": {
            "http": {"method": method},
            "authorizer": {
                "jwt": {
                    "claims": {
                        "sub": "maker",
                        "roles": ["CLOUD_ENGINEER"],
                        "customer_ids": [],
                        "platform_scope": "true",
                        "customer_create": "true",
                    }
                }
            },
        },
    }
    result = lambda_handler(event, SimpleNamespace(aws_request_id="planning-test"))
    return result["statusCode"], json.loads(result["body"])


def test_planning_persistence_audit_concurrency_and_idempotency():
    customer = create_customer()
    body = create_body()
    body.update(customerId=customer["customerId"], name="Planning " + uuid.uuid4().hex)
    status, migration = call("POST", "", body)
    assert status == 201, migration
    identifier = migration["migrationId"]
    with psycopg.connect(os.environ["DATABASE_URL"]) as db:
        db.execute(
            "UPDATE migration_management.migrations SET status='ASSESSMENT_READY' WHERE migration_id=%s",
            [identifier],
        )
        db.execute(
            "INSERT INTO migration_management.migration_source_inventories("
            "migration_id,inventory_version,migration_version,schema_version,observed_at,"
            "source_kubernetes_version,inventory_digest,resource_count,resources,created_by) "
            "VALUES(%s,1,1,1,now(),'v1.35.0',%s,1,%s::jsonb,'test')",
            [identifier, "a" * 64, json.dumps(draft()["resources"])],
        )
        db.execute(
            "INSERT INTO migration_management.migration_assessments("
            "migration_id,assessment_version,migration_version,report_schema_version,source_kubernetes_version,"
            "observed_at,inventory_digest,compatibility_score,contains_blockers,inventory_summary,findings,created_by) "
            "VALUES(%s,2,1,1,'v1.35.0',now(),%s,75,true,'{}',%s::jsonb,'test')",
            [
                identifier,
                "a" * 64,
                json.dumps([{"severity": "BLOCKER", "message": "Storage mapping required"}]),
            ],
        )
    key = str(uuid.uuid4())
    update = {"version": 1, "planningDraft": draft(), "changeReason": "Plan workload migration"}
    status, saved = call("PUT", "/" + identifier, update, 1, key)
    assert status == 200, saved
    assert saved["version"] == 2
    status, replay = call("PUT", "/" + identifier, update, 1, key)
    assert status == 200 and replay == saved
    status, stale = call("PUT", "/" + identifier, update, 1)
    assert status == 409 and stale["error"]["code"] == "CONCURRENT_UPDATE"
    status, loaded = call("GET", "/" + identifier)
    assert status == 200 and loaded["planningDraft"] == saved["planningDraft"]
    assert loaded["status"] == "ASSESSMENT_READY" and loaded["executionMode"] == "ASSESSMENT_ONLY"
    with psycopg.connect(os.environ["DATABASE_URL"]) as db:
        assert (
            db.execute(
                "SELECT count(*) FROM migration_management.migration_audit_log WHERE migration_id=%s AND action='MIGRATION_PLANNING_UPDATED'",
                [identifier],
            ).fetchone()[0]
            == 1
        )
        assert (
            db.execute(
                "SELECT snapshot->'planningDraft' FROM migration_management.migration_versions WHERE migration_id=%s AND version=2",
                [identifier],
            ).fetchone()[0]
            == saved["planningDraft"]
        )
