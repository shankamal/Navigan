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


def test_latest_assessment_is_customer_scoped():
    database = MagicMock()
    repository = Repository(database, MagicMock())
    identifier = "MIG-" + "d" * 32

    repository.get = MagicMock(
        return_value={
            "migration_id": identifier,
            "version": 8,
            "status": "ASSESSMENT_READY",
        }
    )
    database.execute.return_value.fetchone.return_value = {
        "assessment_version": 1,
        "migration_version": 6,
        "report_schema_version": 1,
        "source_kubernetes_version": "v1.37.1",
        "observed_at": "2026-10-06T08:00:00+00:00",
        "inventory_digest": "a" * 64,
        "compatibility_score": 84,
        "contains_blockers": False,
        "inventory_summary": {
            "resourceCount": 12,
            "classification": {
                "SEAMLESS": 8,
                "AUTOMATED_CHANGE": 2,
                "MANUAL_CHANGE": 2,
                "BLOCKER": 0,
            },
        },
        "findings": [],
        "created_by": "NAVIGAN_ASSESSMENT_ENGINE",
        "created_at": "2026-10-06T08:00:01+00:00",
    }

    result = repository.get_assessment(identifier)

    repository.get.assert_called_once_with(identifier)
    assert result["status"] == "ASSESSMENT_READY"
    assert result["assessment"]["compatibilityScore"] == 84
    assert result["assessment"]["containsBlockers"] is False
