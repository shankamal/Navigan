import copy
import uuid

from navigan.shared.errors import ApiError

from .repository import serialize


TRANSITIONS = {
    "discover": (
        {"DRAFT", "REJECTED"},
        "SOURCE_ENROLLMENT_PENDING",
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

        if current["status"] not in {"DRAFT", "REJECTED"}:
            raise ApiError(
                409,
                "MIGRATION_NOT_EDITABLE",
                "Only draft or rejected migrations can be edited.",
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
        if action == "discover":
            connector = self.repo.create_discovery_connector(
                identifier,
                body["connectorToken"],
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
            result["discoveryConnector"] = serialize(connector)

        return result
