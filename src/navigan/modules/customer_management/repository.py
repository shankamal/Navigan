"""SQL persistence. All customer reads are scoped before child records are accessed."""

import json
import uuid
from navigan.shared.errors import ApiError


def json_text(value):
    return json.dumps(value, default=lambda v: v.isoformat())


def scope_clause(principal):
    if principal.platform_scope:
        return "TRUE", []
    own = principal.can_create and "CLOUD_ENGINEER" in principal.roles
    return "(c.customer_id = ANY(%s) OR (%s AND c.created_by = %s))", [
        list(principal.customer_ids),
        own,
        principal.user_id,
    ]


class Repository:
    def __init__(self, connection, principal):
        self.db = connection
        self.principal = principal

    def get(self, customer_id, lock=False):
        scope, params = scope_clause(self.principal)
        row = self.db.execute(
            f"SELECT c.* FROM customer_management.customers c WHERE c.customer_id=%s AND {scope}"
            + (" FOR UPDATE" if lock else ""),
            [customer_id, *params],
        ).fetchone()
        if not row:
            raise ApiError(404, "CUSTOMER_NOT_FOUND", "Customer not found.")
        return row

    def providers(self, customer_id):
        return [
            r["provider_code"]
            for r in self.db.execute(
                "SELECT provider_code FROM customer_management.customer_cloud_providers WHERE customer_id=%s ORDER BY provider_code",
                [customer_id],
            ).fetchall()
        ]

    def contacts(self, customer_id):
        return self.db.execute(
            "SELECT contact_type AS type,name,email,phone FROM "
            "customer_management.customer_contacts WHERE customer_id=%s ORDER BY created_at,contact_id",
            [customer_id],
        ).fetchall()

    def validate_providers(self, codes):
        found = {
            r["provider_code"]
            for r in self.db.execute(
                "SELECT provider_code FROM customer_management.cloud_providers WHERE active AND provider_code=ANY(%s) FOR SHARE",
                [codes],
            ).fetchall()
        }
        if found != set(codes):
            raise ApiError(
                422,
                "INVALID_CLOUD_PROVIDER",
                "Only active configured providers may be selected.",
                {"providers": sorted(set(codes) - found)},
            )

    def insert(self, row):
        columns = list(row)
        # Internal column names only; never derived from unvalidated HTTP input.
        self.db.execute(
            f"INSERT INTO customer_management.customers ({','.join(columns)}) VALUES "
            f"({','.join(['%s'] * len(columns))})",
            list(row.values()),
        )

    def update(self, customer_id, changes):
        self.db.execute(
            "UPDATE customer_management.customers SET "
            + ",".join(f"{key}=%s" for key in changes)
            + " WHERE customer_id=%s",
            [*changes.values(), customer_id],
        )

    def replace_contacts(self, customer_id, contacts):
        self.db.execute(
            "DELETE FROM customer_management.customer_contacts WHERE customer_id=%s", [customer_id]
        )
        for contact in contacts:
            self.db.execute(
                "INSERT INTO customer_management.customer_contacts "
                "(contact_id,customer_id,contact_type,name,email,phone) VALUES (%s,%s,%s,%s,%s,%s)",
                [
                    "CON-" + uuid.uuid4().hex,
                    customer_id,
                    contact["type"],
                    contact["name"],
                    contact.get("email"),
                    contact.get("phone"),
                ],
            )

    def replace_providers(self, customer_id, codes):
        self.db.execute(
            "DELETE FROM customer_management.customer_cloud_providers "
            "WHERE customer_id=%s AND NOT(provider_code=ANY(%s))",
            [customer_id, codes],
        )
        for code in codes:
            self.db.execute(
                "INSERT INTO customer_management.customer_cloud_providers "
                "(customer_id,provider_code,created_by) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                [customer_id, code, self.principal.user_id],
            )

    def history(self, customer_id, old, new, body, correlation):
        self.db.execute(
            "INSERT INTO customer_management.customer_status_history "
            "(customer_id,previous_status,new_status,changed_by,reason,comments,correlation_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            [
                customer_id,
                old,
                new,
                self.principal.user_id,
                body.get("reason"),
                body.get("comments"),
                correlation,
            ],
        )

    def review(self, customer, status, body):
        self.db.execute(
            "INSERT INTO customer_management.customer_reviews "
            "(review_id,customer_id,review_cycle,reviewer_id,review_status,comments,rejection_reason) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            [
                "REV-" + uuid.uuid4().hex,
                customer["customer_id"],
                customer["review_cycle"],
                self.principal.user_id,
                status,
                body.get("comments"),
                body.get("reason"),
            ],
        )

    def audit(self, customer_id, action, old, new, correlation):
        self.db.execute(
            "INSERT INTO customer_management.customer_audit_log "
            "(customer_id,action,performed_by,correlation_id,old_value,new_value) VALUES (%s,%s,%s,%s,%s::jsonb,%s::jsonb)",
            [customer_id, action, self.principal.user_id, correlation, json_text(old), json_text(new)],
        )

    def enqueue(self, payload):
        self.db.execute(
            "INSERT INTO platform.event_outbox(event_id,customer_id,event_type,payload) VALUES (%s,%s,%s,%s::jsonb)",
            [payload["eventId"], payload["customerId"], payload["eventType"], json_text(payload)],
        )

    def list(self, query):
        scope, params = scope_clause(self.principal)
        where = [scope]
        for name, column in [("status", "c.status"), ("createdBy", "c.created_by")]:
            if query.get(name):
                where.append(column + "=%s")
                params.append(query[name])
        if query.get("cloudProvider"):
            where.append(
                "EXISTS (SELECT 1 FROM customer_management.customer_cloud_providers p "
                "WHERE p.customer_id=c.customer_id AND p.provider_code=%s)"
            )
            params.append(query["cloudProvider"])
        if query.get("search"):
            where.append("(strpos(lower(c.name),lower(%s))>0 OR strpos(lower(c.customer_id),lower(%s))>0)")
            params.extend([query["search"], query["search"]])
        condition = " AND ".join(where)
        count = self.db.execute(
            f"SELECT count(*) AS n FROM customer_management.customers c WHERE {condition}", params
        ).fetchone()["n"]
        columns = {
            "name": "lower(c.name)",
            "createdAt": "c.created_at",
            "updatedAt": "c.updated_at",
            "status": "c.status",
        }
        field, direction = query["sort"].split(",")
        rows = self.db.execute(
            f"SELECT c.* FROM customer_management.customers c WHERE {condition} "
            f"ORDER BY {columns[field]} {direction} NULLS LAST,c.customer_id LIMIT %s OFFSET %s",
            [*params, query["pageSize"], query["page"] * query["pageSize"]],
        ).fetchall()
        return rows, count

    def records(self, customer_id, kind, page, page_size):
        table, key = {
            "status-history": ("customer_status_history", "history_id"),
            "audit-log": ("customer_audit_log", "audit_id"),
            "reviews": ("customer_reviews", "review_id"),
        }[kind]
        ordering = "reviewed_at,review_id" if kind == "reviews" else key
        rows = self.db.execute(
            f"SELECT * FROM customer_management.{table} WHERE customer_id=%s "
            f"ORDER BY {ordering} LIMIT %s OFFSET %s",
            [customer_id, page_size, page * page_size],
        ).fetchall()
        count = self.db.execute(
            f"SELECT count(*) AS n FROM customer_management.{table} WHERE customer_id=%s", [customer_id]
        ).fetchone()["n"]
        return rows, count

    def idempotency_get(self, operation, key, request_hash):
        # Serialize equal keys for concurrent creates/actions, inside the same transaction as the mutation.
        lock = json_text([self.principal.user_id, operation, key])
        self.db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", [lock])
        row = self.db.execute(
            "SELECT request_hash,response FROM platform.idempotency WHERE actor_id=%s AND operation=%s AND key=%s",
            [self.principal.user_id, operation, key],
        ).fetchone()
        if row and row["request_hash"] != request_hash:
            raise ApiError(
                409, "IDEMPOTENCY_CONFLICT", "The idempotency key was already used for a different request."
            )
        return row["response"] if row else None

    def idempotency_put(self, operation, key, request_hash, response):
        self.db.execute(
            "INSERT INTO platform.idempotency(actor_id,operation,key,request_hash,response) VALUES (%s,%s,%s,%s,%s::jsonb)",
            [self.principal.user_id, operation, key, request_hash, json_text(response)],
        )
