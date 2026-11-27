
import pytest

from navigan.modules.migration_management.identity_evidence import (
    evaluate_identity_dependencies,
)

from navigan.modules.migration_management.resource_compatibility import (
    evaluate_selected_resources,
)


WORKLOAD = {
    "apiVersion": "apps/v1",
    "kind": "Deployment",
    "namespace": "retailflow",
    "name": "api",
    "pod": {
        "serviceAccountName": "retailflow-api",
        "imagePullSecretCount": 1,
    },
    "dependencyReferences": [
        {"kind": "Secret", "name": "registry"},
    ],
}

ACCOUNT = {
    "apiVersion": "v1",
    "kind": "ServiceAccount",
    "namespace": "retailflow",
    "name": "retailflow-api",
}

SECRET = {
    "apiVersion": "v1",
    "kind": "Secret",
    "namespace": "retailflow",
    "name": "registry",
}

RESOURCES = [WORKLOAD, ACCOUNT, SECRET]

PLANNED = [
    {**WORKLOAD, "treatment": "MIGRATE"},
    {**ACCOUNT, "treatment": "RECREATE"},
    {**SECRET, "treatment": "RECREATE"},
]


def snapshot(namespace="retailflow"):
    return {
        "supplementaryDiscovery": {
            "ServiceAccount": "AVAILABLE"
        },
        "supplementaryInventory": {
            "ServiceAccount": [{
                "namespace": namespace,
                "name": "retailflow-api",
            }]
        },
    }


def assess(target=None, planned=PLANNED,
           resources=RESOURCES, current=True):
    rows = evaluate_identity_dependencies(
        WORKLOAD, resources, planned,
        target if target is not None else snapshot(),
        target_current=current,
    )
    return {r["capability"]: r for r in rows}


def test_recreated_identity_dependencies_are_in_scope():
    checks = assess()
    assert checks["Identity dependency scope"]["status"] == "PARTIAL"
    assert "Secret/registry" in checks["Identity dependency scope"]["reason"]


def test_observed_target_account_is_partial_only():
    checks = assess()
    row = checks["Target ServiceAccount evidence"]
    assert row["status"] == "PARTIAL"
    assert "authorization remain unverified" in row["reason"]


def test_other_namespace_does_not_satisfy_account():
    checks = assess(target=snapshot("other"))
    assert checks["Target ServiceAccount evidence"]["status"] == "PENDING_EVIDENCE"


def test_stale_target_evidence_remains_pending():
    assert assess(current=False)[
        "Target ServiceAccount evidence"
    ]["status"] == "PENDING_EVIDENCE"


def test_denied_discovery_remains_pending():
    target = snapshot()
    target["supplementaryDiscovery"]["ServiceAccount"] = "PERMISSION_DENIED"
    assert assess(target=target)[
        "Target ServiceAccount evidence"
    ]["status"] == "PENDING_EVIDENCE"


@pytest.mark.parametrize("treatment", ["RETIRE", "REVIEW", "REPLACE"])
def test_unresolved_dependency_treatment(treatment):
    planned = PLANNED[:2] + [{**SECRET, "treatment": treatment}]
    assert assess(planned=planned)[
        "Identity dependency scope"
    ]["status"] == "PENDING_EVIDENCE"


def test_missing_source_secret_remains_pending():
    assert assess(resources=[WORKLOAD, ACCOUNT])[
        "Identity dependency scope"
    ]["status"] == "PENDING_EVIDENCE"


def test_identity_inventory_does_not_establish_readiness():
    result = evaluate_selected_resources(
        RESOURCES, PLANNED, [], [], [], [],
        target_current=True,
        target_snapshot=snapshot(),
    )[0]

    checks = {c["capability"]: c for c in result["checks"]}

    assert checks["Target ServiceAccount evidence"]["status"] == "PARTIAL"
    assert checks["Identity and secrets"]["status"] == "PENDING_EVIDENCE"
    assert result["status"] == "PENDING_EVIDENCE"
