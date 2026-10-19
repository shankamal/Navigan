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


NOT_DELETED = (
    "NOT EXISTS(SELECT 1 FROM migration_management.migration_audit_log deleted "
    "WHERE deleted.migration_id=m.migration_id AND deleted.action='MIGRATION_DELETED')"
)


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

    def get_source_cluster(self, identifier, lock=False):
        scope, params = scope_clause(self.principal)
        row = self.db.execute(
            "SELECT s.*,c.name AS customer_name,"
            "(SELECT max(sc.last_seen_at) FROM migration_management.source_cluster_connectors sc "
            "WHERE sc.source_cluster_id=s.source_cluster_id AND sc.status='ACTIVE' "
            "AND sc.expires_at>now()) AS connector_last_seen_at "
            "FROM migration_management.source_clusters s "
            "JOIN customer_management.customers c USING(customer_id) "
            "WHERE s.source_cluster_id=%s AND "
            + scope
            + (" FOR UPDATE OF s" if lock else ""),
            [identifier, *params],
        ).fetchone()
        if not row:
            raise ApiError(
                404,
                "SOURCE_CLUSTER_NOT_FOUND",
                "Source cluster was not found within the permitted scope.",
            )
        return row

    def list_source_clusters(self, query):
        scope, params = scope_clause(self.principal)
        conditions = [scope]
        if query.get("customerId"):
            conditions.append("s.customer_id=%s")
            params.append(query["customerId"])
        if query.get("status"):
            conditions.append("s.status=%s")
            params.append(query["status"])

        rows = self.db.execute(
            "SELECT s.source_cluster_id,s.customer_id,"
            "c.name AS customer_name,s.name,s.distribution,"
            "s.location_type,s.cloud_provider,s.region,"
            "s.registration_method,s.delivery_method,"
            "s.delivery_configuration,s.status,s.version,"
            "s.last_connected_at,s.created_at,s.updated_at "
            "FROM migration_management.source_clusters s "
            "JOIN customer_management.customers c USING(customer_id) "
            "WHERE "
            + " AND ".join(conditions)
            + " ORDER BY s.updated_at DESC,s.source_cluster_id "
            "LIMIT 100",
            params,
        ).fetchall()
        return {"items": [serialize(row) for row in rows]}

    def source_installation_conflicts(self, source):
        # Physical installation identity, never a display-name match. This is an
        # internal conflict check; Service redacts rows outside actor access.
        config = source.get("delivery_configuration") or {}
        return self.db.execute(
            "SELECT s.source_cluster_id,s.customer_id,s.created_by,c.name AS customer_name,"
            "EXISTS(SELECT 1 FROM migration_management.migrations m "
            "WHERE m.source_configuration->>'sourceClusterId'=s.source_cluster_id "
            "AND (m.status IN ('SOURCE_ENROLLMENT_PENDING','INVENTORY_DISCOVERING',"
            "'DISCOVERY_PENDING','DISCOVERING','ASSESSING') OR "
            "(m.status='DRAFT' AND COALESCE(m.source_configuration->>'discoveryMode','')<>'MANUAL'))) "
            "AS has_active_assignment, "
            "EXISTS(SELECT 1 FROM migration_management.source_cluster_audit_log a "
            "WHERE a.source_cluster_id=s.source_cluster_id "
            "AND a.action='SOURCE_CONNECTOR_INSTALLATION_STARTED' "
            "AND a.occurred_at>now()-interval '10 minutes') AS installation_in_progress "
            "FROM migration_management.source_clusters s "
            "JOIN customer_management.customers c USING(customer_id) "
            "WHERE s.source_cluster_id<>%s AND s.status<>'REVOKED' "
            "AND s.delivery_method='AWS_SSM' "
            "AND s.delivery_configuration->>'accountId'=%s "
            "AND s.delivery_configuration->>'region'=%s "
            "AND s.delivery_configuration->>'managedInstanceId'=%s "
            "AND COALESCE(s.delivery_configuration->>'kubeconfigPath','/etc/kubernetes/admin.conf')=%s "
            "AND (EXISTS(SELECT 1 FROM migration_management.source_cluster_connectors sc "
            "WHERE sc.source_cluster_id=s.source_cluster_id AND sc.status='ACTIVE' "
            "AND sc.expires_at>now() AND sc.last_seen_at>now()-interval '2 minutes') "
            "OR EXISTS(SELECT 1 FROM migration_management.source_cluster_audit_log a "
            "WHERE a.source_cluster_id=s.source_cluster_id "
            "AND a.action='SOURCE_CONNECTOR_INSTALLATION_STARTED' "
            "AND a.occurred_at>now()-interval '10 minutes') "
            "OR EXISTS(SELECT 1 FROM migration_management.migrations m "
            "WHERE m.source_configuration->>'sourceClusterId'=s.source_cluster_id "
            "AND (m.status IN ('SOURCE_ENROLLMENT_PENDING','INVENTORY_DISCOVERING',"
            "'DISCOVERY_PENDING','DISCOVERING','ASSESSING') OR "
            "(m.status='DRAFT' AND COALESCE(m.source_configuration->>'discoveryMode','')<>'MANUAL'))))",
            [
                source["source_cluster_id"],
                config.get("accountId"),
                config.get("region"),
                config.get("managedInstanceId"),
                config.get("kubeconfigPath") or "/etc/kubernetes/admin.conf",
            ],
        ).fetchall()

    def lock_source_installation(self, source):
        config = source.get("delivery_configuration") or {}
        identity = json_text(
            [config.get(key) for key in ("accountId", "region", "managedInstanceId")]
            + [config.get("kubeconfigPath") or "/etc/kubernetes/admin.conf"]
        )
        self.db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", [identity])

    def create_source_cluster(self, row, correlation):
        created = self.db.execute(
            "INSERT INTO migration_management.source_clusters("
            "source_cluster_id,customer_id,name,distribution,"
            "location_type,cloud_provider,region,registration_method,"
            "delivery_method,delivery_configuration,"
            "status,version,created_by,updated_by"
            ") VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,"
            "%s,%s,%s,%s) "
            "RETURNING *",
            [
                row["source_cluster_id"],
                row["customer_id"],
                row["name"],
                row.get("distribution"),
                row["location_type"],
                row.get("cloud_provider"),
                row.get("region"),
                row["registration_method"],
                row["delivery_method"],
                json_text(row["delivery_configuration"]),
                row["status"],
                row["version"],
                row["created_by"],
                row["updated_by"],
            ],
        ).fetchone()
        self.audit_source_cluster(
            row["source_cluster_id"],
            "SOURCE_CLUSTER_REGISTERED",
            correlation,
            {
                "registrationMethod": row["registration_method"],
                "locationType": row["location_type"],
            },
        )
        return created

    def update_source_cluster_delivery(
        self,
        source_cluster,
        delivery,
        reason,
        correlation,
    ):
        updated = self.db.execute(
            "UPDATE migration_management.source_clusters "
            "SET delivery_method=%s,delivery_configuration=%s::jsonb,"
            "version=version+1,updated_by=%s,updated_at=now() "
            "WHERE source_cluster_id=%s "
            "RETURNING *",
            [
                delivery["method"],
                json_text({**{k: v for k, v in (source_cluster.get("delivery_configuration") or {}).items() if k in {"deploymentDiscovery", "deploymentAnalysis"}}, **(delivery.get("awsSsm") or {})}),
                self.principal.user_id,
                source_cluster["source_cluster_id"],
            ],
        ).fetchone()
        self.audit_source_cluster(
            source_cluster["source_cluster_id"],
            "SOURCE_CLUSTER_DELIVERY_CONFIGURED",
            correlation,
            {
                "deliveryMethod": delivery["method"],
                "reason": reason,
            },
        )
        return updated

    def save_deployment_configuration(self, source, key, value, correlation):
        # Source-scoped JSON survives assessment creation, deletion and delivery changes.
        if key not in {"deploymentDiscovery", "deploymentAnalysis"}:
            raise ValueError("Invalid deployment configuration key.")
        row = self.db.execute(
            "UPDATE migration_management.source_clusters SET "
            "delivery_configuration=jsonb_set(delivery_configuration,%s,%s::jsonb),"
            "version=version+1,updated_at=now(),updated_by=%s "
            "WHERE source_cluster_id=%s AND version=%s RETURNING *",
            [[key], json_text(value), self.principal.user_id, source["source_cluster_id"], source["version"]],
        ).fetchone()
        if not row:
            raise ApiError(409, "CONCURRENT_UPDATE", "Reload the source connection before saving deployment sources.")
        self.audit_source_cluster(source["source_cluster_id"], "SOURCE_DEPLOYMENT_" + key.upper(), correlation,
                                  {"repositoryCount": len(value.get("repositories", []))})
        return row

    def deployment_connections(self, customer_id):
        self.require_customer_visible(customer_id)
        return [row["organization_login"] for row in self.db.execute(
            "SELECT organization_login FROM cluster_management.github_app_connections "
            "WHERE customer_id=%s AND status='ACTIVE' AND installation_id IS NOT NULL ORDER BY organization_login",
            [customer_id],
        ).fetchall()]

    def create_source_enrollment(
        self,
        source_cluster,
        token,
        reason,
        correlation,
    ):
        self.db.execute(
            "UPDATE migration_management.source_cluster_enrollments "
            "SET status='REVOKED',revoked_at=now() "
            "WHERE source_cluster_id=%s AND status='ISSUED'",
            [source_cluster["source_cluster_id"]],
        )

        enrollment_id = "SCE-" + uuid.uuid4().hex
        token_sha256 = hashlib.sha256(token.encode()).hexdigest()
        enrollment = self.db.execute(
            "INSERT INTO migration_management.source_cluster_enrollments("
            "enrollment_id,source_cluster_id,token_sha256,status,"
            "expires_at,created_by"
            ") VALUES(%s,%s,%s,'ISSUED',"
            "now() + interval '15 minutes',%s) "
            "RETURNING enrollment_id,source_cluster_id,status,expires_at",
            [
                enrollment_id,
                source_cluster["source_cluster_id"],
                token_sha256,
                self.principal.user_id,
            ],
        ).fetchone()
        self.audit_source_cluster(
            source_cluster["source_cluster_id"],
            "SOURCE_CLUSTER_ENROLLMENT_ISSUED",
            correlation,
            {"enrollmentId": enrollment_id, "reason": reason},
        )
        return enrollment

    def audit_source_cluster(
        self,
        identifier,
        action,
        correlation,
        details,
    ):
        self.db.execute(
            "INSERT INTO migration_management.source_cluster_audit_log("
            "source_cluster_id,action,performed_by,correlation_id,details"
            ") VALUES(%s,%s,%s,%s,%s::jsonb)",
            [
                identifier,
                action,
                self.principal.user_id,
                correlation,
                json_text(details),
            ],
        )

    def get(self, identifier, lock=False, include_deleted=False):
        scope, params = scope_clause(self.principal)
        row = self.db.execute(
            "SELECT m.*,c.name AS customer_name "
            "FROM migration_management.migrations m "
            "JOIN customer_management.customers c USING(customer_id) "
            "WHERE m.migration_id=%s AND "
            + scope
            + ("" if include_deleted else " AND " + NOT_DELETED)
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

    def require_registered_target(self, migration, cluster_id):
        config = migration.get("target_configuration") or {}
        row = self.db.execute(
            "SELECT cluster_id, cluster_name, status, customer_id "
            "FROM cluster_management.clusters "
            "WHERE cluster_id=%s AND customer_id=%s",
            [cluster_id, migration["customer_id"]],
        ).fetchone()
        if not row or row["cluster_name"] != config.get("clusterName"):
            raise ApiError(409, "TARGET_IDENTITY_MISMATCH",
                           "Selected target identity does not match the registered Navigan cluster.")
        if row["status"] != "ACTIVE":
            raise ApiError(409, "TARGET_NOT_ACTIVE",
                           "Target cluster must be ACTIVE before read-only analysis.")
        return row

    def get_target_assessment(self, identifier):
        migration = self.get(identifier)
        row = self.db.execute(
            "SELECT target_cluster_id, assessment_version, target_snapshot, "
            "evidence_level, created_at "
            "FROM migration_management.migration_target_assessments "
            "WHERE migration_id=%s ORDER BY created_at DESC, id DESC LIMIT 1",
            [identifier],
        ).fetchone()
        target_id = (migration.get("target_configuration") or {}).get("clusterId")
        # Evidence from an old target must never be presented for the new one.
        latest_source = self.get_assessment(identifier).get("assessment")
        if (not row or row["target_cluster_id"] != target_id or not latest_source or
                row["assessment_version"] != latest_source["assessmentVersion"]):
            return {"migrationId": identifier, "assessment": None}
        return {"migrationId": identifier, "assessment": {
            "targetClusterId": row["target_cluster_id"],
            "assessmentVersion": row["assessment_version"],
            "snapshot": row["target_snapshot"],
            "evidenceLevel": row["evidence_level"],
            "createdAt": row["created_at"].isoformat(),
        }}

    def save_target_assessment(self, identifier, cluster_id, snapshot):
        migration = self.get(identifier, lock=True)
        if (migration.get("target_configuration") or {}).get("clusterId") != cluster_id:
            raise ApiError(409, "TARGET_CHANGED", "Migration target changed; reassess.")
        assessment = self.get_assessment(identifier)["assessment"]
        if not assessment:
            raise ApiError(409, "ASSESSMENT_REQUIRED", "Source assessment is required.")
        self.db.execute(
            "INSERT INTO migration_management.migration_target_assessments "
            "(migration_id,target_cluster_id,assessment_version,target_snapshot,evidence_level,created_by) "
            "VALUES (%s,%s,%s,%s::jsonb,%s,%s)",
            [identifier, cluster_id, assessment["assessmentVersion"], json_text(snapshot),
             snapshot["evidenceLevel"], self.principal.user_id],
        )
        return self.get_target_assessment(identifier)

    def get_source_catalogue(self, identifier):
        migration = self.get(identifier)

        catalogue = self.db.execute(
            "SELECT catalogue_version,migration_version,"
            "schema_version,observed_at,"
            "source_kubernetes_version,inventory_digest,"
            "node_count,architectures,namespaces,created_at "
            "FROM migration_management.migration_source_catalogues "
            "WHERE migration_id=%s "
            "ORDER BY catalogue_version DESC LIMIT 1",
            [identifier],
        ).fetchone()

        return {
            "migrationId": identifier,
            "version": migration["version"],
            "status": migration["status"],
            "catalogue": (
                serialize(catalogue)
                if catalogue
                else None
            ),
        }

    def get_source_inventory(self, identifier):
        migration = self.get(identifier)

        inventory = self.db.execute(
            "SELECT inventory_version,migration_version,"
            "schema_version,observed_at,"
            "source_kubernetes_version,inventory_digest,"
            "resource_count,resources,created_at "
            "FROM migration_management.migration_source_inventories "
            "WHERE migration_id=%s "
            "ORDER BY inventory_version DESC LIMIT 1",
            [identifier],
        ).fetchone()

        return {
            "migrationId": identifier,
            "version": migration["version"],
            "status": migration["status"],
            "inventory": (
                {
                    **serialize(inventory),
                    "sensitiveDataIncluded": False,
                }
                if inventory
                else None
            ),
        }

    def get_assessment(self, identifier):
        migration = self.get(identifier)

        assessment = self.db.execute(
            "SELECT assessment_version,migration_version,"
            "report_schema_version,source_kubernetes_version,"
            "observed_at,inventory_digest,compatibility_score,"
            "contains_blockers,inventory_summary,findings,"
            "created_by,created_at "
            "FROM migration_management.migration_assessments "
            "WHERE migration_id=%s "
            "ORDER BY assessment_version DESC LIMIT 1",
            [identifier],
        ).fetchone()

        return {
            "migrationId": identifier,
            "version": migration["version"],
            "status": migration["status"],
            "assessment": (
                serialize(assessment)
                if assessment
                else None
            ),
        }

    def require_planning_configuration(self, identifier, assessment_version, current, source_only=False):
        snapshot = self.db.execute(
            "SELECT snapshot FROM migration_management.migration_versions "
            "WHERE migration_id=%s AND version=%s",
            [identifier, assessment_version],
        ).fetchone()
        if not snapshot or any(
            snapshot["snapshot"].get(camel(column)) != current[column]
            for column in (("source_configuration", "migration_scope") if source_only else ("source_configuration", "target_configuration", "migration_scope"))
        ):
            raise ApiError(
                409,
                "PLANNING_REASSESSMENT_REQUIRED",
                "Source, target, or assessment scope changed. Run a fresh assessment before planning.",
            )

    def list(self, query):
        scope, params = scope_clause(self.principal)
        conditions = [scope, NOT_DELETED]

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
                "migration_scope=%s::jsonb,planning_draft=%s::jsonb,status=%s,version=%s,"
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
                    json_text(row.get("planning_draft", {})),
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
