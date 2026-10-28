from navigan.modules.migration_management.assessment_report import build_workload_assessment_report


def test_only_primary_selected_workloads_enter_report_and_evidence_is_retained():
    draft = {"resources": [
        {"apiVersion": "apps/v1", "kind": "Deployment", "namespace": "retailflow",
         "name": "api", "treatment": "MIGRATE", "dependency": False},
        {"apiVersion": "v1", "kind": "ServiceAccount", "namespace": "retailflow",
         "name": "api-sa", "treatment": "RECREATE", "dependency": True},
    ]}
    evaluations = [{"resource": {
        "apiVersion": "apps/v1", "kind": "Deployment", "namespace": "retailflow",
        "name": "api"}, "status": "PENDING_EVIDENCE",
        "checks": [{"capability": "Storage", "status": "PENDING_EVIDENCE",
                    "reason": "CSI not verified", "nextAction": "Verify target CSI"}]}]
    evidence = {"relationships": [{"source": {
        "kind": "Deployment", "namespace": "retailflow", "name": "api"},
        "target": {"kind": "ServiceAccount", "namespace": "retailflow", "name": "api-sa"}}],
        "unresolvedReferences": [], "workloadCoverage": {"selectedWorkloads": 1}}
    report = build_workload_assessment_report(draft, evaluations, evidence, "DEV2-CLUS2-DEMO")
    assert report["workloadCount"] == 1
    assert report["executionReady"] is False
    assert report["workloads"][0]["compatibilityStatus"] == "PENDING_EVIDENCE"
    assert report["workloads"][0]["observedDependencies"][0]["name"] == "api-sa"
    assert report["workloads"][0]["checks"][0]["nextAction"] == "Verify target CSI"


def test_unverified_workload_does_not_claim_missing_evidence_means_no_dependencies():
    draft = {"resources": [{"apiVersion": "batch/v1", "kind": "CronJob", "namespace": "apps",
                            "name": "nightly", "treatment": "MIGRATE", "dependency": False}]}
    report = build_workload_assessment_report(draft, [], {}, "target")
    assert report["workloadCount"] == 1
    assert report["workloads"][0]["compatibilityStatus"] == "PENDING_EVIDENCE"
    assert report["workloads"][0]["dependencyEvidenceStatus"] == "NOT_VERIFIED"
    assert report["executionReady"] is False
