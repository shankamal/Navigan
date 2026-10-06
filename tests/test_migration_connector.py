import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from navigan.modules.migration_management import connector_handler
from navigan.modules.migration_management.connector_handler import (
    authenticate,
)
from navigan.modules.migration_management.models import (
    SourceInventoryReport,
    SourceCatalogueReport,
)
from navigan.shared.errors import ApiError


CONNECTOR_ID = "MGC-" + "a" * 32
TOKEN = "migration-connector-token-value-with-sufficient-length"
NOW = datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc)


def connector(
    *,
    token=TOKEN,
    status="ENROLLED",
    expires_at=None,
):
    return {
        "connector_id": CONNECTOR_ID,
        "migration_id": "MIG-" + "b" * 32,
        "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
        "status": status,
        "expires_at": expires_at or NOW + timedelta(hours=1),
    }


def headers(token=TOKEN):
    return {"Authorization": f"Bearer {token}"}


def test_accepts_valid_short_lived_connector():
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = connector()

    result = authenticate(db, CONNECTOR_ID, headers(), NOW)

    assert result["migration_id"] == "MIG-" + "b" * 32


def test_rejects_invalid_token_without_disclosing_state():
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = connector()

    with pytest.raises(ApiError) as error:
        authenticate(
            db,
            CONNECTOR_ID,
            headers("different-token-value-with-sufficient-length-123"),
            NOW,
        )

    assert error.value.code == "MIGRATION_CONNECTOR_UNAUTHENTICATED"


def test_rejects_expired_connector():
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = connector(
        expires_at=NOW - timedelta(seconds=1)
    )

    with pytest.raises(ApiError) as error:
        authenticate(db, CONNECTOR_ID, headers(), NOW)

    assert error.value.code == "MIGRATION_CONNECTOR_UNAUTHENTICATED"


def test_rejects_completed_connector():
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = connector(
        status="COMPLETED"
    )

    with pytest.raises(ApiError) as error:
        authenticate(db, CONNECTOR_ID, headers(), NOW)

    assert error.value.code == "MIGRATION_CONNECTOR_UNAUTHENTICATED"


def test_rejects_malformed_identity_before_database_access():
    db = MagicMock()

    with pytest.raises(ApiError) as error:
        authenticate(
            db,
            "MGC-invalid",
            headers(),
            NOW,
        )

    assert error.value.code == "MIGRATION_CONNECTOR_UNAUTHENTICATED"
    db.execute.assert_not_called()
def test_repository_persists_only_connector_token_digest():
    from types import SimpleNamespace

    from navigan.modules.migration_management.repository import (
        Repository,
    )

    db = MagicMock()
    db.execute.return_value.fetchone.side_effect = [
        None,
        {
            "connector_id": CONNECTOR_ID,
            "migration_id": "MIG-" + "b" * 32,
            "status": "ENROLLED",
            "expires_at": NOW + timedelta(minutes=30),
        },
    ]
    repository = Repository(
        db,
        SimpleNamespace(user_id="creator"),
    )

    result = repository.create_discovery_connector(
        "MIG-" + "b" * 32,
        TOKEN,
    )

    calls = repr(db.execute.call_args_list)
    assert TOKEN not in calls
    assert hashlib.sha256(TOKEN.encode()).hexdigest() in calls
    assert "token_sha256" not in result

def migration_row(status="SOURCE_ENROLLMENT_PENDING"):
    return {
        "migration_id": "MIG-" + "b" * 32,
        "customer_id": "CUS-demo",
        "name": "RetailFlow migration",
        "description": "Assessment only",
        "source_platform": "SELF_MANAGED_KUBERNETES",
        "target_platform": "EKS",
        "source_configuration": {
            "platform": "SELF_MANAGED_KUBERNETES",
            "clusterName": "migration-lab",
        },
        "target_configuration": {
            "platform": "EKS",
            "awsRegion": "ap-south-1",
        },
        "migration_scope": {
            "namespaces": ["retailflow"],
            "excludeNamespaces": ["kube-system"],
            "includePersistentData": False,
        },
        "execution_mode": "ASSESSMENT_ONLY",
        "status": status,
        "version": 2,
        "created_by": "creator",
        "updated_by": "creator",
        "created_at": NOW,
        "updated_at": NOW,
    }


def test_assignment_starts_read_only_discovery(monkeypatch):
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = migration_row()
    saved = {}

    class FakeRepository:
        def __init__(self, observed_db, principal):
            assert observed_db is db
            saved["principal"] = principal.user_id

        def save(self, row, old, action, correlation):
            saved["row"] = row
            saved["old"] = old
            saved["action"] = action
            saved["correlation"] = correlation

    monkeypatch.setattr(
        connector_handler,
        "Repository",
        FakeRepository,
    )

    result = connector_handler.assignment(
        db,
        connector(),
        NOW,
        "corr-1",
    )

    assert result["status"] == "INVENTORY_DISCOVERING"
    assert result["migrationVersion"] == 3
    assert result["scope"]["namespaces"] == ["retailflow"]
    assert saved["principal"] == CONNECTOR_ID
    assert saved["action"] == "MIGRATION_INVENTORY_STARTED"
    assert "ACTIVE" in repr(db.execute.call_args_list)


def test_assignment_is_idempotent_while_discovering(monkeypatch):
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = migration_row(
        "INVENTORY_DISCOVERING"
    )

    class UnexpectedRepository:
        def __init__(self, *_args):
            raise AssertionError(
                "Repeated assignment must not create a transition"
            )

    monkeypatch.setattr(
        connector_handler,
        "Repository",
        UnexpectedRepository,
    )

    result = connector_handler.assignment(
        db,
        connector(status="ACTIVE"),
        NOW,
        "corr-2",
    )

    assert result["status"] == "INVENTORY_DISCOVERING"
    assert result["migrationVersion"] == 2


def test_connector_assignment_rejects_other_methods():
    with pytest.raises(ApiError) as error:
        connector_handler.execute(
            {
                "rawPath": (
                    f"/api/v1/migration-connectors/"
                    f"{CONNECTOR_ID}/assignment"
                ),
                "requestContext": {
                    "http": {"method": "POST"}
                },
            },
            "corr-3",
        )

    assert error.value.code == "ROUTE_NOT_FOUND"

def source_inventory_report(migration_version=2):
    resources = [
        {
            "apiVersion": "v1",
            "kind": "Namespace",
            "name": "retailflow",
            "annotationKeys": [],
        }
    ]
    payload = {
        "schemaVersion": 1,
        "sensitiveDataIncluded": False,
        "resources": resources,
    }
    digest = hashlib.sha256(
        __import__("json").dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()

    return SourceInventoryReport.model_validate(
        {
            **payload,
            "migrationVersion": migration_version,
            "observedAt": "2026-10-05T08:00:00Z",
            "sourceKubernetesVersion": "v1.37.1",
            "inventoryDigest": digest,
        }
    )


def test_source_inventory_generates_trusted_assessment(
    monkeypatch,
):
    db = MagicMock()
    migration = migration_row("DISCOVERING")
    migration["target_configuration"] = {
        "platform": "EKS",
        "targetType": "EXISTING_CLUSTER",
        "clusterId": "CLU-demo",
        "clusterName": "demo-eks",
    }
    db.execute.return_value.fetchone.side_effect = [
        migration,
        {
            "cluster_id": "CLU-demo",
            "customer_id": "CUS-demo",
        },
        {
            "status": "READY",
            "connector_id": "CON-target",
            "source_revision": 1,
            "resources": [],
            "warning_events": [],
            "metrics": {
                "nodeCount": 3,
                "readyNodeCount": 3,
            },
            "observed_at": NOW,
            "expires_at": NOW.replace(hour=9),
        },
        {"inventory_version": 1},
        {"assessment_version": 1},
    ]
    saved = {
        "actions": [],
        "statuses": [],
    }

    class FakeRepository:
        def __init__(self, observed_db, principal):
            assert observed_db is db
            saved["principal"] = principal.user_id

        def save(self, row, old, action, correlation):
            saved["actions"].append(action)
            saved["statuses"].append(row["status"])
            saved["correlation"] = correlation

    monkeypatch.setattr(
        connector_handler,
        "Repository",
        FakeRepository,
    )

    result = connector_handler.submit_source_inventory(
        db,
        connector(status="ACTIVE"),
        source_inventory_report(),
        NOW,
        "corr-source-inventory",
    )

    assert result["status"] == "ASSESSMENT_READY"
    assert result["migrationVersion"] == 4
    assert result["inventoryVersion"] == 1
    assert result["assessmentVersion"] == 1
    assert result["resourceCount"] == 1
    assert result["compatibilityScore"] == 100
    assert result["containsBlockers"] is False

    assert saved["principal"] == CONNECTOR_ID
    assert saved["statuses"] == [
        "ASSESSING",
        "ASSESSMENT_READY",
    ]
    assert saved["actions"] == [
        "MIGRATION_SOURCE_INVENTORY_RECEIVED",
        "MIGRATION_ASSESSMENT_GENERATED",
    ]

    calls = repr(db.execute.call_args_list)
    assert "migration_source_inventories" in calls
    assert "migration_assessments" in calls
    assert "NAVIGAN_ASSESSMENT_ENGINE" in calls
    assert "COMPLETED" in calls


def test_source_inventory_rejects_cross_customer_target():
    db = MagicMock()
    migration = migration_row("DISCOVERING")
    migration["target_configuration"] = {
        "platform": "EKS",
        "targetType": "EXISTING_CLUSTER",
        "clusterId": "CLU-demo",
        "clusterName": "demo-eks",
    }
    db.execute.return_value.fetchone.side_effect = [
        migration,
        None,
    ]

    with pytest.raises(ApiError) as error:
        connector_handler.submit_source_inventory(
            db,
            connector(status="ACTIVE"),
            source_inventory_report(),
            NOW,
            "corr-target",
        )

    assert error.value.code == "TARGET_CLUSTER_NOT_AVAILABLE"


def test_source_inventory_rejects_stale_migration_version():
    db = MagicMock()
    current = migration_row("DISCOVERING")
    current["version"] = 3
    db.execute.return_value.fetchone.return_value = current

    with pytest.raises(ApiError) as error:
        connector_handler.submit_source_inventory(
            db,
            connector(status="ACTIVE"),
            source_inventory_report(migration_version=2),
            NOW,
            "corr-stale",
        )

    assert error.value.code == "STALE_MIGRATION_INVENTORY"

def source_catalogue_report(migration_version=2):
    catalogue = {
        "schemaVersion": 1,
        "sourceKubernetesVersion": "v1.37.1",
        "nodeCount": 3,
        "architectures": ["amd64"],
        "namespaces": [
            {
                "name": "retailflow",
                "resourceCounts": {
                    "Deployment": 3,
                    "Service": 2,
                },
            }
        ],
        "sensitiveDataIncluded": False,
    }
    digest = hashlib.sha256(
        __import__("json").dumps(
            catalogue,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()

    return SourceCatalogueReport.model_validate(
        {
            "version": 1,
            "migrationVersion": migration_version,
            "observedAt": "2026-10-05T12:30:00Z",
            "sourceKubernetesVersion": "v1.37.1",
            "inventoryDigest": digest,
            "nodeCount": 3,
            "architectures": ["amd64"],
            "namespaces": catalogue["namespaces"],
            "sensitiveDataIncluded": False,
        }
    )


def test_source_catalogue_is_stored_and_completes_connector(
    monkeypatch,
):
    db = MagicMock()
    db.execute.return_value.fetchone.side_effect = [
        migration_row("INVENTORY_DISCOVERING"),
        {"catalogue_version": 1},
    ]
    saved = {}

    class FakeRepository:
        def __init__(self, observed_db, principal):
            assert observed_db is db
            saved["principal"] = principal.user_id

        def save(self, row, old, action, correlation):
            saved["row"] = row
            saved["action"] = action
            saved["correlation"] = correlation

    monkeypatch.setattr(
        connector_handler,
        "Repository",
        FakeRepository,
    )

    result = connector_handler.submit_catalogue(
        db,
        connector(status="ACTIVE"),
        source_catalogue_report(),
        NOW,
        "corr-inventory",
    )

    assert result["status"] == "INVENTORY_READY"
    assert result["catalogueVersion"] == 1
    assert result["namespaceCount"] == 1
    assert saved["action"] == "MIGRATION_INVENTORY_RECEIVED"
    assert saved["row"]["source_configuration"][
        "kubernetesVersion"
    ] == "1.37.1"
    calls = repr(db.execute.call_args_list)
    assert "migration_source_catalogues" in calls
    assert "COMPLETED" in calls


def test_source_catalogue_rejects_invalid_digest():
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = migration_row(
        "INVENTORY_DISCOVERING"
    )
    report = source_catalogue_report()
    report.inventoryDigest = "0" * 64

    with pytest.raises(ApiError) as error:
        connector_handler.submit_catalogue(
            db,
            connector(status="ACTIVE"),
            report,
            NOW,
            "corr-invalid-digest",
        )

    assert error.value.code == "INVALID_INVENTORY_DIGEST"
