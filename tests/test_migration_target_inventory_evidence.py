from unittest.mock import Mock

from navigan.modules.cluster_management import repository as cluster_repository
from navigan.modules.migration_management.api_evidence import evaluate_api_versions
from navigan.modules.migration_management.service import Service
from navigan.modules.migration_management.target_inventory_evidence import build_target_inventory_evidence


def test_missing_target_fields_are_reported_not_invented():
    result = build_target_inventory_evidence(
        [{"kind": "Node", "name": "worker-1"}, {"kind": "Node", "name": "worker-2"}],
        {},
    )
    assert result["nodeCapacityCoverage"] == {
        "observedNodes": 2, "nodesWithCapacity": 0, "missingNodes": 2,
    }
    assert result["collectionGaps"]["nodeCapacity"] == "MISSING"
    assert result["collectionGaps"]["kubernetesApi"] == "MISSING"
    assert result["collectionGaps"]["storage"] == "MISSING"
    assert result["storageDiscovery"]["StorageClass"] == "NOT_REPORTED"


def test_observed_connector_fields_are_used_without_claiming_compatibility():
    result = build_target_inventory_evidence(
        [{"kind": "Node", "name": "worker-1", "allocatableCpu": "1900m",
          "allocatableMemory": "7Gi", "nodeTaints": []}],
        {"apiDiscoveryCoreV1": 1, "apiKind_coreV1_Pod": 1,
         "storageClassDiscoveryStatus": 1, "csiDriverDiscoveryStatus": 2,
         "discoveryStatus_Ingress": 1},
    )
    assert result["nodeCapacityCoverage"]["nodesWithCapacity"] == 1
    assert result["nodeCapacity"][0]["allocatableCpu"] == "1900m"
    assert result["discoveredApiVersions"] == ["v1"]
    assert result["discoveredApiResources"] == [{"apiVersion": "v1", "kind": "Pod"}]
    assert result["storageDiscovery"]["CSIDriver"] == "PERMISSION_DENIED"
    assert result["collectionGaps"]["storage"] == "MISSING"
    assert result["collectionGaps"]["nodeCapacity"] == "PARTIAL"
    assert result["collectionGaps"]["networking"] == "MISSING"


def test_aggregated_discovery_matches_only_selected_kind_and_api_version():
    inventory = build_target_inventory_evidence([], {
        "apiDiscoveryCoreV1": 1,
        "apiKind_coreV1_Pod": 1,
        "apiVersion:v1": 1,
        "apiKind:v1:Pod": 1,
        "apiKind:v1:Namespace": 1,
        "apiVersion:batch/v1": 1,
        "apiKind:batch/v1:CronJob": 1,
        "apiKind:batch/v1beta1:CronJob": 1,
        "apiVersion:example.com/v2": 1,
        "apiKind:example.com/v2:Widget": 1,
        "apiKind:example.com/v2:Widget/status": 1,
        "apiKind:example.com/v2:Gadget": 0,
    })
    resources = [
        {"apiVersion": version, "kind": kind, "namespace": "sample", "name": name}
        for version, kind, name in (
            ("batch/v1", "CronJob", "supported"),
            ("batch/v1beta1", "CronJob", "missing-version"),
            ("example.com/v2", "Gadget", "missing-kind"),
            ("example.com/v2", "Widget", "out-of-scope"),
        )
    ]
    selected = {(r["apiVersion"], r["kind"], r["namespace"], r["name"]) for r in resources[:3]}
    results = evaluate_api_versions(
        resources, selected, inventory["discoveredApiVersions"], fresh=True,
        observed_resources=inventory["discoveredApiResources"],
    )
    assert [(r["name"], r["status"]) for r in results] == [
        ("supported", "PARTIAL"),
        ("missing-version", "PENDING_EVIDENCE"),
        ("missing-kind", "PENDING_EVIDENCE"),
    ]
    assert inventory["discoveredApiResources"].count({"apiVersion": "v1", "kind": "Pod"}) == 1
    assert {"apiVersion": "v1", "kind": "Namespace"} in inventory["discoveredApiResources"]
    assert {"apiVersion": "example.com/v2", "kind": "Widget"} in inventory["discoveredApiResources"]
    assert {"apiVersion": "example.com/v2", "kind": "Widget/status"} not in inventory["discoveredApiResources"]


def test_target_assessment_saves_discovered_kinds_with_partial_coverage(monkeypatch):
    repo, access, cluster = Mock(), Mock(), Mock()
    monkeypatch.setattr(cluster_repository, "Repository", Mock(return_value=cluster))
    repo.get.return_value = {
        "customer_id": "CUS-fixture",
        "target_platform": "EKS",
        "target_configuration": {"clusterId": "CLU-fixture", "clusterName": "target"},
    }
    repo.get_assessment.return_value = {"assessment": {"assessmentVersion": 1}}
    cluster.get.return_value = {"customer_id": "CUS-fixture", "cluster_name": "target", "status": "ACTIVE"}
    cluster.runtime_inventory.return_value = {
        "status": "READY", "resources": [],
        "metrics": {"apiVersion:batch/v1": 1, "apiKind:batch/v1:CronJob": 1},
        "sourceRevision": 1, "connectorId": "KCC-fixture",
        "observedAt": "2026-11-20T16:00:00Z", "expiresAt": "2026-11-20T16:10:00Z",
    }

    Service(repo, access, "correlation").analyze_target("MIG-fixture")

    access.require.assert_called_once_with("migration.edit")
    migration, target, snapshot = repo.save_target_assessment.call_args.args
    assert (migration, target) == ("MIG-fixture", "CLU-fixture")
    assert snapshot["discoveredApiVersions"] == ["batch/v1"]
    assert snapshot["discoveredApiResources"] == [{"apiVersion": "batch/v1", "kind": "CronJob"}]
    assert snapshot["capabilityEvidence"]["kubernetesApi"]["status"] == "PARTIAL"
    assert snapshot["coverageComplete"] is False
