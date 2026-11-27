from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from navigan.modules.migration_management.service import Service
from navigan.shared.errors import ApiError


CLUSTER = "CLU-test"
RESOURCE = {"apiVersion": "v1", "kind": "ConfigMap", "namespace": "apps", "name": "settings"}


def snapshot(*, expired=False, status="DEGRADED"):
    now = datetime.now(timezone.utc)
    observed = now - timedelta(minutes=20 if expired else 1)
    return {
        "naviganClusterId": CLUSTER,
        "source": "CLUSTER_MANAGEMENT_CONNECTOR",
        "evidenceLevel": "CONNECTOR_RUNTIME_INVENTORY",
        "connectorId": "connector-test",
        "inventoryStatus": status,
        "observedAt": observed.isoformat(),
        "inventoryExpiresAt": (observed + timedelta(minutes=10)).isoformat(),
        "coverageComplete": False,
        "unverified": ["Admission and authorization"],
        "discoveredApiVersions": ["v1"],
        "discoveredApiResources": [{"apiVersion": "v1", "kind": "ConfigMap"}],
    }


def setup_service(*, expired=True):
    repo = Mock()
    migration = {"target_platform": "EKS", "target_configuration": {"clusterId": CLUSTER},
                 "planning_draft": {"resources": [{**RESOURCE, "treatment": "MIGRATE"}]}}
    target = {"targetClusterId": CLUSTER, "assessmentVersion": 5,
              "evidenceLevel": "CONNECTOR_RUNTIME_INVENTORY", "snapshot": snapshot(expired=expired)}
    repo.get.return_value = migration
    repo.get_assessment.return_value = {"assessment": {"assessmentVersion": 5, "findings": []}}
    repo.get_target_assessment.return_value = {"assessment": target}
    repo.get_source_inventory.return_value = {"inventory": {"resources": [RESOURCE]}}
    service = Service(repo, Mock(), "test")
    service._read_target_snapshot = Mock(return_value=snapshot())
    return service, repo, migration, target


@pytest.mark.parametrize("status", ["READY", "DEGRADED"])
def test_expired_observation_uses_fresh_inventory_without_persisting(status):
    service, repo, migration, target = setup_service()
    candidate = snapshot(status=status)
    service._read_target_snapshot.return_value = candidate
    original = target["snapshot"].copy()
    result = service.target_compatibility("MIG-test")
    service._read_target_snapshot.assert_called_once_with(migration, CLUSTER)
    repo.save_target_assessment.assert_not_called()
    assert target["snapshot"] == original
    assert result["decision"]["path"] == "PENDING_EVIDENCE"
    assert result["coverageComplete"] is False
    assert result["apiEvidence"]["resources"][0]["status"] == "PARTIAL"
    assert not any(c["capability"] == "Evidence freshness"
                   for c in result["resourceEvaluations"][0]["checks"])


def test_current_observation_is_reused():
    service, repo, migration, target = setup_service(expired=False)
    assert service._refresh_expired_target_observation(migration, target) is target
    service._read_target_snapshot.assert_not_called()


@pytest.mark.parametrize("code", ["TARGET_INVENTORY_UNAVAILABLE", "CLUSTER_NOT_FOUND",
                                  "TARGET_IDENTITY_MISMATCH", "TARGET_NOT_ACTIVE"])
def test_unavailable_or_unbound_inventory_keeps_expired_evidence(code):
    service, repo, migration, target = setup_service()
    service._read_target_snapshot.side_effect = ApiError(409, code, "not available")
    result = service.target_compatibility("MIG-test")
    assert result["apiEvidence"]["resources"][0]["status"] == "PENDING_EVIDENCE"
    assert result["coverageComplete"] is False
    repo.save_target_assessment.assert_not_called()


@pytest.mark.parametrize("field,value", [
    ("naviganClusterId", "CLU-other"), ("inventoryStatus", "STALE"),
    ("inventoryExpiresAt", "invalid"), ("observedAt", None),
    ("connectorId", None), ("coverageComplete", True),
    ("source", "OTHER"),
])
def test_invalid_candidate_cannot_replace_expired_observation(field, value):
    service, repo, migration, target = setup_service()
    service._read_target_snapshot.return_value[field] = value
    assert service._refresh_expired_target_observation(migration, target) is target
    repo.save_target_assessment.assert_not_called()


def test_complete_persisted_evidence_is_not_replaced_by_inventory():
    service, repo, migration, target = setup_service()
    target["snapshot"]["coverageComplete"] = True
    assert service._refresh_expired_target_observation(migration, target) is target
    service._read_target_snapshot.assert_not_called()


def test_old_source_assessment_is_not_refreshed():
    service, repo, migration, target = setup_service()
    target["assessmentVersion"] = 4
    result = service.target_compatibility("MIG-test")
    assert result["coverageComplete"] is False
    service._read_target_snapshot.assert_not_called()


def test_changed_target_is_not_refreshed():
    service, repo, migration, target = setup_service()
    migration["target_configuration"]["clusterId"] = "CLU-other"
    result = service.target_compatibility("MIG-test")
    assert result["coverageComplete"] is False
    service._read_target_snapshot.assert_not_called()


def test_unexpected_api_failure_is_not_silently_swallowed():
    service, repo, migration, target = setup_service()
    service._read_target_snapshot.side_effect = ApiError(500, "UNEXPECTED", "unexpected")
    with pytest.raises(ApiError, match="unexpected"):
        service._refresh_expired_target_observation(migration, target)



def test_refresh_rejects_replaced_connector():
    service, repo, migration, target = setup_service()
    service._read_target_snapshot.return_value["connectorId"] = "connector-replaced"
    assert service._refresh_expired_target_observation(migration, target) is target
    repo.save_target_assessment.assert_not_called()


def test_refresh_discards_evidence_when_repository_binding_changes():
    service, repo, migration, target = setup_service()
    repo.get_target_assessment.side_effect = [{"assessment": target}, {"assessment": None}]
    result = service.target_compatibility("MIG-test")
    assert result["decision"]["path"] == "PENDING_EVIDENCE"
    assert result["apiEvidence"]["resources"][0]["status"] == "PENDING_EVIDENCE"
    assert result["storageEvidence"]["targetStorageClasses"] == []
    repo.save_target_assessment.assert_not_called()


@pytest.mark.parametrize("expired", [True, False])
def test_storage_classes_are_returned_only_with_current_evidence(expired):
    service, repo, migration, target = setup_service(expired=expired)
    target["snapshot"]["storageClasses"] = ["navigan-ebs-gp3"]
    service._read_target_snapshot.side_effect = ApiError(409, "TARGET_INVENTORY_UNAVAILABLE", "stale")
    result = service.target_compatibility("MIG-test")
    assert result["storageEvidence"]["targetStorageClasses"] == ([] if expired else ["navigan-ebs-gp3"])
