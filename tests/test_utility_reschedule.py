from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from navigan.modules.cluster_management.utility_upgrades import UtilityUpgradePlans
from navigan.modules.cluster_management.upgrade_plans import utcnow
from navigan.shared.access import EffectiveAccess, Scope
from navigan.shared.errors import ApiError


def service(status="SCHEDULED", privileges=("cluster.upgrade.plan",)):
    repo = MagicMock()
    access = EffectiveAccess("planner", "Planner", 1, frozenset(privileges), (Scope("PLATFORM"),))
    plans = UtilityUpgradePlans(repo, access, "reschedule-test")
    old = {
        "plan_id": "UPG-example",
        "cluster_id": "CLU-example",
        "status": status,
        "version": 3,
        "scheduled_for": utcnow() - timedelta(hours=1),
        "submitted_by": "maker",
        "submitted_at": utcnow() - timedelta(hours=2),
        "approved_by": "reviewer",
        "approved_at": utcnow() - timedelta(hours=2),
        "approved_by_name": "Reviewer",
        "submitted_by_name": "Maker",
        "execution": {"approval": {"actorId": "reviewer"}, "retainedEvidence": "preserve"},
    }
    plans.get = MagicMock(return_value=old)
    plans._save = MagicMock()
    plans._audit = MagicMock()
    plans.present = lambda row: row
    return plans, old


@pytest.mark.parametrize("status", ["DRAFT", "SUBMITTED", "APPROVED", "SCHEDULED"])
def test_rescheduling_clears_approval_and_submission_and_audits_new_draft(status):
    plans, old = service(status)
    future = utcnow() + timedelta(days=1)
    result = plans.change("CLU-example", "UPG-example", "reschedule", {"version": 3, "scheduledFor": future})
    assert result["status"] == "DRAFT" and result["version"] == 4
    assert result["scheduled_for"] == future and result["updated_by"] == "planner"
    for key in (
        "submitted_by",
        "submitted_at",
        "approved_by",
        "approved_at",
        "submitted_by_name",
        "approved_by_name",
    ):
        assert result[key] is None
    assert result["execution"] == {"retainedEvidence": "preserve"}
    assert "approval" in old["execution"]  # audit retains the old approval
    plans.get.assert_called_once_with("CLU-example", "UPG-example", lock=True)
    plans._save.assert_called_once_with(result)
    assert plans._audit.call_args.args == (old, result, "UtilityUpgradePlanRescheduled")


@pytest.mark.parametrize("status", ["EXECUTING", "SUCCEEDED", "FAILED", "CANCELLED", "REJECTED"])
def test_executing_and_closed_plans_cannot_be_rescheduled(status):
    plans, _ = service(status)
    with pytest.raises(ApiError) as error:
        plans.change(
            "CLU-example",
            "UPG-example",
            "reschedule",
            {"version": 3, "scheduledFor": utcnow() + timedelta(days=1)},
        )
    assert error.value.code == "UPGRADE_PLAN_STATE_CONFLICT"
    plans._save.assert_not_called()


@pytest.mark.parametrize(
    "version,scheduled,code",
    [
        (2, "future", "VERSION_CONFLICT"),
        (3, "past", "MAINTENANCE_WINDOW_INVALID"),
        (3, None, "MAINTENANCE_WINDOW_INVALID"),
    ],
)
def test_reschedule_rejects_stale_revision_and_invalid_time(version, scheduled, code):
    plans, _ = service()
    value = (
        utcnow() + timedelta(days=1)
        if scheduled == "future"
        else utcnow() - timedelta(hours=1)
        if scheduled
        else None
    )
    with pytest.raises(ApiError) as error:
        plans.change("CLU-example", "UPG-example", "reschedule", {"version": version, "scheduledFor": value})
    assert error.value.code == code
    plans._save.assert_not_called()


def test_approval_privilege_alone_cannot_reschedule():
    plans, _ = service(privileges=("cluster.upgrade.approve",))
    with pytest.raises(ApiError) as error:
        plans.change(
            "CLU-example",
            "UPG-example",
            "reschedule",
            {"version": 3, "scheduledFor": utcnow() + timedelta(days=1)},
        )
    assert error.value.status == 403
    plans._save.assert_not_called()


def test_rescheduled_plan_cannot_be_approved_without_a_new_submission():
    plans, _ = service(privileges=("cluster.upgrade.plan", "cluster.upgrade.approve"))
    draft = plans.change(
        "CLU-example",
        "UPG-example",
        "reschedule",
        {"version": 3, "scheduledFor": utcnow() + timedelta(days=1)},
    )
    plans.get.return_value = draft
    with pytest.raises(ApiError) as error:
        plans.change("CLU-example", "UPG-example", "approve", {"version": 4})
    assert error.value.code == "UPGRADE_PLAN_STATE_CONFLICT"
