from navigan.modules.cluster_management.capabilities import resolve_cluster_actions
from navigan.shared.access import EffectiveAccess, Scope


def access(*privileges):
    return EffectiveAccess(
        "user",
        "User",
        1,
        frozenset(privileges),
        (Scope("PLATFORM"),),
    )


def actions(status, *privileges):
    return {
        item["code"]: item
        for item in resolve_cluster_actions({"status": status}, access(*privileges))
    }


def test_active_actions_are_permission_filtered_and_future_features_are_disabled():
    result = actions(
        "ACTIVE",
        "cluster.view",
        "cluster.apply",
        "cluster.decommission",
    )

    assert result["MANAGE"]["enabled"]
    assert result["STOP"]["enabled"]
    assert result["DELETE"]["enabled"]
    assert result["DELETE"]["destructive"]
    assert not result["DASHBOARD"]["enabled"]
    assert not result["WEB_KUBECTL"]["enabled"]


def test_cloud_engineer_does_not_receive_lifecycle_actions_without_privileges():
    result = actions("ACTIVE", "cluster.view", "cluster.edit")

    assert "STOP" not in result
    assert "DELETE" not in result
    assert result["MANAGE"]["enabled"]


def test_provisioning_exposes_progress_and_logs_but_not_unsafe_cancellation():
    result = actions(
        "APPLYING",
        "cluster.view",
        "cluster.logs.view",
        "cluster.cancel",
    )

    assert result["VIEW_PROGRESS"]["enabled"]
    assert result["VIEW_LOGS"]["enabled"]
    assert not result["CANCEL_PROVISIONING"]["enabled"]
    assert result["CANCEL_PROVISIONING"]["disabledReason"]


def test_failed_retry_is_explicitly_disabled_until_supported():
    result = actions(
        "FAILED",
        "cluster.view",
        "cluster.edit",
        "cluster.logs.view",
        "cluster.retry",
        "cluster.decommission",
    )

    assert not result["RETRY_PROVISIONING"]["enabled"]
    assert result["DELETE"]["enabled"]


def test_unknown_status_fails_safe():
    result = actions("PROVIDER_NEW_STATE", "cluster.view", "cluster.logs.view")

    assert result["VIEW_DETAILS"]["enabled"]
    assert not result["REFRESH_STATUS"]["enabled"]
    assert not result["TROUBLESHOOT"]["enabled"]
