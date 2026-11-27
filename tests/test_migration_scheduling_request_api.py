from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from navigan.modules.migration_management.service import Service


@pytest.mark.parametrize("requests, expected", [
    ({"cpu": "500m", "memory": "1Gi"}, True),
    ({"cpu": "500m"}, False),
])
def test_constrained_workload_reports_regular_request_evidence_without_approval(requests, expected):
    now = datetime.now(timezone.utc)
    resource = {"apiVersion": "apps/v1", "kind": "Deployment", "namespace": "apps", "name": "web"}
    repo = Mock()
    repo.principal = Mock()
    repo.get.return_value = {"target_configuration": {"clusterId": "CLU-test"},
        "planning_draft": {"resources": [{**resource, "treatment": "MIGRATE"}]}}
    repo.get_assessment.return_value = {"assessment": {"assessmentVersion": 1, "findings": []}}
    repo.get_target_assessment.return_value = {"assessment": {
        "targetClusterId": "CLU-test", "assessmentVersion": 1,
        "evidenceLevel": "CONNECTOR_RUNTIME_INVENTORY",
        "snapshot": {"observedAt": (now - timedelta(seconds=1)).isoformat(),
            "expiresAt": (now + timedelta(minutes=5)).isoformat(),
            "coverageComplete": False,
            "nodeCapacity": [{"allocatableCpu": "2", "allocatableMemory": "4Gi",
                "unschedulable": False, "taintCount": 0}],
            "nodeCapacityCoverage": {"observedNodes": 1}},
    }}
    repo.get_source_inventory.return_value = {"inventory": {"resources": [{**resource,
        "pod": {"affinity": {"podAntiAffinity": True},
                "containers": [{"resources": {"requests": requests}}]}}]}}
    result = Service(repo, Mock(), "test").target_compatibility("MIG-test")
    evidence = result["schedulingEvidence"]["workloads"][0]
    assert evidence["status"] == "PENDING_EVIDENCE"
    assert ("regularContainerRequests" in evidence) == expected
    assert ("Regular-container requests are observed" in evidence["reason"]) == expected
    assert result["decision"]["path"] == "PENDING_EVIDENCE"
    assert result["coverageComplete"] is False
