from navigan.modules.migration_management.storage_evidence import compare_storage_claims


def claim(storage_class="gp3"):
    return {"apiVersion": "v1", "kind": "PersistentVolumeClaim",
            "namespace": "apps", "name": "data", "storageClassName": storage_class}


SELECTED = {("v1", "PersistentVolumeClaim", "apps", "data")}


def test_matching_storage_class_is_only_partial():
    results = compare_storage_claims([claim()], SELECTED, ["gp3"], fresh=True)
    assert results[0]["status"] == "PARTIAL"
    assert "unverified" in results[0]["reason"]


def test_missing_or_stale_evidence_remains_pending():
    assert compare_storage_claims([claim()], SELECTED, [], fresh=True)[0]["status"] == "PENDING_EVIDENCE"
    assert compare_storage_claims([claim()], SELECTED, ["gp3"], fresh=False)[0]["status"] == "PENDING_EVIDENCE"
    assert compare_storage_claims([claim(None)], SELECTED, ["gp3"], fresh=True)[0]["status"] == "PENDING_EVIDENCE"


def test_unselected_claim_not_evaluated():
    assert compare_storage_claims([claim()], set(), ["gp3"], fresh=True) == []
