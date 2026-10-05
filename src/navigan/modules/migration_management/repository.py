import hashlib
import json
import math
import uuid

from navigan.modules.customer_management.repository import scope_clause
from navigan.shared.errors import ApiError


def camel(key):
    first, *rest = key.split("_")
    return first + "".join(part.title() for part in rest)


def serialize(row):
    return {
        camel(key): value.isoformat() if hasattr(value, "isoformat") else value
        for key, value in row.items()
    }


def json_text(value):
    return json.dumps(value, default=str, separators=(",", ":"))


class Repository:
    def __init__(self, db, principal):
        self.db = db
        self.principal = principal

    def require_customer_visible(self, customer_id):
        scope, params = scope_clause(self.principal)
        row = self.db.execute(
            "SELECT c.customer_id "
            "FROM customer_management.customers c "
            "WHERE c.customer_id=%s AND " + scope,
            [customer_id, *params],
        ).fetchone()
        if not row:
            raise ApiError(
                404,
                "CUSTOMER_NOT_FOUND",
                "Customer was not found within the permitted scope.",
            )

    def get(self, identifier, lock=False):
        scope, params = scope_clause(self.principal)
        row = self.db.execute(
            "SELECT m.*,c.name AS customer_name "
            "FROM migration_management.migrations m "
            "JOIN customer_management.customers c USING(customer_id) "
            "WHERE m.migration_id=%s AND "
            + scope
            + (" FOR UPDATE OF m" if lock else ""),
            [identifier, *params],
        ).fetchone()
        if not row:
            raise ApiError(
                404,
                "MIGRATION_NOT_FOUND",
                "Migration request not found.",
            )
        return row

    def list(self, query):
        scope, params = scope_clause(self.principal)
        conditions = [scope]

        for key, column in {
            "status": "m.status",
            "customerId": "m.customer_id",
            "sourcePlatform": "m.source_platform",
            "targetPlatform": "m.target_platform",
        }.items():
            if query.get(key):
                conditions.append(column + "=%s")
                params.append(query[key])

        if query.get("search"):
            conditions.append(
                "(strpos(lower(m.name),lower(%s))>0 OR "
                "strpos(lower(m.migration_id),lower(%s))>0 OR "
                "strpos(lower(c.name),lower(%s))>0)"
            )
            params.extend([query["search"]] * 3)

        base = (
            " FROM migration_management.migrations m "
            "JOIN customer_management.customers c USING(customer_id) "
            "WHERE " + " AND ".join(conditions)
        )

        total = int(
            self.db.execute(
                "SELECT count(*) AS n" + base,
                params,
            ).fetchone()["n"]
        )

        rows = self.db.execute(
            "SELECT m.migration_id,m.customer_id,c.name AS customer_name,"
            "m.name,m.source_platform,m.target_platform,m.execution_mode,"
            "m.status,m.version,m.created_by,m.created_at,m.updated_at"
            + base
            + " ORDER BY m.updated_at DESC,m.migration_id "
            "LIMIT %s OFFSET %s",
            [
                *params,
                query["pageSize"],
                query["page"] * query["pageSize"],
            ],
        ).fetchall()

        return {
            "items": [serialize(row) for row in rows],
            "pagination": {
                "page": query["page"],
                "pageSize": query["pageSize"],
                "totalElements": total,
                "totalPages": math.ceil(total / query["pageSize"]),
            },
        }

    def save(self, row, old, action, correlation, create=False):
        if create:
            self.db.execute(
                "INSERT INTO migration_management.migrations("
                "migration_id,customer_id,name,description,"
                "source_platform,target_platform,source_configuration,"
                "target_configuration,migration_scope,execution_mode,"
                "status,version,created_by,updated_by"
                ") VALUES("
                "%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,"
                "%s,%s,%s,%s,%s)",
                [
                    row["migration_id"],
                    row["customer_id"],
                    row["name"],
                    row.get("description"),
                    row["source_platform"],
                    row["target_platform"],
                    json_text(row["source_configuration"]),
                    json_text(row["target_configuration"]),
                    json_text(row["migration_scope"]),
                    row["execution_mode"],
                    row["status"],
                    row["version"],
                    row["created_by"],
                    row["updated_by"],
                ],
            )
        else:
            self.db.execute(
                "UPDATE migration_management.migrations SET "
                "name=%s,description=%s,source_platform=%s,"
                "target_platform=%s,source_configuration=%s::jsonb,"
                "target_configuration=%s::jsonb,"
                "migration_scope=%s::jsonb,status=%s,version=%s,"
                "updated_by=%s,updated_at=now() "
                "WHERE migration_id=%s",
                [
                    row["name"],
                    row.get("description"),
                    row["source_platform"],
                    row["target_platform"],
                    json_text(row["source_configuration"]),
                    json_text(row["target_configuration"]),
                    json_text(row["migration_scope"]),
                    row["status"],
                    row["version"],
                    row["updated_by"],
                    row["migration_id"],
                ],
            )

        snapshot = serialize(row)
        self.db.execute(
            "INSERT INTO migration_management.migration_versions("
            "migration_id,version,snapshot,change_reason,"
            "created_by"
            ") VALUES(%s,%s,%s::jsonb,%s,%s)",
            [
                row["migration_id"],
                row["version"],
                json_text(snapshot),
                row.get("change_reason"),
                self.principal.user_id,
            ],
        )

        if old is None or old["status"] != row["status"]:
            self.db.execute(
                "INSERT INTO migration_management.migration_status_history("
                "migration_id,previous_status,new_status,changed_by,"
                "reason,comments,correlation_id"
                ") VALUES(%s,%s,%s,%s,%s,%s,%s)",
                [
                    row["migration_id"],
                    old["status"] if old else None,
                    row["status"],
                    self.principal.user_id,
                    row.get("change_reason"),
                    row.get("comments"),
                    correlation,
                ],
            )

        self.db.execute(
            "INSERT INTO migration_management.migration_audit_log("
            "migration_id,action,performed_by,correlation_id,"
            "old_value,new_value"
            ") VALUES(%s,%s,%s,%s,%s::jsonb,%s::jsonb)",
            [
                row["migration_id"],
                action,
                self.principal.user_id,
                correlation,
                json_text(serialize(old)) if old else None,
                json_text(snapshot),
            ],
        )

    def create_discovery_connector(self, identifier, token):
        current = self.db.execute(
            "SELECT connector_id "
            "FROM migration_management.migration_connectors "
            "WHERE migration_id=%s "
            "AND status IN ('ENROLLED','ACTIVE') "
            "FOR UPDATE",
            [identifier],
        ).fetchone()

        if current:
            self.db.execute(
                "UPDATE migration_management.migration_connectors "
                "SET status='REVOKED',revoked_by=%s,revoked_at=now() "
                "WHERE connector_id=%s",
                [
                    self.principal.user_id,
                    current["connector_id"],
                ],
            )

        connector_id = "MGC-" + uuid.uuid4().hex
        token_sha256 = hashlib.sha256(token.encode()).hexdigest()

        return self.db.execute(
            "INSERT INTO migration_management.migration_connectors("
            "connector_id,migration_id,token_sha256,status,"
            "expires_at,created_by"
            ") VALUES(%s,%s,%s,'ENROLLED',"
            "now() + interval '30 minutes',%s) "
            "RETURNING connector_id,migration_id,status,expires_at",
            [
                connector_id,
                identifier,
                token_sha256,
                self.principal.user_id,
            ],
        ).fetchone()
