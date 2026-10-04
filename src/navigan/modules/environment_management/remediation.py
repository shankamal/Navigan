import json
import uuid
from datetime import datetime, timezone

from navigan.shared.errors import ApiError
from navigan.modules.customer_management.repository import scope_clause
from .repository import page_result, serialize


class BootstrapRemediationService:
    def __init__(self, repo, correlation):
        self.repo = repo
        self.db = repo.db
        self.principal = repo.principal
        self.correlation = correlation

    def create(self, body):
        self.principal.require("CLOUD_ENGINEER")
        self.repo.validate_parent(body["customerId"], "AWS", active=True)
        now = datetime.now(timezone.utc)
        existing = self.db.execute(
            "SELECT request_id FROM environment_management.bootstrap_remediation_requests "
            "WHERE customer_id=%s AND account_id=%s AND region=%s "
            "AND status IN ('REQUESTED','APPROVED','PLAN_RUNNING','PLAN_READY','APPLY_RUNNING') "
            "FOR UPDATE",
            [body["customerId"], body["accountId"], body["region"]],
        ).fetchone()
        if existing:
            raise ApiError(
                409,
                "REMEDIATION_ALREADY_OPEN",
                "An unresolved bootstrap remediation request already exists for this customer account and region.",
                {"requestId": existing["request_id"]},
            )
        row = {
            "request_id": "BRQ-" + uuid.uuid4().hex,
            "customer_id": body["customerId"],
            "account_id": body["accountId"],
            "region": body["region"],
            "discovery_role_arn": body["discoveryRoleArn"],
            "missing_resources": body["missingResources"],
            "requested_actions": body["requestedActions"],
            "desired_resources": body.get("desiredResources", {}),
            "verification_details": {},
            "verified_by": None,
            "verified_at": None,
            "status": "REQUESTED",
            "confirmed_by": self.principal.user_id,
            "confirmed_at": now,
            "requested_by": self.principal.user_id,
            "requested_at": now,
            "decided_by": None,
            "decided_at": None,
            "decision_reason": None,
            "version": 1,
            "correlation_id": self.correlation,
        }
        columns = list(row)
        json_columns = {
            "missing_resources",
            "requested_actions",
            "desired_resources",
            "verification_details",
        }
        values = [json.dumps(value) if key in json_columns else value for key, value in row.items()]
        slots = ["%s::jsonb" if key in json_columns else "%s" for key in columns]
        self.db.execute(
            f"INSERT INTO environment_management.bootstrap_remediation_requests ({','.join(columns)}) VALUES ({','.join(slots)})",
            values,
        )
        self._history(
            row["request_id"],
            "REQUESTED",
            {
                "confirmed": True,
                "desiredResources": body.get("desiredResources", {}),
            },
        )
        return self.get(row["request_id"])

    def get(self, request_id, lock=False):
        scope, params = scope_clause(self.principal)
        row = self.db.execute(
            "SELECT r.*,c.name AS customer_name "
            "FROM environment_management.bootstrap_remediation_requests r "
            "JOIN customer_management.customers c USING(customer_id) "
            "WHERE r.request_id=%s AND "
            + scope
            + (" FOR UPDATE OF r" if lock else ""),
            [request_id, *params],
        ).fetchone()
        if not row:
            raise ApiError(404, "BOOTSTRAP_REQUEST_NOT_FOUND", "Bootstrap remediation request not found.")
        return serialize(row)

    def list(self, query):
        self.principal.require("PLATFORM_ARCHITECT")
        scope, params = scope_clause(self.principal)
        conditions = [scope]
        if query.get("status"):
            conditions.append("r.status=%s")
            params.append(query["status"])
        if query.get("customerId"):
            conditions.append("r.customer_id=%s")
            params.append(query["customerId"])
        if query.get("search"):
            conditions.append(
                "(strpos(lower(r.request_id),lower(%s))>0 "
                "OR strpos(lower(c.name),lower(%s))>0 "
                "OR strpos(lower(r.account_id),lower(%s))>0)"
            )
            params.extend([query["search"]] * 3)
        base = (
            " FROM environment_management.bootstrap_remediation_requests r "
            "JOIN customer_management.customers c USING(customer_id) WHERE "
            + " AND ".join(conditions)
        )
        count = self.db.execute("SELECT count(*) AS n" + base, params).fetchone()["n"]
        rows = self.db.execute(
            "SELECT r.*,c.name AS customer_name"
            + base
            + " ORDER BY r.requested_at DESC,r.request_id LIMIT %s OFFSET %s",
            [*params, query["pageSize"], query["page"] * query["pageSize"]],
        ).fetchall()
        return page_result(
            [serialize(row) for row in rows],
            count,
            query["page"],
            query["pageSize"],
        )

    def decide(self, request_id, action, body):
        self.principal.require("PLATFORM_ARCHITECT")
        row = self.get(request_id, lock=True)
        if row["version"] != body["version"]:
            raise ApiError(409, "CONCURRENT_UPDATE", "Reload the latest remediation request.")
        if row["status"] != "REQUESTED":
            raise ApiError(409, "INVALID_STATUS_TRANSITION", "This request has already been decided.")
        if row["requestedBy"] == self.principal.user_id:
            raise ApiError(403, "INDEPENDENT_REVIEW_REQUIRED", "The requester cannot approve remediation.")
        if action == "reject" and not body.get("reason"):
            raise ApiError(422, "REASON_REQUIRED", "Provide a rejection reason.")
        target = "APPROVED" if action == "approve" else "REJECTED"
        now = datetime.now(timezone.utc)
        self.db.execute(
            "UPDATE environment_management.bootstrap_remediation_requests "
            "SET status=%s,decided_by=%s,decided_at=%s,decision_reason=%s,version=version+1 "
            "WHERE request_id=%s",
            [target, self.principal.user_id, now, body.get("reason"), request_id],
        )
        self._history(request_id, target, {"reason": body.get("reason")})
        return self.get(request_id)

    def verify(self, request_id, body, discovery):
        self.principal.require("CLOUD_ENGINEER")
        row = self.get(request_id, lock=True)
        if row["version"] != body["version"]:
            raise ApiError(409, "CONCURRENT_UPDATE", "Reload the latest remediation request.")
        if row["status"] not in {"APPROVED", "PLAN_READY", "APPLY_RUNNING"}:
            raise ApiError(
                409,
                "INVALID_STATUS_TRANSITION",
                "The remediation request must be approved before verification.",
            )
        if row["requestedBy"] != self.principal.user_id and not self.principal.platform_scope:
            raise ApiError(
                403,
                "FORBIDDEN",
                "Only the requester or a platform-scoped Cloud Engineer may verify this request.",
            )

        found, missing = self._verification_result(row, discovery)
        now = datetime.now(timezone.utc)
        details = {"found": found, "missing": missing}
        target = "COMPLETED" if not missing else "FAILED"
        self.db.execute(
            "UPDATE environment_management.bootstrap_remediation_requests "
            "SET status=%s,verification_details=%s::jsonb,verified_by=%s,verified_at=%s,"
            "decision_reason=CASE WHEN %s='FAILED' THEN %s ELSE decision_reason END,"
            "version=version+1 WHERE request_id=%s",
            [
                target,
                json.dumps(details),
                self.principal.user_id,
                now,
                target,
                "Rediscovery did not find every approved prerequisite.",
                request_id,
            ],
        )
        self._history(request_id, target, details)
        return self.get(request_id)

    @staticmethod
    def _verification_result(row, discovery):
        desired = row.get("desiredResources") or {}
        found = {}
        missing = []
        roles = {
            item.get("roleName"): item
            for item in discovery.get("iamRoles", [])
            if item.get("eligibility") == "READY"
        }
        provisioning_roles = {
            item.get("roleName"): item for item in discovery.get("provisioningRoles", [])
        }
        secrets = {
            item.get("name"): item for item in discovery.get("provisioningSecrets", [])
        }
        kms_aliases = {
            item.get("aliasName"): item
            for region in discovery.get("regions", [])
            for item in region.get("kmsKeys", [])
            if item.get("eligibility") == "READY"
        }
        inventories = {
            "EKS_CLUSTER_ROLE": {
                name: item for name, item in roles.items() if item.get("roleType") == "CLUSTER"
            },
            "EKS_NODE_ROLE": {
                name: item for name, item in roles.items() if item.get("roleType") == "NODE"
            },
            "PROVISIONING_ROLE": provisioning_roles,
            "EXTERNAL_ID_SECRET": secrets,
            "KMS_KEY": kms_aliases,
        }
        for resource, name in desired.items():
            if inventories.get(resource, {}).get(name):
                found[resource] = name
            else:
                missing.append(resource)

        default_checks = {
            "EKS_CLUSTER_ROLE": any(
                item.get("roleType") == "CLUSTER" for item in roles.values()
            ),
            "EKS_NODE_ROLE": any(
                item.get("roleType") == "NODE" for item in roles.values()
            ),
            "KMS_KEY": bool(kms_aliases),
            "PROVISIONING_ROLE": bool(provisioning_roles),
            "EXTERNAL_ID_SECRET": bool(secrets),
            "KUBERNETES_VERSIONS": any(
                region.get("kubernetesVersions") for region in discovery.get("regions", [])
            ),
        }
        for resource in row.get("missingResources") or []:
            if resource in desired:
                continue
            if default_checks.get(resource):
                found[resource] = "discovered"
            elif resource not in missing:
                missing.append(resource)
        return found, sorted(missing)

    def _history(self, request_id, status, details):
        self.db.execute(
            "INSERT INTO environment_management.bootstrap_remediation_history "
            "(request_id,status,performed_by,details,correlation_id) VALUES (%s,%s,%s,%s::jsonb,%s)",
            [request_id, status, self.principal.user_id, json.dumps(details), self.correlation],
        )
