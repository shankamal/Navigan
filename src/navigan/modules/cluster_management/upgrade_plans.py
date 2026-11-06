"""Governed, resumable Amazon EKS upgrade plans."""

from datetime import datetime, timezone
from typing import Literal
import uuid

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import Field, field_validator

from navigan.modules.customer_management.repository import json_text
from navigan.shared.errors import ApiError
from .models import Model
from .repository import serialize
from .upgrade_readiness import EksUpgradeDiscovery


ACTIVE = {"DRAFT", "SUBMITTED", "APPROVED", "SCHEDULED", "EXECUTING"}


class CreateEksUpgradePlan(Model):
    targetVersion: str = Field(pattern=r"^1\.[0-9]{2}$")
    strategy: Literal["PROVIDER_MANAGED_ROLLING"] = "PROVIDER_MANAGED_ROLLING"
    scheduledFor: datetime | None = None
    changeReason: str = Field(min_length=8, max_length=2000)

    @field_validator("scheduledFor", mode="before")
    @classmethod
    def parse_maintenance_start(cls, value):
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if isinstance(value, datetime) and value.utcoffset() is None:
            raise ValueError("Maintenance start must include a timezone.")
        return value


class UpgradePlanAction(Model):
    version: int = Field(gt=0)
    reason: str | None = Field(default=None, max_length=2000)


def utcnow():
    return datetime.now(timezone.utc)


class EksUpgradePlans:
    def __init__(self, repo, access, correlation, discovery=None):
        self.repo = repo
        self.access = access
        self.correlation = correlation
        self.discovery = discovery or EksUpgradeDiscovery()

    def list(self, cluster_id):
        cluster = self.repo.get(cluster_id)
        rows = self.repo.db.execute(
            "SELECT * FROM cluster_management.upgrade_plans "
            "WHERE cluster_id=%s ORDER BY created_at DESC,plan_id",
            [cluster_id],
        ).fetchall()
        return {
            "clusterId": cluster_id,
            "customerId": cluster["customer_id"],
            "items": [serialize(row) for row in rows],
        }

    def get(self, cluster_id, plan_id, lock=False):
        self.repo.get(cluster_id)
        row = self.repo.db.execute(
            "SELECT * FROM cluster_management.upgrade_plans "
            "WHERE cluster_id=%s AND plan_id=%s" + (" FOR UPDATE" if lock else ""),
            [cluster_id, plan_id],
        ).fetchone()
        if not row:
            raise ApiError(404, "UPGRADE_PLAN_NOT_FOUND", "Upgrade plan not found.")
        return row

    def create(self, cluster_id, body):
        self.access.require("cluster.plan")
        cluster = self.repo.get(cluster_id, lock=True)
        active = self.repo.db.execute(
            "SELECT plan_id FROM cluster_management.upgrade_plans "
            "WHERE cluster_id=%s AND status=ANY(%s) LIMIT 1",
            [cluster_id, list(ACTIVE)],
        ).fetchone()
        if active:
            raise ApiError(
                409,
                "ACTIVE_UPGRADE_PLAN_EXISTS",
                "Complete or cancel the active upgrade plan before creating another.",
                {"planId": active["plan_id"]},
            )
        _, environment = self.repo.pinned_environment_snapshot(
            cluster["environment_id"], cluster["environment_approved_version"]
        )
        evidence = self.discovery.discover(cluster, environment)
        target = evidence.get("recommendedTarget")
        if evidence["readiness"]["status"] != "READY":
            raise ApiError(
                409,
                "UPGRADE_READINESS_REQUIRED",
                "Resolve all live readiness findings before creating an upgrade plan.",
                {
                    "status": evidence["readiness"]["status"],
                    "blockers": len(evidence["readiness"]["blockers"]),
                    "warnings": len(evidence["readiness"]["warnings"]),
                },
            )
        if not target or body["targetVersion"] != target["version"]:
            raise ApiError(
                409,
                "UPGRADE_TARGET_CHANGED",
                "Use the current provider-supported sequential target.",
                {"recommendedTarget": target["version"] if target else None},
            )
        scheduled = body.get("scheduledFor")
        if scheduled and scheduled <= utcnow():
            raise ApiError(
                422,
                "MAINTENANCE_WINDOW_INVALID",
                "Choose a future maintenance window.",
            )
        now = utcnow()
        row = {
            "plan_id": "UPG-" + uuid.uuid4().hex,
            "cluster_id": cluster_id,
            "customer_id": cluster["customer_id"],
            "provider": "EKS",
            "current_version": evidence["controlPlane"]["version"],
            "target_version": target["version"],
            "strategy": body["strategy"],
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
        self._audit(None, row, "EksUpgradePlanCreated")
        return serialize(row)

    def change(self, cluster_id, plan_id, action, body):
        plan = self.get(cluster_id, plan_id, lock=True)
        if plan["version"] != body["version"]:
            raise ApiError(409, "VERSION_CONFLICT", "Refresh the upgrade plan and retry.")
        if action == "submit":
            self.access.require("cluster.plan")
            self._require_status(plan, {"DRAFT"})
            return self._transition(
                plan,
                "SUBMITTED",
                "EksUpgradePlanSubmitted",
                {
                    "submitted_by": self.access.user_id,
                    "submitted_at": utcnow(),
                },
            )
        if action == "approve":
            self.access.require("cluster.approve")
            self._require_status(plan, {"SUBMITTED"})
            if plan["created_by"] == self.access.user_id:
                raise ApiError(
                    409,
                    "MAKER_CHECKER_REQUIRED",
                    "A different authorized user must approve this upgrade plan.",
                )
            status = (
                "SCHEDULED" if plan.get("scheduled_for") and plan["scheduled_for"] > utcnow() else "APPROVED"
            )
            return self._transition(
                plan,
                status,
                "EksUpgradePlanApproved",
                {
                    "approved_by": self.access.user_id,
                    "approved_at": utcnow(),
                },
            )
        if action == "reject":
            self.access.require("cluster.approve")
            self._require_status(plan, {"SUBMITTED"})
            if not body.get("reason"):
                raise ApiError(422, "REJECTION_REASON_REQUIRED", "Provide a rejection reason.")
            return self._transition(
                plan,
                "REJECTED",
                "EksUpgradePlanRejected",
                {
                    "execution": {"rejectionReason": body["reason"]},
                },
            )
        if action == "cancel":
            self.access.require("cluster.plan")
            self._require_status(plan, {"DRAFT", "SUBMITTED", "APPROVED", "SCHEDULED"})
            return self._transition(
                plan,
                "CANCELLED",
                "EksUpgradePlanCancelled",
                {
                    "execution": {"cancellationReason": body.get("reason")},
                },
            )
        if action == "execute":
            return self._execute(plan)
        if action == "refresh":
            return self._refresh(plan)
        raise ApiError(404, "ROUTE_NOT_FOUND", "Endpoint not found.")

    def _execute(self, plan):
        self.access.require("cluster.apply")
        self._require_status(plan, {"APPROVED", "SCHEDULED"})
        if plan.get("scheduled_for") and plan["scheduled_for"] > utcnow():
            raise ApiError(
                409,
                "MAINTENANCE_WINDOW_NOT_STARTED",
                "The approved maintenance window has not started.",
            )
        cluster = self.repo.get(plan["cluster_id"])
        _, environment = self.repo.pinned_environment_snapshot(
            cluster["environment_id"], cluster["environment_approved_version"]
        )
        evidence = self.discovery.discover(cluster, environment)
        if (
            evidence["readiness"]["status"] != "READY"
            or evidence["controlPlane"]["version"] != plan["current_version"]
            or not evidence.get("recommendedTarget")
            or evidence["recommendedTarget"]["version"] != plan["target_version"]
        ):
            raise ApiError(
                409,
                "UPGRADE_EVIDENCE_CHANGED",
                "Live EKS evidence changed after approval. Create a new plan.",
            )
        eks, _ = self.discovery.client(cluster, environment)
        try:
            result = eks.update_cluster_version(
                name=cluster["cluster_name"],
                version=plan["target_version"],
                clientRequestToken=plan["plan_id"],
            )["update"]
        except (ClientError, BotoCoreError) as error:
            raise self._provider_error(error) from None
        execution = {
            "phase": "CONTROL_PLANE",
            "updateId": result["id"],
            "providerStatus": result.get("status"),
            "startedAt": utcnow().isoformat(),
            "completedStages": [],
            "addonQueue": [
                {"name": item["name"], "version": item["targetVersion"]}
                for item in evidence["addons"]
                if item.get("targetVersion") and item.get("targetVersion") != item.get("version")
            ],
            "nodeGroupQueue": [item["name"] for item in evidence["nodeGroups"]],
        }
        return self._transition(
            plan,
            "EXECUTING",
            "EksUpgradeExecutionStarted",
            {
                "readiness_evidence": evidence,
                "execution": execution,
            },
        )

    def _refresh(self, plan):
        self.access.require("cluster.apply")
        self._require_status(plan, {"EXECUTING"})
        cluster = self.repo.get(plan["cluster_id"])
        _, environment = self.repo.pinned_environment_snapshot(
            cluster["environment_id"], cluster["environment_approved_version"]
        )
        eks, _ = self.discovery.client(cluster, environment)
        execution = dict(plan.get("execution") or {})
        describe = {
            "name": cluster["cluster_name"],
            "updateId": execution["updateId"],
        }
        phase = execution.get("phase", "")
        if phase.startswith("ADDON:"):
            describe["addonName"] = phase.removeprefix("ADDON:")
        elif phase.startswith("NODEGROUP:"):
            describe["nodegroupName"] = phase.removeprefix("NODEGROUP:")
        try:
            update = eks.describe_update(**describe)["update"]
        except (ClientError, BotoCoreError, KeyError) as error:
            raise self._provider_error(error) from None
        execution["providerStatus"] = update.get("status")
        execution["lastCheckedAt"] = utcnow().isoformat()
        if update.get("status") in {"InProgress", "Pending"}:
            return self._transition(
                plan,
                "EXECUTING",
                "EksUpgradeExecutionChecked",
                {
                    "execution": execution,
                },
            )
        if update.get("status") != "Successful":
            execution["errors"] = update.get("errors", [])
            execution["failedAt"] = utcnow().isoformat()
            return self._transition(
                plan,
                "FAILED",
                "EksUpgradeExecutionFailed",
                {
                    "execution": execution,
                },
            )
        completed = list(execution.get("completedStages", []))
        completed.append(execution.get("phase"))
        execution["completedStages"] = completed
        try:
            if execution.get("addonQueue"):
                item = execution["addonQueue"].pop(0)
                next_update = eks.update_addon(
                    clusterName=cluster["cluster_name"],
                    addonName=item["name"],
                    addonVersion=item["version"],
                    resolveConflicts="PRESERVE",
                    clientRequestToken=f"{plan['plan_id']}-{item['name']}"[:64],
                )["update"]
                execution.update(
                    {
                        "phase": f"ADDON:{item['name']}",
                        "updateId": next_update["id"],
                        "providerStatus": next_update.get("status"),
                    }
                )
                return self._transition(plan, "EXECUTING", "EksUpgradeAddonStarted", {"execution": execution})
            if execution.get("nodeGroupQueue"):
                name = execution["nodeGroupQueue"].pop(0)
                next_update = eks.update_nodegroup_version(
                    clusterName=cluster["cluster_name"],
                    nodegroupName=name,
                    version=plan["target_version"],
                    clientRequestToken=f"{plan['plan_id']}-{name}"[:64],
                )["update"]
                execution.update(
                    {
                        "phase": f"NODEGROUP:{name}",
                        "updateId": next_update["id"],
                        "providerStatus": next_update.get("status"),
                    }
                )
                return self._transition(
                    plan, "EXECUTING", "EksUpgradeNodeGroupStarted", {"execution": execution}
                )
        except (ClientError, BotoCoreError) as error:
            raise self._provider_error(error) from None
        evidence = self.discovery.discover(cluster, environment)
        execution["phase"] = "VALIDATION"
        execution["completedAt"] = utcnow().isoformat()
        succeeded = (
            evidence["controlPlane"]["version"] == plan["target_version"]
            and evidence["readiness"]["checks"]["controlPlaneActive"]
            and evidence["readiness"]["checks"]["nodeGroupsAligned"]
            and evidence["readiness"]["checks"]["addonsHealthy"]
        )
        return self._transition(
            plan,
            "SUCCEEDED" if succeeded else "FAILED",
            "EksUpgradeExecutionSucceeded" if succeeded else "EksUpgradeValidationFailed",
            {"execution": execution, "readiness_evidence": evidence},
        )

    def _transition(self, old, status, action, changes):
        row = dict(old)
        row.update(changes)
        row.update(
            {
                "status": status,
                "version": old["version"] + 1,
                "updated_by": self.access.user_id,
                "updated_at": utcnow(),
            }
        )
        self._save(row)
        self._audit(old, row, action)
        return serialize(row)

    @staticmethod
    def _require_status(plan, expected):
        if plan["status"] not in expected:
            raise ApiError(
                409,
                "UPGRADE_PLAN_STATE_CONFLICT",
                "Refresh the upgrade plan before performing this action.",
                {"status": plan["status"], "expected": sorted(expected)},
            )

    def _save(self, row, create=False):
        json_columns = {"readiness_evidence", "execution"}
        if create:
            columns = list(row)
            slots = ["%s::jsonb" if key in json_columns else "%s" for key in columns]
            values = [json_text(value) if key in json_columns else value for key, value in row.items()]
            self.repo.db.execute(
                "INSERT INTO cluster_management.upgrade_plans ("
                + ",".join(columns)
                + ") VALUES ("
                + ",".join(slots)
                + ")",
                values,
            )
            return
        mutable = [
            "status",
            "readiness_evidence",
            "execution",
            "version",
            "submitted_by",
            "submitted_at",
            "approved_by",
            "approved_at",
            "updated_by",
            "updated_at",
        ]
        values = [json_text(row[key]) if key in json_columns else row.get(key) for key in mutable]
        self.repo.db.execute(
            "UPDATE cluster_management.upgrade_plans SET "
            + ",".join(f"{key}={'%s::jsonb' if key in json_columns else '%s'}" for key in mutable)
            + " WHERE plan_id=%s AND version=%s",
            [*values, row["plan_id"], row["version"] - 1],
        )

    def _audit(self, old, row, action):
        self.repo.db.execute(
            "INSERT INTO cluster_management.cluster_audit_log"
            "(cluster_id,action,performed_by,correlation_id,old_value,new_value) "
            "VALUES (%s,%s,%s,%s,%s::jsonb,%s::jsonb)",
            [
                row["cluster_id"],
                action,
                self.access.user_id,
                self.correlation,
                json_text(serialize(old)) if old else None,
                json_text(serialize(row)),
            ],
        )

    @staticmethod
    def _provider_error(error):
        code = ""
        if isinstance(error, ClientError):
            code = error.response.get("Error", {}).get("Code", "")
        if code in {"AccessDenied", "AccessDeniedException", "UnauthorizedOperation"}:
            return ApiError(
                409,
                "EKS_UPGRADE_EXECUTION_ACCESS_DENIED",
                "The customer provisioning role does not permit the approved EKS update.",
            )
        return ApiError(
            502,
            "EKS_UPGRADE_EXECUTION_FAILED",
            "Amazon EKS could not start or inspect the approved update.",
        )
