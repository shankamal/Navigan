"""Provider-validated, immutable component scopes and sequential EKS upgrade paths.

Read-only preview/create never update AWS. Each hop is explicitly started inside
its approved window. Refresh advances only a healthy, already started hop.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import re
from functools import wraps
import uuid

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import Field, model_validator

from navigan.shared.errors import ApiError
from .models import Model
from .upgrade_plans import EksUpgradePlans, ACTIVE, UpgradePlanAction, utcnow
from .upgrade_readiness import minor_tuple, EksUpgradeDiscovery

SUPPORTED = {"STANDARD_SUPPORT", "EXTENDED_SUPPORT"}


def fail(code, message):
    raise ApiError(409, code, message)


def timestamp(value):
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.utcoffset() is None:
        raise ValueError("Maintenance start must include a timezone.")
    return result.astimezone(timezone.utc)


class HopWindow(Model):
    scheduledFor: str
    durationMinutes: int = Field(default=120, ge=30, le=1440)

    @model_validator(mode="after")
    def valid_time(self):
        self.scheduledFor = timestamp(self.scheduledFor).isoformat()
        return self


class CreateScopedUpgradePlan(Model):
    upgradeScope: str = Field(pattern=r"^(CLUSTER|CONTROL_PLANE|NODES|ADDONS)$")
    targetVersion: str | None = Field(default=None, pattern=r"^1\.[0-9]{2}$")
    nodeGroups: list[str] = Field(default_factory=list, max_length=100)
    addons: dict[str, str] = Field(default_factory=dict)
    hopWindows: list[HopWindow] = Field(default_factory=list, max_length=20)
    strategy: str = Field(default="PROVIDER_MANAGED_ROLLING", pattern=r"^PROVIDER_MANAGED_ROLLING$")
    changeReason: str = Field(min_length=8, max_length=2000)

    @model_validator(mode="after")
    def valid_scope(self):
        if self.upgradeScope in {"CLUSTER", "CONTROL_PLANE"} and not self.targetVersion:
            raise ValueError("Choose a final Kubernetes target.")
        if self.upgradeScope == "NODES" and not self.nodeGroups:
            raise ValueError("Select at least one managed node group.")
        if self.upgradeScope == "ADDONS" and not self.addons:
            raise ValueError("Select at least one managed add-on and version.")
        if len(self.addons) > 100 or len(set(self.nodeGroups)) != len(self.nodeGroups):
            raise ValueError("Invalid component selection.")
        return self


class ScopedUpgradePlanAction(UpgradePlanAction):
    hopWindows: list[HopWindow] | None = Field(default=None, max_length=20)


def sequential_path(current, target, catalogue):
    source, final = minor_tuple(current), minor_tuple(target)
    if not source or not final or source[0] != final[0] or final[1] <= source[1]:
        fail("INVALID_UPGRADE_PATH", "Choose a higher Kubernetes minor version in the same major version.")
    if final[1] - source[1] > 20:
        fail("UPGRADE_PATH_TOO_LONG", "Review this upgrade path with the platform team.")
    versions = {item["version"]: item for item in catalogue}
    path = [f"{source[0]}.{minor}" for minor in range(source[1] + 1, final[1] + 1)]
    if any(versions.get(v, {}).get("supportStatus") not in SUPPORTED for v in path):
        fail("UPGRADE_PATH_UNAVAILABLE", "Every intermediate version must be reported as supported in this AWS Region. Versions cannot be skipped.")
    return path


def validate_windows(steps, *, require_all=False, future=False):
    previous_end = None
    for step in steps:
        window = step.get("window")
        if not window:
            if require_all:
                fail("MAINTENANCE_WINDOWS_REQUIRED", "Choose a maintenance start and duration for every upgrade step before submission.")
            continue
        start = timestamp(window["scheduledFor"])
        minutes = window.get("durationMinutes", 120)
        if not isinstance(minutes, int) or not 30 <= minutes <= 1440:
            fail("MAINTENANCE_WINDOW_INVALID", "Use a maintenance duration between 30 minutes and 24 hours.")
        if future and start <= utcnow():
            fail("MAINTENANCE_SCHEDULE_OVERDUE", "An upgrade step is overdue. Revise the schedule and submit it again.")
        if previous_end and start < previous_end:
            fail("MAINTENANCE_WINDOWS_OVERLAP", "Upgrade-step windows must be ordered and must not overlap.")
        previous_end = start + timedelta(minutes=minutes)


def provider_read(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        try:
            self._compatibility_cache = {}
            return method(self, *args, **kwargs)
        except (ClientError, BotoCoreError) as error:
            code = getattr(error, "response", {}).get("Error", {}).get("Code", "")
            if code in {"AccessDenied", "AccessDeniedException", "UnauthorizedOperation"}:
                raise ApiError(409, "EKS_DISCOVERY_ACCESS_DENIED", "The registered customer provisioning role cannot read cluster versions or add-on compatibility in this account and Region.") from None
            raise ApiError(502, "EKS_DISCOVERY_UNAVAILABLE", "Amazon EKS component discovery is unavailable. Refresh and retry before saving a plan.") from None
    return guarded


def addon_path(installed, desired, catalogue):
    """Never skip an add-on minor; only use provider-compatible releases."""
    def version(value):
        match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:-eksbuild\.(\d+))?", value or "")
        return tuple(int(v or 0) for v in match.groups()) if match else None
    source, target = version(installed), version(desired)
    if not source or not target or source[0] != target[0] or target <= source:
        fail("ADDON_PATH_UNAVAILABLE", "Choose a newer add-on release within the same major version. Unrecognised versions need a separately reviewed migration.")
    choices = {item["version"]: version(item["version"]) for item in catalogue}
    result = []
    for minor in range(source[1] + 1, target[1]):
        candidates = [(v, key) for key,v in choices.items() if v and v[:2] == (source[0],minor)]
        if not candidates:
            fail("ADDON_PATH_UNAVAILABLE", "An intermediate add-on minor is not compatible with this control plane. Upgrade it in a separate reviewed stage.")
        result.append(max(candidates)[1])
    return result + [desired]


class ScopedEksUpgradePlans(EksUpgradePlans):
    def present(self, row):
        result = super().present(row)
        if not row.get("plan_spec"):
            result.pop("planSpec", None)
        if row.get("plan_spec") and not row.get("readiness_evidence"):
            result.pop("readinessEvidence", None)
        return result

    def _context(self, cluster_id):
        cluster = self.repo.get(cluster_id)
        _, environment = self.repo.pinned_environment_snapshot(cluster["environment_id"], cluster["environment_approved_version"])
        eks, region = self.discovery.client(cluster, environment)
        return cluster, environment, eks, region

    def _inventory(self, cluster, eks):
        cp = eks.describe_cluster(name=cluster["cluster_name"])["cluster"]
        return cp, self.discovery._node_groups(eks, cluster["cluster_name"]), self.discovery._addons(eks, cluster["cluster_name"], cp["version"])

    def _compatible(self, eks, name, version):
        # Cache only within this request/service; never reuse customer evidence
        # between requests, approvals or execution refreshes.
        cache = getattr(self, "_compatibility_cache", None)
        if cache is None:
            cache = self._compatibility_cache = {}
        key = (id(eks), name, version)
        if key in cache:
            return cache[key]
        candidates, token = [], None
        for _ in range(20):
            request = {"addonName": name, "kubernetesVersion": version, "maxResults": 100}
            if token:
                request["nextToken"] = token
            page = eks.describe_addon_versions(**request)
            for addon in page.get("addons", []):
                for item in addon.get("addonVersions", []):
                    compatible = [c for c in item.get("compatibilities", []) if c.get("clusterVersion") == version]
                    if compatible and item.get("addonVersion"):
                        candidates.append({"version": item["addonVersion"], "recommended": any(c.get("defaultVersion") for c in compatible)})
            token = page.get("nextToken")
            if not token:
                cache[key] = candidates
                return candidates
        fail("ADDON_CATALOGUE_INCOMPLETE", "The complete add-on compatibility catalogue could not be read.")

    @provider_read
    def options(self, cluster_id):
        cluster, _, eks, region = self._context(cluster_id)
        cp, nodes, addons = self._inventory(cluster, eks)
        catalogue = self.discovery._versions(eks)
        targets = []
        for item in catalogue:
            candidate = minor_tuple(item.get("version"))
            if candidate and candidate > minor_tuple(cp["version"]):
                try:
                    sequential_path(cp["version"], item["version"], catalogue)
                    targets.append(item["version"])
                except ApiError:
                    pass
        return {"clusterId": cluster_id, "provider": "EKS", "region": region,
                "currentVersion": cp["version"], "status": cp.get("status"),
                "targetVersions": sorted(set(targets), key=minor_tuple), "nodeGroups": nodes,
                "addons": [{**a, "versions": self._compatible(eks, a["name"], cp["version"])} for a in addons],
                "observedAt": utcnow().isoformat(), "nodeUpgradeNote": "Node-only plans align selected managed node groups to the current control-plane Kubernetes version. Custom AMIs require a separate launch-template workflow."}

    def _specification(self, cluster, eks, body):
        cp, nodes, addons = self._inventory(cluster, eks)
        self._healthy(cp, nodes, addons, eks, cluster["cluster_name"], require_aligned=body["upgradeScope"] in {"CLUSTER", "CONTROL_PLANE"})
        scope, current = body["upgradeScope"], cp["version"]
        targets = sequential_path(current, body["targetVersion"], self.discovery._versions(eks)) if scope in {"CLUSTER", "CONTROL_PLANE"} else [current]
        if scope == "NODES" and body.get("targetVersion") not in {None, current}:
            fail("NODE_TARGET_INVALID", "Node-only plans must target the current control-plane version.")
        if (scope in {"CLUSTER", "CONTROL_PLANE"} and (body.get("nodeGroups") or body.get("addons"))) or (scope == "NODES" and body.get("addons")) or (scope == "ADDONS" and body.get("nodeGroups")):
            fail("UPGRADE_SCOPE_INVALID", "Use the components belonging to the selected upgrade scope.")
        if scope == "ADDONS" and body.get("targetVersion") not in {None, current}:
            fail("ADDON_TARGET_INVALID", "Add-on-only plans use the current control-plane version.")
        node_by_name = {n["name"]: n for n in nodes}
        selected = list(node_by_name) if scope == "CLUSTER" else body.get("nodeGroups", []) if scope == "NODES" else []
        if any(name not in node_by_name for name in selected):
            fail("NODE_SELECTION_CHANGED", "A selected managed node group is no longer present.")
        if any(node_by_name[name].get("amiType") == "CUSTOM" for name in selected):
            fail("CUSTOM_AMI_REQUIRES_PLAN", "Custom AMI node groups need an explicit AMI/launch-template plan and cannot use this adapter.")
        addon_by_name = {a["name"]: a for a in addons}
        if scope == "ADDONS" and any(name not in addon_by_name for name in body["addons"]):
            fail("ADDON_SELECTION_CHANGED", "A selected managed add-on is no longer present.")
        windows = body.get("hopWindows", [])
        if windows and len(windows) != len(targets):
            fail("MAINTENANCE_WINDOWS_REQUIRED", "Provide one maintenance window for each version transition.")
        steps = []
        node_versions = {name: node_by_name[name].get("version") for name in selected}
        addon_versions = {name: a["version"] for name, a in addon_by_name.items()}
        for index, target in enumerate(targets):
            operations = []
            names = list(addon_by_name) if scope in {"CLUSTER", "CONTROL_PLANE"} else list(body.get("addons", {})) if scope == "ADDONS" else []
            before, after = [], []
            for name in names:
                installed = addon_versions[name]
                choices = self._compatible(eks, name, target)
                valid = {c["version"] for c in choices}
                if scope == "ADDONS":
                    desired = body["addons"][name]
                    if desired not in valid:
                        fail("ADDON_VERSION_INCOMPATIBLE", "A selected add-on version is not compatible with the cluster.")
                    if desired != installed:
                        previous = installed
                        for version in addon_path(installed, desired, choices):
                            after.append({"kind": "ADDON", "stage": "COMPATIBILITY_COMPONENTS", "name": name, "from": previous, "to": version})
                            previous = version
                elif scope == "CONTROL_PLANE" and installed not in valid:
                    fail("ADDON_PREREQUISITE_REQUIRED", f"Managed add-on {name} at {installed} is not compatible with Kubernetes {target}. Create and approve a managed add-on plan before the control-plane upgrade.")
                elif installed not in valid:
                    source_choices = {c["version"] for c in self._compatible(eks, name, current)}
                    bridge = next((c["version"] for c in choices if c["recommended"] and c["version"] in source_choices), None)
                    bridge = bridge or next((c["version"] for c in choices if c["version"] in source_choices), None)
                    if not bridge:
                        fail("ADDON_BRIDGE_UNAVAILABLE", f"Add-on {name} has no provider-reported version compatible with both {current} and {target}. Remediate it before this upgrade.")
                    previous = installed
                    for version in addon_path(installed, bridge, self._compatible(eks, name, current)):
                        before.append({"kind": "ADDON", "stage": "PREREQUISITE_COMPONENTS", "name": name, "from": previous, "to": version, "prerequisite": True})
                        previous = version
                    desired = bridge
                else:
                    desired = installed
                addon_versions[name] = desired
            operations.extend(before)
            if scope in {"CLUSTER", "CONTROL_PLANE"}:
                operations.append({"kind": "CONTROL_PLANE", "stage": "CONTROL_PLANE", "name": cluster["cluster_name"], "from": current, "to": target})
            operations.extend(after)
            for name in selected:
                if node_versions[name] != target:
                    operations.append({"kind": "NODEGROUP", "stage": "DATA_PLANE", "name": name, "from": node_versions[name], "to": target})
                    node_versions[name] = target
            if not operations:
                fail("NO_UPGRADE_CHANGES", "Selected components are already at the requested versions. Same-version AMI patching is not included in this adapter.")
            steps.append({"fromVersion": current, "targetVersion": target, "operations": operations,
                          "window": windows[index] if windows else None})
            current = target
        validate_windows(steps, future=True)
        return {"format": 1, "scope": scope, "sourceVersion": cp["version"], "finalVersion": targets[-1],
                "steps": steps, "nodeGroups": selected, "addonNames": list(addon_by_name) if scope == "CLUSTER" else list(body.get("addons", {})) if scope == "ADDONS" else [],
                "validation": "Only discovered EKS-managed components are included. Self-managed nodes and utilities require separate plans. Application checks require operator verification."}

    @provider_read
    def create(self, cluster_id, body):
        self.access.require("cluster.upgrade.plan")
        self.repo.get(cluster_id, lock=True)
        if self.repo.db.execute(f"SELECT plan_id FROM {self.table} WHERE cluster_id=%s AND status=ANY(%s) LIMIT 1", [cluster_id, list(ACTIVE)]).fetchone():
            fail("ACTIVE_UPGRADE_PLAN_EXISTS", "Complete or cancel the active cluster/component plan before creating another for this cluster.")
        cluster, _, eks, _ = self._context(cluster_id)
        spec = self._specification(cluster, eks, body)
        first = spec["steps"][0].get("window")
        now = utcnow()
        row = {"plan_id": "UPG-" + uuid.uuid4().hex, "cluster_id": cluster_id, "customer_id": cluster["customer_id"],
               "provider": "EKS", "current_version": spec["sourceVersion"], "target_version": spec["finalVersion"],
               "strategy": "PROVIDER_MANAGED_ROLLING", "status": "DRAFT", "scheduled_for": timestamp(first["scheduledFor"]) if first else None,
               "change_reason": body["changeReason"], "readiness_evidence": {}, "execution": {}, "plan_spec": spec,
               "version": 1, "created_by": self.access.user_id, "created_at": now, "updated_by": self.access.user_id, "updated_at": now}
        self._save(row, create=True)
        self._audit(None, row, "ScopedEksUpgradePlanCreated")
        return self.present(row)

    def _save(self, row, create=False):
        # Keep the old service usable for pre-migration plans and utility subclasses.
        if not row.get("plan_spec"):
            return super()._save(row, create)
        from navigan.modules.customer_management.repository import json_text
        spec = row["plan_spec"]
        if create:
            json_columns = {"readiness_evidence", "execution", "plan_spec"}
            columns = list(row)
            slots = ["%s::jsonb" if key in json_columns else "%s" for key in columns]
            values = [json_text(value) if key in json_columns else value for key,value in row.items()]
            self.repo.db.execute(f"INSERT INTO {self.table} (" + ",".join(columns) + ") VALUES (" + ",".join(slots) + ")", values)
        else:
            super()._save(row)
            self.repo.db.execute(f"UPDATE {self.table} SET plan_spec=%s::jsonb WHERE plan_id=%s AND version=%s", [json_text(spec), row["plan_id"], row["version"]])

    def change(self, cluster_id, plan_id, action, body):
        plan = self.get(cluster_id, plan_id, lock=True)
        if not plan.get("plan_spec"):
            return super().change(cluster_id, plan_id, action, body)
        if plan["version"] != body["version"]:
            fail("VERSION_CONFLICT", "Refresh the plan before retrying.")
        if action in {"submit", "approve"}:
            validate_windows(plan["plan_spec"]["steps"], require_all=True, future=True)
        if action == "cancel":
            self.access.require("cluster.upgrade.plan")
            self._require_status(plan, {"DRAFT", "SUBMITTED", "APPROVED", "SCHEDULED"})
            execution = deepcopy(plan.get("execution") or {})
            execution["cancellationReason"] = body.get("reason")
            return self._transition(plan, "CANCELLED", "ScopedEksUpgradeCancelled", {"execution": execution})
        if action == "continue":
            return self._continue(plan)
        if action == "reschedule":
            self.access.require("cluster.upgrade.plan")
            self._require_status(plan, {"DRAFT", "SUBMITTED"})
            spec = deepcopy(plan["plan_spec"])
            windows = body.get("hopWindows")
            if windows is None and len(spec["steps"]) == 1 and body.get("scheduledFor"):
                windows = [{"scheduledFor": body["scheduledFor"].isoformat(), "durationMinutes": (spec["steps"][0].get("window") or {}).get("durationMinutes", 120)}]
            if not windows or len(windows) != len(spec["steps"]):
                fail("MAINTENANCE_WINDOWS_REQUIRED", "Revise every upgrade-step window before resubmitting this path.")
            for step, window in zip(spec["steps"], windows):
                step["window"] = window
            validate_windows(spec["steps"], require_all=True, future=True)
            return self._transition(plan, "DRAFT", "ScopedEksUpgradePlanRescheduled", {"plan_spec": spec, "scheduled_for": timestamp(windows[0]["scheduledFor"]), "submitted_by": None, "submitted_at": None, "approved_by": None, "approved_at": None})
        return super().change(cluster_id, plan_id, action, body)

    @staticmethod
    def _healthy(cp, nodes, addons, eks, name, require_aligned):
        if cp.get("status") != "ACTIVE" or any(n.get("status") != "ACTIVE" or not minor_tuple(n.get("version")) or n.get("healthIssues") for n in nodes) or any(a.get("status") != "ACTIVE" or a.get("healthIssues") for a in addons):
            fail("UPGRADE_READINESS_REQUIRED", "Control plane, node groups and managed add-ons must be healthy.")
        if require_aligned and any(n.get("version") != cp["version"] for n in nodes):
            fail("NODE_ALIGNMENT_REQUIRED", "Align managed node groups with the control plane before starting this version transition.")
        if any(u.get("status") in {"InProgress", "Pending"} for u in EksUpgradeDiscovery._updates(eks, name)):
            fail("EKS_UPDATE_IN_PROGRESS", "An EKS update is already in progress.")

    @staticmethod
    def _operation_stage(operation):
        explicit = operation.get("stage")
        if explicit:
            return explicit
        if operation["kind"] == "CONTROL_PLANE":
            return "CONTROL_PLANE"
        if operation["kind"] == "NODEGROUP":
            return "DATA_PLANE"
        if operation.get("prerequisite"):
            return "PREREQUISITE_COMPONENTS"
        return "COMPATIBILITY_COMPONENTS"

    @staticmethod
    def _gate_phase(stage):
        return f"AWAITING_{stage}_HEALTH"

    def _complete_step(self, plan, execution):
        execution["completedHops"] = execution["hopIndex"] + 1
        if execution["completedHops"] < len(plan["plan_spec"]["steps"]):
            execution["hopIndex"] += 1
            execution["operationIndex"] = 0
            execution["phase"] = "AWAITING_NEXT_WINDOW"
            execution.pop("gate", None)
            next_window = plan["plan_spec"]["steps"][execution["hopIndex"]]["window"]
            return self._transition(
                plan,
                "SCHEDULED",
                "ScopedEksUpgradeHopCompleted",
                {
                    "execution": execution,
                    "scheduled_for": timestamp(next_window["scheduledFor"]),
                },
            )
        cluster, _, eks, _ = self._context(plan["cluster_id"])
        cp, nodes, addons = self._inventory(cluster, eks)
        self._healthy(
            cp,
            nodes,
            addons,
            eks,
            cluster["cluster_name"],
            require_aligned=False,
        )
        final_target = plan["plan_spec"]["finalVersion"]
        selected = set(plan["plan_spec"].get("nodeGroups") or [])
        if cp["version"] != final_target:
            fail(
                "UPGRADE_POST_VALIDATION_FAILED",
                "The control plane does not match the approved final target.",
            )
        if any(
            node["name"] in selected and node.get("version") != final_target
            for node in nodes
        ):
            fail(
                "UPGRADE_POST_VALIDATION_FAILED",
                "Managed node groups have not all reached the approved final target.",
            )
        observed = utcnow().isoformat()
        execution.update(
            {
                "phase": "POST_VALIDATION",
                "completedAt": observed,
                "postValidation": {
                    "status": "PASSED",
                    "observedAt": observed,
                    "controlPlaneVersion": cp["version"],
                    "nodeGroupsHealthy": all(
                        node.get("status") == "ACTIVE" and not node.get("healthIssues")
                        for node in nodes
                    ),
                    "addonsHealthy": all(
                        addon.get("status") == "ACTIVE" and not addon.get("healthIssues")
                        for addon in addons
                    ),
                    "applicationValidation": "OPERATOR_VERIFICATION_REQUIRED",
                },
            }
        )
        execution.pop("gate", None)
        return self._transition(
            plan,
            "SUCCEEDED",
            "ScopedEksUpgradeSucceeded",
            {"execution": execution},
        )

    def _pause_for_gate(self, plan, execution, after_stage, next_stage):
        observed = utcnow().isoformat()
        execution.update(
            {
                "phase": self._gate_phase(after_stage),
                "providerStatus": "Successful",
                "gate": {
                    "afterStage": after_stage,
                    "nextStage": next_stage,
                    "status": "PENDING",
                    "requiredAt": observed,
                },
            }
        )
        return self._transition(
            plan,
            "EXECUTING",
            "ScopedEksUpgradeHealthGateRequired",
            {"execution": execution},
        )

    def _continue(self, plan):
        self._compatibility_cache = {}
        self.access.require("cluster.upgrade.execute")
        self._require_status(plan, {"EXECUTING"})
        spec = plan.get("plan_spec")
        if not spec or spec.get("scope") != "CLUSTER":
            fail(
                "UPGRADE_HEALTH_GATE_UNAVAILABLE",
                "Explicit stage continuation is only used by full platform upgrade plans.",
            )
        execution = deepcopy(plan.get("execution") or {})
        gate = execution.get("gate")
        if not isinstance(gate, dict) or gate.get("status") != "PENDING":
            fail(
                "UPGRADE_HEALTH_GATE_NOT_READY",
                "No staged health gate is awaiting confirmation.",
            )
        expected_phase = self._gate_phase(gate.get("afterStage"))
        if execution.get("phase") != expected_phase:
            fail(
                "UPGRADE_HEALTH_GATE_NOT_READY",
                "Refresh the execution state before continuing.",
            )
        cluster, _, eks, _ = self._context(plan["cluster_id"])
        cp, nodes, addons = self._inventory(cluster, eks)
        self._healthy(
            cp,
            nodes,
            addons,
            eks,
            cluster["cluster_name"],
            require_aligned=False,
        )
        step = spec["steps"][execution["hopIndex"]]
        after_stage = gate["afterStage"]
        if after_stage == "CONTROL_PLANE":
            if cp["version"] != step["targetVersion"]:
                fail(
                    "UPGRADE_HEALTH_GATE_FAILED",
                    "The control plane has not reached the approved target version.",
                )
            incompatible = [
                addon["name"]
                for addon in addons
                if addon.get("version")
                not in {
                    item["version"]
                    for item in self._compatible(
                        eks, addon["name"], step["targetVersion"]
                    )
                }
            ]
            if incompatible:
                fail(
                    "UPGRADE_HEALTH_GATE_FAILED",
                    "Managed add-ons are not compatible with the upgraded control plane.",
                )
        elif after_stage == "DATA_PLANE":
            selected = set(spec.get("nodeGroups") or [])
            lagging = [
                node["name"]
                for node in nodes
                if node["name"] in selected
                and node.get("version") != step["targetVersion"]
            ]
            if lagging:
                fail(
                    "UPGRADE_HEALTH_GATE_FAILED",
                    "Managed node groups have not all reached the approved target version.",
                )
        else:
            fail(
                "UPGRADE_HEALTH_GATE_NOT_READY",
                "This execution stage does not require an operator continuation.",
            )
        gate.update(
            {
                "status": "PASSED",
                "confirmedAt": utcnow().isoformat(),
                "confirmedBy": self.access.user_id,
            }
        )
        execution["gate"] = gate
        history = list(execution.get("gateHistory") or [])
        history.append(deepcopy(gate))
        execution["gateHistory"] = history
        execution.pop("gate", None)
        if execution["operationIndex"] < len(step["operations"]):
            execution["phase"] = "STARTING_NEXT_STAGE"
            return self._start_operation(plan, execution, eks, cluster)
        return self._complete_step(plan, execution)

    def _execute(self, plan):
        self._compatibility_cache = {}
        self.access.require("cluster.upgrade.execute")
        self._require_status(plan, {"APPROVED", "SCHEDULED"})
        spec = plan.get("plan_spec")
        if not spec:
            fail("UPGRADE_PLAN_REVISION_REQUIRED", "Recreate this legacy plan with explicit component scope and maintenance windows before execution.")
        if not self.recorded_approval_valid(plan):
            fail("APPROVAL_REQUIRED", "Record an authorized approval before execution. Platform Architect self-approval must include its policy record.")
        execution = deepcopy(plan.get("execution") or {})
        index = execution.get("hopIndex", 0)
        step = spec["steps"][index]
        start = timestamp(step["window"]["scheduledFor"])
        now = utcnow()
        if now < start:
            fail("MAINTENANCE_WINDOW_NOT_STARTED", "The approved upgrade-step window has not started.")
        if now >= start + timedelta(minutes=step["window"]["durationMinutes"]):
            fail("MAINTENANCE_SCHEDULE_OVERDUE", "The approved upgrade-step window has expired. Create a new reviewed plan.")
        cluster, _, eks, _ = self._context(plan["cluster_id"])
        cp, nodes, addons = self._inventory(cluster, eks)
        if spec["scope"] == "CLUSTER" and (set(spec["nodeGroups"]) != {n["name"] for n in nodes} or set(spec["addonNames"]) != {a["name"] for a in addons}):
            fail("UPGRADE_COMPONENT_DRIFT", "Managed component membership changed after approval. Create a fresh plan.")
        if cp["version"] != step["fromVersion"]:
            fail("UPGRADE_EVIDENCE_CHANGED", "The live control-plane version differs from the approved upgrade step.")
        self._healthy(cp, nodes, addons, eks, cluster["cluster_name"], require_aligned=spec["scope"] in {"CLUSTER", "CONTROL_PLANE"})
        insights = []
        if spec["scope"] in {"CLUSTER", "CONTROL_PLANE"}:
            sequential_path(cp["version"], step["targetVersion"], self.discovery._versions(eks))
            insights = self.discovery._insights(eks, cluster["cluster_name"], step["targetVersion"])
            if any(i.get("status") != "PASSING" for i in insights):
                fail("UPGRADE_INSIGHTS_REQUIRED", "Resolve fresh EKS upgrade insights before executing this step.")
        first_operation = step["operations"][0]
        execution.update(
            {
                "hopIndex": index,
                "operationIndex": 0,
                "phase": "STARTING",
                "startedAt": now.isoformat(),
                "results": execution.get("results", []),
                "startPreflight": {
                    "status": "PASSED",
                    "observedAt": now.isoformat(),
                    "operatorId": self.access.user_id,
                    "approvedBy": plan.get("approved_by"),
                    "windowStartsAt": start.isoformat(),
                    "windowEndsAt": (
                        start + timedelta(minutes=step["window"]["durationMinutes"])
                    ).isoformat(),
                    "fromVersion": step["fromVersion"],
                    "targetVersion": step["targetVersion"],
                    "firstStage": self._operation_stage(first_operation),
                    "controlPlaneVersion": cp["version"],
                    "nodeGroupsHealthy": all(
                        node.get("status") == "ACTIVE" and not node.get("healthIssues")
                        for node in nodes
                    ),
                    "addonsHealthy": all(
                        addon.get("status") == "ACTIVE" and not addon.get("healthIssues")
                        for addon in addons
                    ),
                    "upgradeInsightsPassing": all(
                        insight.get("status") == "PASSING" for insight in insights
                    ),
                    "applicationValidation": "OPERATOR_CONFIRMED_BEFORE_START",
                },
            }
        )
        return self._start_operation(plan, execution, eks, cluster)

    def _start_operation(self, plan, execution, eks, cluster):
        step = plan["plan_spec"]["steps"][execution["hopIndex"]]
        operation = step["operations"][execution["operationIndex"]]
        window = step["window"]
        if utcnow() >= timestamp(window["scheduledFor"]) + timedelta(minutes=window["durationMinutes"]):
            execution["validationError"] = "Maintenance window expired. No further component update was started. Reconcile completed changes and create a new reviewed plan."
            return self._transition(plan, "FAILED", "ScopedEksUpgradeWindowExpired", {"execution": execution})
        cp, nodes, addons = self._inventory(cluster, eks)
        self._healthy(cp, nodes, addons, eks, cluster["cluster_name"], require_aligned=False)
        actual = cp["version"] if operation["kind"] == "CONTROL_PLANE" else next((c.get("version") for c in (nodes if operation["kind"] == "NODEGROUP" else addons) if c["name"] == operation["name"]), None)
        if actual != operation["from"]:
            fail("UPGRADE_COMPONENT_DRIFT", "An approved component version changed. Review a fresh plan.")
        if operation["kind"] == "ADDON" and operation["to"] not in {c["version"] for c in self._compatible(eks, operation["name"], cp["version"])}:
            fail("ADDON_VERSION_INCOMPATIBLE", "The approved add-on target is no longer compatible with the live control plane.")
        if operation["kind"] == "CONTROL_PLANE":
            if any(n.get("version") != cp["version"] for n in nodes):
                fail("NODE_ALIGNMENT_REQUIRED", "Align managed nodes before this control-plane transition.")
            if any(a.get("version") not in {c["version"] for c in self._compatible(eks,a["name"],operation["to"])} for a in addons):
                fail("ADDON_VERSION_INCOMPATIBLE", "All installed add-ons must be compatible with the next control-plane version.")
        token = hashlib.sha256(f"{plan['plan_id']}:{execution['hopIndex']}:{execution['operationIndex']}".encode()).hexdigest()
        try:
            if operation["kind"] == "CONTROL_PLANE":
                result = eks.update_cluster_version(name=cluster["cluster_name"], version=operation["to"], clientRequestToken=token)
            elif operation["kind"] == "NODEGROUP":
                result = eks.update_nodegroup_version(clusterName=cluster["cluster_name"], nodegroupName=operation["name"], version=operation["to"], clientRequestToken=token)
            else:
                result = eks.update_addon(clusterName=cluster["cluster_name"], addonName=operation["name"], addonVersion=operation["to"], resolveConflicts="PRESERVE", clientRequestToken=token)
        except (ClientError, BotoCoreError) as error:
            raise self._provider_error(error) from None
        execution.update({"phase": operation["kind"] + ":" + operation["name"], "updateId": result["update"]["id"], "providerStatus": result["update"].get("status")})
        return self._transition(plan, "EXECUTING", "ScopedEksUpgradeOperationStarted", {"execution": execution})

    def _refresh(self, plan):
        self._compatibility_cache = {}
        if not plan.get("plan_spec"):
            return super()._refresh(plan)
        self.access.require("cluster.upgrade.execute")
        self._require_status(plan, {"EXECUTING"})
        if not plan.get("plan_spec"):
            fail("UPGRADE_PLAN_REVISION_REQUIRED", "This legacy plan cannot use the component executor.")
        cluster, _, eks, _ = self._context(plan["cluster_id"])
        execution = deepcopy(plan["execution"])
        if str(execution.get("phase", "")).startswith("AWAITING_") and execution.get("gate"):
            fail(
                "UPGRADE_HEALTH_GATE_REQUIRED",
                "Validate the live stage health and explicitly continue before starting the next stage.",
            )
        step = plan["plan_spec"]["steps"][execution["hopIndex"]]
        operation = step["operations"][execution["operationIndex"]]
        request = {"name": cluster["cluster_name"], "updateId": execution["updateId"]}
        if operation["kind"] == "NODEGROUP":
            request["nodegroupName"] = operation["name"]
        elif operation["kind"] == "ADDON":
            request["addonName"] = operation["name"]
        try:
            update = eks.describe_update(**request)["update"]
        except (ClientError, BotoCoreError) as error:
            raise self._provider_error(error) from None
        execution.update({"providerStatus": update.get("status"), "lastCheckedAt": utcnow().isoformat()})
        if update.get("status") in {"InProgress", "Pending"}:
            return self._transition(plan, "EXECUTING", "ScopedEksUpgradeChecked", {"execution": execution})
        if update.get("status") != "Successful":
            execution["errors"] = update.get("errors", [])
            return self._transition(plan, "FAILED", "ScopedEksUpgradeFailed", {"execution": execution})
        cp, nodes, addons = self._inventory(cluster, eks)
        actual = cp["version"] if operation["kind"] == "CONTROL_PLANE" else next((c.get("version") for c in (nodes if operation["kind"] == "NODEGROUP" else addons) if c["name"] == operation["name"]), None)
        try:
            self._healthy(cp, nodes, addons, eks, cluster["cluster_name"], require_aligned=False)
            if actual != operation["to"]:
                fail("UPGRADE_VALIDATION_FAILED", "The component did not reach its approved target version.")
        except ApiError as error:
            execution["validationError"] = error.message
            return self._transition(plan, "FAILED", "ScopedEksUpgradeValidationFailed", {"execution": execution})
        execution["results"].append({**operation, "hopIndex": execution["hopIndex"], "status": "SUCCEEDED", "completedAt": utcnow().isoformat()})
        execution["operationIndex"] += 1
        scope = plan["plan_spec"]["scope"]
        stage = self._operation_stage(operation)
        next_operation = (
            step["operations"][execution["operationIndex"]]
            if execution["operationIndex"] < len(step["operations"])
            else None
        )
        next_stage = self._operation_stage(next_operation) if next_operation else "POST_VALIDATION"
        if scope == "CLUSTER" and stage in {"CONTROL_PLANE", "DATA_PLANE"} and stage != next_stage:
            return self._pause_for_gate(plan, execution, stage, next_stage)
        if next_operation:
            return self._start_operation(plan, execution, eks, cluster)
        return self._complete_step(plan, execution)
