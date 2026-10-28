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
