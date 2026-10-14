from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from navigan.modules.migration_management.service import Service


def test_compatibility_exposes_selected_workload_scheduling_without_approving_path():
    expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    repo = Mock()
    repo.principal = Mock()
    repo.get.return_value = {
        "target_configuration": {"clusterId": "CLU-test"},
        "planning_draft": {"resources": [
            {"apiVersion": "apps/v1", "kind": "Deployment",
             "namespace": "apps", "name": "web", "treatment": "MIGRATE"},
        ]},
    }
    repo.get_assessment.return_value = {"assessment": {
        "assessmentVersion": 1, "findings": [],
    }}
    repo.get_target_assessment.return_value = {"assessment": {
        "targetClusterId": "CLU-test",
        "evidenceLevel": "CONNECTOR_RUNTIME_INVENTORY",
        "snapshot": {
            "coverageComplete": False,
            "expiresAt": expiry,
            "nodeCapacity": [{"name": "worker", "allocatableCpu": "2",
                              "allocatableMemory": "4Gi", "unschedulable": False,
                              "taintCount": 0}],
            "nodeCapacityCoverage": {"observedNodes": 1, "nodesWithCapacity": 1},
            "unverified": ["Scheduling and storage"],
        },
    }}
    repo.get_source_inventory.return_value = {"inventory": {
        "resources": [{"apiVersion": "apps/v1", "kind": "Deployment",
                       "namespace": "apps", "name": "web",
                       "pod": {"containers": [{"name": "web", "resources": {"requests": {"cpu": "500m", "memory": "1Gi"}}}]}}],
    }}
    result = Service(repo, Mock(), "test").target_compatibility("MIG-test")
    assert result["decision"]["path"] == "PENDING_EVIDENCE"
    assert result["schedulingEvidence"]["workloads"][0]["status"] == "PARTIAL"
    assert result["coverageComplete"] is False


def test_compatibility_does_not_invent_missing_workload_requests():
    expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    repo = Mock()
    repo.principal = Mock()
    repo.get.return_value = {
        "target_configuration": {"clusterId": "CLU-test"},
        "planning_draft": {"resources": [
            {"apiVersion": "apps/v1", "kind": "Deployment",
             "namespace": "apps", "name": "web", "treatment": "MIGRATE"}]},
    }
    repo.get_assessment.return_value = {"assessment": {"assessmentVersion": 1, "findings": []}}
    repo.get_target_assessment.return_value = {"assessment": {
        "targetClusterId": "CLU-test", "snapshot": {"expiresAt": expiry,
        "nodeCapacity": [{"allocatableCpu": "2", "allocatableMemory": "4Gi",
                          "unschedulable": False, "taintCount": 0}],
        "nodeCapacityCoverage": {"observedNodes": 1}},
    }}
    repo.get_source_inventory.return_value = {"inventory": {"resources": [
        {"apiVersion": "apps/v1", "kind": "Deployment", "namespace": "apps",
         "name": "web"}]}}
    result = Service(repo, Mock(), "test").target_compatibility("MIG-test")
    assert result["schedulingEvidence"]["workloads"][0]["status"] == "PENDING_EVIDENCE"
