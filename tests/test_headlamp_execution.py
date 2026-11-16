from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from navigan.modules.cluster_management.utility_gitops import HeadlampGitOps
from navigan.modules.cluster_management.utility_upgrades import UtilityUpgradePlans
from navigan.modules.cluster_management.upgrade_plans import utcnow
from navigan.shared.access import EffectiveAccess, Scope
from navigan.shared.errors import ApiError


def setup(status="SCHEDULED", minutes=-1):
    repo = MagicMock()
    repo.get.return_value = {"status": "ACTIVE"}
    access = EffectiveAccess(
        "engineer",
        "Engineer",
        1,
        frozenset({"cluster.upgrade.execute", "cluster.upgrade.plan"}),
        (Scope("PLATFORM"),),
    )
    service = UtilityUpgradePlans(repo, access, "test")
    policy = {"adapter": HeadlampGitOps.ADAPTER, "durationMinutes": 120}
    plan = {
        "plan_id": "UPG-example",
        "cluster_id": "CLU-example",
        "utility_code": "headlamp",
        "version": 4,
        "status": status,
        "current_version": "0.45.0",
        "target_version": "0.46.0",
        "created_by": "engineer",
        "submitted_by": "engineer",
        "approved_by": "architect",
        "scheduled_for": utcnow() + timedelta(minutes=minutes),
        "readiness_evidence": {"executionPolicy": policy},
        "execution": {"compatibilityReview": {"actorId": "architect", "adapter": HeadlampGitOps.ADAPTER}},
    }
    service.get = MagicMock(side_effect=lambda *a, **kw: plan)
    service._save = MagicMock()
    service._audit = MagicMock()
    service.present = lambda row: row
    adapter = MagicMock()
    adapter.prepare.return_value = {"commit": "commit", "baseCommit": "base", "targetManifestHash": "hash"}
    adapter.publication_state.return_value = "UNPUBLISHED"
    service._headlamp_adapter = MagicMock(return_value=adapter)
    observe(repo, "0.45.0")
    return service, repo, adapter, plan


def observe(repo, version, **overrides):
    now = utcnow().isoformat()
    component = {
        "componentCode": "headlamp",
        "status": "READY",
        "syncStatus": "Synced",
        "healthStatus": "Healthy",
        "version": version,
        "observedAt": now,
        "sourceRevision": 8,
    }
    component.update(overrides)
    repo.platform_components.return_value = {
        "components": [component],
        "runtimeInventory": {
            "status": "READY",
            "observedAt": now,
            "expiresAt": (utcnow() + timedelta(minutes=5)).isoformat(),
            "resources": [
                {
                    "kind": "Deployment",
                    "name": "navigan-dashboard-headlamp",
                    "namespace": "navigan-dashboard",
                    "ready": 2,
                    "desired": 2,
                }
            ],
        },
    }


def test_execute_only_persists_prepared_intent_and_never_publishes():
    service, _, adapter, _ = setup()
    result = service.change("CLU-example", "UPG-example", "execute", {"version": 4})
    assert result["status"] == "EXECUTING"
    assert result["execution"]["phase"] == "GITOPS_PREPARED"
    assert result["execution"]["intent"]["commit"] == "commit"
    adapter.publish.assert_not_called()
    service._save.assert_called_once_with(result)


def test_publish_then_verify_requires_a_later_fresh_target_and_ready_workload():
    service, repo, adapter, old = setup()
    prepared = service.change("CLU-example", "UPG-example", "execute", {"version": 4})
    old.update(prepared)
    published = service.change("CLU-example", "UPG-example", "refresh", {"version": 5})
    assert published["status"] == "EXECUTING"
    assert published["execution"]["phase"] == "WAITING_FOR_ARGO"
    assert adapter.publish.call_count == 1
    old.update(published)
    adapter.publication_state.return_value = "PUBLISHED"
    waiting = service.change("CLU-example", "UPG-example", "refresh", {"version": 6})
    assert waiting["status"] == "EXECUTING"
    old.update(waiting)
    observe(repo, "0.46.0")
    success = service.change("CLU-example", "UPG-example", "refresh", {"version": 7})
    assert success["status"] == "SUCCEEDED"
    assert success["execution"]["verifiedChartVersion"] == "0.46.0"
    assert adapter.publish.call_count == 1


def test_successful_external_publication_with_lost_db_response_is_recovered_without_repeating():
    service, _, adapter, old = setup()
    old.update(service.change("CLU-example", "UPG-example", "execute", {"version": 4}))
    adapter.publication_state.return_value = "PUBLISHED"
    result = service.change("CLU-example", "UPG-example", "refresh", {"version": 5})
    assert result["status"] == "EXECUTING" and result["execution"]["publishedAt"]
    adapter.publish.assert_not_called()
    assert service._audit.call_args.args[2] == "UtilityGitOpsPublicationRecovered"


@pytest.mark.parametrize("minutes", [10, -121])
def test_no_execution_before_or_after_window(minutes):
    service, _, adapter, _ = setup(minutes=minutes)
    with pytest.raises(ApiError) as error:
        service.change("CLU-example", "UPG-example", "execute", {"version": 4})
    assert error.value.code == "UTILITY_WINDOW_CLOSED"
    adapter.prepare.assert_not_called()


def test_unpublished_intent_expires_without_publishing():
    service, _, adapter, plan = setup(status="EXECUTING", minutes=-121)
    plan["execution"]["intent"] = adapter.prepare.return_value
    result = service.change("CLU-example", "UPG-example", "refresh", {"version": 4})
    assert result["status"] == "FAILED"
    adapter.publish.assert_not_called()


@pytest.mark.parametrize(
    "change",
    ["stale_version", "no_approval", "no_policy", "no_permission", "unhealthy", "stopped", "runtime_missing"],
)
def test_execution_guards_prevent_preparation(change):
    service, repo, adapter, plan = setup()
    version = 4
    if change == "stale_version":
        version = 3
    if change == "no_approval":
        plan["approved_by"] = None
    if change == "no_policy":
        plan["readiness_evidence"] = {}
    if change == "no_permission":
        service.access = EffectiveAccess("user", "User", 1, frozenset(), ())
    if change == "unhealthy":
        observe(repo, "0.45.0", healthStatus="Degraded")
    if change == "stopped":
        repo.get.return_value = {"status": "STOPPED"}
    if change == "runtime_missing":
        repo.platform_components.return_value["runtimeInventory"] = {}
    with pytest.raises(ApiError):
        service.change("CLU-example", "UPG-example", "execute", {"version": version})
    adapter.prepare.assert_not_called()
    service._save.assert_not_called()


def test_stale_or_prepublication_observations_never_complete():
    service, repo, adapter, plan = setup(status="EXECUTING")
    plan["execution"].update({"intent": adapter.prepare.return_value, "publishedAt": utcnow().isoformat()})
    adapter.publication_state.return_value = "PUBLISHED"
    observe(repo, "0.46.0", observedAt=(utcnow() - timedelta(hours=1)).isoformat())
    result = service.change("CLU-example", "UPG-example", "refresh", {"version": 4})
    assert result["status"] == "EXECUTING"


def test_approval_drift_and_branch_protection_propagate_without_success():
    service, _, adapter, plan = setup()
    adapter.prepare.side_effect = ApiError(409, "UTILITY_APPROVAL_DRIFT", "Drift")
    with pytest.raises(ApiError):
        service.change("CLU-example", "UPG-example", "execute", {"version": 4})
    service._save.assert_not_called()
    adapter.publish.assert_not_called()


def test_execution_approval_requires_compatibility_signoff():
    service, _, _, plan = setup(status="SUBMITTED", minutes=10)
    service.access = EffectiveAccess(
        "architect", "Architect", 1, frozenset({"cluster.upgrade.approve"}), (Scope("PLATFORM"),)
    )
    with pytest.raises(ApiError) as error:
        service.change("CLU-example", "UPG-example", "approve", {"version": 4})
    assert error.value.code == "UTILITY_COMPATIBILITY_REVIEW_REQUIRED"
    approved = service.change(
        "CLU-example",
        "UPG-example",
        "approve",
        {"version": 4, "reason": "Release, values, Kubernetes and recovery reviewed"},
    )
    assert approved["execution"]["compatibilityReview"]["actorId"] == "architect"
    assert approved["status"] == "SCHEDULED"


def test_submission_captures_execution_policy_before_approval_and_never_publishes():
    service, _, adapter, plan = setup(status="DRAFT", minutes=60)
    plan["readiness_evidence"] = {"label": "Headlamp"}
    adapter.evidence.return_value = {"adapter": HeadlampGitOps.ADAPTER, "durationMinutes": 120}
    service.options = MagicMock(
        return_value={"blockReason": None, "currentVersion": "0.45.0", "versions": ["0.46.0"]}
    )
    submitted = service.change("CLU-example", "UPG-example", "submit", {"version": 4})
    assert submitted["status"] == "SUBMITTED"
    assert submitted["readiness_evidence"]["executionPolicy"] == adapter.evidence.return_value
    adapter.publish.assert_not_called()
    adapter.prepare.assert_not_called()


def test_platform_architect_self_approval_preserves_recorded_role_policy():
    from types import SimpleNamespace

    service, repo, _, plan = setup(status="SUBMITTED", minutes=60)
    repo.principal = SimpleNamespace(roles=frozenset({"PLATFORM_ARCHITECT"}))
    service.access = EffectiveAccess(
        "engineer", "Architect", 1, frozenset({"cluster.upgrade.approve"}), (Scope("PLATFORM"),)
    )
    approved = service.change(
        "CLU-example",
        "UPG-example",
        "approve",
        {"version": 4, "reason": "Compatibility and recovery reviewed"},
    )
    assert service.recorded_approval_valid(approved)
    assert approved["execution"]["approval"]["selfApproved"] is True
