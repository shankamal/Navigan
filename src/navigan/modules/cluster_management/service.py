import copy
import uuid
from datetime import datetime, timezone
from navigan.shared.errors import ApiError
from .models import ClusterBlueprint
from .repository import serialize
from .provisioning import Provisioner


TRANSITIONS = {
    "submit": ({"DRAFT", "REJECTED"}, "SUBMITTED", "CLOUD_ENGINEER"),
    "review": ({"SUBMITTED"}, "UNDER_REVIEW", "PLATFORM_ARCHITECT"),
    "approve": ({"SUBMITTED", "UNDER_REVIEW"}, "APPROVED", "PLATFORM_ARCHITECT"),
    "reject": ({"SUBMITTED", "UNDER_REVIEW"}, "REJECTED", "PLATFORM_ARCHITECT"),
}


class Service:
    def __init__(self, repo, correlation, provisioner=None):
        self.repo, self.principal, self.correlation = repo, repo.principal, correlation
        self.provisioner = provisioner

    def create(self, body):
        self.principal.require("CLOUD_ENGINEER")
        environment, snapshot = self.repo.active_environment_snapshot(
            body["environmentId"], body.get("environmentApprovedVersion")
        )
        approved = environment["approved_version"]
        env_configuration = (snapshot or {}).get("configuration") or {}
        blueprints = env_configuration.get("clusters") or []
        if not blueprints:
            raise ApiError(
                422,
                "ENVIRONMENT_MISSING_CLUSTER_CONFIG",
                "The approved environment snapshot has no cluster blueprints. "
                "Add a cluster blueprint to the environment and get it "
                "re-approved before creating a Cluster Setup request.",
            )
        blueprint_block = next(
            (b for b in blueprints if isinstance(b, dict) and b.get("name") == body.get("blueprintName")),
            None,
        )
        if blueprint_block is None:
            raise ApiError(
                422,
                "CLUSTER_BLUEPRINT_NOT_FOUND",
                "The requested cluster blueprint is not defined on the approved environment snapshot.",
            )
        blueprint = ClusterBlueprint.model_validate(blueprint_block)
        configuration = blueprint.model_dump(exclude={"provisioning", "name"})
        configuration["blueprintName"] = blueprint.name
        now = datetime.now(timezone.utc)
        row = {
            "cluster_id": "CLU-" + uuid.uuid4().hex,
            "customer_id": environment["customer_id"],
            "environment_id": environment["environment_id"],
            "environment_approved_version": approved,
            "platform": "EKS",
            "cluster_name": body["clusterName"],
            "description": body.get("description"),
            "configuration": configuration,
            "provisioning_role_arn": blueprint.provisioning.roleArn,
            "external_id_secret_arn": blueprint.provisioning.externalIdSecretArn,
            "terraform_module_version": "1.0.0",
            "terraform_state_key": (
                f"customers/{environment['customer_id']}/environments/"
                f"{environment['environment_id']}/clusters/{body['clusterName']}/terraform.tfstate"
            ),
            "status": "DRAFT", "version": 1, "plan_artifact_key": None,
            "plan_sha256": None, "provider_execution_id": None,
            "execution_artifact_prefix": None, "outputs": {}, "workflow": {},
            "created_by": self.principal.user_id, "created_at": now,
            "updated_by": self.principal.user_id, "updated_at": now,
        }
        self.repo.save(row, create=True)
        self.repo.record(None, row, "ClusterCreated", body, self.correlation)
        return serialize(row)

    def change(self, identifier, action, body):
        row = self.repo.get(identifier, lock=True)
        if row["version"] != body["version"]:
            raise ApiError(409, "CONCURRENT_UPDATE", "Reload the latest cluster request.")
        old = copy.deepcopy(row)
        if action == "update":
            self.principal.require("CLOUD_ENGINEER")
            if row["status"] not in {"DRAFT", "REJECTED"}:
                raise ApiError(409, "INVALID_STATUS_TRANSITION", "Only draft or rejected requests can be edited.")
            if body.get("clusterName") is not None:
                row["cluster_name"] = body["clusterName"]
            if body.get("description") is not None:
                row["description"] = body["description"]
        elif action in TRANSITIONS:
            states, target, role = TRANSITIONS[action]
            self.principal.require(role)
            if row["status"] not in states:
                raise ApiError(409, "INVALID_STATUS_TRANSITION", "Action is not allowed in the current status.")
            submitted = row.get("workflow", {}).get("submitted", {}).get("by")
            if action in {"review", "approve", "reject"} and self.principal.user_id in {
                row["created_by"], submitted,
            }:
                raise ApiError(403, "INDEPENDENT_REVIEW_REQUIRED", "The request author cannot review it.")
            if action == "reject" and not body.get("reason"):
                raise ApiError(422, "REASON_REQUIRED", "Provide a rejection reason.")
            self.repo.active_environment_snapshot(
                row["environment_id"], row["environment_approved_version"]
            )
            row["status"] = target
            field = {"submit": "submitted", "review": "reviewStarted", "approve": "approved", "reject": "rejected"}[action]
            row["workflow"][field] = {
                "by": self.principal.user_id, "at": datetime.now(timezone.utc).isoformat(),
                "reason": body.get("reason"), "comments": body.get("comments"),
            }
            # Approval is the immutable hand-off to Terraform planning.  Applying
            # infrastructure remains a separate architect action after the exact
            # plan artifact and SHA-256 digest have been reviewed.
            if action == "approve":
                _, snapshot = self.repo.active_environment_snapshot(
                    row["environment_id"], row["environment_approved_version"]
                )
                build_id, prefix = (self.provisioner or Provisioner()).start(
                    "plan", row, snapshot
                )
                row["provider_execution_id"] = build_id
                row["execution_artifact_prefix"] = prefix
                row["plan_artifact_key"] = prefix + "/terraform.tfplan"
                row["plan_sha256"] = None
                row["status"] = "PLAN_RUNNING"
        elif action in {"plan", "apply"}:
            self.principal.require("PLATFORM_ARCHITECT")
            expected = {"FAILED", "PLAN_READY"} if action == "plan" else {"PLAN_READY"}
            if row["status"] not in expected:
                raise ApiError(409, "INVALID_STATUS_TRANSITION", f"{action} is not allowed in the current status.")
            if action == "apply":
                certification = row.get("workflow", {}).get("certification", {})
                if certification.get("status") != "PASSED":
                    raise ApiError(
                        409,
                        "PLAN_NOT_CERTIFIED",
                        "Terraform validation and security checks must pass before apply.",
                    )
            _, snapshot = self.repo.active_environment_snapshot(
                row["environment_id"], row["environment_approved_version"]
            )
            build_id, prefix = (self.provisioner or Provisioner()).start(action, row, snapshot)
            row["provider_execution_id"] = build_id
            row["execution_artifact_prefix"] = prefix
            row["status"] = "PLAN_RUNNING" if action == "plan" else "APPLYING"
            if action == "plan":
                row["plan_artifact_key"] = prefix + "/terraform.tfplan"
                row["plan_sha256"] = None
        else:
            raise ApiError(404, "ACTION_NOT_FOUND", "Cluster action not found.")
        row["version"] += 1
        row["updated_by"], row["updated_at"] = self.principal.user_id, datetime.now(timezone.utc)
        self.repo.save(row)
        self.repo.record(old, row, "Cluster" + action.title(), body, self.correlation)
        return serialize(row)
