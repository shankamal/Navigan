import hashlib
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from navigan.modules.cluster_management import connector_handler
from navigan.shared.errors import ApiError


def event(token="connector-token-value-with-sufficient-length", body=None):
    return {
        "rawPath": (
            "/api/v1/connectors/"
            "KCC-0123456789abcdef0123456789abcdef/inventory/namespaces"
        ),
        "headers": {
            "authorization": f"Bearer {token}",
            "content-type": "application/json",
        },
        "body": __import__("json").dumps(
            body or {
                "revision": 10,
                "namespaces": [{"name": "apps"}, {"name": "kube-system"}],
            }
        ),
        "requestContext": {"http": {"method": "POST"}, "stage": "$default"},
    }


def test_connector_rejects_invalid_token_without_disclosing_connector_state(monkeypatch):
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = {
        "connector_id": "KCC-0123456789abcdef0123456789abcdef",
        "cluster_id": "CLU-test",
        "token_sha256": hashlib.sha256(b"different-token").hexdigest(),
        "status": "ACTIVE",
    }

    @contextmanager
    def tx():
        yield db

    monkeypatch.setattr(connector_handler, "transaction", tx)
    with pytest.raises(ApiError) as error:
        connector_handler.execute(event(), "correlation")

    assert error.value.code == "CONNECTOR_UNAUTHENTICATED"


def test_connector_rejects_stale_inventory_revision(monkeypatch):
    token = "connector-token-value-with-sufficient-length"
    db = MagicMock()
    db.execute.return_value.fetchone.side_effect = [
        {
            "connector_id": "KCC-0123456789abcdef0123456789abcdef",
            "cluster_id": "CLU-test",
            "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
            "status": "ACTIVE",
        },
        {"source_revision": 10},
    ]

    @contextmanager
    def tx():
        yield db

    monkeypatch.setattr(connector_handler, "transaction", tx)
    with pytest.raises(ApiError) as error:
        connector_handler.execute(event(token), "correlation")

    assert error.value.code == "STALE_CONNECTOR_REVISION"


def test_connector_rejects_invalid_namespace_before_database_access(monkeypatch):
    tx = MagicMock()
    monkeypatch.setattr(connector_handler, "transaction", tx)

    with pytest.raises(Exception):
        connector_handler.execute(
            event(body={"revision": 11, "namespaces": [{"name": "Not_Valid"}]}),
            "correlation",
        )

    tx.assert_not_called()


def test_connector_returns_desired_access_rules(monkeypatch):
    token = "connector-token-value-with-sufficient-length"
    db = MagicMock()
    db.execute.return_value.fetchone.side_effect = [
        {
            "connector_id": "KCC-0123456789abcdef0123456789abcdef",
            "cluster_id": "CLU-test",
            "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
            "status": "ACTIVE",
        },
        {"revision": 1234},
    ]
    db.execute.return_value.fetchall.return_value = [
        {
            "assignment_id": "KAA-0123456789abcdef0123456789abcdef",
            "subject_type": "USER",
            "subject_id": "cognito-subject",
            "namespace": "apps",
            "profile_code": "NAMESPACE_VIEWER",
            "scope_type": "NAMESPACE",
            "permissions": [{"apiGroups": [""], "resources": ["pods"], "verbs": ["get"]}],
            "created_at": None,
        }
    ]

    @contextmanager
    def tx():
        yield db

    monkeypatch.setattr(connector_handler, "transaction", tx)
    request = event(token)
    request["rawPath"] = (
        "/api/v1/connectors/"
        "KCC-0123456789abcdef0123456789abcdef/access/desired"
    )
    request["requestContext"]["http"]["method"] = "GET"
    request["headers"].pop("content-type")

    result = connector_handler.execute(request, "correlation")

    assert result["revision"] == 1234
    assert result["assignments"][0]["subjectId"] == "cognito-subject"
    assert result["assignments"][0]["rules"][0]["resources"] == ["pods"]


def test_connector_acknowledgement_activates_pending_assignment(monkeypatch):
    token = "connector-token-value-with-sufficient-length"
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = {
        "connector_id": "KCC-0123456789abcdef0123456789abcdef",
        "cluster_id": "CLU-test",
        "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
        "status": "ACTIVE",
    }

    @contextmanager
    def tx():
        yield db

    monkeypatch.setattr(connector_handler, "transaction", tx)
    request = event(
        token,
        {
            "revision": 1234,
            "results": [
                {
                    "assignmentId": "KAA-0123456789abcdef0123456789abcdef",
                    "status": "APPLIED",
                }
            ],
        },
    )
    request["rawPath"] = (
        "/api/v1/connectors/"
        "KCC-0123456789abcdef0123456789abcdef/access/status"
    )

    result = connector_handler.execute(request, "correlation")

    assert result["appliedCount"] == 1
    statements = [call.args[0] for call in db.execute.call_args_list]
    assert any("SET status='ACTIVE'" in sql for sql in statements)


def test_connector_accepts_runtime_inventory(monkeypatch):
    token = "connector-token-value-with-sufficient-length"
    db = MagicMock()
    db.execute.return_value.fetchone.side_effect = [
        {
            "connector_id": "KCC-0123456789abcdef0123456789abcdef",
            "cluster_id": "CLU-test",
            "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
            "status": "ACTIVE",
        },
        None,
        None,
        None,
    ]

    @contextmanager
    def tx():
        yield db

    monkeypatch.setattr(connector_handler, "transaction", tx)
    request = event(
        token,
        {
            "revision": 1234,
            "components": [
                {
                    "code": "connector",
                    "status": "READY",
                    "healthStatus": "Healthy",
                }
            ],
            "runtime": {
            "resources": [
                {
                    "kind": "Deployment",
                    "namespace": "apps",
                    "name": "checkout",
                    "status": "HEALTHY",
                    "ready": 2,
                    "desired": 2,
                    "restarts": 0,
                }
            ],
            "warningEvents": [],
            "metrics": {
                "nodeCount": 2,
                "readyNodeCount": 2,
                "podCount": 8,
                "readyPodCount": 8,
            },
            },
        },
    )
    request["rawPath"] = (
        "/api/v1/connectors/"
        "KCC-0123456789abcdef0123456789abcdef/inventory/platform-components"
    )

    result = connector_handler.execute(request, "correlation")

    assert result["status"] == "ACCEPTED"
    assert result["runtimeResourceCount"] == 1
    statements = [call.args[0] for call in db.execute.call_args_list]
    assert any("cluster_runtime_inventories" in sql for sql in statements)


def test_successful_reconciliation_completes_bootstrap_after_inventory_is_ready():
    db = MagicMock()
    db.execute.return_value.fetchone.side_effect = [
        {"status": "READY"},
        {"namespace_count": 3},
        {
            "cluster_id": "CLU-test",
            "status": "BOOTSTRAPPING",
            "version": 4,
            "workflow": {"platformBootstrap": {"status": "RUNNING"}},
            "configuration": {
                "platformBaseline": {
                    "readinessContract": "PLATFORM_COMPONENTS_V1",
                    "requiredComponents": ["connector", "argocd"],
                    "components": ["connector", "argocd"],
                }
            },
        },
    ]
    db.execute.return_value.fetchall.return_value = [
        {"component_code": "connector", "status": "READY"},
        {"component_code": "argocd", "status": "READY"},
    ]

    connector_handler.complete_platform_bootstrap(
        db,
        {
            "connector_id": "KCC-0123456789abcdef0123456789abcdef",
            "cluster_id": "CLU-test",
        },
        datetime.now(timezone.utc),
        "correlation",
    )

    statements = [call.args[0] for call in db.execute.call_args_list]
    assert any(
        "SET status='ACTIVE',version=%s,workflow=%s::jsonb" in sql
        for sql in statements
    )
    assert any("ClusterPlatformBootstrapCompleted" in sql for sql in statements)


def test_legacy_platform_baseline_requires_the_reported_connector_code():
    assert connector_handler.required_platform_components(
        {
            "components": [
                "navigan-connector",
                "argocd",
                "falco",
                "prometheus",
                "grafana",
                "headlamp",
            ]
        }
    ) == {
        "connector",
        "argocd",
        "falco",
        "prometheus",
        "grafana",
        "headlamp",
    }


def test_bootstrap_remains_pending_until_namespace_inventory_is_ready():
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = {"status": "NOT_CONFIGURED"}

    connector_handler.complete_platform_bootstrap(
        db,
        {
            "connector_id": "KCC-0123456789abcdef0123456789abcdef",
            "cluster_id": "CLU-test",
        },
        datetime.now(timezone.utc),
        "correlation",
    )

    statements = [call.args[0] for call in db.execute.call_args_list]
    assert not any("SET status='ACTIVE'" in sql for sql in statements)
