"""Regression coverage for the sanitized source connector identity contract."""
import pytest

from navigan.modules.migration_management.resource_compatibility import evaluate_selected_resources


def evaluate(pod, *, current=True):
    resource = {"apiVersion": "apps/v1", "kind": "Deployment",
                "namespace": "apps", "name": "web", "pod": pod}
    result = evaluate_selected_resources(
        [resource], [{**resource, "treatment": "MIGRATE"}], [], [], [], [],
        target_current=current,
    )[0]
    identity = [check for check in result["checks"]
                if check["capability"] == "Identity and secrets"]
    return result, identity


@pytest.mark.parametrize("evidence", [
    {"imagePullSecretCount": 0},
    {"imagePullSecrets": []},
    {"imagePullSecrets": [], "imagePullSecretCount": 0},
])
def test_explicit_default_and_no_direct_references(evidence):
    result, identity = evaluate({"serviceAccountName": "default", **evidence})
    assert not identity
    assert result["status"] == "PENDING_EVIDENCE"


@pytest.mark.parametrize("evidence", [
    {"imagePullSecretCount": 2},
    {"imagePullSecrets": [{"name": "registry"}]},
    {"imagePullSecrets": [], "imagePullSecretCount": 1},
    {"imagePullSecrets": [{"name": "registry"}], "imagePullSecretCount": 0},
])
def test_reported_references_keep_authorization_pending(evidence):
    _, identity = evaluate({"serviceAccountName": "default", **evidence})
    assert identity[0]["status"] == "PENDING_EVIDENCE"
    assert "target authorization is unverified" in identity[0]["reason"]


@pytest.mark.parametrize("evidence", [
    {}, {"imagePullSecretCount": None}, {"imagePullSecretCount": -1},
    {"imagePullSecretCount": False}, {"imagePullSecretCount": "0"},
    {"imagePullSecrets": ""}, {"imagePullSecrets": [], "imagePullSecretCount": -1},
])
def test_missing_or_invalid_evidence_does_not_become_zero(evidence):
    _, identity = evaluate({"serviceAccountName": "default", **evidence})
    assert identity[0]["status"] == "PENDING_EVIDENCE"
    assert "trustworthy" in identity[0]["reason"]


@pytest.mark.parametrize("service_account", [None, "", "custom"])
def test_unconfirmed_or_named_service_account_stays_pending(service_account):
    _, identity = evaluate({"serviceAccountName": service_account, "imagePullSecretCount": 0})
    assert identity[0]["status"] == "PENDING_EVIDENCE"


def test_stale_evidence_still_blocks_readiness():
    result, identity = evaluate({"serviceAccountName": "default", "imagePullSecretCount": 0}, current=False)
    assert not identity
    assert result["status"] == "PENDING_EVIDENCE"
    assert any(c["capability"] == "Evidence freshness" for c in result["checks"])
