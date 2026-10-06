import copy
import secrets
import uuid

from navigan.shared.errors import ApiError

from .repository import serialize


TRANSITIONS = {
    "discover": (
        {"DRAFT", "REJECTED"},
        "SOURCE_ENROLLMENT_PENDING",
        "migration.edit",
    ),
    "assess": (
        {"INVENTORY_READY"},
        "DISCOVERY_PENDING",
        "migration.edit",
    ),
    "submit": (
        {"ASSESSMENT_READY"},
        "SUBMITTED",
        "migration.submit",
    ),
    "review": ({"SUBMITTED"}, "UNDER_REVIEW", "migration.review"),
    "approve": ({"UNDER_REVIEW"}, "APPROVED", "migration.approve"),
    "reject": (
        {"SUBMITTED", "UNDER_REVIEW"},
        "REJECTED",
        "migration.approve",
    ),
    "cancel": (
        {
            "DRAFT",
            "REJECTED",
            "DISCOVERY_PENDING",
            "DISCOVERING",
            "ASSESSMENT_READY",
            "SUBMITTED",
        },
        "CANCELLED",
        "migration.edit",
    ),
}


class Service:
    def __init__(self, repo, access, correlation):
        self.repo = repo
        self.access = access
        self.principal = repo.principal
        self.correlation = correlation

    def create(self, body):
        self.access.require("migration.create")
        self.access.require_customer(body["customerId"])
        self.repo.require_customer_visible(body["customerId"])

        row = {
            "migration_id": "MIG-" + uuid.uuid4().hex,
            "customer_id": body["customerId"],
            "name": body["name"],
            "description": body.get("description"),
            "source_platform": body["source"]["platform"],
            "target_platform": body["target"]["platform"],
            "source_configuration": body["source"],
            "target_configuration": body["target"],
            "migration_scope": body["scope"],
            "execution_mode": "ASSESSMENT_ONLY",
            "status": "DRAFT",
            "version": 1,
            "created_by": self.principal.user_id,
            "updated_by": self.principal.user_id,
            "change_reason": "Created assessment-only migration request",
        }

        self.repo.save(
            row,
            None,
            "MIGRATION_CREATED",
            self.correlation,
            create=True,
        )
        return serialize(row)

    def create_source_cluster(self, body):
        self.access.require("migration.create")
        self.access.require_customer(body["customerId"])
        self.repo.require_customer_visible(body["customerId"])

        location = body["location"]
        row = {
            "source_cluster_id": "SRC-" + uuid.uuid4().hex,
            "customer_id": body["customerId"],
            "name": body["name"],
            "distribution": body.get("distribution"),
            "location_type": location["type"],
            "cloud_provider": location.get("cloudProvider"),
            "region": location.get("region"),
            "registration_method": body["registrationMethod"],
            "delivery_method": body["delivery"]["method"],
            "delivery_configuration": (
                body["delivery"].get("awsSsm") or {}
            ),
            "status": "PENDING_ENROLLMENT",
            "version": 1,
            "created_by": self.principal.user_id,
            "updated_by": self.principal.user_id,
        }
        return serialize(
            self.repo.create_source_cluster(row, self.correlation)
        )

    def update_source_cluster_delivery(self, identifier, body):
        self.access.require("migration.edit")
        source_cluster = self.repo.get_source_cluster(
            identifier,
            lock=True,
        )
        self.access.require_customer(
            source_cluster["customer_id"],
            source_cluster["created_by"],
        )
        if source_cluster["version"] != body["version"]:
            raise ApiError(
                409,
                "CONCURRENT_UPDATE",
                "Reload the latest source cluster.",
            )
        if source_cluster["status"] == "REVOKED":
            raise ApiError(
                409,
                "SOURCE_CLUSTER_REVOKED",
                "A revoked source cluster cannot be configured.",
            )
        return serialize(
            self.repo.update_source_cluster_delivery(
                source_cluster,
                body["delivery"],
                body["reason"],
                self.correlation,
            )
        )

    def create_source_enrollment(self, identifier, body):
        self.access.require("migration.edit")
        source_cluster = self.repo.get_source_cluster(
            identifier,
            lock=True,
        )
        self.access.require_customer(
            source_cluster["customer_id"],
            source_cluster["created_by"],
        )
        if source_cluster["version"] != body["version"]:
            raise ApiError(
                409,
                "CONCURRENT_UPDATE",
                "Reload the latest source cluster.",
            )
        if source_cluster["status"] == "REVOKED":
            raise ApiError(
                409,
                "SOURCE_CLUSTER_REVOKED",
                "A revoked source cluster cannot be enrolled.",
            )

        token = secrets.token_urlsafe(32)
        enrollment = self.repo.create_source_enrollment(
            source_cluster,
            token,
            body["reason"],
            self.correlation,
        )
        result = serialize(enrollment)
        result["enrollmentToken"] = token
        return result

    def update(self, identifier, body):
        self.access.require("migration.edit")
        current = self.repo.get(identifier, lock=True)
        self.access.require_customer(
            current["customer_id"],
            current["created_by"],
        )

        if current["version"] != body["version"]:
            raise ApiError(
                409,
                "CONCURRENT_UPDATE",
                "Reload the latest migration request.",
            )

        source = body.get("source")
        recovering_source_registration = (
            current["status"] == "SOURCE_ENROLLMENT_PENDING"
            and not current["source_configuration"].get("sourceClusterId")
            and source is not None
            and source.get("sourceClusterId")
        )

        if current["status"] not in {
            "DRAFT",
            "REJECTED",
            "INVENTORY_READY",
        } and not recovering_source_registration:
            raise ApiError(
                409,
                "MIGRATION_NOT_EDITABLE",
                "The migration cannot be edited in its current status.",
            )

        if recovering_source_registration:
            unexpected = set(body) - {
                "version",
                "source",
                "changeReason",
            }
            if unexpected:
                raise ApiError(
                    409,
                    "SOURCE_REGISTRATION_RECOVERY_ONLY",
                    "Only the missing source cluster can be attached at this stage.",
                )

            registered_source = self.repo.get_source_cluster(
                source["sourceClusterId"]
            )
            if registered_source["customer_id"] != current["customer_id"]:
                raise ApiError(
                    409,
                    "SOURCE_CLUSTER_CUSTOMER_MISMATCH",
                    "The source cluster must belong to the migration customer.",
                )
            if registered_source["status"] == "REVOKED":
                raise ApiError(
                    409,
                    "SOURCE_CLUSTER_REVOKED",
                    "The selected source cluster has been revoked.",
                )

        row = copy.deepcopy(current)
        for key, column in {
            "name": "name",
            "description": "description",
            "scope": "migration_scope",
        }.items():
            if key in body:
                row[column] = body[key]

        if "source" in body:
            row["source_configuration"] = body["source"]
            row["source_platform"] = body["source"]["platform"]

        if "target" in body:
            row["target_configuration"] = body["target"]
            row["target_platform"] = body["target"]["platform"]

        row["version"] += 1
        row["updated_by"] = self.principal.user_id
        row["change_reason"] = body["changeReason"]

        self.repo.save(
            row,
            current,
            "MIGRATION_UPDATED",
            self.correlation,
        )
        return serialize(row)

    def change(self, identifier, action, body):
        if action not in TRANSITIONS:
            raise ApiError(404, "ROUTE_NOT_FOUND", "Endpoint not found.")

        allowed, target, privilege = TRANSITIONS[action]
        self.access.require(privilege)

        current = self.repo.get(identifier, lock=True)
        self.access.require_customer(
            current["customer_id"],
            current["created_by"],
        )

        if current["version"] != body["version"]:
            raise ApiError(
                409,
                "CONCURRENT_UPDATE",
                "Reload the latest migration request.",
            )

        if current["status"] not in allowed:
            raise ApiError(
                409,
                "INVALID_MIGRATION_TRANSITION",
                f"Cannot {action} a migration in {current['status']} status.",
            )

        if action in {"review", "approve", "reject"} and (
            current["created_by"] == self.principal.user_id
        ):
            raise ApiError(
                409,
                "SEPARATION_OF_DUTIES_REQUIRED",
                "The request creator cannot review or approve it.",
            )

        connector = None
        if action in {"discover", "assess"}:
            connector_token = body.get("connectorToken")
            if connector_token:
                connector = self.repo.create_discovery_connector(
                    identifier,
                    connector_token,
                )
            elif not current["source_configuration"].get("sourceClusterId"):
                raise ApiError(
                    409,
                    "SOURCE_CLUSTER_REQUIRED",
                    "Select a connected source cluster.",
                )

        row = copy.deepcopy(current)
        row["status"] = target
        row["version"] += 1
        row["updated_by"] = self.principal.user_id
        row["change_reason"] = body["reason"]
        row["comments"] = body.get("comments")

        self.repo.save(
            row,
            current,
            "MIGRATION_" + action.upper(),
            self.correlation,
        )

        result = serialize(row)
        if connector:
            connector_field = (
                "discoveryConnector"
                if action == "discover"
                else "assessmentConnector"
            )
            result[connector_field] = serialize(connector)

        return result
