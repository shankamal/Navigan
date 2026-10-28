from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from navigan.modules.migration_management.models import CancelMigration, MigrationAction
from navigan.modules.migration_management.repository import Repository
from navigan.modules.migration_management.service import Service
from navigan.shared.errors import ApiError

STATUSES = [
    "DRAFT",
    "SOURCE_ENROLLMENT_PENDING",
    "INVENTORY_DISCOVERING",
    "INVENTORY_READY",
    "DISCOVERY_PENDING",
    "DISCOVERING",
    "ASSESSING",
    "ASSESSMENT_READY",
    "SUBMITTED",
    "UNDER_REVIEW",
    "APPROVED",
    "REJECTED",
    "FAILED",
    "CANCELLED",
]


def setup(status="DRAFT"):
    repo = MagicMock()
    repo.principal = SimpleNamespace(user_id="engineer")
    repo.get.return_value = {
        "migration_id": "MIG-example",
        "customer_id": "CUS-db",
        "created_by": "owner",
        "name": "Example assessment",
        "status": status,
        "version": 3,
        "source_configuration": {"sourceClusterId": "SRC-shared"},
    }
    access = MagicMock()
    return Service(repo, access, "delete-test"), repo, access


def delete_body(**changes):
    return {"version": 3, "reason": "Delete assessment", "deleteAssessment": True, **changes}


@pytest.mark.parametrize("status", STATUSES)
def test_delete_cancels_any_assessment_status_and_preserves_source_registration(status):
    service, repo, access = setup(status)
    result = service.change("MIG-example", "cancel", delete_body())
    assert result["status"] == "CANCELLED"
    assert result["version"] == 4
    access.require.assert_called_once_with("migration.edit")
    access.require_customer.assert_called_once_with("CUS-db", "owner")
    row, old, action, correlation = repo.save.call_args.args
    assert action == "MIGRATION_DELETED"
    assert old["status"] == status
    assert row["source_configuration"] == {"sourceClusterId": "SRC-shared"}
    repo.create_source_cluster.assert_not_called()
    repo.audit_source_cluster.assert_not_called()


@pytest.mark.parametrize("boundary", ["privilege", "customer", "version"])
def test_delete_checks_authority_and_latest_version(boundary):
    service, repo, access = setup("APPROVED")
    if boundary == "privilege":
        access.require.side_effect = ApiError(403, "FORBIDDEN", "Not permitted")
    elif boundary == "customer":
        access.require_customer.side_effect = ApiError(403, "FORBIDDEN", "Outside customer scope")
    else:
        repo.get.return_value["version"] = 4
    with pytest.raises(ApiError):
        service.change("MIG-example", "cancel", delete_body())
    repo.save.assert_not_called()


def test_normal_cancel_and_archive_remains_distinct_from_delete():
    service, repo, _ = setup()
    service.change("MIG-example", "cancel", {"version": 3, "reason": "Archive assessment"})
    assert repo.save.call_args.args[2] == "MIGRATION_CANCEL"


def test_delete_flag_is_strict_and_supported_only_on_cancellation():
    assert CancelMigration.model_validate(delete_body()).deleteAssessment is True
    with pytest.raises(ValidationError):
        CancelMigration.model_validate(delete_body(deleteAssessment="true"))
    with pytest.raises(ValidationError):
        MigrationAction.model_validate(delete_body())


def test_deleted_assessments_are_excluded_from_list_count_and_direct_get():
    db = MagicMock()
    principal = SimpleNamespace(user_id="engineer", platform_scope=True, customer_ids=())
    repo = Repository(db, principal)
    db.execute.return_value.fetchone.return_value = {"n": 0}
    db.execute.return_value.fetchall.return_value = []
    result = repo.list({"page": 0, "pageSize": 20, "status": "CANCELLED"})
    assert result["items"] == []
    assert result["pagination"]["totalElements"] == 0
    for call in db.execute.call_args_list:
        assert "NOT EXISTS" in call.args[0]
        assert "deleted.action='MIGRATION_DELETED'" in call.args[0]
    db.execute.reset_mock()
    db.execute.return_value.fetchone.return_value = None
    with pytest.raises(ApiError) as error:
        repo.get("MIG-example")
    assert error.value.code == "MIGRATION_NOT_FOUND"
    assert "deleted.action='MIGRATION_DELETED'" in db.execute.call_args.args[0]


def test_delete_retry_replays_success_with_current_permissions(monkeypatch):
    import json
    from contextlib import nullcontext
    from navigan.modules.migration_management import handler

    identifier = "MIG-" + "a" * 32
    service, repo, access = setup()
    customer_repo = MagicMock()
    customer_repo.idempotency_get.return_value = {
        "status": 200,
        "body": {"migrationId": identifier, "status": "CANCELLED", "version": 4},
    }
    monkeypatch.setattr(handler, "transaction", lambda: nullcontext(object()))
    monkeypatch.setattr(handler, "Repository", lambda *_: repo)
    monkeypatch.setattr(handler, "CustomerRepository", lambda *_: customer_repo)
    monkeypatch.setattr(handler, "AccessRepository", MagicMock())
    evaluator = MagicMock()
    evaluator.evaluate.return_value = access
    monkeypatch.setattr(handler, "AccessEvaluator", lambda *_: evaluator)
    result = handler.execute(
        {
            "rawPath": f"/api/v1/migrations/{identifier}/cancel",
            "requestContext": {"http": {"method": "POST"}},
            "headers": {"content-type": "application/json", "idempotency-key": "delete-retry"},
            "body": json.dumps(delete_body()),
        },
        repo.principal,
        "retry-test",
    )
    assert result["statusCode"] == 200
    assert result["headers"]["Idempotency-Replayed"] == "true"
    repo.get.assert_called_once_with(identifier, include_deleted=True)
    access.require.assert_called_once_with("migration.edit")
    access.require_customer.assert_called_once_with("CUS-db", "owner")
    repo.save.assert_not_called()
