import copy
import uuid
from datetime import datetime, timezone
from navigan.shared.errors import ApiError
from navigan.shared.diagnostics import phase
from .configuration import DISTRIBUTIONS, validate
from .repository import serialize

TRANSITIONS = {
    "submit": ({"DRAFT", "REJECTED"}, "SUBMITTED", "CLOUD_ENGINEER"),
    "resubmit": ({"REJECTED"}, "SUBMITTED", "CLOUD_ENGINEER"),
    "review": ({"SUBMITTED"}, "UNDER_REVIEW", "PLATFORM_ARCHITECT"),
    "approve": ({"UNDER_REVIEW"}, "APPROVED", "PLATFORM_ARCHITECT"),
    "reject": ({"UNDER_REVIEW"}, "REJECTED", "PLATFORM_ARCHITECT"),
    "activate": ({"APPROVED"}, "ACTIVE", "PLATFORM_ARCHITECT"),
    "suspend": ({"ACTIVE"}, "SUSPENDED", "PLATFORM_ARCHITECT"),
    "reactivate": ({"SUSPENDED"}, "ACTIVE", "PLATFORM_ARCHITECT"),
    "deactivate": ({"ACTIVE"}, "DEACTIVATED", "PLATFORM_ARCHITECT"),
}
EVENTS = {
    "create": "EnvironmentCreated",
    "update": "EnvironmentUpdated",
    "submit": "EnvironmentSubmitted",
    "resubmit": "EnvironmentResubmitted",
    "review": "EnvironmentReviewStarted",
    "approve": "EnvironmentApproved",
    "reject": "EnvironmentRejected",
    "activate": "EnvironmentActivated",
    "suspend": "EnvironmentSuspended",
    "reactivate": "EnvironmentReactivated",
    "deactivate": "EnvironmentDeactivated",
}


class Service:
    def __init__(self, repo, correlation):
        self.repo, self.principal, self.correlation = repo, repo.principal, correlation

    def create(self, body):
        self.principal.require("CLOUD_ENGINEER")
        if DISTRIBUTIONS[body["cloudProvider"]] != body["kubernetesDistribution"]:
            raise ApiError(422, "INVALID_DISTRIBUTION", "Distribution must match the cloud provider.")
        self.repo.validate_parent(body["customerId"], body["cloudProvider"])
        self.repo.validate_type(body["environmentType"])
        with phase("environment_configuration_validation"):
            validate(
                body["configuration"], body["kubernetesDistribution"], body["configurationSchemaVersion"]
            )
        now = datetime.now(timezone.utc)
        row = {
            "environment_id": "ENV-" + uuid.uuid4().hex,
            "customer_id": body["customerId"],
            "provider_code": body["cloudProvider"],
            "kubernetes_distribution": body["kubernetesDistribution"],
            "environment_name": body["environmentName"],
            "environment_type": body["environmentType"],
            "description": body["description"],
            "configuration_schema_version": body["configurationSchemaVersion"],
            "configuration": body["configuration"],
            "status": "DRAFT",
            "version": 1,
            "approved_version": None,
            "created_by": self.principal.user_id,
            "created_at": now,
            "updated_by": self.principal.user_id,
            "updated_at": now,
            "workflow": {},
        }
        self.repo.save(row, create=True)
        row = self.repo.get(row["environment_id"])
        self.repo.record(None, row, "create", body, self.correlation, EVENTS["create"])
        return serialize(self.repo.get(row["environment_id"]))

    def change(self, identifier, action, body):
        row = self.repo.get(identifier, lock=True)
        if row["version"] != body["version"]:
            raise ApiError(409, "CONCURRENT_UPDATE", "Reload the latest environment before saving.")
        old = copy.deepcopy(row)
        if action == "update":
            if not self.principal.roles.intersection({"CLOUD_ENGINEER", "PLATFORM_ARCHITECT"}):
                self.principal.require("CLOUD_ENGINEER")
            if row["status"] not in {"DRAFT", "REJECTED"}:
                raise ApiError(
                    409, "INVALID_STATUS_TRANSITION", "Only draft or rejected environments can be edited."
                )
            self.repo.validate_parent(row["customer_id"], row["provider_code"])
            for api, column in {
                "environmentName": "environment_name",
                "environmentType": "environment_type",
                "description": "description",
                "configurationSchemaVersion": "configuration_schema_version",
                "configuration": "configuration",
            }.items():
                if api in body and body[api] is not None:
                    row[column] = body[api]
            self.repo.validate_type(row["environment_type"])
            validate(
                row["configuration"], row["kubernetes_distribution"], row["configuration_schema_version"]
            )
        else:
            states, target, role = TRANSITIONS[action]
            self.principal.require(role)
            if row["status"] not in states:
                raise ApiError(
                    409, "INVALID_STATUS_TRANSITION", "Action is not allowed in the current status."
                )
            if action in {"reject", "suspend", "deactivate"} and not body.get("reason"):
                raise ApiError(422, "REASON_REQUIRED", "Provide a reason for this action.")
            if action in {"submit", "resubmit", "approve", "activate", "reactivate"}:
                self.repo.validate_parent(row["customer_id"], row["provider_code"], active=True)
                with phase("environment_submission_validation"):
                    validate(
                        row["configuration"],
                        row["kubernetes_distribution"],
                        row["configuration_schema_version"],
                        submitting=True,
                    )
            row["status"] = target
            field = {
                "submit": "submitted",
                "resubmit": "submitted",
                "review": "reviewStarted",
                "approve": "approved",
                "reject": "rejected",
                "activate": "activated",
                "suspend": "suspended",
                "reactivate": "reactivated",
                "deactivate": "deactivated",
            }[action]
            row["workflow"][field] = {
                "by": self.principal.user_id,
                "at": datetime.now(timezone.utc).isoformat(),
                "reason": body.get("reason"),
                "reasonCode": body.get("reasonCode"),
                "comments": body.get("comments"),
            }
            if action == "approve":
                row["approved_version"] = row["version"] + 1
        row["version"] += 1
        row["updated_by"], row["updated_at"] = self.principal.user_id, datetime.now(timezone.utc)
        self.repo.save(row)
        self.repo.record(old, row, action, body, self.correlation, EVENTS[action])
        return serialize(row)
