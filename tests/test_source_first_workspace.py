import copy
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from navigan.modules.migration_management.models import MigrationPlanningDraft
from navigan.modules.migration_management.repository import Repository, serialize
from navigan.modules.migration_management.service import Service
from navigan.shared.errors import ApiError


def draft():
    return {
        "workflow": "SOURCE_FIRST",
        "mode": "SELECTED_WORKLOADS",
        "assessmentVersion": 1,
        "inventoryDigest": "a" * 64,
        "resources": [
            {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "namespace": "payments",
                "name": "api",
                "treatment": "MIGRATE",
                "dependency": False,
            }
        ],
        "deploymentSources": [
            {
                "workload": {
                    "apiVersion": "apps/v1",
                    "kind": "Deployment",
                    "namespace": "payments",
                    "name": "api",
                },
                "method": "HELM",
                "bundleName": "payments",
                "reference": "repo/charts/payments",
                "releaseName": "payments",
            }
        ],
    }


def test_deployment_sources_are_saved_only_for_selected_workloads():
    parsed = MigrationPlanningDraft.model_validate(draft())
    assert parsed.deploymentSources[0].method == "HELM"
    invalid = draft()
    invalid["deploymentSources"][0]["workload"]["name"] = "unselected-worker"
    with pytest.raises(ValidationError, match="selected workloads"):
        MigrationPlanningDraft.model_validate(invalid)
    invalid = draft()
    invalid["deploymentSources"] *= 2
    with pytest.raises(ValidationError, match="unique selected workloads"):
        MigrationPlanningDraft.model_validate(invalid)


def test_source_first_scope_does_not_allow_full_cluster_mode():
    with pytest.raises(ValidationError, match="not a full cluster"):
        MigrationPlanningDraft.model_validate({**draft(), "mode": "FULL_CLUSTER"})


def test_target_changes_do_not_invalidate_source_first_inventory_but_source_changes_do():
    db = MagicMock()
    repo = Repository(db, MagicMock())
    original = {
        "source_configuration": {"sourceClusterId": "SRC-db"},
        "target_configuration": {},
        "migration_scope": {"namespaces": ["payments"]},
    }
    db.execute.return_value.fetchone.return_value = {"snapshot": serialize(original)}
    current = copy.deepcopy(original)
    current["target_configuration"] = {"clusterId": "CLU-target"}
    repo.require_planning_configuration("MIG-db", 4, current, source_only=True)
    current["source_configuration"] = {"sourceClusterId": "SRC-other"}
    with pytest.raises(ApiError):
        repo.require_planning_configuration("MIG-db", 4, current, source_only=True)


def setup_target(monkeypatch):
    repo = MagicMock()
    repo.principal = SimpleNamespace(user_id="engineer")
    source = {
        "customer_id": "CUS-db",
        "created_by": "engineer",
        "version": 7,
        "status": "ASSESSMENT_READY",
        "source_configuration": {"sourceClusterId": "SRC-db"},
        "target_configuration": {},
        "planning_draft": draft(),
    }
    repo.get.return_value = source
    repo.get_assessment.return_value = {
        "assessment": {"assessmentVersion": 1, "migrationVersion": 4, "inventoryDigest": "a" * 64}
    }
    access = MagicMock()
    registered = {
        "cluster_id": "CLU-target",
        "customer_id": "CUS-db",
        "created_by": "owner",
        "platform": "EKS",
        "environment_id": "ENV-db",
        "environment_approved_version": 8,
        "cluster_name": "dbs-target",
        "status": "ACTIVE",
    }
    cluster_repo = MagicMock()
    cluster_repo.get.return_value = registered
    monkeypatch.setattr("navigan.modules.cluster_management.repository.Repository", lambda *_: cluster_repo)
    body = {
        "version": 7,
        "changeReason": "Select target",
        "target": {
            "platform": "EKS",
            "targetType": "EXISTING_CLUSTER",
            "clusterId": "CLU-target",
            "clusterName": "dbs-target",
            "environmentId": "ENV-db",
            "environmentApprovedVersion": 8,
        },
    }
    return Service(repo, access, "source-first"), repo, source, registered, body, access


def test_target_selection_preserves_source_assessment_scope_and_draft(monkeypatch):
    monkeypatch.setenv("MIGRATION_SOURCE_FIRST_ENABLED", "true")
    service, repo, source, _, body, _ = setup_target(monkeypatch)
    source["migration_id"] = "MIG-db"
    result = service.update("MIG-db", body)
    assert result["targetConfiguration"]["clusterId"] == "CLU-target"
    row, old, action, _ = repo.save.call_args.args
    assert row["source_configuration"] == source["source_configuration"]
    assert row["planning_draft"] == draft()
    assert row["status"] == "ASSESSMENT_READY"
    assert action == "MIGRATION_TARGET_SELECTED"
    repo.require_planning_configuration.assert_called_with("MIG-db", 4, source, source_only=True)


@pytest.mark.parametrize(
    "change",
    [
        {"customer_id": "CUS-other"},
        {"status": "STOPPED"},
        {"environment_approved_version": 9},
        {"workflow": {"ownershipStatus": "ARCHIVED"}},
    ],
)
def test_target_must_match_customer_active_cluster_and_environment(monkeypatch, change):
    service, repo, source, registered, body, _ = setup_target(monkeypatch)
    registered.update(change)
    with pytest.raises(ApiError) as error:
        service.select_planning_target("MIG-db", source, body)
    assert error.value.code == "TARGET_IDENTITY_MISMATCH"
    repo.save.assert_not_called()


def test_target_selection_rejects_missing_scope_and_stale_evidence(monkeypatch):
    service, repo, source, _, body, _ = setup_target(monkeypatch)
    source["planning_draft"] = {}
    with pytest.raises(ApiError, match="Save selected application workloads"):
        service.select_planning_target("MIG-db", source, body)
    source["planning_draft"] = draft()
    source["planning_draft"]["inventoryDigest"] = "b" * 64
    with pytest.raises(ApiError):
        service.select_planning_target("MIG-db", source, body)
    repo.save.assert_not_called()


def test_unselected_and_old_target_findings_do_not_block_selected_scope(monkeypatch):
    service, repo, source, _, _, _ = setup_target(monkeypatch)
    source["target_configuration"] = {"clusterId": "CLU-target"}
    source["migration_id"] = "MIG-db"
    repo.get_assessment.return_value["assessment"]["findings"] = [
        {
            "code": "APP_BLOCKED",
            "severity": "BLOCKER",
            "resourceKind": "Deployment",
            "namespace": "payments",
            "resourceName": "worker",
        },
        {"code": "TARGET_OLD_BLOCKER", "severity": "BLOCKER"},
    ]
    repo.get_target_assessment.return_value = {"assessment": None}
    repo.get_source_inventory.return_value = {"inventory": {"resources": [], "inventoryDigest": "a" * 64}}
    result = service.target_compatibility("MIG-db")
    assert result["decision"]["path"] == "PENDING_EVIDENCE"


def test_source_first_scope_and_deployment_metadata_persist_through_existing_update_api(monkeypatch):
    from test_migration_planning import setup_planning

    monkeypatch.setenv("MIGRATION_SOURCE_FIRST_ENABLED", "true")
    repo, service, identifier, body = setup_planning("ASSESSMENT_READY")
    original_source = copy.deepcopy(repo.rows[identifier]["source_configuration"])
    original_target = copy.deepcopy(repo.rows[identifier]["target_configuration"])
    body["planningDraft"]["workflow"] = "SOURCE_FIRST"
    workload = body["planningDraft"]["resources"][0]
    body["planningDraft"]["deploymentSources"] = [
        {
            "workload": {k: workload[k] for k in ("apiVersion", "kind", "namespace", "name")},
            "method": "HELM",
            "bundleName": "retailflow",
            "reference": "repo/charts/retailflow",
        }
    ]
    result = service.update(identifier, body)
    assert result["planningDraft"]["deploymentSources"][0]["method"] == "HELM"
    assert repo.rows[identifier]["source_configuration"] == original_source
    assert repo.rows[identifier]["target_configuration"] == original_target
    assert result["status"] == "ASSESSMENT_READY"
    assert repo.require_planning_configuration.call_args.kwargs == {"source_only": True}
