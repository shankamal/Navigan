import copy

import pytest
from pydantic import ValidationError

from migration_connector.inventory import build_inventory
from navigan.modules.migration_management.models import (
    SourceInventoryReport,
)


def source_inventory():
    inventory = build_inventory(
        [
            {
                "apiVersion": "v1",
                "kind": "Namespace",
                "metadata": {"name": "retailflow"},
            },
            {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "metadata": {
                    "name": "api",
                    "namespace": "retailflow",
                },
                "spec": {
                    "replicas": 2,
                    "template": {
                        "spec": {
                            "containers": [
                                {
                                    "name": "api",
                                    "image": "example/api:v1",
                                    "securityContext": {
                                        "privileged": False,
                                    },
                                }
                            ]
                        }
                    },
                },
            },
            {
                "apiVersion": "autoscaling/v2",
                "kind": "HorizontalPodAutoscaler",
                "metadata": {
                    "name": "api",
                    "namespace": "retailflow",
                },
                "spec": {
                    "minReplicas": 2,
                    "maxReplicas": 8,
                    "scaleTargetRef": {
                        "kind": "Deployment",
                        "name": "api",
                    },
                },
            },
            {
                "apiVersion": "policy/v1",
                "kind": "PodDisruptionBudget",
                "metadata": {
                    "name": "api",
                    "namespace": "retailflow",
                },
                "spec": {
                    "minAvailable": 1,
                },
            },
            {
                "apiVersion": "v1",
                "kind": "Node",
                "metadata": {"name": "worker-1"},
                "status": {
                    "nodeInfo": {
                        "kubeletVersion": "v1.30.1",
                        "operatingSystem": "linux",
                        "architecture": "amd64",
                    }
                },
            },
            {
                "apiVersion": "v1",
                "kind": "Node",
                "metadata": {"name": "worker-2"},
                "status": {
                    "nodeInfo": {
                        "kubeletVersion": "v1.30.1",
                        "operatingSystem": "linux",
                        "architecture": "amd64",
                    }
                },
            },
        ]
    )
    return {
        **inventory,
        "migrationVersion": 4,
        "observedAt": "2026-10-05T12:30:00Z",
        "sourceKubernetesVersion": "v1.37.1",
    }


def test_accepts_connector_generated_sanitized_inventory():
    report = SourceInventoryReport.model_validate(
        source_inventory()
    )

    assert report.schemaVersion == 1
    assert len(report.resources) == 6
    assert report.sensitiveDataIncluded is False
    hpa = next(
        resource
        for resource in report.resources
        if resource["kind"] == "HorizontalPodAutoscaler"
    )
    pdb = next(
        resource
        for resource in report.resources
        if resource["kind"] == "PodDisruptionBudget"
    )
    assert hpa["minimumReplicas"] == 2
    assert hpa["maximumReplicas"] == 8
    assert pdb["minimumAvailable"] == 1
    assert sum(
        resource["kind"] == "Node"
        for resource in report.resources
    ) == 2


def resource_by_kind(payload, kind):
    return next(
        resource
        for resource in payload["resources"]
        if resource["kind"] == kind
    )


def test_rejects_inventory_digest_tampering():
    payload = source_inventory()
    resource_by_kind(payload, "Deployment")["replicas"] = 99

    with pytest.raises(
        ValidationError,
        match="digest validation failed",
    ):
        SourceInventoryReport.model_validate(payload)


def test_rejects_sensitive_nested_keys():
    payload = source_inventory()
    resource_by_kind(
        payload,
        "Deployment",
    )["pod"]["secretName"] = "customer-secret"

    with pytest.raises(
        ValidationError,
        match="Sensitive inventory key is forbidden",
    ):
        SourceInventoryReport.model_validate(payload)


def test_allows_sanitized_read_only_system_namespace_inventory():
    from migration_connector.inventory import finalize_inventory
    payload = copy.deepcopy(source_inventory())
    resource_by_kind(payload, "Namespace")["name"] = "kube-system"
    payload.update(finalize_inventory(payload["resources"]))
    report = SourceInventoryReport.model_validate(payload)
    assert any(item.get("name") == "kube-system" for item in report.resources)


def test_migration_schema_has_immutable_source_inventory_table():
    sql = (
        __import__("pathlib")
        .Path("database/migrations/022_migration_management.sql")
        .read_text()
    )

    assert (
        "migration_management.migration_source_inventories"
        in sql
    )
    assert "PRIMARY KEY(migration_id,inventory_version)" in sql
    assert "migration_source_inventory_digest_uq" in sql
    assert (
        "REVOKE ALL\n"
        " ON migration_management.migration_source_inventories"
        in sql
    )

def test_connector_retains_reference_names_without_secret_values():
    from migration_connector.inventory import sanitize_resource

    resource = {
        "apiVersion": "apps/v1", "kind": "Deployment",
        "metadata": {"name": "api", "namespace": "retailflow"},
        "spec": {"template": {"spec": {
            "serviceAccountName": "api-sa",
            "imagePullSecrets": [{"name": "registry-auth"}],
            "volumes": [
                {"name": "config", "configMap": {"name": "api-config"}},
                {"name": "data", "persistentVolumeClaim": {"claimName": "data-pvc"}},
                {"name": "secret", "secret": {"secretName": "app-cert"}},
            ],
            "containers": [{"name": "api", "image": "example:1",
                "env": [{"name": "PASSWORD", "valueFrom": {"secretKeyRef": {"name": "database-secret", "key": "password"}}}],
                "envFrom": [{"configMapRef": {"name": "runtime-config"}}],
            }],
        }}},
    }
    inventory = sanitize_resource(resource)
    assert inventory["dependencyReferences"] == [
        {"kind": "ConfigMap", "name": "api-config"},
        {"kind": "ConfigMap", "name": "runtime-config"},
        {"kind": "PersistentVolumeClaim", "name": "data-pvc"},
        {"kind": "Secret", "name": "app-cert"},
        {"kind": "Secret", "name": "database-secret"},
        {"kind": "Secret", "name": "registry-auth"},
        {"kind": "ServiceAccount", "name": "api-sa"},
    ]
    assert "password" not in str(inventory)
    assert "PASSWORD" in str(inventory)  # Existing metadata retains variable names only.


def test_rejects_unexpected_dependency_reference_fields():
    payload = source_inventory()
    deployment = resource_by_kind(payload, "Deployment")
    deployment["dependencyReferences"] = [{"kind": "Secret", "name": "db", "value": "forbidden"}]
    with pytest.raises(ValidationError, match="Invalid inventory dependency reference"):
        SourceInventoryReport.model_validate(payload)


def test_rejects_unsupported_dependency_reference_kinds():
    payload = source_inventory()
    deployment = resource_by_kind(payload, "Deployment")
    deployment["dependencyReferences"] = [{"kind": "Node", "name": "worker"}]
    with pytest.raises(ValidationError, match="Unsupported inventory dependency kind"):
        SourceInventoryReport.model_validate(payload)


def test_service_selector_relationships_preserve_privacy_and_namespace():
    from migration_connector.inventory import build_inventory

    def deployment(namespace, labels):
        return {
            "apiVersion": "apps/v1", "kind": "Deployment",
            "metadata": {"name": "api", "namespace": namespace},
            "spec": {"template": {
                "metadata": {"labels": labels},
                "spec": {"containers": [{"name": "app", "image": "example:1"}]},
            }},
        }

    def service(namespace, name, selector):
        return {
            "apiVersion": "v1", "kind": "Service",
            "metadata": {"name": name, "namespace": namespace},
            "spec": {"selector": selector},
        }

    inventory = build_inventory([
        deployment("retailflow", {"app": "retail-api", "sensitive-label": "not-exported"}),
        service("retailflow", "api-svc", {"app": "retail-api"}),
        service("retailflow", "headless", {}),
        service("another", "api-svc", {"app": "retail-api"}),
    ])
    workload = resource_by_kind(inventory, "Deployment")
    assert {"kind": "Service", "name": "api-svc"} in workload["dependencyReferences"]
    assert {"kind": "Service", "name": "headless"} not in workload["dependencyReferences"]
    assert "not-exported" not in str(inventory)
    SourceInventoryReport.model_validate({
        **inventory, "migrationVersion": 4,
        "observedAt": "2026-10-11T12:00:00Z",
        "sourceKubernetesVersion": "v1.37.1",
    })


def test_ingress_backend_services_are_sanitized_and_validated():
    from migration_connector.inventory import build_inventory
    objects = [
        {"apiVersion": "networking.k8s.io/v1", "kind": "Ingress",
         "metadata": {"name": "edge", "namespace": "retailflow"},
         "spec": {"defaultBackend": {"service": {"name": "fallback", "port": {"number": 80}}},
                  "tls": [{"hosts": ["private.example.com"], "secretName": "edge-cert"}],
                  "rules": [{"host": "private.example.com", "http": {"paths": [
                      {"path": "/private", "pathType": "Prefix", "backend": {
                          "service": {"name": "retail-api", "port": {"number": 8080}}}}
                  ]}}]}},
    ]
    inventory = build_inventory(objects)
    ingress = resource_by_kind(inventory, "Ingress")
    assert ingress["backendServiceReferences"] == [
        {"kind": "Service", "name": "fallback"},
        {"kind": "Service", "name": "retail-api"},
    ]
    assert "private.example.com" not in str(inventory)
    assert "edge-cert" not in str(inventory)
    SourceInventoryReport.model_validate({
        **inventory, "migrationVersion": 4,
        "observedAt": "2026-10-11T12:00:00Z",
        "sourceKubernetesVersion": "v1.37.1",
    })


def test_rejects_unexpected_ingress_backend_payload():
    payload = source_inventory()
    from migration_connector.inventory import build_inventory
    incoming = build_inventory([{
        "apiVersion": "networking.k8s.io/v1", "kind": "Ingress",
        "metadata": {"name": "edge", "namespace": "retailflow"},
        "spec": {},
    }])
    payload["resources"].append(incoming["resources"][0])
    payload["resources"][-1]["backendServiceReferences"] = [
        {"kind": "Service", "name": "api", "host": "private.example.com"}
    ]
    with pytest.raises(ValidationError, match="Invalid ingress backend reference"):
        SourceInventoryReport.model_validate(payload)


def statefulset_inventory():
    inventory = build_inventory([{
        "apiVersion": "apps/v1",
        "kind": "StatefulSet",
        "metadata": {"name": "postgres", "namespace": "retailflow"},
        "spec": {"volumeClaimTemplates": [{
            "metadata": {"name": "data"},
            "spec": {"storageClassName": "private-storage-config"},
        }]},
    }])
    return {
        **inventory,
        "migrationVersion": 4,
        "observedAt": "2026-10-19T08:30:00Z",
        "sourceKubernetesVersion": "v1.37.1",
    }


def test_accepts_connector_statefulset_claim_template_names_without_raw_configuration():
    import json

    report = statefulset_inventory()
    validated = SourceInventoryReport.model_validate(report)
    assert validated.resources[0]["volumeClaimTemplateNames"] == ["data"]
    assert "private-storage-config" not in json.dumps(report)


@pytest.mark.parametrize("names", [None, "data", [{}], [""], ["x" * 254], ["data", "data"], [str(i) for i in range(101)]])
def test_rejects_invalid_statefulset_claim_template_metadata(names):
    report = statefulset_inventory()
    report["resources"][0]["volumeClaimTemplateNames"] = names
    with pytest.raises(ValidationError, match="StatefulSet volume claim template"):
        SourceInventoryReport.model_validate(report)


def test_all_supported_collector_resource_kinds_match_backend_inventory_contract():
    from migration_connector.inventory import SUPPORTED_KINDS

    for kind in sorted(SUPPORTED_KINDS):
        inventory = build_inventory([{
            "apiVersion": "v1",
            "kind": kind,
            "metadata": {"name": "example", "namespace": "retailflow"},
            "spec": {"template": {"spec": {}}, "jobTemplate": {"spec": {"template": {"spec": {}}}}},
        }])
        SourceInventoryReport.model_validate({
            **inventory,
            "migrationVersion": 1,
            "observedAt": "2026-10-19T08:30:00Z",
            "sourceKubernetesVersion": "v1.37.1",
        })
