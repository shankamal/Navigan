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
