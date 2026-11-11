"""Scoped utility release discovery and persisted, independently reviewed plans.

Planning never changes the system repository or a Kubernetes resource.
"""
import json
import re
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from pydantic import Field, field_validator
from .models import Model
from .upgrade_plans import EksUpgradePlans, CreateEksUpgradePlan, ACTIVE, utcnow
from .repository import serialize
from navigan.shared.errors import ApiError

# Fixed upstream identities: callers cannot supply a URL or a repository.
CHARTS = {
    "headlamp": ("kubernetes-sigs/headlamp", "headlamp-helm-", "headlamp", "Headlamp"),
    "grafana": ("prometheus-community/helm-charts", "kube-prometheus-stack-", "kube-prometheus-stack", "Monitoring stack (Grafana and Prometheus)"),
    "prometheus": ("prometheus-community/helm-charts", "kube-prometheus-stack-", "kube-prometheus-stack", "Monitoring stack (Grafana and Prometheus)"),
    "falco": ("falcosecurity/charts", "falco-", "falco", "Falco"),
}
_CACHE = {}


def semver(value):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", str(value or ""))
    return tuple(map(int, match.groups())) if match else None


def upstream_releases(code, fetch=None):
    repository, prefix, chart, _ = CHARTS[code]
    cached = _CACHE.get(repository + prefix)
    if fetch is None and cached and cached[0] > time.monotonic():
        return cached[1]
    def request(url):
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "Navigan-Utility-Planning"})
        with urllib.request.urlopen(req, timeout=6) as response:
            payload = response.read(2_000_001)
            if len(payload) > 2_000_000:
                raise ValueError("Release response exceeds limit")
            return json.loads(payload)
    try:
        releases = (fetch or request)(f"https://api.github.com/repos/{repository}/releases?per_page=100")
        versions = sorted({item["tag_name"][len(prefix):] for item in releases
                           if isinstance(item, dict) and not item.get("draft") and not item.get("prerelease")
                           and item.get("tag_name", "").startswith(prefix)
                           and semver(item["tag_name"][len(prefix):])}, key=semver, reverse=True)
    except (OSError, ValueError, KeyError, TypeError):
        raise ApiError(502, "UTILITY_RELEASES_UNAVAILABLE", "The official chart release catalogue is unavailable. Retry shortly; no versions have been invented.") from None
    if fetch is None:
        _CACHE[repository + prefix] = (time.monotonic() + 300, versions)
    return versions


class CreateUtilityUpgradePlan(Model):
    utilityCode: str = Field(pattern=r"^(headlamp|grafana|prometheus|falco)$")
    targetVersion: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    scheduledFor: datetime | None = None
    changeReason: str = Field(min_length=8, max_length=2000)

    _time = field_validator("scheduledFor", mode="before")(CreateEksUpgradePlan.parse_maintenance_start.__func__)


class UtilityUpgradePlans(EksUpgradePlans):
    table = "cluster_management.utility_upgrade_plans"

    def __init__(self, repo, access, correlation, releases=None):
        self.repo, self.access, self.correlation = repo, access, correlation
        self.releases = releases or upstream_releases

    @staticmethod
    def present(row):
        result = serialize(row)
        result["kind"] = "UTILITY"
        result["utilityEvidence"] = result.pop("readinessEvidence")
        return result

    def options(self, cluster_id, code):
        self.repo.get(cluster_id)
        if code not in CHARTS:
            return {"utilityCode": code, "label": code, "chart": None, "currentVersion": None,
                    "versions": [], "blockReason": "This utility has no supported chart planning adapter yet.", "observedAt": None}
        inventory = self.repo.platform_components(cluster_id)
        component = next((item for item in inventory["components"] if item["componentCode"].lower() == code), {})
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
            peers = [item for item in inventory["components"] if item["componentCode"].lower() in {"grafana", "prometheus"}]
            if len(peers) < 2 or any(item.get("version") != current or item.get("status") != "READY" or item.get("syncStatus") != "Synced" for item in peers):
                blocked = "Grafana and Prometheus share one monitoring chart. Both must report the same version and be healthy / synced before planning."
        versions = []
        if semver(current):
            versions = [value for value in self.releases(code) if semver(value) > semver(current)]
        if not versions and not blocked:
            blocked = "No newer stable chart release was returned by the official catalogue."
        return {"utilityCode": code, "label": label, "chart": chart, "currentVersion": current,
                "versions": versions, "blockReason": blocked, "observedAt": observed,
                "source": f"https://github.com/{repository}/releases",
                "versionKind": "Helm chart version", "compatibility": "Compatibility review required before execution"}

    def create(self, cluster_id, body):
        self.access.require("cluster.upgrade.plan")
        cluster = self.repo.get(cluster_id, lock=True)
        code = body["utilityCode"]
        evidence = self.options(cluster_id, code)
        if evidence["blockReason"]:
            raise ApiError(409, "UTILITY_EVIDENCE_REQUIRED", evidence["blockReason"])
        if body["targetVersion"] not in evidence["versions"]:
            raise ApiError(409, "UTILITY_TARGET_UNAVAILABLE", "Select a current stable release from the official chart catalogue.")
        self.repo.system_repository_access(cluster_id)  # never accept an arbitrary Git repository
        group = evidence["chart"]
        active = self.repo.db.execute(
            f"SELECT plan_id FROM {self.table} WHERE cluster_id=%s AND managed_group=%s AND status=ANY(%s)",
            [cluster_id, group, list(ACTIVE)],
        ).fetchone()
        if active:
            raise ApiError(409, "ACTIVE_UTILITY_PLAN_EXISTS", "Review the existing plan for this chart first.", {"planId": active["plan_id"]})
        scheduled = body.get("scheduledFor")
        if scheduled and scheduled <= utcnow():
            raise ApiError(422, "MAINTENANCE_WINDOW_INVALID", "Choose a future maintenance start.")
        now = utcnow()
        row = {"plan_id": "UPG-" + uuid.uuid4().hex, "cluster_id": cluster_id,
               "customer_id": cluster["customer_id"], "provider": "EKS", "utility_code": code,
               "managed_group": group, "current_version": evidence["currentVersion"],
               "target_version": body["targetVersion"], "strategy": "GITOPS_REVIEW",
               "status": "DRAFT", "scheduled_for": scheduled, "change_reason": body["changeReason"],
               "readiness_evidence": evidence, "execution": {}, "version": 1,
               "created_by": self.access.user_id, "created_at": now,
               "updated_by": self.access.user_id, "updated_at": now}
        self._save(row, create=True)
        self._audit(None, row, "UtilityUpgradePlanCreated")
        return self.present(row)

    def change(self, cluster_id, plan_id, action, body):
        # Never dispatch a utility plan into the EKS execution adapter.
        if action in {"execute", "refresh"}:
            self.get(cluster_id, plan_id)
            raise ApiError(409, "UTILITY_EXECUTION_NOT_ENABLED", "This release supports utility draft and approval. Compatibility validation and GitOps execution are not enabled; approval does not deploy the chart.")
        return super().change(cluster_id, plan_id, action, body)


def plan_service(repo, access, correlation, cluster_id, plan_id):
    """Route a scoped plan ID without allowing a utility plan into EKS execution."""
    repo.get(cluster_id)
    exists = repo.db.execute("SELECT plan_id FROM cluster_management.utility_upgrade_plans WHERE cluster_id=%s AND plan_id=%s", [cluster_id, plan_id]).fetchone()
    from .upgrade_paths import ScopedEksUpgradePlans
    return UtilityUpgradePlans(repo, access, correlation) if exists else ScopedEksUpgradePlans(repo, access, correlation)
