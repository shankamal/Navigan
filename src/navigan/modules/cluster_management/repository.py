import math
import hashlib
from datetime import datetime, timedelta, timezone
from navigan.shared.errors import ApiError
from navigan.modules.customer_management.repository import scope_clause, json_text
from .capabilities import resolve_cluster_actions


def camel(key):
    first, *rest = key.split("_")
    return first + "".join(part.title() for part in rest)


def serialize(row, access=None):
    result = {
        camel(key): value.isoformat() if hasattr(value, "isoformat") else value
        for key, value in row.items()
    }
    identity_status = result.pop("identityStatus", None)
    if identity_status is not None:
        result["identityIntegration"] = {
            "status": identity_status,
            "lastVerifiedAt": result.pop("identityLastVerifiedAt", None),
            "failureCode": result.pop("identityFailureCode", None),
        }
    if access is not None:
        result["allowedActions"] = resolve_cluster_actions(row, access)
    return result


class Repository:
    def __init__(self, db, principal):
        self.db, self.principal = db, principal

    def get(self, identifier, lock=False):
        scope, params = scope_clause(self.principal)
        row = self.db.execute(
            "SELECT k.*,c.name AS customer_name,e.environment_name,"
            "coalesce(i.status,'NOT_CONFIGURED') AS identity_status,"
            "i.last_verified_at AS identity_last_verified_at,"
            "i.failure_code AS identity_failure_code "
            "FROM cluster_management.clusters k "
            "JOIN customer_management.customers c USING(customer_id) "
            "JOIN environment_management.environments e USING(environment_id) "
            "LEFT JOIN cluster_management.cluster_identity_integrations i USING(cluster_id) "
            "WHERE k.cluster_id=%s AND " + scope + (" FOR UPDATE OF k" if lock else ""),
            [identifier, *params],
        ).fetchone()
        if not row:
            raise ApiError(404, "CLUSTER_NOT_FOUND", "Cluster request not found.")
        return row

    def create_system_repository(
        self, cluster_id, customer_id, organization_login, repository_name
    ):
        connection = self.active_github_connection(customer_id, organization_login)
        self.db.execute(
            "INSERT INTO cluster_management.cluster_system_repositories"
            "(cluster_id,connection_id,provider,organization_login,repository_name,status,"
            "created_by,updated_by) "
            "VALUES (%s,%s,'GITHUB',%s,%s,%s,%s,%s)",
            [
                cluster_id,
                connection["connection_id"] if connection else None,
                organization_login,
                repository_name,
                "READY_TO_PROVISION" if connection else "AUTHORIZATION_REQUIRED",
                self.principal.user_id,
                self.principal.user_id,
            ],
        )
        return connection

    def active_github_connection(self, customer_id, organization_login):
        return self.db.execute(
            "SELECT * FROM cluster_management.github_app_connections "
            "WHERE customer_id=%s AND lower(organization_login)=lower(%s) "
            "AND status='ACTIVE' AND installation_id IS NOT NULL",
            [customer_id, organization_login],
        ).fetchone()

    def bind_system_repository_connection(self, cluster_id, connection_id):
        self.db.execute(
            "UPDATE cluster_management.cluster_system_repositories "
            "SET connection_id=%s,status='READY_TO_PROVISION',updated_by=%s,"
            "updated_at=now() WHERE cluster_id=%s",
            [connection_id, self.principal.user_id, cluster_id],
        )

    def system_repository(self, cluster_id, lock=False):
        row = self.db.execute(
            "SELECT * FROM cluster_management.cluster_system_repositories "
            "WHERE cluster_id=%s" + (" FOR UPDATE" if lock else ""),
            [cluster_id],
        ).fetchone()
        if not row:
            raise ApiError(
                409,
                "SYSTEM_REPOSITORY_NOT_CONFIGURED",
                "This cluster request has no system repository configuration.",
            )
        return row

    def mark_system_repository_active(self, cluster_id, repository):
        self.db.execute(
            "UPDATE cluster_management.cluster_system_repositories "
            "SET repository_id=%s,repository_url=%s,status='ACTIVE',"
            "last_error_code=NULL,updated_by=%s,updated_at=now() WHERE cluster_id=%s",
            [
                repository["id"],
                repository["html_url"],
                self.principal.user_id,
                cluster_id,
            ],
        )

    def begin_github_authorization(self, cluster, state_sha256):
        repository = self.db.execute(
            "SELECT * FROM cluster_management.cluster_system_repositories "
            "WHERE cluster_id=%s FOR UPDATE",
            [cluster["cluster_id"]],
        ).fetchone()
        if not repository:
            raise ApiError(
                409,
                "SYSTEM_REPOSITORY_NOT_CONFIGURED",
                "This cluster request has no system repository configuration.",
            )
        connection = self.db.execute(
            "SELECT * FROM cluster_management.github_app_connections "
            "WHERE customer_id=%s AND lower(organization_login)=lower(%s) FOR UPDATE",
            [cluster["customer_id"], repository["organization_login"]],
        ).fetchone()
        if not connection:
            connection_id = "GHC-" + __import__("uuid").uuid4().hex
            self.db.execute(
                "INSERT INTO cluster_management.github_app_connections"
                "(connection_id,customer_id,organization_login,status,created_by,updated_by) "
                "VALUES (%s,%s,%s,'AUTHORIZATION_REQUIRED',%s,%s)",
                [
                    connection_id,
                    cluster["customer_id"],
                    repository["organization_login"],
                    self.principal.user_id,
                    self.principal.user_id,
                ],
            )
        else:
            connection_id = connection["connection_id"]
        self.db.execute(
            "DELETE FROM cluster_management.github_app_authorization_states "
            "WHERE connection_id=%s AND consumed_at IS NULL",
            [connection_id],
        )
        self.db.execute(
            "INSERT INTO cluster_management.github_app_authorization_states"
            "(state_sha256,connection_id,requested_by,expires_at) "
            "VALUES (%s,%s,%s,%s)",
            [
                state_sha256,
                connection_id,
                self.principal.user_id,
                datetime.now(timezone.utc) + timedelta(minutes=15),
            ],
        )
        return {
            "connectionId": connection_id,
            "organization": repository["organization_login"],
            "repositoryName": repository["repository_name"],
        }

    def complete_github_authorization(
        self, cluster, state_sha256, installation_id, permissions
    ):
        state = self.db.execute(
            "SELECT s.connection_id,c.customer_id,c.organization_login "
            "FROM cluster_management.github_app_authorization_states s "
            "JOIN cluster_management.github_app_connections c USING(connection_id) "
            "WHERE s.state_sha256=%s AND s.consumed_at IS NULL "
            "AND s.expires_at>now() FOR UPDATE OF s,c",
            [state_sha256],
        ).fetchone()
        if not state or state["customer_id"] != cluster["customer_id"]:
            raise ApiError(
                422,
                "GITHUB_AUTHORIZATION_STATE_INVALID",
                "The GitHub authorization request is invalid or has expired.",
            )
        self.db.execute(
            "UPDATE cluster_management.github_app_authorization_states "
            "SET consumed_at=now() WHERE state_sha256=%s",
            [state_sha256],
        )
        self.db.execute(
            "UPDATE cluster_management.github_app_connections "
            "SET installation_id=%s,permissions=%s::jsonb,status='ACTIVE',"
            "updated_by=%s,updated_at=now() "
            "WHERE connection_id=%s",
            [
                installation_id,
                json_text(permissions),
                self.principal.user_id,
                state["connection_id"],
            ],
        )
        self.bind_system_repository_connection(
            cluster["cluster_id"], state["connection_id"]
        )
        return {
            "connectionId": state["connection_id"],
            "organization": state["organization_login"],
            "installationId": installation_id,
            "status": "ACTIVE",
        }

    def identity(self, identifier):
        cluster = self.get(identifier)
        row = self.db.execute(
            "SELECT provider,status,issuer,audience,username_claim,groups_claim,"
            "username_prefix,groups_prefix,configuration_fingerprint,desired_revision,"
            "applied_revision,last_verified_at,failure_code,version,updated_at "
            "FROM cluster_management.cluster_identity_integrations WHERE cluster_id=%s",
            [identifier],
        ).fetchone()
        if not row:
            return {
                "clusterId": identifier,
                "customerId": cluster["customer_id"],
                "provider": cluster["platform"],
                "status": "NOT_CONFIGURED",
                "desiredRevision": 1,
                "appliedRevision": None,
                "lastVerifiedAt": None,
                "failureCode": None,
            }
        return {
            "clusterId": identifier,
            "customerId": cluster["customer_id"],
            **serialize(row),
        }

    def kubernetes_access(self, identifier):
        cluster = self.get(identifier)
        rows = self.db.execute(
            "SELECT a.assignment_id,a.subject_type,a.subject_id,p.profile_code,"
            "p.profile_name,p.scope_type,a.namespace,a.valid_from,a.valid_until,a.status "
            "FROM access_management.kubernetes_access_assignments a "
            "JOIN access_management.kubernetes_access_profiles p USING(profile_id) "
            "WHERE a.customer_id=%s AND (a.cluster_id IS NULL OR a.cluster_id=%s) "
            "AND a.status IN ('PENDING','ACTIVE') "
            "ORDER BY p.profile_name,a.subject_type,a.subject_id",
            [cluster["customer_id"], identifier],
        ).fetchall()
        profiles = self.db.execute(
            "SELECT profile_code,profile_name,description,scope_type "
            "FROM access_management.kubernetes_access_profiles "
            "WHERE status='ACTIVE' ORDER BY profile_name"
        ).fetchall()
        return {
            "clusterId": identifier,
            "customerId": cluster["customer_id"],
            "assignments": [serialize(row) for row in rows],
            "profiles": [serialize(row) for row in profiles],
        }

    def kubernetes_namespaces(self, identifier):
        cluster = self.get(identifier)
        inventory = self.db.execute(
            "SELECT status,source,source_revision,connector_id,observed_at,expires_at,failure_code,"
            "CASE WHEN status='READY' AND expires_at <= now() THEN 'STALE' ELSE status END "
            "AS effective_status "
            "FROM cluster_management.cluster_namespace_inventories WHERE cluster_id=%s",
            [identifier],
        ).fetchone()
        if not inventory:
            return {
                "clusterId": identifier,
                "customerId": cluster["customer_id"],
                "status": "NOT_CONFIGURED",
                "source": "IN_CLUSTER_CONNECTOR",
                "connectorId": None,
                "observedAt": None,
                "expiresAt": None,
                "failureCode": None,
                "namespaces": [],
            }
        rows = []
        if inventory["effective_status"] == "READY":
            rows = self.db.execute(
                "SELECT namespace,is_system,observed_at "
                "FROM cluster_management.cluster_namespaces "
                "WHERE cluster_id=%s AND source_revision=%s "
                "ORDER BY is_system,namespace",
                [identifier, inventory["source_revision"]],
            ).fetchall()
        return {
            "clusterId": identifier,
            "customerId": cluster["customer_id"],
            "status": inventory["effective_status"],
            "source": inventory["source"],
            "connectorId": inventory["connector_id"],
            "observedAt": (
                inventory["observed_at"].isoformat()
                if inventory["observed_at"] else None
            ),
            "expiresAt": (
                inventory["expires_at"].isoformat()
                if inventory["expires_at"] else None
            ),
            "failureCode": inventory["failure_code"],
            "namespaces": [serialize(row) for row in rows],
        }

    def node_group_requests(self, identifier):
        cluster = self.get(identifier)
        rows = self.db.execute(
            "SELECT request_id,cluster_id,customer_id,node_group,reason,status,version,"
            "plan_sha256,provider_execution_id,workflow,created_by,created_at,"
            "updated_by,updated_at "
            "FROM cluster_management.cluster_node_group_requests "
            "WHERE cluster_id=%s ORDER BY created_at DESC,request_id",
            [identifier],
        ).fetchall()
        return {
            "clusterId": identifier,
            "customerId": cluster["customer_id"],
            "items": [serialize(row) for row in rows],
        }

    def active_application_node_groups(self, identifier):
        self.get(identifier)
        rows = self.db.execute(
            "SELECT node_group FROM cluster_management.cluster_node_group_requests "
            "WHERE cluster_id=%s AND status='ACTIVE' "
            "ORDER BY created_at,request_id",
            [identifier],
        ).fetchall()
        return [
            row["node_group"]
            for row in rows
            if isinstance(row.get("node_group"), dict)
            and row["node_group"].get("purpose") == "APPLICATION"
        ]

    def get_node_group_request(self, cluster_id, request_id, lock=False):
        self.get(cluster_id)
        row = self.db.execute(
            "SELECT * FROM cluster_management.cluster_node_group_requests "
            "WHERE cluster_id=%s AND request_id=%s"
            + (" FOR UPDATE" if lock else ""),
            [cluster_id, request_id],
        ).fetchone()
        if not row:
            raise ApiError(
                404, "NODE_GROUP_REQUEST_NOT_FOUND", "Node-group request not found."
            )
        return row

    def audit_log(self, identifier, limit=200):
        cluster = self.get(identifier)
        rows = self.db.execute(
            "SELECT audit_id,cluster_id,action,performed_by,correlation_id,"
            "old_value,new_value,occurred_at "
            "FROM cluster_management.cluster_audit_log "
            "WHERE cluster_id=%s ORDER BY audit_id DESC LIMIT %s",
            [identifier, limit],
        ).fetchall()
        return {
            "clusterId": identifier,
            "customerId": cluster["customer_id"],
            "items": [serialize(row) for row in rows],
        }

    def save_node_group_request(self, row, create=False):
        columns = list(row)
        json_columns = {"node_group", "workflow"}
        values = [
            json_text(value) if key in json_columns else value
            for key, value in row.items()
        ]
        slots = ["%s::jsonb" if key in json_columns else "%s" for key in columns]
        if create:
            sql = (
                "INSERT INTO cluster_management.cluster_node_group_requests ("
                + ",".join(columns)
                + ") VALUES ("
                + ",".join(slots)
                + ")"
            )
        else:
            sql = (
                "UPDATE cluster_management.cluster_node_group_requests SET "
                + ",".join(
                    f"{column}={slot}" for column, slot in zip(columns, slots)
                )
                + " WHERE request_id=%s"
            )
            values.append(row["request_id"])
        self.db.execute(sql, values)

    def record_node_group_request(self, old, row, action, correlation):
        self.db.execute(
            "INSERT INTO cluster_management.cluster_audit_log"
            "(cluster_id,action,performed_by,correlation_id,old_value,new_value) "
            "VALUES (%s,%s,%s,%s,%s::jsonb,%s::jsonb)",
            [
                row["cluster_id"],
                action,
                self.principal.user_id,
                correlation,
                json_text(serialize(old)) if old else None,
                json_text(serialize(row)),
            ],
        )

    def request_connector_install(self, identifier, token, reason, correlation, installer):
        cluster = self.get(identifier, lock=True)
        current = self.db.execute(
            "SELECT connector_id FROM cluster_management.cluster_connectors "
            "WHERE cluster_id=%s AND status IN ('ENROLLED','ACTIVE','STALE') FOR UPDATE",
            [identifier],
        ).fetchone()
        if current:
            self.db.execute(
                "UPDATE cluster_management.cluster_connectors "
                "SET status='REVOKED',revoked_by=%s,revoked_at=now() "
                "WHERE connector_id=%s",
                [self.principal.user_id, current["connector_id"]],
            )
        connector_id = "KCC-" + __import__("uuid").uuid4().hex
        token_sha256 = hashlib.sha256(token.encode()).hexdigest()
        self.db.execute(
            "INSERT INTO cluster_management.cluster_connectors"
            "(connector_id,cluster_id,token_sha256,status,created_by,"
            "installation_status,installation_reason) "
            "VALUES (%s,%s,%s,'ENROLLED',%s,'REQUESTED',%s)",
            [connector_id, identifier, token_sha256, self.principal.user_id, reason],
        )
        self.db.execute(
            "INSERT INTO cluster_management.cluster_namespace_inventories"
            "(cluster_id,status,source,source_revision,connector_id,updated_at) "
            "VALUES (%s,'NOT_CONFIGURED','IN_CLUSTER_CONNECTOR',0,%s,now()) "
            "ON CONFLICT(cluster_id) DO UPDATE SET "
            "status='NOT_CONFIGURED',source_revision=0,connector_id=excluded.connector_id,"
            "observed_at=NULL,expires_at=NULL,failure_code=NULL,updated_at=now()",
            [identifier, connector_id],
        )
        _, snapshot = self.pinned_environment_snapshot(
            cluster["environment_id"], cluster["environment_approved_version"]
        )
        execution = installer.start(cluster, snapshot, connector_id, token)
        self.db.execute(
            "UPDATE cluster_management.cluster_connectors "
            "SET installation_status=%s,installation_execution_id=%s,"
            "installation_secret_arn=%s WHERE connector_id=%s",
            [
                execution["status"],
                execution["executionId"],
                execution["secretArn"],
                connector_id,
            ],
        )
        audit = {
            "connectorId": connector_id,
            "clusterId": identifier,
            "status": execution["status"],
            "executionId": execution["executionId"],
        }
        self.db.execute(
            "INSERT INTO cluster_management.cluster_audit_log"
            "(cluster_id,action,performed_by,correlation_id,new_value) "
            "VALUES (%s,'ClusterConnectorInstallationRequested',%s,%s,%s::jsonb)",
            [
                identifier,
                self.principal.user_id,
                correlation,
                json_text({**audit, "reason": reason}),
            ],
        )
        return {
            **audit,
            "customerId": cluster["customer_id"],
        }

    def create_kubernetes_access(self, identifier, body, correlation):
        cluster = self.get(identifier)
        profile = self.db.execute(
            "SELECT profile_id,profile_code,profile_name,scope_type "
            "FROM access_management.kubernetes_access_profiles "
            "WHERE profile_code=%s AND status='ACTIVE' FOR SHARE",
            [body["profileCode"]],
        ).fetchone()
        if not profile:
            raise ApiError(404, "ACCESS_PROFILE_NOT_FOUND", "Access profile not found.")
        namespace = body.get("namespace")
        if profile["scope_type"] == "NAMESPACE" and not namespace:
            raise ApiError(422, "NAMESPACE_REQUIRED", "Select a namespace for this profile.")
        if profile["scope_type"] == "CLUSTER" and namespace:
            raise ApiError(422, "NAMESPACE_NOT_ALLOWED", "This profile applies to the cluster.")
        if profile["scope_type"] == "NAMESPACE":
            discovered = self.db.execute(
                "SELECT n.namespace "
                "FROM cluster_management.cluster_namespace_inventories i "
                "JOIN cluster_management.cluster_namespaces n "
                "ON n.cluster_id=i.cluster_id AND n.source_revision=i.source_revision "
                "WHERE i.cluster_id=%s AND i.status='READY' AND i.expires_at > now() "
                "AND n.namespace=%s",
                [identifier, namespace],
            ).fetchone()
            if not discovered:
                raise ApiError(
                    422,
                    "NAMESPACE_NOT_DISCOVERED",
                    "Select a namespace from the latest verified cluster inventory.",
                )
        existing = self.db.execute(
            "SELECT assignment_id FROM access_management.kubernetes_access_assignments "
            "WHERE subject_type=%s AND subject_id=%s AND profile_id=%s "
            "AND customer_id=%s AND cluster_id=%s "
            "AND coalesce(namespace,'')=coalesce(%s,'') "
            "AND status IN ('PENDING','ACTIVE')",
            [
                body["subjectType"], body["subjectId"], profile["profile_id"],
                cluster["customer_id"], identifier, namespace,
            ],
        ).fetchone()
        if existing:
            raise ApiError(409, "ACCESS_ASSIGNMENT_EXISTS", "This access assignment already exists.")
        assignment_id = "KAA-" + __import__("uuid").uuid4().hex
        self.db.execute(
            "INSERT INTO access_management.kubernetes_access_assignments"
            "(assignment_id,subject_type,subject_id,profile_id,customer_id,cluster_id,"
            "namespace,status,reason,created_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,'PENDING',%s,%s)",
            [
                assignment_id, body["subjectType"], body["subjectId"],
                profile["profile_id"], cluster["customer_id"], identifier,
                namespace, body["reason"], self.principal.user_id,
            ],
        )
        value = {
            "assignmentId": assignment_id,
            "subjectType": body["subjectType"],
            "subjectId": body["subjectId"],
            "profileCode": profile["profile_code"],
            "profileName": profile["profile_name"],
            "scopeType": profile["scope_type"],
            "namespace": namespace,
            "status": "PENDING",
        }
        self.db.execute(
            "INSERT INTO access_management.access_audit_log"
            "(action,target_type,target_id,performed_by,reason,correlation_id,new_value) "
            "VALUES ('KubernetesAccessAssigned','KUBERNETES_ASSIGNMENT',%s,%s,%s,%s,%s::jsonb)",
            [
                assignment_id, self.principal.user_id, body["reason"], correlation,
                json_text(value),
            ],
        )
        return value

    def revoke_kubernetes_access(self, identifier, assignment_id, body, correlation):
        cluster = self.get(identifier)
        row = self.db.execute(
            "SELECT a.assignment_id,a.subject_type,a.subject_id,p.profile_code,p.profile_name,"
            "p.scope_type,a.namespace,a.status "
            "FROM access_management.kubernetes_access_assignments a "
            "JOIN access_management.kubernetes_access_profiles p USING(profile_id) "
            "WHERE a.assignment_id=%s AND a.cluster_id=%s AND a.customer_id=%s FOR UPDATE",
            [assignment_id, identifier, cluster["customer_id"]],
        ).fetchone()
        if not row:
            raise ApiError(404, "ACCESS_ASSIGNMENT_NOT_FOUND", "Access assignment not found.")
        if row["status"] not in {"PENDING", "ACTIVE"}:
            raise ApiError(409, "ACCESS_ASSIGNMENT_NOT_ACTIVE", "Access is already inactive.")
        self.db.execute(
            "UPDATE access_management.kubernetes_access_assignments "
            "SET status='REVOKED',revoked_by=%s,revoked_at=now() WHERE assignment_id=%s",
            [self.principal.user_id, assignment_id],
        )
        old_value = serialize(row)
        new_value = {**old_value, "status": "REVOKED"}
        self.db.execute(
            "INSERT INTO access_management.access_audit_log"
            "(action,target_type,target_id,performed_by,reason,correlation_id,old_value,new_value) "
            "VALUES ('KubernetesAccessRevoked','KUBERNETES_ASSIGNMENT',%s,%s,%s,%s,%s::jsonb,%s::jsonb)",
            [
                assignment_id, self.principal.user_id, body["reason"], correlation,
                json_text(old_value), json_text(new_value),
            ],
        )
        return new_value

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

    def pinned_environment_snapshot(self, identifier, version):
        """Load the immutable environment revision recorded by a cluster.

        Lifecycle operations must not be blocked merely because the environment
        has since received a newer approved revision.
        """
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
        snapshot = self.db.execute(
            "SELECT snapshot FROM environment_management.environment_versions "
            "WHERE environment_id=%s AND version=%s",
            [identifier, version],
        ).fetchone()
        if not snapshot:
            raise ApiError(
                409,
                "PINNED_VERSION_MISSING",
                "The environment revision pinned to this cluster is unavailable.",
            )
        return row, snapshot["snapshot"]

    def save(self, row, create=False):
        read_only = {
            "customer_name",
            "environment_name",
            "identity_status",
            "identity_last_verified_at",
            "identity_failure_code",
        }
        clean = {k: v for k, v in row.items() if k not in read_only}
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

    def list(self, query, access=None):
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
            "JOIN environment_management.environments e USING(environment_id) "
            "LEFT JOIN cluster_management.cluster_identity_integrations i USING(cluster_id) WHERE "
            + " AND ".join(conditions)
        )
        count = int(
            self.db.execute("SELECT count(*) AS n" + base, params).fetchone()["n"]
        )
        rows = self.db.execute(
            "SELECT k.cluster_id,k.customer_id,c.name AS customer_name,k.environment_id,"
            "e.environment_name,k.environment_approved_version,k.platform,k.cluster_name,"
            "k.status,k.version,k.provider_execution_id,k.created_at,k.updated_at,"
            "coalesce(i.status,'NOT_CONFIGURED') AS identity_status,"
            "i.last_verified_at AS identity_last_verified_at,"
            "i.failure_code AS identity_failure_code" + base
            + " ORDER BY k.updated_at DESC,k.cluster_id LIMIT %s OFFSET %s",
            [*params, query["pageSize"], query["page"] * query["pageSize"]],
        ).fetchall()
        return {
            "items": [serialize(row, access) for row in rows],
            "pagination": {
                "page": int(query["page"]),
                "pageSize": int(query["pageSize"]),
                "totalElements": count,
                "totalPages": math.ceil(count / int(query["pageSize"])),
            },
        }
