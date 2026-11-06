from datetime import datetime, timedelta, timezone

import pytest
import json
from unittest.mock import MagicMock

from navigan.shared.errors import ApiError
from navigan.modules.cluster_management.upgrade_plans import CreateEksUpgradePlan, EksUpgradePlans


def test_browser_maintenance_timestamp_is_accepted_and_timezone_is_required():
    body = {"targetVersion": "1.37", "changeReason": "Scheduled platform upgrade"}
    plan = CreateEksUpgradePlan.model_validate({**body, "scheduledFor": "2026-12-01T10:30:00.000Z"})
    assert plan.scheduledFor == datetime(2026, 12, 1, 10, 30, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="timezone"):
        CreateEksUpgradePlan.model_validate({**body, "scheduledFor": "2026-12-01T10:30:00"})


def test_scheduled_draft_handler_fingerprints_datetime_and_replays(monkeypatch):
    from navigan.modules.cluster_management import handler

    customer = MagicMock()
    customer.idempotency_get.return_value = None
    plans = MagicMock()
    plans.create.return_value = {"planId": "UPG-test", "status": "DRAFT", "version": 1}
    monkeypatch.setattr(handler, "transaction", MagicMock())
    monkeypatch.setattr(handler, "Repository", MagicMock())
    monkeypatch.setattr(handler, "AccessEvaluator", MagicMock())
    monkeypatch.setattr(handler, "CustomerRepository", MagicMock(return_value=customer))
    monkeypatch.setattr(handler, "EksUpgradePlans", MagicMock(return_value=plans))
    event = {
        "rawPath": "/api/v1/clusters/CLU-live/upgrade-plans",
        "requestContext": {"http": {"method": "POST"}},
        "headers": {"content-type": "application/json", "idempotency-key": "draft-test"},
        "body": json.dumps({"targetVersion": "1.37", "changeReason": "Scheduled upgrade",
                            "scheduledFor": "2026-12-01T10:30:00.000Z"}),
    }
    result = handler.execute(event, MagicMock(), "test-correlation")
    assert result["statusCode"] == 201
    assert isinstance(plans.create.call_args.args[1]["scheduledFor"], datetime)
    fingerprint = customer.idempotency_get.call_args.args[2]
    assert len(fingerprint) == 64
    customer.idempotency_get.return_value = {"status": 201, "body": plans.create.return_value}
    replay = handler.execute(event, MagicMock(), "test-correlation")
    assert replay["headers"]["Idempotency-Replayed"] == "true"
    assert customer.idempotency_get.call_args.args[2] == fingerprint
    plans.create.assert_called_once()


def evidence():
    return {
        "clusterId": "CLU-live",
        "customerId": "CUS-live",
        "provider": "EKS",
        "region": "ap-south-1",
        "source": "AWS_EKS_API",
        "observedAt": "2026-11-06T08:00:00+00:00",
        "controlPlane": {"version": "1.36", "status": "ACTIVE"},
        "recommendedTarget": {"version": "1.37", "supportStatus": "STANDARD_SUPPORT"},
        "nodeGroups": [{"name": "system", "version": "1.36", "status": "ACTIVE", "healthIssues": []}],
        "addons": [
            {
                "name": "coredns",
                "version": "v1",
                "targetVersion": "v2",
                "status": "ACTIVE",
                "healthIssues": [],
            }
        ],
        "insights": [],
        "updates": [],
        "readiness": {
            "status": "READY",
            "blockers": [],
            "warnings": [],
            "checks": {
                "controlPlaneActive": True,
                "nodeGroupsAligned": True,
                "addonsHealthy": True,
                "upgradeInsightsPassing": True,
                "noUpdateInProgress": True,
            },
        },
    }


class Result:
    def __init__(self, one=None, many=None):
        self.one, self.many = one, many or []

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.many


class Database:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))
        if "SELECT plan_id" in sql:
            return Result()
        return Result()


class Repo:
    def __init__(self):
        self.db = Database()
        self.cluster = {
            "cluster_id": "CLU-live",
            "customer_id": "CUS-live",
            "cluster_name": "live-eks",
            "platform": "EKS",
            "environment_id": "ENV-live",
            "environment_approved_version": 3,
        }

    def get(self, identifier, lock=False):
        assert identifier == "CLU-live"
        return self.cluster

    def pinned_environment_snapshot(self, identifier, version):
        return {}, {"configuration": {"location": {"region": "ap-south-1"}}}


class Access:
    def __init__(self, user="architect-a", privileges=None):
        self.user_id = user
        self.privileges = set(privileges or {"cluster.plan", "cluster.approve", "cluster.apply"})

    def require(self, privilege):
        if privilege not in self.privileges:
            raise ApiError(403, "FORBIDDEN", "Forbidden")


class Eks:
    def update_cluster_version(self, **request):
        assert request["name"] == "live-eks"
        assert request["version"] == "1.37"
        return {"update": {"id": "update-control", "status": "InProgress"}}


class Discovery:
    def discover(self, cluster, environment):
        return evidence()

    def client(self, cluster, environment):
        return Eks(), "ap-south-1"


def test_creates_durable_plan_only_from_ready_sequential_target():
    repo = Repo()
    plan = EksUpgradePlans(repo, Access(), "correlation", Discovery()).create(
        "CLU-live",
        {
            "targetVersion": "1.37",
            "strategy": "PROVIDER_MANAGED_ROLLING",
            "scheduledFor": datetime.now(timezone.utc) + timedelta(days=1),
            "changeReason": "Apply the supported EKS lifecycle update.",
        },
    )
    assert plan["status"] == "DRAFT"
    assert plan["currentVersion"] == "1.36"
    assert plan["targetVersion"] == "1.37"
    assert any("INSERT INTO cluster_management.upgrade_plans" in sql for sql, _ in repo.db.calls)
    assert any("EksUpgradePlanCreated" in params for _, params in repo.db.calls)


def test_rejects_non_sequential_target():
    with pytest.raises(ApiError) as raised:
        EksUpgradePlans(Repo(), Access(), "correlation", Discovery()).create(
            "CLU-live",
            {
                "targetVersion": "1.38",
                "strategy": "PROVIDER_MANAGED_ROLLING",
                "changeReason": "Skip an unsupported intermediate version.",
            },
        )
    assert raised.value.code == "UPGRADE_TARGET_CHANGED"


class TransitionPlans(EksUpgradePlans):
    def __init__(self, row, access, discovery=None):
        super().__init__(Repo(), access, "correlation", discovery or Discovery())
        self.row = row

    def get(self, cluster_id, plan_id, lock=False):
        return self.row

    def _save(self, row, create=False):
        self.row = row

    def _audit(self, old, row, action):
        pass


def base_plan(status="SUBMITTED"):
    now = datetime.now(timezone.utc)
    return {
        "plan_id": "UPG-" + "a" * 32,
        "cluster_id": "CLU-live",
        "customer_id": "CUS-live",
        "provider": "EKS",
        "current_version": "1.36",
        "target_version": "1.37",
        "strategy": "PROVIDER_MANAGED_ROLLING",
        "status": status,
        "scheduled_for": None,
        "change_reason": "Supported lifecycle update",
        "readiness_evidence": evidence(),
        "execution": {},
        "version": 1,
        "created_by": "architect-a",
        "created_at": now,
        "updated_by": "architect-a",
        "updated_at": now,
        "submitted_by": "architect-a",
        "submitted_at": now,
        "approved_by": None,
        "approved_at": None,
    }


def test_enforces_independent_approval():
    service = TransitionPlans(base_plan(), Access("architect-a"))
    with pytest.raises(ApiError) as raised:
        service.change("CLU-live", service.row["plan_id"], "approve", {"version": 1})
    assert raised.value.code == "MAKER_CHECKER_REQUIRED"
    service = TransitionPlans(base_plan(), Access("architect-b"))
    result = service.change("CLU-live", service.row["plan_id"], "approve", {"version": 1})
    assert result["status"] == "APPROVED"
    assert result["approvedBy"] == "architect-b"


def test_execute_revalidates_and_starts_only_control_plane_stage():
    row = base_plan("APPROVED")
    row["approved_by"] = "architect-b"
    service = TransitionPlans(row, Access("operator"))
    result = service.change("CLU-live", row["plan_id"], "execute", {"version": 1})
    assert result["status"] == "EXECUTING"
    assert result["execution"]["phase"] == "CONTROL_PLANE"
    assert result["execution"]["updateId"] == "update-control"
    assert result["execution"]["addonQueue"] == [{"name": "coredns", "version": "v2"}]


class TrackingEks:
    def __init__(self):
        self.describe_requests = []

    def describe_update(self, **request):
        self.describe_requests.append(request)
        return {"update": {"id": request["updateId"], "status": "InProgress"}}


class TrackingDiscovery(Discovery):
    def __init__(self, eks):
        self.eks = eks

    def client(self, cluster, environment):
        return self.eks, "ap-south-1"


@pytest.mark.parametrize(
    ("phase", "resource_key", "resource_name"),
    [
        ("ADDON:coredns", "addonName", "coredns"),
        ("NODEGROUP:system", "nodegroupName", "system"),
    ],
)
def test_refresh_identifies_the_active_eks_resource(phase, resource_key, resource_name):
    row = base_plan("EXECUTING")
    row["execution"] = {"phase": phase, "updateId": "update-1"}
    eks = TrackingEks()
    service = TransitionPlans(row, Access("operator"), TrackingDiscovery(eks))

    result = service.change("CLU-live", row["plan_id"], "refresh", {"version": 1})

    assert result["status"] == "EXECUTING"
    assert eks.describe_requests == [
        {
            "name": "live-eks",
            "updateId": "update-1",
            resource_key: resource_name,
        }
    ]
