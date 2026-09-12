import math
from navigan.shared.errors import ApiError
from navigan.modules.customer_management.repository import scope_clause, json_text


def camel(key):
    first, *rest = key.split("_")
    return first + "".join(part.title() for part in rest)


def serialize(row):
    return {
        camel(key): value.isoformat() if hasattr(value, "isoformat") else value
        for key, value in row.items()
    }


class Repository:
    def __init__(self, db, principal):
        self.db, self.principal = db, principal

    def get(self, identifier, lock=False):
        scope, params = scope_clause(self.principal)
        row = self.db.execute(
            "SELECT k.*,c.name AS customer_name,e.environment_name "
            "FROM cluster_management.clusters k "
            "JOIN customer_management.customers c USING(customer_id) "
            "JOIN environment_management.environments e USING(environment_id) "
            "WHERE k.cluster_id=%s AND " + scope + (" FOR UPDATE OF k" if lock else ""),
            [identifier, *params],
        ).fetchone()
        if not row:
            raise ApiError(404, "CLUSTER_NOT_FOUND", "Cluster request not found.")
        return row

    def active_environment_snapshot(self, identifier, requested_version=None):
        scope, params = scope_clause(self.principal)
        row = self.db.execute(
            "SELECT e.*,c.status AS customer_status,c.name AS customer_name "
            "FROM environment_management.environments e "
            "JOIN customer_management.customers c USING(customer_id) "
            "WHERE e.environment_id=%s AND " + scope + " FOR SHARE OF e,c",
            [identifier, *params],
        ).fetchone()
        if not row:
            raise ApiError(404, "ENVIRONMENT_NOT_FOUND", "Environment profile not found.")
        approved_status = row.get("approved_status") or row["status"]
        if approved_status != "ACTIVE" or row["customer_status"] != "ACTIVE":
            raise ApiError(409, "ENVIRONMENT_NOT_ACTIVE", "Environment and customer must both be ACTIVE.")
        approved = row["approved_version"]
        if not approved or (requested_version is not None and requested_version != approved):
            raise ApiError(409, "APPROVED_VERSION_CHANGED", "Reload and pin the current approved version.")
        version = self.db.execute(
            "SELECT snapshot FROM environment_management.environment_versions "
            "WHERE environment_id=%s AND version=%s",
            [identifier, approved],
        ).fetchone()
        if not version:
            raise ApiError(409, "APPROVED_VERSION_MISSING", "Approved environment snapshot is unavailable.")
        return row, version["snapshot"]

    def save(self, row, create=False):
        clean = {k: v for k, v in row.items() if k not in {"customer_name", "environment_name"}}
        columns = list(clean)
        json_columns = {"configuration", "outputs", "workflow"}
        values = [json_text(v) if k in json_columns else v for k, v in clean.items()]
        slots = ["%s::jsonb" if k in json_columns else "%s" for k in columns]
        if create:
            sql = f"INSERT INTO cluster_management.clusters ({','.join(columns)}) VALUES ({','.join(slots)})"
        else:
            sql = "UPDATE cluster_management.clusters SET " + ",".join(
                f"{column}={slot}" for column, slot in zip(columns, slots)
            ) + " WHERE cluster_id=%s"
            values.append(clean["cluster_id"])
        self.db.execute(sql, values)

    def record(self, old, row, action, body, correlation):
        snapshot = serialize(row)
        self.db.execute(
            "INSERT INTO cluster_management.cluster_versions"
            "(cluster_id,version,snapshot,created_by,change_reason) VALUES (%s,%s,%s::jsonb,%s,%s)",
            [row["cluster_id"], row["version"], json_text(snapshot), self.principal.user_id,
             body.get("changeReason") or body.get("reason")],
        )
        if not old or old["status"] != row["status"]:
            self.db.execute(
                "INSERT INTO cluster_management.cluster_status_history"
                "(cluster_id,previous_status,new_status,changed_by,reason,comments,correlation_id) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                [row["cluster_id"], old["status"] if old else None, row["status"],
                 self.principal.user_id, body.get("reason"), body.get("comments"), correlation],
            )
        self.db.execute(
            "INSERT INTO cluster_management.cluster_audit_log"
            "(cluster_id,action,performed_by,correlation_id,old_value,new_value) "
            "VALUES (%s,%s,%s,%s,%s::jsonb,%s::jsonb)",
            [row["cluster_id"], action, self.principal.user_id, correlation,
             json_text(serialize(old)) if old else None, json_text(snapshot)],
        )

    def list(self, query):
        scope, params = scope_clause(self.principal)
        conditions = [scope]
        for key, column in {
            "status": "k.status", "environmentId": "k.environment_id",
            "customerId": "k.customer_id", "platform": "k.platform",
        }.items():
            if query.get(key):
                conditions.append(column + "=%s")
                params.append(query[key])
        if query.get("search"):
            conditions.append(
                "(strpos(lower(k.cluster_name),lower(%s))>0 OR "
                "strpos(lower(c.name),lower(%s))>0 OR strpos(lower(k.cluster_id),lower(%s))>0)"
            )
            params.extend([query["search"]] * 3)
        base = (
            " FROM cluster_management.clusters k "
            "JOIN customer_management.customers c USING(customer_id) "
            "JOIN environment_management.environments e USING(environment_id) WHERE "
            + " AND ".join(conditions)
        )
        count = int(
            self.db.execute("SELECT count(*) AS n" + base, params).fetchone()["n"]
        )
        rows = self.db.execute(
            "SELECT k.cluster_id,k.customer_id,c.name AS customer_name,k.environment_id,"
            "e.environment_name,k.environment_approved_version,k.platform,k.cluster_name,"
            "k.status,k.version,k.provider_execution_id,k.created_at,k.updated_at" + base
            + " ORDER BY k.updated_at DESC,k.cluster_id LIMIT %s OFFSET %s",
            [*params, query["pageSize"], query["page"] * query["pageSize"]],
        ).fetchall()
        return {
            "items": [serialize(row) for row in rows],
            "pagination": {
                "page": int(query["page"]),
                "pageSize": int(query["pageSize"]),
                "totalElements": count,
                "totalPages": math.ceil(count / int(query["pageSize"])),
            },
        }
