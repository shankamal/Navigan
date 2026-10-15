from navigan.modules.migration_management.resource_compatibility import evaluate_selected_resources

SOURCE = [
    {"apiVersion": "apps/v1", "kind": "Deployment", "namespace": "retailflow",
     "name": "api"},
    {"apiVersion": "v1", "kind": "PersistentVolumeClaim", "namespace": "retailflow",
     "name": "db"},
]
PLANNED = [{**r, "treatment": "MIGRATE"} for r in SOURCE]
API = [{"apiVersion": "apps/v1", "kind": "Deployment", "namespace": "retailflow",
        "name": "api", "status": "PARTIAL", "reason": "Group version observed"}]


def test_every_selected_resource_gets_explanations_and_next_actions():
    result = evaluate_selected_resources(SOURCE, PLANNED, [], API, [], [], target_current=True)
    assert len(result) == 2
    assert all(row["checks"] for row in result)
    assert all(check["reason"] and check["nextAction"]
               for row in result for check in row["checks"])
    assert all(row["status"] == "PENDING_EVIDENCE" for row in result)


def test_blocker_is_not_overridden_by_partial_target_observations():
    finding = {"resourceKind": "Deployment", "namespace": "retailflow",
               "resourceName": "api", "severity": "BLOCKER", "message": "Unsupported configuration"}
    result = evaluate_selected_resources(SOURCE, PLANNED, [finding], API, [], [], target_current=True)
    assert result[0]["status"] == "INCOMPATIBLE"
    assert result[1]["status"] == "PENDING_EVIDENCE"


def test_missing_inventory_and_stale_target_remain_pending():
    planned = [{"apiVersion": "apps/v1", "kind": "Deployment", "namespace": "retailflow",
                "name": "missing", "treatment": "MIGRATE"}]
    result = evaluate_selected_resources([], planned, [], [], [], [], target_current=False)
    assert result[0]["status"] == "PENDING_EVIDENCE"
    assert {c["capability"] for c in result[0]["checks"]} >= {"Source inventory", "Evidence freshness"}


def test_retired_resource_requires_explicit_decommission_decision():
    planned = [{**SOURCE[0], "treatment": "RETIRE"}]
    result = evaluate_selected_resources(SOURCE, planned, [], [], [], [], target_current=True)
    assert result[0]["status"] == "REMEDIATION_REQUIRED"


def test_resource_specific_capabilities_not_blanket_unknowns():
    source = [
        {"apiVersion": "v1", "kind": "PersistentVolumeClaim", "namespace": "apps", "name": "db"},
        {"apiVersion": "v1", "kind": "ServiceAccount", "namespace": "apps", "name": "api"},
        {"apiVersion": "apps/v1", "kind": "Deployment", "namespace": "apps", "name": "frontend"},
    ]
    result = evaluate_selected_resources(source, [{**item, "treatment": "MIGRATE"} for item in source],
                                         [], [], [], [], target_current=True)
    pvc, identity, workload = [{c["capability"] for c in item["checks"]} for item in result]
    assert "Persistent storage" in pvc
    assert "Workload scheduling" not in pvc
    assert "Identity and secrets" not in pvc
    assert "Persistent storage" not in identity
    assert "Workload scheduling" not in identity
    assert "Workload scheduling" in workload
    assert "Networking" not in workload


def test_source_remediation_distinct_from_pending_target():
    finding = {"resourceKind": "Deployment", "namespace": "retailflow", "resourceName": "api",
               "severity": "WARNING", "message": "Update deployment configuration"}
    result = evaluate_selected_resources(SOURCE, PLANNED, [finding], API, [], [], target_current=True)
    assert result[0]["sourceStatus"] == "REMEDIATION_REQUIRED"
    assert result[0]["targetStatus"] == "PENDING_EVIDENCE"
    assert result[0]["status"] == "PENDING_EVIDENCE"


def test_network_checks_only_apply_to_network_resources():
    source = [{"apiVersion":"v1","kind":"Service","namespace":"apps","name":"svc"},
              {"apiVersion":"v1","kind":"ConfigMap","namespace":"apps","name":"cfg"}]
    result = evaluate_selected_resources(source,[{**x,"treatment":"MIGRATE"} for x in source],
                                         [],[],[],[],target_current=True)
    assert "Networking" in {c["capability"] for c in result[0]["checks"]}
    assert "Networking" not in {c["capability"] for c in result[1]["checks"]}
    assert result[0]["targetStatus"] == "PENDING_EVIDENCE"


def test_seamless_source_finding_is_not_remediation():
    finding = {"resourceKind": "Deployment", "namespace": "retailflow", "resourceName": "api",
               "severity": "INFO", "disposition": "SEAMLESS", "message": "No source change required"}
    result = evaluate_selected_resources(SOURCE, PLANNED, [finding], API, [], [], target_current=True)
    assert result[0]["sourceStatus"] == "NO_FINDINGS"
    assert result[0]["targetStatus"] == "PENDING_EVIDENCE"


def test_workload_identity_checks_follow_observed_source_references():
    common = {"apiVersion":"apps/v1","kind":"Deployment","namespace":"apps","name":"web"}
    plain = {**common, "pod": {"serviceAccountName":"default","imagePullSecrets":[]}}
    privileged = {**common, "pod": {"serviceAccountName":"custom","imagePullSecrets":[]}}
    planned = [{**common, "treatment":"MIGRATE"}]
    ordinary = evaluate_selected_resources([plain],planned,[],[],[],[],target_current=True)[0]
    special = evaluate_selected_resources([privileged],planned,[],[],[],[],target_current=True)[0]
    assert "Identity and secrets" not in {check["capability"] for check in ordinary["checks"]}
    assert "Identity and secrets" in {check["capability"] for check in special["checks"]}


def test_missing_source_podspec_keeps_identity_unverified():
    result = evaluate_selected_resources([SOURCE[0]], [PLANNED[0]], [], API, [], [], target_current=True)[0]
    assert any(c["capability"] == "Identity and secrets" and c["status"] == "PENDING_EVIDENCE"
               for c in result["checks"])
