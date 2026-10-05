from unittest.mock import MagicMock

from navigan.modules.migration_management.repository import Repository


def test_source_catalogue_is_customer_scoped_and_sanitized():
    database = MagicMock()
    repository = Repository(database, MagicMock())

    repository.get = MagicMock(
        return_value={
            "migration_id": "MIG-" + "a" * 32,
            "version": 4,
            "status": "INVENTORY_READY",
        }
    )
    database.execute.return_value.fetchone.return_value = {
        "catalogue_version": 1,
        "migration_version": 3,
        "schema_version": 1,
        "observed_at": "2026-10-05T12:30:00+00:00",
        "source_kubernetes_version": "v1.37.1",
        "inventory_digest": "a" * 64,
        "node_count": 3,
        "architectures": ["amd64"],
        "namespaces": [
            {
                "name": "retailflow",
                "resourceCounts": {
                    "Deployment": 2,
                    "Service": 1,
                },
            }
        ],
        "created_at": "2026-10-05T12:30:01+00:00",
    }

    identifier = "MIG-" + "a" * 32
    result = repository.get_source_catalogue(identifier)

    repository.get.assert_called_once_with(identifier)
    assert result["status"] == "INVENTORY_READY"
    assert result["catalogue"]["nodeCount"] == 3
    assert "connectorToken" not in str(result)
    assert "tokenSha256" not in str(result)


def test_source_catalogue_returns_pending_without_fake_data():
    database = MagicMock()
    repository = Repository(database, MagicMock())

    repository.get = MagicMock(
        return_value={
            "migration_id": "MIG-" + "b" * 32,
            "version": 2,
            "status": "INVENTORY_DISCOVERING",
        }
    )
    database.execute.return_value.fetchone.return_value = None

    result = repository.get_source_catalogue(
        "MIG-" + "b" * 32
    )

    assert result["catalogue"] is None
    assert result["status"] == "INVENTORY_DISCOVERING"
