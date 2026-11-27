
"""Target PVC mapping requirements; no live cluster operations."""

import pytest

from navigan.modules.migration_management.storage_evidence import (
    compare_storage_claims,
)


def assess(capacity="", mode="", fresh=True):
    pvc = {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "namespace": "retailflow",
        "name": "data",
        "storageClassName": "source",
        "requestedStorage": "10Gi",
        "accessModes": ["ReadWriteOnce"],
        "volumeMode": "Filesystem",
    }

    return compare_storage_claims(
        [pvc],
        {("v1", "PersistentVolumeClaim", "retailflow", "data")},
        ["target"],
        fresh=fresh,
        class_details=[{
            "name": "target",
            "provisioner": "example.csi.driver",
            "volumeBindingMode": "WaitForFirstConsumer",
        }],
        csi_drivers=["example.csi.driver"],
        mappings=[{
            "namespace": "retailflow",
            "sourceClaim": "data",
            "targetStorageClass": "target",
            "targetCapacity": capacity,
            "targetAccessMode": mode,
        }],
        data_strategy="DATA_MIGRATION_HANDLED_SEPARATELY",
    )[0]


@pytest.mark.parametrize("capacity", ["10Gi", "10240Mi", "20Gi"])
def test_sufficient_mapped_capacity_remains_partial(capacity):
    result = assess(capacity, "ReadWriteOnce")
    assert result["status"] == "PARTIAL"
    assert "mounting remain unverified" in result["reason"]


@pytest.mark.parametrize("capacity", ["5Gi", "10239Mi", "10G"])
def test_smaller_capacity_requires_remediation(capacity):
    result = assess(capacity, "ReadWriteOnce")
    assert result["status"] == "REMEDIATION_REQUIRED"
    assert "smaller" in result["reason"]


def test_invalid_capacity_remains_pending():
    assert assess("invalid")["status"] == "PENDING_EVIDENCE"


def test_invalid_access_mode_remains_pending():
    assert assess(mode="invalid")["status"] == "PENDING_EVIDENCE"


@pytest.mark.parametrize("mode", [
    "ReadOnlyMany", "ReadWriteMany", "ReadWriteOncePod"
])
def test_different_access_mode_requires_review(mode):
    assert assess(mode=mode)["status"] == "REMEDIATION_REQUIRED"


def test_legacy_mapping_remains_supported():
    assert assess()["status"] == "PARTIAL"


def test_stale_inventory_remains_pending():
    assert assess("10Gi", "ReadWriteOnce", fresh=False)[
        "status"
    ] == "PENDING_EVIDENCE"


def test_workload_scope_preserves_separate_data_strategy():
    result = assess("10Gi", "ReadWriteOnce")
    assert "Persistent data migration is handled separately" in result["reason"]
    assert "snapshots" not in result["reason"]
