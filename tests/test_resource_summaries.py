"""Aggregated metrics must share the same customer scope as list endpoints."""

from unittest.mock import MagicMock

from navigan.shared.auth import Principal
from navigan.modules.customer_management.repository import Repository as Customers
from navigan.modules.environment_management.repository import Repository as Environments
from navigan.modules.cluster_management.repository import Repository as Clusters


def scoped_principal():
    return Principal("engineer-1", frozenset({"CLOUD_ENGINEER"}), frozenset({"CUS-allowed"}))


def result(rows):
    cursor = MagicMock()
    cursor.fetchall.return_value = rows
    return cursor


def test_customer_summary_counts_each_customer_once_per_provider():
    db = MagicMock()
    db.execute.side_effect = [
        result([{"status": "ACTIVE", "n": 2}, {"status": "DRAFT", "n": 1}]),
        result([{"provider_code": "AWS", "n": 2}, {"provider_code": "GCP", "n": 1}]),
    ]
    summary = Customers(db, scoped_principal()).summary()
    assert summary == {"total": 3, "byStatus": {"ACTIVE": 2, "DRAFT": 1}, "byProvider": {"AWS": 2, "GCP": 1}}
    for call in db.execute.call_args_list:
        assert "c.customer_id = ANY(%s)" in call.args[0]
        assert call.args[1][0] == ["CUS-allowed"]
    assert "count(DISTINCT c.customer_id)" in db.execute.call_args_list[1].args[0]


def test_environment_summary_aggregates_status_and_provider_with_customer_scope():
    db = MagicMock()
    db.execute.return_value = result([
        {"status": "ACTIVE", "provider_code": "AWS", "n": 2},
        {"status": "ACTIVE", "provider_code": "AZURE", "n": 1},
        {"status": "DRAFT", "provider_code": "AWS", "n": 4},
    ])
    summary = Environments(db, scoped_principal()).summary()
    assert summary == {"total": 7, "byStatus": {"ACTIVE": 3, "DRAFT": 4}, "byProvider": {"AWS": 6, "AZURE": 1}}
    sql, params = db.execute.call_args.args
    assert "JOIN customer_management.customers c" in sql
    assert "c.customer_id = ANY(%s)" in sql
    assert params[0] == ["CUS-allowed"]


def test_cluster_summary_excludes_archived_clusters_and_scopes_access():
    db = MagicMock()
    db.execute.return_value = result([{"status": "ACTIVE", "n": 2}, {"status": "FAILED", "n": 1}])
    summary = Clusters(db, scoped_principal()).summary()
    assert summary == {"total": 3, "byStatus": {"ACTIVE": 2, "FAILED": 1}, "byProvider": {}}
    sql, params = db.execute.call_args.args
    assert "ownershipStatus" in sql
    assert "c.customer_id = ANY(%s)" in sql
    assert params[0] == ["CUS-allowed"]
