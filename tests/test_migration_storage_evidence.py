from navigan.modules.migration_management.storage_evidence import compare_storage_claims


def claim(storage_class="gp3", **overrides):
    return {"apiVersion": "v1", "kind": "PersistentVolumeClaim",
            "namespace": "apps", "name": "data", "storageClassName": storage_class,
            "accessModes": ["ReadWriteOnce"], "requestedStorage": "10Gi",
            "volumeMode": "Filesystem", **overrides}


SELECTED = {("v1", "PersistentVolumeClaim", "apps", "data")}
DETAILS = [{"name": "gp3", "provisioner": "ebs.csi.aws.com",
            "volumeBindingMode": "WaitForFirstConsumer"}]


def compare(resource, *, fresh=True, details=DETAILS, drivers=("ebs.csi.aws.com",),
            classes=("gp3",)):
    return compare_storage_claims([resource], SELECTED, classes, fresh=fresh,
                                  class_details=details, csi_drivers=drivers)[0]


def test_matching_storage_class_and_driver_are_partial_only():
    result = compare(claim())
    assert result["status"] == "PARTIAL"
    assert result["requestedStorage"] == "10Gi"
    assert result["sourceAccessModes"] == ["ReadWriteOnce"]
    assert result["csiDriverObserved"] is True
    assert "unverified" in result["reason"]


def test_missing_or_stale_evidence_remains_pending():
    assert compare(claim(), classes=())["status"] == "PENDING_EVIDENCE"
    assert compare(claim(), fresh=False)["status"] == "PENDING_EVIDENCE"
    assert compare(claim(None))["status"] == "PENDING_EVIDENCE"
    assert compare(claim(), drivers=())["status"] == "PENDING_EVIDENCE"
    assert compare(claim(), details=[])["status"] == "PENDING_EVIDENCE"


def test_missing_source_requirements_remain_pending():
    assert compare(claim(requestedStorage=None))["status"] == "PENDING_EVIDENCE"
    assert compare(claim(accessModes=[]))["status"] == "PENDING_EVIDENCE"
    assert compare(claim(volumeMode="Invalid"))["status"] == "PENDING_EVIDENCE"


def test_unselected_claim_not_evaluated():
    assert compare_storage_claims([claim()], set(), ["gp3"], fresh=True) == []
