from navigan.modules.migration_management.dependency_evidence import discover_dependencies


def resource(kind, name, references=None, namespace="apps", api_version="v1"):
    item = {
        "apiVersion": api_version, "kind": kind,
        "namespace": namespace, "name": name,
    }
    if references is not None:
        item["dependencyReferences"] = references
    return item


def test_sanitized_source_inventory_resolves_observed_references():
    inventory = [
        resource("Deployment", "orders", [
            {"kind": "ServiceAccount", "name": "orders-sa"},
            {"kind": "PersistentVolumeClaim", "name": "orders-data"},
            {"kind": "ConfigMap", "name": "orders-config"},
            {"kind": "Secret", "name": "missing-secret"},
        ], api_version="apps/v1"),
        resource("ServiceAccount", "orders-sa"),
        resource("PersistentVolumeClaim", "orders-data"),
        resource("ConfigMap", "orders-config"),
    ]
    result = discover_dependencies(inventory)
    assert result["status"] == "PARTIAL"
    assert result["relationshipCount"] == 3
    assert result["unresolvedCount"] == 1
    assert {e["target"]["kind"] for e in result["relationships"]} == {
        "ServiceAccount", "PersistentVolumeClaim", "ConfigMap",
    }
    assert result["unresolvedReferences"][0]["target"]["name"] == "missing-secret"


def test_selected_workload_scope_and_namespaces():
    inventory = [
        resource("Deployment", "selected", [{"kind": "ConfigMap", "name": "config"}], api_version="apps/v1"),
        resource("Deployment", "unselected", [{"kind": "Secret", "name": "private"}], api_version="apps/v1"),
        resource("ConfigMap", "config", namespace="elsewhere"),
        resource("Secret", "private"),
    ]
    selected = {("apps/v1", "Deployment", "apps", "selected")}
    result = discover_dependencies(inventory, selected)
    assert result["relationshipCount"] == 0
    assert result["unresolvedCount"] == 1
    assert result["unresolvedReferences"][0]["source"]["name"] == "selected"


def test_cronjob_dependencies_and_duplicate_references():
    inventory = [
        resource("CronJob", "cleanup", [
            {"kind": "ServiceAccount", "name": "batch"},
            {"kind": "ConfigMap", "name": "batch-settings"},
            {"kind": "ConfigMap", "name": "batch-settings"},
        ], api_version="batch/v1"),
        resource("ServiceAccount", "batch"),
        resource("ConfigMap", "batch-settings"),
    ]
    result = discover_dependencies(inventory)
    assert result["relationshipCount"] == 2
    assert result["unresolvedCount"] == 0


def test_empty_or_summary_only_inventory_does_not_claim_coverage():
    assert discover_dependencies([])["status"] == "PARTIAL"
    summary = [resource("Deployment", "orders", api_version="apps/v1")]
    result = discover_dependencies(summary)
    assert result["relationshipCount"] == 0
    assert result["unresolvedCount"] == 0
    assert result["status"] == "PARTIAL"
    assert "unverified" in result["reason"]
