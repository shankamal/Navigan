"""Environment persistence, with customer scope enforced before every record access."""

import math
from navigan.shared.errors import ApiError
from navigan.modules.customer_management.repository import (
    Repository as CustomerRepository,
    scope_clause,
    json_text,
)


def camel(key):
    first, *rest = key.split("_")
    return first + "".join(s.title() for s in rest)


def serialize(row):
    renamed = {"provider_code": "cloudProvider"}
    return {renamed.get(k, camel(k)): v.isoformat() if hasattr(v, "isoformat") else v for k, v in row.items()}


def page_result(rows, count, page, size):
    return {
        "items": rows,
        "pagination": {
            "page": page,
            "pageSize": size,
            "totalElements": count,
            "totalPages": math.ceil(count / size),
        },
    }


class Repository:
    def __init__(self, db, principal):
        self.db, self.principal = db, principal
        self.customers = CustomerRepository(db, principal)

    def get(self, identifier, lock=False):
        scope, params = scope_clause(self.principal)
        row = self.db.execute(
            "SELECT e.*,c.name AS customer_name FROM environment_management.environments e "
            "JOIN customer_management.customers c USING(customer_id) WHERE e.environment_id=%s AND "
            + scope
            + (" FOR UPDATE OF e" if lock else ""),
            [identifier, *params],
        ).fetchone()
        if not row:
            raise ApiError(404, "ENVIRONMENT_NOT_FOUND", "Environment not found.")
        return row

    def validate_parent(self, customer_id, provider, active=False):
        # Serialize against Customer Management updates/removal of provider associations.
        parent = self.customers.get(customer_id, lock=True)
        if parent["status"] == "DEACTIVATED" or (active and parent["status"] != "ACTIVE"):
            raise ApiError(
                409,
                "CUSTOMER_NOT_ACTIVE",
                "Customer must be active for submission and activation; deactivated customers cannot be edited.",
            )
        if provider not in self.customers.providers(customer_id):
            raise ApiError(
                422, "CLOUD_PROVIDER_NOT_ALLOWED", "Provider is not associated with this customer."
            )
        self.customers.validate_providers([provider])

    def validate_type(self, code):
        if not self.db.execute(
            "SELECT code FROM environment_management.environment_types WHERE code=%s AND active", [code]
        ).fetchone():
            raise ApiError(422, "INVALID_ENVIRONMENT_TYPE", "Select an active environment type.")

    def save(self, row, create=False):
        row = {k: v for k, v in row.items() if k != "customer_name"}
        columns = list(row)
        values = [json_text(v) if k in {"configuration", "workflow"} else v for k, v in row.items()]
        slots = ["%s::jsonb" if k in {"configuration", "workflow"} else "%s" for k in columns]
        if create:
            sql = f"INSERT INTO environment_management.environments ({','.join(columns)}) VALUES ({','.join(slots)})"
        else:
            sql = (
                "UPDATE environment_management.environments SET "
                + ",".join(f"{k}={slot}" for k, slot in zip(columns, slots))
                + " WHERE environment_id=%s"
            )
            values.append(row["environment_id"])
        self.db.execute(sql, values)

    def record(self, old, row, action, body, correlation, event_type):
        identifier, user = row["environment_id"], self.principal.user_id
        snapshot = serialize(row)
        self.db.execute(
            "INSERT INTO environment_management.environment_versions(environment_id,version,snapshot,created_by,change_reason) VALUES (%s,%s,%s::jsonb,%s,%s)",
            [
                identifier,
                row["version"],
                json_text(snapshot),
                user,
                body.get("changeReason") or body.get("reason"),
            ],
        )
        if not old or old["status"] != row["status"]:
            self.db.execute(
                "INSERT INTO environment_management.environment_status_history(environment_id,previous_status,new_status,changed_by,reason,comments,correlation_id) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                [
                    identifier,
                    old["status"] if old else None,
                    row["status"],
                    user,
                    body.get("reason"),
                    body.get("comments"),
                    correlation,
                ],
            )
        if action in {"review", "approve", "reject"}:
            self.db.execute(
                "INSERT INTO environment_management.environment_reviews(environment_id,environment_version,reviewer_id,review_status,reason_code,reason,comments) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                [
                    identifier,
                    row["version"],
                    user,
                    row["status"],
                    body.get("reasonCode"),
                    body.get("reason"),
                    body.get("comments"),
                ],
            )
        self.db.execute(
            "INSERT INTO environment_management.environment_audit_log(environment_id,action,performed_by,correlation_id,old_value,new_value) VALUES (%s,%s,%s,%s,%s::jsonb,%s::jsonb)",
            [
                identifier,
                event_type,
                user,
                correlation,
                json_text(serialize(old)) if old else None,
                json_text(snapshot),
            ],
        )
        import uuid

        self.customers.enqueue(
            {
                "eventId": str(uuid.uuid4()),
                "eventType": event_type,
                "eventVersion": "1.0",
                "source": "navigan.environment-management",
                "environmentId": identifier,
                "environmentVersion": row["version"],
                "customerId": row["customer_id"],
                "cloudProvider": row["provider_code"],
                "performedBy": user,
                "timestamp": row["updated_at"].isoformat(),
                "correlationId": correlation,
            }
        )

    def list(self, query):
        scope, params = scope_clause(self.principal)
        conditions = [scope]
        fields = {
            "customerId": "e.customer_id",
            "cloudProvider": "e.provider_code",
            "kubernetesDistribution": "e.kubernetes_distribution",
            "environmentType": "e.environment_type",
            "status": "e.status",
            "createdBy": "e.created_by",
            "region": "e.configuration #>> '{location,region}'",
        }
        for key, column in fields.items():
            if query.get(key):
                conditions.append(column + "=%s")
                params.append(query[key])
        for key, column in {"customerName": "c.name", "environmentName": "e.environment_name"}.items():
            if query.get(key):
                conditions.append("strpos(lower(" + column + "),lower(%s))>0")
                params.append(query[key])
        if query.get("search"):
            conditions.append(
                "(strpos(lower(e.environment_name),lower(%s))>0 OR strpos(lower(c.name),lower(%s))>0 OR strpos(lower(e.environment_id),lower(%s))>0)"
            )
            params.extend([query["search"]] * 3)
        for key, op in [("createdFrom", ">="), ("createdTo", "<=")]:
            if query.get(key):
                conditions.append("e.created_at" + op + "%s::timestamptz")
                params.append(query[key])
        base = (
            " FROM environment_management.environments e JOIN customer_management.customers c USING(customer_id) WHERE "
            + " AND ".join(conditions)
        )
        count = self.db.execute("SELECT count(*) AS n" + base, params).fetchone()["n"]
        field, direction = query["sort"].split(",")
        column = {
            "environmentName": "e.environment_name",
            "createdAt": "e.created_at",
            "updatedAt": "e.updated_at",
            "status": "e.status",
        }[field]
        rows = self.db.execute(
            "SELECT e.environment_id,e.customer_id,c.name AS customer_name,e.provider_code,e.kubernetes_distribution,e.environment_name,e.environment_type,e.status,e.version,e.approved_version,e.created_at,e.updated_at"
            + base
            + f" ORDER BY {column} {direction},e.environment_id LIMIT %s OFFSET %s",
            [*params, query["pageSize"], query["page"] * query["pageSize"]],
        ).fetchall()
        return page_result([serialize(r) for r in rows], count, query["page"], query["pageSize"])

    def records(self, identifier, kind, page, size, version=None):
        self.get(identifier)
        if version is not None:
            row = self.db.execute(
                "SELECT snapshot FROM environment_management.environment_versions WHERE environment_id=%s AND version=%s",
                [identifier, version],
            ).fetchone()
            if not row:
                raise ApiError(404, "VERSION_NOT_FOUND", "Environment version not found.")
            return row["snapshot"]
        table, key = {
            "versions": ("environment_versions", "version"),
            "status-history": ("environment_status_history", "history_id"),
            "reviews": ("environment_reviews", "review_id"),
            "audit-log": ("environment_audit_log", "audit_id"),
        }[kind]
        columns = "environment_id,version,created_by,created_at,change_reason" if kind == "versions" else "*"
        count = self.db.execute(
            f"SELECT count(*) AS n FROM environment_management.{table} WHERE environment_id=%s", [identifier]
        ).fetchone()["n"]
        rows = self.db.execute(
            f"SELECT {columns} FROM environment_management.{table} WHERE environment_id=%s ORDER BY {key} DESC LIMIT %s OFFSET %s",
            [identifier, size, page * size],
        ).fetchall()
        return page_result([serialize(r) for r in rows], count, page, size)
