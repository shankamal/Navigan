from navigan.modules.migration_management.dependency_evidence import discover_dependencies


def resource(kind, name, spec=None, namespace="apps", api_version="v1"):
    return {
        "apiVersion": api_version,
        "kind": kind,
        "namespace": namespace,
        "name": name,
        "spec": spec or {},
    }


def test_discovers_only_actual_references_and_surfaces_missing():
    inventory = [
        resource("Deployment", "orders", {
            "template": {"spec": {
                "serviceAccountName": "orders-sa",
                "volumes": [
                    {"name": "data", "persistentVolumeClaim": {"claimName": "orders-data"}},
                    {"name": "settings", "configMap": {"name": "orders-config"}},
                ],
                "containers": [{
                    "name": "app",
                    "envFrom": [{"secretRef": {"name": "missing-secret"}}],
                }],
            }},
        }, api_version="apps/v1"),
        resource("ServiceAccount", "orders-sa"),
        resource("PersistentVolumeClaim", "orders-data"),
        resource("ConfigMap", "orders-config"),
    ]
    result = discover_dependencies(inventory)
    assert result["status"] == "PARTIAL"
    assert result["relationshipCount"] == 3
    assert result["unresolvedCount"] == 1
    assert {e["target"]["kind"] for e in result["relationships"]} == {
        "ServiceAccount", "PersistentVolumeClaim", "ConfigMap"
    }
    assert result["unresolvedReferences"][0]["target"]["name"] == "missing-secret"


def test_selected_workloads_are_scoped_and_cross_namespace_is_not_inferred():
    inventory = [
        resource("Pod", "selected", {"volumes": [
            {"configMap": {"name": "config"}},
        ]}),
        resource("Pod", "unselected", {"volumes": [
            {"secret": {"secretName": "private"}},
        ]}),
        resource("ConfigMap", "config", namespace="elsewhere"),
        resource("Secret", "private"),
    ]
    selected = {("v1", "Pod", "apps", "selected")}
    result = discover_dependencies(inventory, selected)
    assert result["relationshipCount"] == 0
    assert result["unresolvedCount"] == 2  # default service account and config
    assert all(e["source"]["name"] == "selected" for e in result["unresolvedReferences"])


def test_cronjob_template_and_projected_references_are_recognized():
    inventory = [
        resource("CronJob", "cleanup", {"jobTemplate": {"spec": {
            "template": {"spec": {
                "serviceAccountName": "batch",
                "volumes": [{"projected": {"sources": [
                    {"configMap": {"name": "batch-settings"}}
                ]}}],
            }}
        }}}, api_version="batch/v1"),
        resource("ServiceAccount", "batch"),
        resource("ConfigMap", "batch-settings"),
    ]
    result = discover_dependencies(inventory)
    assert result["relationshipCount"] == 2
    assert result["unresolvedCount"] == 0


def test_empty_inventory_does_not_claim_complete_graph():
    result = discover_dependencies([])
    assert result["status"] == "PARTIAL"
    assert result["relationshipCount"] == 0
    assert "external dependencies remain unverified" in result["reason"]
