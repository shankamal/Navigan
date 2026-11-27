
import pytest

from navigan.modules.migration_management.network_evidence import (
    build_network_inventory,
    evaluate_target_network,
)

from navigan.modules.migration_management.resource_compatibility import (
    evaluate_selected_resources,
)


def resource(kind="Service", name="api", namespace="retailflow", **extra):
    return {
        "apiVersion": "v1",
        "kind": kind,
        "namespace": namespace,
        "name": name,
        **extra,
    }


def assess(source, target, current=True):
    return evaluate_target_network(
        source,
        {"networkInventory": target},
        target_current=current,
    )


@pytest.mark.parametrize("kind", [
    "Service", "Ingress", "NetworkPolicy"
])
def test_matching_network_objects_remain_partial(kind):
    source = resource(kind)
    result = assess(source, [source])

    assert result["status"] == "PARTIAL"
    assert "ownership" in result["reason"]
    assert "connectivity remain unverified" in result["reason"]


def test_target_namespace_must_match():
    result = assess(
        resource(),
        [resource(namespace="other")]
    )

    assert result["status"] == "PENDING_EVIDENCE"
    assert "not observed" in result["reason"]


def test_workload_service_dependency_is_observed():
    source = resource(
        "Deployment",
        "web",
        dependencyReferences=[
            {"kind": "Service", "name": "api"}
        ]
    )

    result = assess(source, [resource()])

    assert result["status"] == "PARTIAL"
    assert "Service/api" in result["reason"]


def test_ingress_backend_remains_pending_when_unobserved():
    source = resource(
        "Ingress", "web",
        backendServiceReferences=[
            {"kind": "Service", "name": "api"}
        ]
    )

    result = assess(source, [source])

    assert result["status"] == "PENDING_EVIDENCE"
    assert "Service/api" in result["reason"]


def test_empty_inventory_does_not_prove_absence():
    result = assess(resource(), [])

    assert result["status"] == "PENDING_EVIDENCE"
    assert "does not establish nonexistence" in result["reason"]


def test_expired_target_inventory_is_not_used():
    assert assess(
        resource(), [resource()], current=False
    )["status"] == "PENDING_EVIDENCE"


def test_legacy_snapshot_without_inventory_remains_pending():
    result = evaluate_target_network(
        resource(), {}, target_current=True
    )

    assert result["status"] == "PENDING_EVIDENCE"


def test_inventory_retains_only_network_identities():
    rows = build_network_inventory([
        resource(selector={"app": "web"}),
        resource("Secret"),
        resource(namespace=None),
        resource("NetworkPolicy"),
    ])

    assert len(rows) == 2
    assert all(
        set(row) == {"kind", "namespace", "name"}
        for row in rows
    )


def test_target_object_match_never_certifies_connectivity():
    source = resource()

    result = evaluate_selected_resources(
        [source],
        [{**source, "treatment": "RECREATE"}],
        [], [], [], [],
        target_current=True,
        target_snapshot={"networkInventory": [source]},
    )[0]

    checks = {
        check["capability"]: check
        for check in result["checks"]
    }

    assert checks[
        "Target network object evidence"
    ]["status"] == "PARTIAL"

    assert checks["Networking"]["status"] == "PENDING_EVIDENCE"

    assert result["status"] == "PENDING_EVIDENCE"
