"""Cross-module contract tests: source connector output -> migration dependency graph."""

from migration_connector.inventory import build_inventory
from navigan.modules.migration_management.dependency_evidence import discover_dependencies


def source(kind, name, spec=None, namespace="payments", api_version="v1", labels=None):
    return {
        "apiVersion": api_version,
        "kind": kind,
        "metadata": {"name": name, "namespace": namespace, "labels": labels or {}},
        "spec": spec or {},
    }


def test_sanitized_connector_inventory_produces_real_dependency_graph():
    deployment = source("Deployment", "checkout", {
        "template": {
            "metadata": {"labels": {"app": "checkout"}},
            "spec": {
                "serviceAccountName": "checkout-sa",
                "containers": [{"name": "api", "envFrom": [
                    {"configMapRef": {"name": "checkout-settings"}}
                ]}],
                "volumes": [{"name": "data", "persistentVolumeClaim": {
                    "claimName": "checkout-data"
                }}],
            },
        },
    }, api_version="apps/v1")
    inventory = build_inventory([
        deployment,
        source("Service", "checkout-service", {
            "selector": {"app": "checkout"}, "ports": [{"port": 80}]
        }),
        source("ServiceAccount", "checkout-sa"),
        source("ConfigMap", "checkout-settings"),
        source("PersistentVolumeClaim", "checkout-data"),
    ])
    sanitized = inventory["resources"]
    selected = {("apps/v1", "Deployment", "payments", "checkout")}
    result = discover_dependencies(sanitized, selected)
    assert result["relationshipCount"] == 4
    assert result["unresolvedCount"] == 0
    assert {edge["target"]["kind"] for edge in result["relationships"]} == {
        "ServiceAccount", "ConfigMap", "PersistentVolumeClaim", "Service",
    }
    assert "spec" not in next(x for x in sanitized if x["kind"] == "Deployment")


def test_missing_dependencies_are_reported_not_claimed_resolved():
    inventory = build_inventory([source("Deployment", "api", {
        "template": {"spec": {
            "serviceAccountName": "missing-sa",
            "containers": [{"name": "api"}],
        }}
    }, api_version="apps/v1")])
    result = discover_dependencies(inventory["resources"])
    assert result["relationshipCount"] == 0
    assert result["unresolvedCount"] == 1
    assert result["unresolvedReferences"][0]["target"]["name"] == "missing-sa"
