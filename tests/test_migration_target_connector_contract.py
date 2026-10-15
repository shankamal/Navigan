"""Schema contract for read-only target connector inventory. No cluster access."""
import pytest
from pydantic import ValidationError

from navigan.modules.cluster_management.connector_handler import RuntimeInventory, RuntimeResourceItem


def observed(kind, name, namespace=None):
    return {
        "kind": kind,
        "namespace": namespace,
        "name": name,
        "status": "OBSERVED",
        "ready": 0,
        "desired": 0,
        "restarts": 0,
    }


def test_crd_report_is_accepted_by_target_runtime_contract():
    report = RuntimeInventory.model_validate({
        "resources": [
            observed("CustomResourceDefinition", "widgets.example.io"),
            observed("ClusterRole", "read-only"),
            observed("StorageClass", "gp3"),
        ],
        "warningEvents": [],
        "metrics": {"discoveryStatus_CustomResourceDefinition": 1,
                    "storageClassDiscoveryStatus": 1},
    })
    assert report.resources[0].kind == "CustomResourceDefinition"
    assert report.metrics["discoveryStatus_CustomResourceDefinition"] == 1


def test_sensitive_unknown_resource_fields_remain_rejected():
    with pytest.raises(ValidationError):
        RuntimeResourceItem.model_validate({
            **observed("CustomResourceDefinition", "widgets.example.io"),
            "spec": {"schema": "must-not-be-transmitted"},
        })


def test_node_allocatable_and_api_discovery_metrics_pass_contract():
    report = RuntimeInventory.model_validate({
        "resources": [{
            **observed("Node", "worker-1"),
            "allocatableCpu": "1900m",
            "allocatableMemory": "7Gi",
            "nodeTaints": [],
        }],
        "warningEvents": [],
        "metrics": {"apiDiscoveryCoreV1": 1, "apiDiscoveryAppsV1": 1,
                    "apiKind_appsV1_Deployment": 1},
    })
    assert report.resources[0].allocatableCpu == "1900m"
    assert report.metrics["apiDiscoveryAppsV1"] == 1
