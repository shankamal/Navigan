from unittest.mock import Mock

import pytest

from navigan.modules.cluster_management import repository as cluster_repository
from navigan.modules.migration_management.repository import Repository
from navigan.modules.migration_management.service import Service
from navigan.shared.errors import ApiError


def test_repository_rejects_unbound_target_assessment():
    db = Mock()
    repo = Repository(db, Mock())
    repo.get = Mock(return_value={"customer_id": "CUS-test", "target_configuration": {"clusterId": "CLU-test"}})
    repo.get_assessment = Mock(return_value={"assessment": {"assessmentVersion": 1}})
    db.execute.return_value.fetchone.return_value = None
    assert repo.get_target_assessment("MIG-test")["assessment"] is None
    sql, params = db.execute.call_args.args
    assert params == ["MIG-test", "CLU-test", "CUS-test"]
    for required in ("k.customer_id=%s", "k.platform='EKS'", "k.status='ACTIVE'", "<> 'ARCHIVED'", "c.status='ACTIVE'", "r.expires_at > now()", "r.connector_id=a.target_snapshot->>'connectorId'"):
        assert required in sql


def test_persisted_analysis_fails_if_binding_is_lost():
    repo = Repository(Mock(), Mock())
    repo.get = Mock(return_value={"target_configuration": {"clusterId": "CLU-test"}})
    repo.get_assessment = Mock(return_value={"assessment": {"assessmentVersion": 1}})
    repo.get_target_assessment = Mock(return_value={"assessment": None})
    with pytest.raises(ApiError) as caught:
        repo.save_target_assessment("MIG-test", "CLU-test", {"evidenceLevel": "CONNECTOR_RUNTIME_INVENTORY"})
    assert caught.value.code == "TARGET_INVENTORY_UNAVAILABLE"


@pytest.mark.parametrize("platform,workflow", [("AKS", {}), ("EKS", {"ownershipStatus": "ARCHIVED"})])
def test_snapshot_rejects_invalid_target_before_inventory_read(monkeypatch, platform, workflow):
    cluster = Mock()
    monkeypatch.setattr(cluster_repository, "Repository", Mock(return_value=cluster))
    cluster.get.return_value = {"customer_id": "CUS-test", "cluster_name": "target", "platform": platform, "workflow": workflow, "status": "ACTIVE"}
    migration = {"customer_id": "CUS-test", "target_platform": "EKS", "target_configuration": {"clusterId": "CLU-test", "clusterName": "target"}}
    with pytest.raises(ApiError) as caught:
        Service(Mock(), Mock(), "test")._read_target_snapshot(migration, "CLU-test")
    assert caught.value.code == "TARGET_IDENTITY_MISMATCH"
    cluster.runtime_inventory.assert_not_called()


def test_explicit_analysis_locks_migration():
    repo = Mock()
    repo.get.return_value = {"target_platform": "EKS", "target_configuration": {"clusterId": "CLU-test"}}
    repo.get_assessment.return_value = {"assessment": {"assessmentVersion": 1}}
    service = Service(repo, Mock(), "test")
    service._read_target_snapshot = Mock(return_value={"evidenceLevel": "CONNECTOR_RUNTIME_INVENTORY"})
    service.analyze_target("MIG-test")
    repo.get.assert_called_once_with("MIG-test", lock=True)


@pytest.mark.parametrize("old_target,cleared", [("CLU-old", True), ("CLU-new", False)])
def test_target_change_clears_only_old_storage_mapping(monkeypatch, old_target, cleared):
    cluster = Mock()
    monkeypatch.setattr(cluster_repository, "Repository", Mock(return_value=cluster))
    cluster.get.return_value = {"customer_id": "CUS-test", "created_by": "engineer", "cluster_name": "target", "platform": "EKS", "environment_id": "ENV-test", "environment_approved_version": 1, "status": "ACTIVE", "workflow": {}}
    repo = Mock()
    repo.get_assessment.return_value = {"assessment": {"assessmentVersion": 1, "inventoryDigest": "digest", "migrationVersion": 1}}
    mapping = {"namespace": "apps", "sourceClaim": "db", "targetStorageClass": "gp3"}
    current = {"customer_id": "CUS-test", "version": 1, "target_configuration": {"clusterId": old_target}, "planning_draft": {"workflow": "SOURCE_FIRST", "assessmentVersion": 1, "inventoryDigest": "digest", "resources": [{"kind": "Deployment", "treatment": "MIGRATE"}], "storageMappings": [mapping]}}
    body = {"version": 1, "changeReason": "target selection", "target": {"clusterId": "CLU-new", "clusterName": "target", "platform": "EKS", "targetType": "EXISTING_CLUSTER", "environmentId": "ENV-test", "environmentApprovedVersion": 1}}
    Service(repo, Mock(), "test").select_planning_target("MIG-test", current, body)
    row = repo.save.call_args.args[0]
    assert row["planning_draft"]["storageMappings"] == ([] if cleared else [mapping])
    assert current["planning_draft"]["storageMappings"] == [mapping]
