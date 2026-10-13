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
        {"INVENTORY_READY", "REJECTED"},
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

    def analyze_target(self, identifier):
        """Capture existing Cluster Management connector inventory, read-only."""
        self.access.require("migration.edit")
        migration = self.repo.get(identifier)
        configuration = migration.get("target_configuration") or {}
        if migration["target_platform"] != "EKS":
            raise ApiError(422, "TARGET_ADAPTER_UNAVAILABLE",
                           "Existing target inventory assessment currently supports EKS.")
        cluster_id = configuration.get("clusterId")
        assessment = self.repo.get_assessment(identifier).get("assessment")
        if not cluster_id or not assessment:
            raise ApiError(409, "TARGET_NOT_READY",
                           "A selected target and source assessment are required.")
        from navigan.modules.cluster_management.repository import Repository as ClusterRepository
        cluster_repo = ClusterRepository(self.repo.db, self.principal)
        registered = cluster_repo.get(cluster_id)
        if registered["customer_id"] != migration["customer_id"] or registered["cluster_name"] != configuration.get("clusterName"):
            raise ApiError(409, "TARGET_IDENTITY_MISMATCH",
                           "Target is not the registered cluster for this migration and customer.")
        if registered["status"] != "ACTIVE":
            raise ApiError(409, "TARGET_NOT_ACTIVE", "Target cluster must be ACTIVE.")
        existing = cluster_repo.runtime_inventory(cluster_id, cluster=registered)
        if existing["status"] not in {"READY", "DEGRADED"}:
            raise ApiError(409, "TARGET_INVENTORY_UNAVAILABLE",
                           "Cluster Management connector inventory is missing or stale. Refresh it in Cluster Management and retry.")
        resources = existing.get("resources") or []
        # Include only source-observed resource kinds; unknown shapes remain
        # explicitly unclassified rather than being guessed.
        resource_kinds = {}
        unclassified = 0
        for resource in resources:
            kind = resource.get("kind") if isinstance(resource, dict) else None
            if isinstance(kind, str) and kind.strip():
                kind = kind.strip()
                resource_kinds[kind] = resource_kinds.get(kind, 0) + 1
            else:
                unclassified += 1

        snapshot = {
            "resourceKinds": dict(sorted(resource_kinds.items())),
            "unclassifiedResourceCount": unclassified,
            "capabilityEvidence": {
                "kubernetesApi": {"status": "NOT_VERIFIED", "reason": "Supported target API versions and discovery endpoints were not included in the connector inventory."},
                "compute": {"status": "PARTIAL", "observedNodeCount": resource_kinds.get("Node", 0), "reason": "Node objects observed; allocatable resources, quota and scheduling constraints were not verified."} if resource_kinds.get("Node", 0) else {"status": "NOT_VERIFIED", "reason": "No usable node capacity evidence was provided."},
                "storage": {"status": "NOT_VERIFIED", "reason": "StorageClass, CSI, volume capabilities and PVC requirements are not verified."},
                "networking": {"status": "PARTIAL", "observedServiceCount": resource_kinds.get("Service", 0), "reason": "Service objects observed; ingress, DNS, routing and network policy compatibility unverified."} if resource_kinds.get("Service", 0) else {"status": "NOT_VERIFIED", "reason": "Target routing and service capabilities are not verified."},
                "identity": {"status": "NOT_VERIFIED", "reason": "Workload identity permissions and secret/image access have not been evaluated."},
                "dependencies": {"status": "NOT_VERIFIED", "reason": "Installed operators, CRDs and external dependencies have not been verified."},
            },
            "inventoryExpiresAt": existing.get("expiresAt"),
            "provider": "AWS",
            "platform": "EKS",
            "clusterName": registered["cluster_name"],
            "naviganClusterId": cluster_id,
            "clusterStatus": registered["status"],
            "source": "CLUSTER_MANAGEMENT_CONNECTOR",
            "sourceRevision": existing["sourceRevision"],
            "connectorId": existing["connectorId"],
            "inventoryStatus": existing["status"],
            "observedAt": existing["observedAt"],
            "expiresAt": existing["expiresAt"],
            "evidenceLevel": "CONNECTOR_RUNTIME_INVENTORY",
            "coverageComplete": False,
            "resourceCount": len(resources),
            "unverified": [
                "Workload-specific target scheduling compatibility",
                "StorageClass and CSI compatibility",
                "Ingress and networking compatibility",
                "Workload identity and image pull authorization",
            ],
        }
        return self.repo.save_target_assessment(identifier, cluster_id, snapshot)

    def target_compatibility(self, identifier):
        """Return the backend-authoritative migration-path decision.

        A direct/assisted recommendation is only allowed when the persisted
        target assessment is bound to the current source assessment and the
        target snapshot declares complete coverage. Source blockers can block
        the path even before target coverage is complete.
        """
        self.access.require("migration.view")
        migration = self.repo.get(identifier)
        assessment = self.repo.get_assessment(identifier).get("assessment")
        target = self.repo.get_target_assessment(identifier).get("assessment")

        if not assessment:
            return {
                "migrationId": identifier,
                "assessmentVersion": None,
                "targetClusterId": (migration.get("target_configuration") or {}).get("clusterId"),
                "evidenceLevel": None,
                "coverageComplete": False,
                "decision": {
                    "path": "PENDING_EVIDENCE",
                    "reason": "A current source assessment is required before compatibility can be decided.",
                },
            }

        findings = assessment.get("findings") or []
        blocked = any(
            finding.get("severity") == "BLOCKER"
            or finding.get("disposition") == "BLOCKER"
            for finding in findings
            if isinstance(finding, dict)
        )
        if blocked:
            path = "BLOCKED"
            reason = "The source assessment contains one or more blocking findings that must be resolved."
        elif not target:
            path = "PENDING_EVIDENCE"
            reason = "Run target analysis and collect target-bound evidence before selecting a migration path."
        else:
            snapshot = target.get("snapshot") or {}
            complete = bool(snapshot.get("coverageComplete")) and not (snapshot.get("unverified") or [])
            if not complete:
                path = "PENDING_EVIDENCE"
                reason = "Target evidence is present but incomplete; required capabilities remain unverified."
            elif any(
                finding.get("disposition") in {"MANUAL_CHANGE", "AUTOMATED_CHANGE"}
                for finding in findings
                if isinstance(finding, dict)
            ):
                path = "ASSISTED"
                reason = "Compatibility evidence is complete, but one or more source findings require remediation or assisted translation."
            else:
                path = "DIRECT"
                reason = "Current source and target evidence is complete and no blocking or remediation findings remain."

        snapshot = (target or {}).get("snapshot") or {}
        return {
            "migrationId": identifier,
            "assessmentVersion": assessment.get("assessmentVersion"),
            "targetClusterId": (target or {}).get("targetClusterId")
            or (migration.get("target_configuration") or {}).get("clusterId"),
            "evidenceLevel": (target or {}).get("evidenceLevel"),
            "coverageComplete": bool(snapshot.get("coverageComplete")) and not (snapshot.get("unverified") or []),
            "decision": {"path": path, "reason": reason},
        }

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

    def install_source_connector(self, identifier, body, installer):
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
                "A revoked source cluster cannot be installed.",
            )

        token = secrets.token_urlsafe(32)
        enrollment = self.repo.create_source_enrollment(
            source_cluster,
            token,
            body["reason"],
            self.correlation,
        )
        installation = installer.start(source_cluster, token)
        self.repo.audit_source_cluster(
            identifier,
            "SOURCE_CONNECTOR_INSTALLATION_STARTED",
            self.correlation,
            {
                "commandId": installation["commandId"],
                "managedInstanceId": installation["managedInstanceId"],
            },
        )
        return {
            "sourceClusterId": identifier,
            "enrollmentId": enrollment["enrollment_id"],
            **installation,
        }

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

        if "planningDraft" in body:
            return self.save_planning_draft(identifier, current, body)

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

    def save_planning_draft(self, identifier, current, body):
        if set(body) - {"version", "planningDraft", "changeReason"}:
            raise ApiError(
                400, "PLANNING_UPDATE_ONLY", "Save planning separately from assessment configuration."
            )
        if current["status"] not in {"ASSESSMENT_READY", "SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED"}:
            raise ApiError(409, "ASSESSMENT_REQUIRED", "Complete assessment before planning migration.")
        assessment = self.repo.get_assessment(identifier)["assessment"]
        inventory = self.repo.get_source_inventory(identifier)["inventory"]
        draft = body["planningDraft"]
        if (
            not assessment
            or not inventory
            or (
                draft["assessmentVersion"] != assessment["assessmentVersion"]
                or draft["inventoryDigest"] != assessment["inventoryDigest"]
                or draft["inventoryDigest"] != inventory["inventoryDigest"]
            )
        ):
            raise ApiError(
                409,
                "PLANNING_EVIDENCE_CHANGED",
                "Reload the latest assessment and inventory before planning.",
            )
        available = {
            (r["apiVersion"], r["kind"], r.get("namespace"), r.get("name")) for r in inventory["resources"]
        }
        self.repo.require_planning_configuration(identifier, assessment["migrationVersion"], current)
        for resource in draft["resources"]:
            key = (resource["apiVersion"], resource["kind"], resource.get("namespace"), resource["name"])
            if key not in available:
                raise ApiError(
                    400, "RESOURCE_OUTSIDE_INVENTORY", "Select resources from the assessed source inventory."
                )
            if resource["kind"] == "Node" and resource["treatment"] == "MIGRATE":
                raise ApiError(
                    400,
                    "SOURCE_NODE_NOT_PORTABLE",
                    "Source nodes must be recreated or retired, not migrated to EKS.",
                )
        for item in draft["remediations"]:
            if item["findingIndex"] >= len(assessment["findings"]):
                raise ApiError(400, "FINDING_NOT_FOUND", "Select a finding from this assessment.")
        row = copy.deepcopy(current)
        row["planning_draft"] = draft
        row["version"] += 1
        row["updated_by"] = self.principal.user_id
        row["change_reason"] = body["changeReason"]
        # Planning is not assessment approval, verification, or execution authority.
        self.repo.save(row, current, "MIGRATION_PLANNING_UPDATED", self.correlation)
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
