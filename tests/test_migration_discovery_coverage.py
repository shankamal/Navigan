from datetime import datetime, timezone

from navigan.modules.migration_management.discovery_coverage import build_discovery_coverage

NOW = datetime(2026, 10, 16, tzinfo=timezone.utc)


def test_consolidated_discovery_never_claims_complete_based_on_resource_counts():
    source = {"resources": [
        {"apiVersion": "apps/v1", "kind": "Deployment", "namespace": "retailflow", "name": "api",
         "pod": {"serviceAccountName": "api-sa"}},
        {"apiVersion": "v1", "kind": "ServiceAccount", "namespace": "retailflow", "name": "api-sa"},
    ], "observedAt": "2026-10-08T12:00:00Z"}
    draft = {"resources": [{"apiVersion": "apps/v1", "kind": "Deployment",
                            "namespace": "retailflow", "name": "api", "dependency": False}]}
    target = {"snapshot": {
        "resourceCount": 65, "observedAt": "2026-10-15T12:00:00Z",
        "inventoryExpiresAt": "2026-10-15T13:00:00Z",
        "capabilityEvidence": {"compute": {"status": "PARTIAL", "reason": "Only node objects found"}},
    }}
    report = build_discovery_coverage(source, draft, target, NOW)
    assert report["source"]["inventoryResourceCount"] == 2
    assert report["source"]["matchedSelectedWorkloads"] == 1
    assert report["source"]["dependencyEvidence"]["relationshipCount"] == 1
    assert report["source"]["dependencyEvidence"]["workloadCoverage"]["withReferenceEvidence"] == 0
    assert report["source"]["discoveryAccepted"] is False
    assert report["target"]["freshness"] == "STALE"
    assert report["target"]["capabilities"]["compute"]["status"] == "STALE"
    assert report["target"]["discoveryAccepted"] is False


def test_discovery_gaps_are_missing_when_no_evidence_present():
    report = build_discovery_coverage({}, {}, {}, NOW)
    assert report["source"]["capabilities"]["inventory"]["status"] == "MISSING"
    assert report["source"]["capabilities"]["dependencies"]["status"] == "MISSING"
    assert report["target"]["freshness"] == "UNKNOWN"
    assert report["target"]["capabilities"]["storage"]["status"] == "MISSING"


def test_source_scope_counts_are_not_inflated_by_unselected_workloads():
    inventory = {"resources": [
        {"apiVersion": "apps/v1", "kind": "Deployment", "namespace": "apps",
         "name": "selected", "dependencyReferences": []},
        {"apiVersion": "apps/v1", "kind": "Deployment", "namespace": "other",
         "name": "unselected", "dependencyReferences": []},
    ]}
    draft = {"resources": [{"apiVersion": "apps/v1", "kind": "Deployment",
                            "namespace": "apps", "name": "selected", "dependency": False}]}
    report = build_discovery_coverage(inventory, draft, {}, NOW)
    assert report["source"]["selectedWorkloadCount"] == 1
    assert report["source"]["matchedSelectedWorkloads"] == 1
    assert report["source"]["dependencyEvidence"]["workloadCoverage"]["withReferenceEvidence"] == 1
    assert report["source"]["capabilities"]["dependencies"]["status"] == "PARTIAL"
