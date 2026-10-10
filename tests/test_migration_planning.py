"""Planning must never grant execution authority or resolve assessment findings."""

import copy
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from navigan.modules.migration_management.models import UpdateMigration
from navigan.modules.migration_management.repository import Repository as SqlRepository, serialize
from navigan.modules.migration_management.service import Service
from navigan.shared.errors import ApiError
from test_migration_service import Access, Repository, create_body


def draft():
    return {
        "mode": "SELECTED_WORKLOADS",
        "assessmentVersion": 2,
        "inventoryDigest": "a" * 64,
        "resources": [
            {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "namespace": "retailflow",
                "name": "retailflow-api",
                "treatment": "MIGRATE",
                "dependency": False,
            }
        ],
        "remediations": [
            {
                "findingIndex": 0,
                "owner": "App owner",
                "targetMapping": "EBS CSI",
                "evidenceReference": "artifact:restore-test",
                "status": "EVIDENCE_ATTACHED",
            }
        ],
    }


def setup_planning(status="APPROVED"):
    repo = Repository()
    service = Service(repo, Access("creator", {"migration.create", "migration.edit"}), "corr-plan")
    created = service.create(create_body())
    identifier = created["migrationId"]
    repo.rows[identifier]["status"] = status
    repo.get_assessment = MagicMock(
        return_value={
            "assessment": {
                "assessmentVersion": 2,
                "migrationVersion": 1,
                "inventoryDigest": "a" * 64,
                "findings": [{"severity": "BLOCKER", "message": "Storage mapping required"}],
            }
        }
    )
    repo.get_source_inventory = MagicMock(
        return_value={
            "inventory": {
                "inventoryDigest": "a" * 64,
                "resources": draft()["resources"],
            }
        }
    )
    repo.require_planning_configuration = MagicMock()
    body = UpdateMigration.model_validate(
        {"version": 1, "planningDraft": draft(), "changeReason": "Plan application migration"}
    ).model_dump(mode="json", exclude_none=True)
    return repo, service, identifier, body


def test_planning_persists_without_changing_assessment_scope_or_approval():
    repo, service, identifier, body = setup_planning()
    original = copy.deepcopy(repo.rows[identifier])
    report = copy.deepcopy(repo.get_assessment.return_value)
    result = service.update(identifier, body)
    assert result["planningDraft"]["resources"][0]["name"] == "retailflow-api"
    assert result["planningDraft"]["remediations"][0]["status"] == "EVIDENCE_ATTACHED"
    assert result["version"] == 2
    for column in (
        "status",
        "migration_scope",
        "source_configuration",
        "target_configuration",
        "execution_mode",
    ):
        assert repo.rows[identifier][column] == original[column]
    assert result["executionMode"] == "ASSESSMENT_ONLY"
    assert repo.get_assessment.return_value == report
    assert repo.saved[-1] == ("MIGRATION_PLANNING_UPDATED", "corr-plan", False)


@pytest.mark.parametrize(
    "edit,code",
    [
        (lambda b: b.update(version=99), "CONCURRENT_UPDATE"),
        (lambda b: b.update(name="Changed request"), "PLANNING_UPDATE_ONLY"),
        (lambda b: b["planningDraft"].update(assessmentVersion=1), "PLANNING_EVIDENCE_CHANGED"),
        (lambda b: b["planningDraft"].update(inventoryDigest="b" * 64), "PLANNING_EVIDENCE_CHANGED"),
        (
            lambda b: b["planningDraft"]["resources"][0].update(namespace="another-customer"),
            "RESOURCE_OUTSIDE_INVENTORY",
        ),
        (lambda b: b["planningDraft"]["remediations"][0].update(findingIndex=5), "FINDING_NOT_FOUND"),
    ],
)
def test_rejects_unsafe_planning_updates(edit, code):
    repo, service, identifier, body = setup_planning()
    edit(body)
    with pytest.raises(ApiError) as error:
        service.update(identifier, body)
    assert error.value.code == code
    assert repo.rows[identifier]["version"] == 1


@pytest.mark.parametrize("status", ["DRAFT", "DISCOVERING", "ASSESSING", "CANCELLED"])
def test_planning_requires_completed_assessment(status):
    _, service, identifier, body = setup_planning(status)
    with pytest.raises(ApiError) as error:
        service.update(identifier, body)
    assert error.value.code == "ASSESSMENT_REQUIRED"


def test_planning_still_requires_edit_permission_and_customer_access():
    repo, _, identifier, body = setup_planning()
    with pytest.raises(ApiError) as error:
        Service(repo, Access("creator", set()), "corr").update(identifier, body)
    assert error.value.status == 403
    repo.rows[identifier]["customer_id"] = "CUS-other"
    with pytest.raises(ApiError) as error:
        Service(repo, Access("creator", {"migration.edit"}), "corr").update(identifier, body)
    assert error.value.status == 403


@pytest.mark.parametrize(
    "field,value", [("status", "VERIFIED"), ("status", "RESOLVED"), ("treatment", "EXECUTE")]
)
def test_planning_cannot_self_verify(field, value):
    value_draft = draft()
    value_draft["remediations"][0][field] = value
    with pytest.raises(ValidationError):
        UpdateMigration.model_validate(
            {"version": 1, "planningDraft": value_draft, "changeReason": "Update draft"}
        )


def test_evidence_status_requires_reference_and_duplicate_entries_are_rejected():
    value = draft()
    value["remediations"][0]["evidenceReference"] = ""
    with pytest.raises(ValidationError, match="evidence reference"):
        UpdateMigration.model_validate({"version": 1, "planningDraft": value, "changeReason": "Update draft"})
    value = draft()
    value["resources"].append(value["resources"][0])
    with pytest.raises(ValidationError, match="unique"):
        UpdateMigration.model_validate({"version": 1, "planningDraft": value, "changeReason": "Update draft"})


def test_rejects_migrating_source_nodes():
    repo, service, identifier, body = setup_planning()
    node = {
        "apiVersion": "v1",
        "kind": "Node",
        "name": "source-node",
        "treatment": "MIGRATE",
        "dependency": False,
    }
    body["planningDraft"]["resources"] = [node]
    repo.get_source_inventory.return_value["inventory"]["resources"] = [node]
    with pytest.raises(ApiError) as error:
        service.update(identifier, body)
    assert error.value.code == "SOURCE_NODE_NOT_PORTABLE"


def test_configuration_comparison_rejects_stale_target_even_with_matching_inventory():
    db = MagicMock()
    repo = SqlRepository(db, MagicMock())
    current = {
        "source_configuration": {"sourceClusterId": "SRC-demo"},
        "target_configuration": {"clusterId": "CLU-target"},
        "migration_scope": {"namespaces": ["retailflow"]},
    }
    db.execute.return_value.fetchone.return_value = {"snapshot": serialize(current)}
    repo.require_planning_configuration("MIG-demo", 3, current)
    current["target_configuration"] = {"clusterId": "CLU-different"}
    with pytest.raises(ApiError) as error:
        repo.require_planning_configuration("MIG-demo", 3, current)
    assert error.value.code == "PLANNING_REASSESSMENT_REQUIRED"
