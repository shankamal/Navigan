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
    assert result["status"] == "EVIDENCE_UNAVAILABLE"
    assert "future controlled source discovery is required" in result["reason"]


def test_explicit_empty_references_are_distinct_from_legacy_missing_evidence():
    legacy = [resource("Deployment", "legacy", api_version="apps/v1")]
    current = [resource("Deployment", "current", [], api_version="apps/v1")]
    assert discover_dependencies(legacy)["status"] == "EVIDENCE_UNAVAILABLE"
    assert discover_dependencies(current)["status"] == "PARTIAL"



def test_legacy_pod_summary_recovers_only_explicit_service_account():
    inventory = [
        {**resource("Deployment", "api", api_version="apps/v1"),
         "pod": {"serviceAccountName": "api-sa",
                 "volumes": [{"name": "config", "type": "configMap"}]}},
        resource("ServiceAccount", "api-sa"),
        resource("ConfigMap", "config"),
    ]
    result = discover_dependencies(inventory)
    assert result["status"] == "EVIDENCE_UNAVAILABLE"
    assert result["relationshipCount"] == 1
    assert result["relationships"][0]["target"]["name"] == "api-sa"
    assert "ConfigMap" not in {e["target"]["kind"] for e in result["relationships"]}


def test_legacy_pod_summary_flags_missing_named_service_account():
    inventory = [
        {**resource("StatefulSet", "db", api_version="apps/v1"),
         "pod": {"serviceAccountName": "db-sa"}},
    ]
    result = discover_dependencies(inventory)
    assert result["status"] == "EVIDENCE_UNAVAILABLE"
    assert result["unresolvedCount"] == 1
    assert result["unresolvedReferences"][0]["target"]["name"] == "db-sa"
