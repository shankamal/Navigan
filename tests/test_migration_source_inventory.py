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
    assert len(report.resources) == 2
    assert report.sensitiveDataIncluded is False


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


def test_rejects_system_namespace_inventory():
    payload = copy.deepcopy(source_inventory())
    resource_by_kind(payload, "Namespace")["name"] = (
        "kube-system"
    )

    with pytest.raises(
        ValidationError,
        match="System namespaces cannot be assessed",
    ):
        SourceInventoryReport.model_validate(payload)


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
