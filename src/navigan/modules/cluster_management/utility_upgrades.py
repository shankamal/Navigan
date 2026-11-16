"""Scoped utility release discovery and persisted, authorized review plans.

Drafting/review never deploys. The reviewed Headlamp adapter separates durable
preparation, explicit publication and fresh post-deployment verification.
"""

import re
import time
import urllib.request
import uuid
import yaml
from datetime import datetime, timedelta
from pydantic import Field, field_validator
from .models import Model
from .utility_gitops import HeadlampGitOps
from .upgrade_plans import EksUpgradePlans, CreateEksUpgradePlan, ACTIVE, utcnow
from navigan.shared.errors import ApiError

# Fixed upstream identities: callers cannot supply a URL or a repository.
CHARTS = {
    "headlamp": ("kubernetes-sigs/headlamp", "headlamp-helm-", "headlamp", "Headlamp"),
    "grafana": (
        "prometheus-community/helm-charts",
        "kube-prometheus-stack-",
        "kube-prometheus-stack",
        "Monitoring stack (Grafana and Prometheus)",
    ),
    "prometheus": (
        "prometheus-community/helm-charts",
        "kube-prometheus-stack-",
        "kube-prometheus-stack",
        "Monitoring stack (Grafana and Prometheus)",
    ),
    "falco": ("falcosecurity/charts", "falco-", "falco", "Falco"),
}
_CACHE = {}
CHART_INDEXES = {
    "headlamp": "https://kubernetes-sigs.github.io/headlamp/index.yaml",
    "kube-prometheus-stack": "https://prometheus-community.github.io/helm-charts/index.yaml",
    "falco": "https://falcosecurity.github.io/charts/index.yaml",
}


def semver(value):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", str(value or ""))
    return tuple(map(int, match.groups())) if match else None


def chart_index_entries(payload, chart):
    """Read one chart entry at a time to fit the existing 256 MiB Lambda."""
    entries, chunk = [], []
    collecting = False

    def flush():
        if not chunk:
            return
        value = yaml.load("\n".join(chunk), Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))
        if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
            raise ValueError("Invalid chart index entry")
        item = value[0]
        entries.append({key: item.get(key) for key in ("name", "version", "deprecated", "urls")})
        chunk.clear()

    for line in payload.decode("utf-8").splitlines():
        if not collecting:
            if line.rstrip() == f"  {chart}:":
                collecting = True
            continue
        if re.match(r"^  [\w.-]+:\s*$", line) or (line and not line.startswith(" ")):
            break
        if line.startswith("  - "):
            flush()
        chunk.append(line)
    flush()
    if not entries:
        raise ValueError("Chart not found in index")
    return {"entries": {chart: entries}}


def upstream_releases(code, fetch=None):
    _, _, chart, _ = CHARTS[code]
    index_url = CHART_INDEXES[chart]
    cached = _CACHE.get(index_url)
    if fetch is None and cached and cached[0] > time.monotonic():
        return cached[1]

    def request(url):
        req = urllib.request.Request(
            url, headers={"Accept": "application/yaml", "User-Agent": "Navigan-Utility-Planning"}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            payload = response.read(12_000_001)
            if len(payload) > 12_000_000:
                raise ValueError("Release response exceeds limit")
            return chart_index_entries(payload, chart)

    try:
        index = (fetch or request)(index_url)
        releases = index["entries"][chart]
        versions = sorted(
            {
                str(item["version"]).removeprefix("v")
                for item in releases
                if isinstance(item, dict)
                and not item.get("deprecated")
                and item.get("name") == chart
                and item.get("urls")
                and semver(item.get("version"))
            },
            key=semver,
            reverse=True,
        )
        if not versions:
            raise ValueError("No stable chart entries")
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError):
        raise ApiError(
            502,
            "UTILITY_RELEASES_UNAVAILABLE",
            "The official chart release catalogue is unavailable. Retry shortly; no versions have been invented.",
        ) from None
    if fetch is None:
        _CACHE[index_url] = (time.monotonic() + 300, versions)
    return versions


class CreateUtilityUpgradePlan(Model):
    utilityCode: str = Field(pattern=r"^(headlamp|grafana|prometheus|falco)$")
    targetVersion: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    scheduledFor: datetime | None = None
    changeReason: str = Field(min_length=8, max_length=2000)

    _time = field_validator("scheduledFor", mode="before")(
        CreateEksUpgradePlan.parse_maintenance_start.__func__
    )


class UtilityUpgradePlans(EksUpgradePlans):
    table = "cluster_management.utility_upgrade_plans"

    def __init__(self, repo, access, correlation, releases=None, github=None):
        self.repo, self.access, self.correlation = repo, access, correlation
        self.releases = releases or upstream_releases
        self.github = github

    def present(self, row):
        result = super().present(row)
        result["kind"] = "UTILITY"
        result["utilityEvidence"] = result.pop("readinessEvidence")
        return result

    def options(self, cluster_id, code):
        self.repo.get(cluster_id)
        if code not in CHARTS:
            return {
                "utilityCode": code,
                "label": code,
                "chart": None,
                "currentVersion": None,
                "versions": [],
                "blockReason": "This utility has no supported chart planning adapter yet.",
                "observedAt": None,
            }
        inventory = self.repo.platform_components(cluster_id)
        component = next(
            (item for item in inventory["components"] if item["componentCode"].lower() == code), {}
        )
        repository, _, chart, label = CHARTS[code]
        current = component.get("version")
        observed = component.get("observedAt")
        blocked = None
        if not semver(current):
            blocked = "An installed chart version must be reported by the connector before planning."
        elif component.get("status") != "READY" or component.get("syncStatus") != "Synced":
            blocked = f"Utility is {component.get('status', 'unreported')} / {component.get('syncStatus', 'unknown')}. Restore healthy, synced evidence before planning."
        else:
            try:
                age = (utcnow() - datetime.fromisoformat(observed.replace("Z", "+00:00"))).total_seconds()
                if age < -60 or age > 900:
                    blocked = "Utility evidence is older than 15 minutes. Refresh the cluster connector before planning."
            except (AttributeError, ValueError, TypeError):
                blocked = "A valid connector observation time is required."
        if chart == "kube-prometheus-stack":
            peers = [
                item
                for item in inventory["components"]
                if item["componentCode"].lower() in {"grafana", "prometheus"}
            ]
            if len(peers) < 2 or any(
                item.get("version") != current
                or item.get("status") != "READY"
                or item.get("syncStatus") != "Synced"
                for item in peers
            ):
                blocked = "Grafana and Prometheus share one monitoring chart. Both must report the same version and be healthy / synced before planning."
        versions = []
        release_status = "UNAVAILABLE"
        if semver(current):
            try:
                catalog = self.releases(code)
                versions = [value for value in catalog if semver(value) > semver(current)]
                release_status = (
                    "UPDATE_AVAILABLE"
                    if versions
                    else "UP_TO_DATE"
                    if any(semver(value) == semver(current) for value in catalog)
                    else "INSTALLED_VERSION_UNVERIFIED"
                )
                if not versions and not blocked:
                    blocked = (
                        "Up to date — no action needed."
                        if release_status == "UP_TO_DATE"
                        else "Installed version is not verified in the official chart catalogue. No target has been assumed."
                    )
            except ApiError as error:
                if error.code != "UTILITY_RELEASES_UNAVAILABLE":
                    raise
                if not blocked:
                    blocked = "Unable to check available versions. Retry the official chart catalogue; this does not mean the utility is up to date."
        return {
            "utilityCode": code,
            "label": label,
            "chart": chart,
            "currentVersion": current,
            "versions": versions,
            "blockReason": blocked,
            "observedAt": observed,
            "source": CHART_INDEXES[chart],
            "releaseStatus": release_status,
            "versionKind": "Helm chart version",
            "compatibility": "Compatibility review required before execution",
        }

    def create(self, cluster_id, body):
        self.access.require("cluster.upgrade.plan")
        cluster = self.repo.get(cluster_id, lock=True)
        code = body["utilityCode"]
        evidence = self.options(cluster_id, code)
        if evidence["blockReason"]:
            raise ApiError(409, "UTILITY_EVIDENCE_REQUIRED", evidence["blockReason"])
        if body["targetVersion"] not in evidence["versions"]:
            raise ApiError(
                409,
                "UTILITY_TARGET_UNAVAILABLE",
                "Select a current stable release from the official chart catalogue.",
            )
        repository = self.repo.system_repository_access(cluster_id)
        if code == "headlamp":
            from .utility_gitops import headlamp_preflight

            evidence["gitOps"] = headlamp_preflight(repository, evidence["currentVersion"], self.github)
        group = evidence["chart"]
        active = self.repo.db.execute(
            f"SELECT plan_id FROM {self.table} WHERE cluster_id=%s AND managed_group=%s AND status=ANY(%s)",
            [cluster_id, group, list(ACTIVE)],
        ).fetchone()
        if active:
            raise ApiError(
                409,
                "ACTIVE_UTILITY_PLAN_EXISTS",
                "Review the existing plan for this chart first.",
                {"planId": active["plan_id"]},
            )
        scheduled = body.get("scheduledFor")
        if scheduled and scheduled <= utcnow():
            raise ApiError(422, "MAINTENANCE_WINDOW_INVALID", "Choose a future maintenance start.")
        now = utcnow()
        row = {
            "plan_id": "UPG-" + uuid.uuid4().hex,
            "cluster_id": cluster_id,
            "customer_id": cluster["customer_id"],
            "provider": "EKS",
            "utility_code": code,
            "managed_group": group,
            "current_version": evidence["currentVersion"],
            "target_version": body["targetVersion"],
            "strategy": "GITOPS_REVIEW",
            "status": "DRAFT",
            "scheduled_for": scheduled,
            "change_reason": body["changeReason"],
            "readiness_evidence": evidence,
            "execution": {},
            "version": 1,
            "created_by": self.access.user_id,
            "created_at": now,
            "updated_by": self.access.user_id,
            "updated_at": now,
        }
        self._save(row, create=True)
        self._audit(None, row, "UtilityUpgradePlanCreated")
        return self.present(row)

    def change(self, cluster_id, plan_id, action, body):
        if action == "submit" and self.get(cluster_id, plan_id).get("utility_code") == "headlamp":
            self.access.require("cluster.upgrade.plan")
            plan = self.get(cluster_id, plan_id, lock=True)
            self._checked_version(plan, body)
            self._require_status(plan, {"DRAFT"})
            if (plan["current_version"], plan["target_version"]) != ("0.45.0", HeadlampGitOps.TARGET):
                return super().change(cluster_id, plan_id, action, body)
            self._require_future_requested_time(plan)
            if not plan.get("scheduled_for"):
                raise ApiError(
                    409,
                    "UTILITY_WINDOW_REQUIRED",
                    "Choose a maintenance start before submitting an executable Headlamp plan.",
                )
            options = self.options(cluster_id, "headlamp")
            if (
                options["blockReason"]
                or plan["current_version"] != options["currentVersion"]
                or plan["target_version"] not in options["versions"]
            ):
                raise ApiError(
                    409,
                    "UTILITY_EVIDENCE_REQUIRED",
                    options["blockReason"] or "Installed or target version changed. Create a fresh plan.",
                )
            policy = self._headlamp_adapter(cluster_id).evidence(
                plan["current_version"], plan["target_version"]
            )
            evidence = dict(plan["readiness_evidence"])
            evidence["executionPolicy"] = policy
            return self._transition(
                plan,
                "SUBMITTED",
                "UtilityExecutionReviewRequested",
                {
                    "readiness_evidence": evidence,
                    "submitted_by": self.access.user_id,
                    "submitted_at": utcnow(),
                },
            )
        if action == "approve":
            candidate = self.get(cluster_id, plan_id)
            policy = (candidate.get("readiness_evidence") or {}).get("executionPolicy")
            if policy:
                self.require_approval()
                plan = self.get(cluster_id, plan_id, lock=True)
                self._checked_version(plan, body)
                self._require_status(plan, {"SUBMITTED"})
                self._require_future_requested_time(plan)
                if len((body.get("reason") or "").strip()) < 8:
                    raise ApiError(
                        422,
                        "UTILITY_COMPATIBILITY_REVIEW_REQUIRED",
                        "Record your compatibility and recovery review before approving Headlamp execution.",
                    )
                self_review = self.access.user_id in {plan["created_by"], plan.get("submitted_by")}
                if self_review and not self.allows_self_approval():
                    raise ApiError(
                        409, "MAKER_CHECKER_REQUIRED", "An authorized independent reviewer is required."
                    )
                from .upgrade_plans import SELF_APPROVAL_POLICY

                now = utcnow()
                execution = dict(plan.get("execution") or {})
                execution["approval"] = {
                    "policy": SELF_APPROVAL_POLICY if self_review else "REVIEWER_APPROVAL_V1",
                    "actorId": self.access.user_id,
                    "selfApproved": self_review,
                    "role": "PLATFORM_ARCHITECT" if self_review else "AUTHORIZED_REVIEWER",
                    "planVersion": plan["version"],
                    "approvedAt": now.isoformat(),
                }
                execution["compatibilityReview"] = {
                    "actorId": self.access.user_id,
                    "comment": body["reason"].strip(),
                    "adapter": policy["adapter"],
                }
                return self._transition(
                    plan,
                    "SCHEDULED",
                    "UtilityExecutionApproved",
                    {"approved_by": self.access.user_id, "approved_at": now, "execution": execution},
                )
        if action == "reschedule":
            self.access.require("cluster.upgrade.plan")
            plan = self.get(cluster_id, plan_id, lock=True)
            if plan["version"] != body["version"]:
                raise ApiError(409, "VERSION_CONFLICT", "Refresh the upgrade plan and retry.")
            self._require_status(plan, {"DRAFT", "SUBMITTED", "APPROVED", "SCHEDULED"})
            scheduled = body.get("scheduledFor")
            if not scheduled or scheduled <= utcnow():
                raise ApiError(422, "MAINTENANCE_WINDOW_INVALID", "Choose a future maintenance start.")
            execution = dict(plan.get("execution") or {})
            execution.pop("approval", None)
            execution.pop("compatibilityReview", None)
            evidence = dict(plan.get("readiness_evidence") or {})
            evidence.pop("executionPolicy", None)
            return self._transition(
                plan,
                "DRAFT",
                "UtilityUpgradePlanRescheduled",
                {
                    "scheduled_for": scheduled,
                    "submitted_by": None,
                    "submitted_at": None,
                    "submitted_by_name": None,
                    "approved_by": None,
                    "approved_at": None,
                    "approved_by_name": None,
                    "execution": execution,
                    "readiness_evidence": evidence,
                },
            )
        if (
            action in {"execute", "refresh"}
            and self.get(cluster_id, plan_id).get("utility_code") == "headlamp"
        ):
            return self._execute_headlamp(cluster_id, plan_id, action, body)
        # Never dispatch any utility into the EKS execution adapter.
        if action in {"execute", "refresh"}:
            self.get(cluster_id, plan_id)
            raise ApiError(
                409,
                "UTILITY_EXECUTION_NOT_ENABLED",
                "This release supports utility draft and approval. Compatibility validation and GitOps execution are not enabled; approval does not deploy the chart.",
            )
        return super().change(cluster_id, plan_id, action, body)

    @staticmethod
    def _checked_version(plan, body):
        if plan["version"] != body["version"]:
            raise ApiError(409, "VERSION_CONFLICT", "Refresh the upgrade plan and retry.")

    def _headlamp_adapter(self, cluster_id):
        return HeadlampGitOps(self.repo.system_repository_access(cluster_id), self.github)

    @staticmethod
    def _fresh(value, now, after=None):
        try:
            observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return -60 <= (now - observed).total_seconds() <= 300 and (after is None or observed > after)
        except (AttributeError, TypeError, ValueError):
            return False

    def _headlamp_health(self, cluster_id, version, after=None):
        now = utcnow()
        inventory = self.repo.platform_components(cluster_id)
        component = next(
            (item for item in inventory["components"] if item["componentCode"].lower() == "headlamp"), {}
        )
        runtime = inventory.get("runtimeInventory") or {}
        workload = next(
            (
                item
                for item in runtime.get("resources", [])
                if item.get("kind") == "Deployment"
                and item.get("namespace") == "navigan-dashboard"
                and item.get("name") == "navigan-dashboard-headlamp"
            ),
            {},
        )
        try:
            runtime_unexpired = datetime.fromisoformat(runtime["expiresAt"].replace("Z", "+00:00")) > now
        except (KeyError, AttributeError, TypeError, ValueError):
            runtime_unexpired = False
        healthy = (
            component.get("version") == version
            and component.get("status") == "READY"
            and component.get("syncStatus") == "Synced"
            and component.get("healthStatus") == "Healthy"
            and self._fresh(component.get("observedAt"), now, after)
            and runtime_unexpired
            and self._fresh(runtime.get("observedAt"), now, after)
            and workload.get("desired", 0) > 0
            and workload.get("ready") == workload.get("desired")
        )
        return healthy, component

    def _execute_headlamp(self, cluster_id, plan_id, action, body):
        self.access.require("cluster.upgrade.execute")
        plan = self.get(cluster_id, plan_id, lock=True)
        self._checked_version(plan, body)
        policy = (plan.get("readiness_evidence") or {}).get("executionPolicy") or {}
        execution = dict(plan.get("execution") or {})
        review = execution.get("compatibilityReview") or {}
        if (
            policy.get("adapter") != HeadlampGitOps.ADAPTER
            or not self.recorded_approval_valid(plan)
            or review.get("actorId") != plan.get("approved_by")
            or review.get("adapter") != HeadlampGitOps.ADAPTER
        ):
            raise ApiError(
                409,
                "UTILITY_EXECUTION_REVIEW_REQUIRED",
                "Reschedule and submit this plan for the Headlamp execution review. Previous planning-only approval cannot start an upgrade.",
            )
        now = utcnow()
        starts = plan.get("scheduled_for")
        if not starts or policy.get("durationMinutes") != HeadlampGitOps.DURATION:
            raise ApiError(
                409, "UTILITY_WINDOW_REQUIRED", "A reviewed Headlamp maintenance window is required."
            )
        ends = starts + timedelta(minutes=HeadlampGitOps.DURATION)
        adapter = self._headlamp_adapter(cluster_id)
        if action == "execute":
            self._require_status(plan, {"APPROVED", "SCHEDULED"})
            if not starts <= now < ends:
                raise ApiError(
                    409,
                    "UTILITY_WINDOW_CLOSED",
                    "The approved utility maintenance window is not open. Reschedule an overdue plan.",
                )
            if self.repo.get(cluster_id).get("status") != "ACTIVE":
                raise ApiError(409, "UTILITY_CLUSTER_NOT_ACTIVE", "The cluster must be active.")
            healthy, component = self._headlamp_health(cluster_id, plan["current_version"])
            if not healthy:
                raise ApiError(
                    409,
                    "UTILITY_EVIDENCE_REQUIRED",
                    "Fresh healthy Headlamp workload and Argo evidence is required before execution.",
                )
            intent = adapter.prepare(policy, plan["target_version"], plan_id + ":" + str(plan["version"]))
            execution.update(
                {
                    "phase": "GITOPS_PREPARED",
                    "intent": intent,
                    "preparedAt": now.isoformat(),
                    "startedBy": self.access.user_id,
                    "sourceRevision": component.get("sourceRevision"),
                    "windowEndsAt": ends.isoformat(),
                }
            )
            return self._transition(plan, "EXECUTING", "UtilityGitOpsPrepared", {"execution": execution})
        self._require_status(plan, {"EXECUTING"})
        intent = execution.get("intent")
        if not isinstance(intent, dict) or not all(
            isinstance(intent.get(key), str) and intent[key]
            for key in ("commit", "baseCommit", "targetManifestHash")
        ):
            raise ApiError(
                409,
                "UTILITY_EXECUTION_INTENT_MISSING",
                "The saved execution intent is incomplete; do not republish without review.",
            )
        publication = adapter.publication_state(policy, intent)
        if publication == "UNPUBLISHED":
            if not starts <= now < ends:
                execution.update({"phase": "PUBLICATION_EXPIRED", "lastCheckedAt": now.isoformat()})
                return self._transition(plan, "FAILED", "UtilityGitOpsWindowMissed", {"execution": execution})
            healthy, _ = self._headlamp_health(cluster_id, plan["current_version"])
            if not healthy or self.repo.get(cluster_id).get("status") != "ACTIVE":
                raise ApiError(
                    409,
                    "UTILITY_EVIDENCE_REQUIRED",
                    "Fresh healthy evidence is required before publishing the prepared commit.",
                )
            adapter.publish(intent, ends)
            # Persist this separately from success verification. A timed-out write is
            # recovered by checking the exact saved commit, never creating another.
            execution.update(
                {
                    "phase": "WAITING_FOR_ARGO",
                    "publishedAt": now.isoformat(),
                    "lastCheckedAt": now.isoformat(),
                }
            )
            return self._transition(plan, "EXECUTING", "UtilityGitOpsPublished", {"execution": execution})
        if not execution.get("publishedAt"):
            execution.update(
                {
                    "phase": "WAITING_FOR_ARGO",
                    "publishedAt": now.isoformat(),
                    "lastCheckedAt": now.isoformat(),
                }
            )
            return self._transition(
                plan, "EXECUTING", "UtilityGitOpsPublicationRecovered", {"execution": execution}
            )
        published = datetime.fromisoformat(execution["publishedAt"])
        healthy, component = self._headlamp_health(cluster_id, plan["target_version"], published)
        execution["lastCheckedAt"] = now.isoformat()
        if healthy:
            execution.update(
                {
                    "phase": "VERIFIED",
                    "completedAt": now.isoformat(),
                    "verifiedChartVersion": component["version"],
                    "verification": "Fresh Synced/Healthy Argo observation and ready Headlamp deployment",
                }
            )
            return self._transition(plan, "SUCCEEDED", "UtilityUpgradeVerified", {"execution": execution})
        execution["phase"] = "VALIDATION_REQUIRED" if now >= ends else "WAITING_FOR_ARGO"
        return self._transition(plan, "EXECUTING", "UtilityUpgradeObserved", {"execution": execution})


def plan_service(repo, access, correlation, cluster_id, plan_id):
    """Route a scoped plan ID without allowing a utility plan into EKS execution."""
    repo.get(cluster_id)
    exists = repo.db.execute(
        "SELECT plan_id FROM cluster_management.utility_upgrade_plans WHERE cluster_id=%s AND plan_id=%s",
        [cluster_id, plan_id],
    ).fetchone()
    from .upgrade_paths import ScopedEksUpgradePlans

    return (
        UtilityUpgradePlans(repo, access, correlation)
        if exists
        else ScopedEksUpgradePlans(repo, access, correlation)
    )
