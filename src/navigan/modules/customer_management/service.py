from datetime import datetime, timezone
from math import ceil
from uuid import uuid4
from navigan.shared.errors import ApiError
from .interfaces import NoEnvironmentModule
from .workflow import check_edit, check_transition, check_version


def camel(key):
    parts = key.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


def external(row):
    return {
        camel(k): v.isoformat().replace("+00:00", "Z") if isinstance(v, datetime) else v
        for k, v in row.items()
    }


def pagination(page, size, total):
    return {"page": page, "pageSize": size, "totalElements": total, "totalPages": ceil(total / size)}


class CustomerService:
    def __init__(self, repository, correlation_id, dependencies=None):
        self.repo = repository
        self.principal = repository.principal
        self.correlation = correlation_id
        self.dependencies = dependencies or NoEnvironmentModule()

    def details(self, row):
        value = external(row)
        value["cloudProviders"] = self.repo.providers(row["customer_id"])
        value["contacts"] = self.repo.contacts(row["customer_id"])
        return value

    def record(self, row, action, event, old=None, changes=None):
        # Only structured governance values are copied to audit; contact PII/free-text is excluded.
        safe = {
            "status": row["status"],
            "version": row["version"],
            "cloudProviders": self.repo.providers(row["customer_id"]),
        }
        if changes:
            safe["changedFields"] = changes
        self.repo.audit(row["customer_id"], action, old, safe, self.correlation)
        self.repo.enqueue(
            {
                "eventType": event,
                "eventVersion": "1.0",
                "eventId": str(uuid4()),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "customerId": row["customer_id"],
                "cloudProviders": safe["cloudProviders"],
                "status": row["status"],
                "customerVersion": row["version"],
                "performedBy": self.principal.user_id,
                "correlationId": self.correlation,
            }
        )

    def create(self, body):
        self.principal.require("CLOUD_ENGINEER")
        if not self.principal.can_create:
            raise ApiError(403, "FORBIDDEN", "Customer onboarding entitlement is required.")
        self.repo.validate_providers(body["cloudProviders"])
        now = datetime.now(timezone.utc)
        row = {
            "customer_id": "CUS-" + uuid4().hex,
            "onboarding_request_id": "ONB-" + uuid4().hex,
            "name": body["name"],
            "description": body["description"],
            "status": "DRAFT",
            "created_by": self.principal.user_id,
            "created_at": now,
            "version": 1,
        }
        self.repo.insert(row)
        self.repo.replace_contacts(row["customer_id"], body["contacts"])
        self.repo.replace_providers(row["customer_id"], body["cloudProviders"])
        self.repo.history(row["customer_id"], None, "DRAFT", {}, self.correlation)
        self.record(row, "CUSTOMER_CREATED", "CustomerCreated")
        return self.details(self.repo.get(row["customer_id"]))

    def update(self, customer_id, body, version, providers=False):
        row = self.repo.get(customer_id, lock=True)
        check_edit(row, self.principal)
        check_version(row, version)
        old = {
            "status": row["status"],
            "version": row["version"],
            "cloudProviders": self.repo.providers(customer_id),
        }
        changes = {
            "version": row["version"] + 1,
            "updated_by": self.principal.user_id,
            "updated_at": datetime.now(timezone.utc),
        }
        if providers:
            self.repo.validate_providers(body["cloudProviders"])
            removed = set(old["cloudProviders"]) - set(body["cloudProviders"])
            for code in sorted(removed):
                if self.dependencies.has_dependencies(customer_id, code):
                    raise ApiError(
                        409,
                        "PROVIDER_HAS_DEPENDENCIES",
                        "Provider removal is blocked by dependent environments.",
                        {"provider": code},
                    )
            self.repo.replace_providers(customer_id, body["cloudProviders"])
            action, event = "CLOUD_PROVIDERS_UPDATED", "CustomerCloudProvidersUpdated"
        else:
            changes.update(name=body["name"], description=body["description"])
            self.repo.replace_contacts(customer_id, body["contacts"])
            action, event = "CUSTOMER_UPDATED", "CustomerUpdated"
        self.repo.update(customer_id, changes)
        row.update(changes)
        self.record(row, action, event, old, list(body))
        return self.details(row)

    def transition(self, customer_id, action, body, version):
        row = self.repo.get(customer_id, lock=True)
        target, audit, event = check_transition(row, action, self.principal, body)
        check_version(row, version)
        if action in {"submit", "resubmit", "activate"}:
            codes = self.repo.providers(customer_id)
            self.repo.validate_providers(codes)
            missing = []
            if not codes:
                missing.append("cloudProviders")
            if not any(c["type"] == "PRIMARY" for c in self.repo.contacts(customer_id)):
                missing.append("contacts.PRIMARY")
            if missing:
                raise ApiError(
                    422,
                    "SUBMISSION_VALIDATION_FAILED",
                    "Complete the required onboarding information.",
                    {"fields": missing},
                )
        now = datetime.now(timezone.utc)
        changes = {
            "status": target,
            "version": row["version"] + 1,
            "updated_by": self.principal.user_id,
            "updated_at": now,
        }
        prefix = {
            "submit": "submitted",
            "resubmit": "submitted",
            "approve": "approved",
            "reject": "rejected",
            "activate": "activated",
            "suspend": "suspended",
            "reactivate": "reactivated",
            "deactivate": "deactivated",
        }.get(action)
        if prefix:
            changes.update({prefix + "_by": self.principal.user_id, prefix + "_at": now})
        if action in {"submit", "resubmit"}:
            changes["review_cycle"] = row["review_cycle"] + 1
        reason_column = {
            "reject": "rejection_reason",
            "suspend": "suspension_reason",
            "deactivate": "deactivation_reason",
        }.get(action)
        if reason_column:
            changes[reason_column] = body["reason"]
        if action in {"review/start", "approve", "reject"}:
            self.repo.review(row, target, body)
        self.repo.history(customer_id, row["status"], target, body, self.correlation)
        old = {"status": row["status"], "version": row["version"]}
        self.repo.update(customer_id, changes)
        row.update(changes)
        self.record(row, audit, event, old)
        return self.details(row)

    def list(self, query):
        rows, count = self.repo.list(query)
        items = []
        for row in rows:
            item = external(
                {k: row[k] for k in ["customer_id", "name", "status", "version", "created_at", "updated_at"]}
            )
            item["cloudProviders"] = self.repo.providers(row["customer_id"])
            items.append(item)
        return {"items": items, "pagination": pagination(query["page"], query["pageSize"], count)}

    def records(self, customer_id, kind, query):
        self.repo.get(customer_id)
        if kind == "audit-log":
            self.principal.require("PLATFORM_ARCHITECT")
        rows, total = self.repo.records(customer_id, kind, query["page"], query["pageSize"])
        values = [external(row) for row in rows]
        if kind == "status-history":
            for value in values:
                value["fromStatus"] = value.pop("previousStatus")
                value["toStatus"] = value.pop("newStatus")
        return {
            "customerId": customer_id,
            "history" if kind == "status-history" else "items": values,
            "pagination": pagination(query["page"], query["pageSize"], total),
        }
