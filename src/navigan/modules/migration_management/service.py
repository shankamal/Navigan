import copy
import os
from datetime import datetime, timezone
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

    def require_source_first(self):
        if os.environ.get("MIGRATION_SOURCE_FIRST_ENABLED") != "true":
            raise ApiError(404, "ROUTE_NOT_FOUND", "Endpoint not found.")

    def deployment_source_configuration(self, identifier):
        self.require_source_first()
        source = self.repo.get_source_cluster(identifier)
        configuration = (source.get("delivery_configuration") or {}).get("deploymentDiscovery") or {"repositories": [], "registries": []}
        from .source_authentication import ready
        authentication = (source.get("delivery_configuration") or {}).get("deploymentAuthentication", {})
        return {"sourceClusterId": identifier, "version": source["version"], "configuration": configuration,
                "authentication": {k: {f: v for f, v in entry.items() if f != "secretVersion"} for k, entry in authentication.items()}, "readyForDiscovery": ready(configuration, authentication),
                "githubOrganizations": self.repo.deployment_connections(source["customer_id"]),
                "registryPrincipalArn": os.environ.get("SOURCE_REGISTRY_PRINCIPAL_ARN", ""),
                "registryAdapters": ["AWS_ECR", "REGISTRY_V2"]}

    def save_deployment_sources(self, identifier, body):
        self.require_source_first()
        self.access.require("migration.edit")
        source = self.repo.get_source_cluster(identifier, lock=True)
        self.access.require_customer(source["customer_id"], source["created_by"])
        if source["version"] != body["version"]:
            raise ApiError(409, "CONCURRENT_UPDATE", "Reload deployment sources before saving.")
        artifacts = [a for r in (source.get("delivery_configuration") or {}).get("deploymentAnalysis", {}).get("repositories", []) for a in r.get("artifacts", [])]
        for mapping in body["configuration"].get("confirmations", []):
            if not any(all(mapping[k] == a.get(k) for k in ("repository", "commit", "filePath")) for a in artifacts):
                raise ApiError(400, "DEPLOYMENT_SOURCE_NOT_ANALYZED", "Confirm a deployment artifact returned by source analysis.")
        from .source_authentication import configure
        previous = (source.get("delivery_configuration") or {}).get("deploymentAuthentication", {})
        authentication = configure(source, body["configuration"], body.get("credentials", []), previous, body.get("verify", False), lambda name: self.source_repository_app_token(source, name))
        row = self.repo.save_deployment_configuration(source, "deploymentDiscovery", body["configuration"], self.correlation)
        self.repo.save_deployment_configuration(row, "deploymentAuthentication", authentication, self.correlation)
        return self.deployment_source_configuration(identifier)

    def source_repository_app_token(self, source, repository):
        from .deployment_sources import repository_read_token
        from navigan.modules.cluster_management.repository import Repository as ClusterRepository
        organization, name = repository.split("/", 1)
        connection = ClusterRepository(self.repo.db, self.principal).active_github_connection(source["customer_id"], organization)
        if not connection:
            return None
        return repository_read_token(connection["installation_id"], name)

    def deployment_context(self, identifier):
        self.require_source_first()
        migration = self.repo.get(identifier)
        source_id = migration["source_configuration"].get("sourceClusterId")
        if not source_id:
            raise ApiError(409, "SOURCE_CLUSTER_REQUIRED", "Connect a registered source cluster first.")
        source = self.repo.get_source_cluster(source_id)
        if source["customer_id"] != migration["customer_id"]:
            raise ApiError(403, "SOURCE_CUSTOMER_MISMATCH", "The source cluster belongs to another customer.")
        return migration, source

    def deployment_evidence(self, identifier):
        from .deployment_sources import build_report
        migration, source = self.deployment_context(identifier)
        inventory = self.repo.get_source_inventory(identifier).get("inventory")
        report = build_report(migration, inventory, source)
        from .artifact_recovery import public_job
        report["recoveries"] = [public_job(job) for job in (source.get("delivery_configuration") or {}).get("artifactRecovery", {}).get(identifier, []) if not job.get("workspaceId")]
        report["recoveryStorageConfigured"] = bool(os.environ.get("MIGRATION_RECOVERY_BUCKET"))
        return report

    def analyze_deployment_sources(self, identifier, body):
        if body.get("recovery"):
            if body.get("refreshCluster") or body.get("continueAnalysis"):
                raise ApiError(400, "RECOVERY_ACTION_CONFLICT", "Run recovery separately from discovery or analysis.")
            from .artifact_recovery import recover
            return recover(self, identifier, body)
        import time
        from .deployment_sources import analyze_repository, check_image, config_digest, WORKLOADS
        self.access.require("migration.edit")
        migration, source = self.deployment_context(identifier)
        self.access.require_customer(migration["customer_id"], migration["created_by"])
        if migration["version"] != body["version"]:
            raise ApiError(409, "CONCURRENT_UPDATE", "Reload the latest assessment before analyzing deployment sources.")
        if body.get("refreshCluster"):
            from .source_authentication import ready
            delivery = source.get("delivery_configuration") or {}
            if not ready(delivery.get("deploymentDiscovery", {}), delivery.get("deploymentAuthentication", {})):
                raise ApiError(409, "SOURCE_CONNECTIONS_REQUIRED", "Verify source connections above, or save the inventory-only choice, before refreshing discovery.")
            if migration["status"] != "ASSESSMENT_READY":
                raise ApiError(409, "SOURCE_REFRESH_NOT_READY", "Refresh cluster evidence after the current source assessment completes.")
            current = self.repo.get(identifier, lock=True)
            if current["version"] != body["version"]:
                raise ApiError(409, "CONCURRENT_UPDATE", "Reload the latest assessment.")
            row = copy.deepcopy(current)
            row.update(status="DISCOVERY_PENDING", version=current["version"] + 1,
                       updated_by=self.principal.user_id, change_reason="Refresh running images and deployment metadata")
            self.repo.save(row, current, "MIGRATION_DEPLOYMENT_EVIDENCE_REFRESH", self.correlation)
            return {"migrationId": identifier, "migration": serialize(row), "refreshRequested": True}
        inventory = self.repo.get_source_inventory(identifier).get("inventory")
        if not inventory:
            raise ApiError(409, "SOURCE_INVENTORY_REQUIRED", "Complete source discovery before analyzing deployment sources.")
        configuration = (source.get("delivery_configuration") or {}).get("deploymentDiscovery") or {"repositories": [], "registries": []}
        deadline = time.monotonic() + 18
        repositories = []
        from .source_authentication import repository_token, read_credential, registry_read, ecr_client
        authentication = (source.get("delivery_configuration") or {}).get("deploymentAuthentication", {})
        import hashlib, json
        context_digest = hashlib.sha256(json.dumps({"inventory": inventory.get("inventoryDigest"), "images": [c.get("image") for r in inventory["resources"] for c in (r.get("pod") or {}).get("containers", [])], "configuration": config_digest(configuration), "authentication": authentication}, sort_keys=True, default=str).encode()).hexdigest()
        previous = (source.get("delivery_configuration") or {}).get("deploymentAnalysis", {})
        if not body.get("continueAnalysis") or previous.get("contextDigest") != context_digest:
            previous = {}
        for entry in configuration["repositories"]:
            completed = next((value for value in previous.get("repositories", []) if value.get("repository") == entry["repository"] and value.get("status") != "PENDING"), None)
            if completed:
                repositories.append(completed)
                continue
            if time.monotonic() >= deadline:
                repositories.append({"repository": entry["repository"], "status": "PENDING", "artifacts": [], "gaps": ["Analysis time budget reached. Narrow the repository directory and retry."]})
                continue
            try:
                token = repository_token(source, entry["repository"], authentication.get("github:" + entry["repository"], {}), lambda name: self.source_repository_app_token(source, name))
                repositories.append(analyze_repository(entry, token, deadline=deadline))
            except Exception:
                # Do not persist upstream exception bodies, repository contents or credentials.
                repositories.append({"repository": entry["repository"], "status": "UNAVAILABLE", "artifacts": [],
                                     "gaps": ["Repository could not be inspected. Check the customer GitHub App access, revision and directory; public repositories use anonymous access."]})
        images = sorted({c["image"] for r in inventory["resources"] if r.get("kind") in WORKLOADS
                         for field in ("containers", "initContainers") for c in (r.get("pod") or {}).get(field, []) if c.get("image")})
        checks = []
        registry_clients = {}
        registry_credentials = {}
        for image in images:
            completed = next((value for value in previous.get("images", []) if value.get("image") == image and value.get("status") != "PENDING"), None)
            if completed:
                checks.append(completed)
                continue
            if time.monotonic() >= deadline:
                checks.append({"image": image, "status": "PENDING", "reason": "Analysis time budget reached. Continue evidence analysis to process remaining images."})
                continue
            try:
                from .deployment_sources import image_parts
                parts = image_parts(image)
                key = "registry:" + parts["registry"]
                auth = authentication.get(key, {})
                if ".dkr.ecr." in parts["registry"] and auth.get("mode") not in {"AWS_ROLE", "AWS_EXISTING_ROLE"}:
                    checks.append({"image": image, "status": "NOT_CONNECTED", "reason": "Configure customer IAM role access for this private ECR registry."})
                    continue
                if parts["registry"] not in configuration["registries"]:
                    # Public registry metadata can be inspected without inventing
                    # credentials. registry_read enforces TLS, public-IP pinning,
                    # bounded reads and restricted bearer challenges.
                    ref = parts["digest"] or parts["tag"]
                    payload = registry_read(parts["registry"], {"mode": "PUBLIC"}, "/v2/" + parts["repository"] + "/manifests/" + ref, parts["repository"])
                    checks.append({"image": image, "status": "AVAILABLE", "registryDigest": payload.get("_registryDigest"), "architectures": sorted({m.get("platform", {}).get("architecture") for m in payload.get("manifests", []) if m.get("platform", {}).get("architecture")}), "reason": "Anonymous read-only registry manifest access succeeded."})
                    continue
                if parts["registry"] in configuration["registries"] and auth.get("mode") in {"TOKEN", "BEARER", "PUBLIC"}:
                    if key not in registry_credentials:
                        registry_credentials[key] = {"mode": auth["mode"], **read_credential(source, key, auth)}
                    credential = registry_credentials[key]
                    ref = parts["digest"] or parts["tag"]
                    payload = registry_read(parts["registry"], credential, "/v2/" + parts["repository"] + "/manifests/" + ref, parts["repository"])
                    checks.append({"image": image, "status": "AVAILABLE", "registryDigest": payload.get("_registryDigest"), "architectures": sorted({m.get("platform", {}).get("architecture") for m in payload.get("manifests", []) if m.get("platform", {}).get("architecture")}), "reason": "Read-only registry manifest access succeeded."})
                else:
                    if auth.get("mode") in {"AWS_ROLE", "AWS_EXISTING_ROLE"} and key not in registry_clients:
                        registry_clients[key] = ecr_client(parts["registry"], auth)
                    checks.append(check_image(image, None, configuration["registries"], aws_client=registry_clients.get(key)))
            except Exception as error:
                upstream = getattr(error, "registry_status", getattr(error, "code", None))
                aws_code = getattr(error, "response", {}).get("Error", {}).get("Code")
                missing = upstream == 404 or aws_code in {"ImageNotFoundException", "RepositoryNotFoundException"}
                denied = upstream in {401, 403} or aws_code in {"AccessDeniedException", "UnrecognizedClientException", "ExpiredTokenException"}
                checks.append({"image": image, "status": "NOT_FOUND" if missing else "ACCESS_REQUIRED" if denied else "UNAVAILABLE", "reason": "The referenced artifact was not found at the queried registry endpoint. This does not establish deletion or cache recoverability." if missing else "Registry authentication or authorization failed; artifact existence is unverified." if denied else "Image metadata could not be read. Check network access, authentication and the image reference; unavailability does not prove deletion."})
        analysis = {"inventoryDigest": inventory.get("inventoryDigest"), "configurationDigest": config_digest(configuration), "contextDigest": context_digest, "repositories": repositories, "images": checks,
                    "analyzedAt": datetime.now(timezone.utc).isoformat()}
        self.repo.save_deployment_configuration(source, "deploymentAnalysis", analysis, self.correlation)
        return self.deployment_evidence(identifier)

    def prepare_artifact_upload(self, identifier, body):
        """Issue a scoped, encrypted S3 upload intent for a reviewed artifact.

        Upload is a separate, explicitly authorized action from assessment.
        Successful PUTs remain pending server-side validation.
        """
        import os
        from .artifacts import ArtifactRequest, artifact_key, presign_artifact_put

        self.access.require("migration.edit")
        migration = self.repo.get(identifier)
        assessment = self.repo.get_assessment(identifier).get("assessment")
        if not assessment:
            raise ApiError(409, "SOURCE_ASSESSMENT_REQUIRED", "Save a Source assessment before preparing migration artifacts.")
        if not migration.get("planning_draft"):
            raise ApiError(409, "SOURCE_SCOPE_REQUIRED", "Save the Source migration scope before preparing artifacts.")
        bucket = os.environ.get("MIGRATION_ARTIFACT_BUCKET", "")
        kms_key = os.environ.get("MIGRATION_ARTIFACT_KMS_KEY_ARN", "")
        if not bucket or not kms_key:
            raise ApiError(503, "ARTIFACT_STORAGE_UNAVAILABLE", "Migration artifact storage is not configured.")
        expected = {"kind", "filename", "sha256", "sizeBytes", "contentType"}
        if set(body) != expected or type(body.get("sizeBytes")) is not int:
            raise ApiError(400, "INVALID_ARTIFACT", "Provide kind, filename, SHA-256, integer sizeBytes and contentType only.")
        try:
            request = ArtifactRequest(
                customer_id=str(migration["customer_id"]), migration_id=identifier,
                assessment_version=int(assessment["assessmentVersion"]),
                kind=body["kind"], filename=body["filename"],
                sha256=body["sha256"], size_bytes=body["sizeBytes"],
                content_type=body["contentType"],
            )
            artifact_key(request)
        except (KeyError, TypeError, ValueError) as exc:
            raise ApiError(400, "INVALID_ARTIFACT", str(exc)) from exc
        import boto3
        return presign_artifact_put(
            boto3.client("s3"), bucket=bucket, kms_key_id=kms_key,
            request=request,
        )

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

        nodes = [item for item in resources if isinstance(item, dict) and item.get("kind") == "Node"]
        node_capacity = [
            {"name": node.get("name"), "allocatableCpu": node.get("allocatableCpu"),
             "allocatableMemory": node.get("allocatableMemory"),
             "unschedulable": node.get("unschedulable"),
             "taintCount": node.get("taintCount"),
             "nodeLabels": node.get("nodeLabels"),
             "nodeTaints": node.get("nodeTaints")}
            for node in nodes
            if node.get("allocatableCpu") and node.get("allocatableMemory")
        ]

        metrics = existing.get("metrics") or {}
        discovered_api_versions = [
            version for key, version in (
                ("apiDiscoveryCoreV1", "v1"),
                ("apiDiscoveryAppsV1", "apps/v1"),
            ) if metrics.get(key) == 1
        ]

        # Kind-specific evidence comes only from successful read-only discovery.
        discovered_api_resources = [
            {"apiVersion": version, "kind": kind}
            for group, version, kinds in (
                ("coreV1", "v1", ("Pod", "Service", "PersistentVolumeClaim", "ConfigMap", "Secret", "ServiceAccount")),
                ("appsV1", "apps/v1", ("Deployment", "StatefulSet", "DaemonSet")),
            )
            for kind in kinds
            if metrics.get(f"apiKind_{group}_{kind}") == 1
        ]

        storage_classes = sorted({item["name"] for item in resources if isinstance(item, dict) and item.get("kind") == "StorageClass" and isinstance(item.get("name"), str)})
        csi_drivers = sorted({item["name"] for item in resources if isinstance(item, dict) and item.get("kind") == "CSIDriver" and isinstance(item.get("name"), str)})
        storage_class_details = [{"name": item["name"], "provisioner": item.get("provisioner"), "volumeBindingMode": item.get("volumeBindingMode"), "reclaimPolicy": item.get("reclaimPolicy")} for item in resources if isinstance(item, dict) and item.get("kind") == "StorageClass" and isinstance(item.get("name"), str)]

        storage_discovery_states = {
            kind: ("AVAILABLE" if metrics.get(key) == 1 else
                   "PERMISSION_DENIED" if metrics.get(key) == 2 else
                   "UNAVAILABLE" if metrics.get(key) == 3 else "NOT_REPORTED")
            for kind, key in (
                ("StorageClass", "storageClassDiscoveryStatus"),
                ("CSIDriver", "csiDriverDiscoveryStatus"),
            )
        }
        supplementary_discovery = {
            kind: ("AVAILABLE" if metrics.get(f"discoveryStatus_{kind}") == 1 else
                   "PERMISSION_DENIED" if metrics.get(f"discoveryStatus_{kind}") == 2 else
                   "UNAVAILABLE" if metrics.get(f"discoveryStatus_{kind}") == 3 else "NOT_REPORTED")
            for kind in ("Ingress", "NetworkPolicy", "ServiceAccount", "Role",
                         "RoleBinding", "ClusterRole", "ClusterRoleBinding", "CustomResourceDefinition")
        }
        supplementary_inventory = {
            kind: [{"namespace": r.get("namespace"), "name": r["name"]}
                   for r in resources if isinstance(r, dict)
                   and r.get("kind") == kind and isinstance(r.get("name"), str)]
            for kind in supplementary_discovery
        }

        storage_discovery_reason = (
            "Storage API discovery was denied by Kubernetes RBAC; grant the connector read-only list access to the reported resource kinds."
            if "PERMISSION_DENIED" in storage_discovery_states.values() else
            "Storage discovery was unavailable; check connector Kubernetes API responses."
            if "UNAVAILABLE" in storage_discovery_states.values() else
            "StorageClass and CSI discovery completed; no matching resources were reported."
            if all(v == "AVAILABLE" for v in storage_discovery_states.values()) and not (storage_classes or csi_drivers) else
            "StorageClass/CSI inventory is incomplete or predates discovery support."
        )

        from .target_inventory_evidence import build_target_inventory_evidence
        target_collection = build_target_inventory_evidence(resources, metrics)
        snapshot = {
            "collectionGaps": target_collection["collectionGaps"],
            "collectionLimitations": target_collection["collectionLimitations"],
            "storageDiscovery": storage_discovery_states,
            "supplementaryDiscovery": supplementary_discovery,
            "supplementaryInventory": supplementary_inventory,
            "storageClasses": storage_classes,
            "storageClassDetails": storage_class_details,
            "csiDrivers": csi_drivers,
            "discoveredApiVersions": discovered_api_versions,
            "discoveredApiResources": discovered_api_resources,
            "nodeCapacity": node_capacity,
            "nodeCapacityCoverage": {"observedNodes": len(nodes), "nodesWithCapacity": len(node_capacity)},
            "resourceKinds": dict(sorted(resource_kinds.items())),
            "unclassifiedResourceCount": unclassified,
            "capabilityEvidence": {
                "kubernetesApi": {"status": "PARTIAL" if discovered_api_versions else "NOT_VERIFIED", "observedApiVersions": discovered_api_versions, "reason": "Core API version discovery observed; source resource API compatibility, deprecations, CRDs and admission are not yet evaluated." if discovered_api_versions else "No supported target API versions were verified from connector discovery endpoints."},
                "compute": {"status": "PARTIAL", "observedNodeCount": resource_kinds.get("Node", 0), "reason": "Node capacity observations are available for some nodes; pod requests, current utilization, quotas, affinity and taints are not yet compared." if node_capacity else "Node objects observed; allocatable resources, quota and scheduling constraints were not verified."} if resource_kinds.get("Node", 0) else {"status": "NOT_VERIFIED", "reason": "No usable node capacity evidence was provided."},
                "storage": {"status": "PARTIAL" if storage_classes or csi_drivers else "NOT_VERIFIED", "observedStorageClassCount": len(storage_classes), "observedCSIDriverCount": len(csi_drivers), "reason": "StorageClass and CSI driver names observed; provisioning, access modes, topology, snapshots and PVC migration compatibility are not verified." if storage_classes or csi_drivers else storage_discovery_reason},
                "networking": {"status": "PARTIAL", "observedServiceCount": resource_kinds.get("Service", 0), "reason": "Service objects observed; ingress, DNS, routing and network policy compatibility unverified."} if resource_kinds.get("Service", 0) else {"status": "NOT_VERIFIED", "reason": "Target routing and service capabilities are not verified."},
                "identity": {"status": "NOT_VERIFIED", "reason": "Workload identity permissions and secret/image access have not been evaluated."},
                "dependencies": {"status": "PARTIAL" if supplementary_discovery.get("CustomResourceDefinition") == "AVAILABLE" else "NOT_VERIFIED", "observedCRDCount": len(supplementary_inventory.get("CustomResourceDefinition", [])), "reason": "CRD inventory observed, but operators, admission and external dependencies remain unverified." if supplementary_discovery.get("CustomResourceDefinition") == "AVAILABLE" else "Installed operators, CRDs and external dependencies have not been verified."},
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

        # Never allow evidence from a previous target or assessment to influence
        # the current compatibility decision.
        configured_target = (migration.get("target_configuration") or {}).get("clusterId")
        target_matches = bool(
            target and target.get("targetClusterId") == configured_target
            and target.get("assessmentVersion") == assessment.get("assessmentVersion")
        )
        if not target_matches:
            target = None
        draft = migration.get("planning_draft") or {}
        findings = assessment.get("findings") or []
        if draft.get("workflow") == "SOURCE_FIRST":
            if draft.get("inventoryDigest") != assessment.get("inventoryDigest") or draft.get("assessmentVersion") != assessment.get("assessmentVersion"):
                raise ApiError(409, "PLANNING_EVIDENCE_CHANGED", "Save the current source scope before comparing a target.")
            selected_findings = {(r.get("kind"), r.get("namespace"), r.get("name")) for r in draft.get("resources", []) if r.get("treatment") != "RETIRE"}
            # Old assessments can contain findings against a previously chosen
            # target. Destination checks now come from fresh target evidence.
            findings = [f for f in findings if isinstance(f, dict)
                        and not str(f.get("code", "")).startswith("TARGET_")
                        and (not f.get("resourceName") or
                             (f.get("resourceKind"), f.get("namespace"), f.get("resourceName")) in selected_findings)]
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
            expires_raw = snapshot.get("inventoryExpiresAt") or snapshot.get("expiresAt")
            try:
                expires = datetime.fromisoformat(expires_raw.replace("Z", "+00:00")) if isinstance(expires_raw, str) else None
                current = expires is not None and expires.tzinfo is not None and expires > datetime.now(timezone.utc)
            except ValueError:
                current = False
            complete = current and bool(snapshot.get("coverageComplete")) and not (snapshot.get("unverified") or [])
            if not current:
                path = "PENDING_EVIDENCE"
                reason = "Target connector evidence has expired or has no trustworthy expiry timestamp."
            elif not complete:
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
        # A source inventory identifies workloads, but does not necessarily
        # contain Kubernetes PodSpec resource requests. Keep those pending.
        from .scheduling_evidence import evaluate_node_capacity, workload_pod_requests, scheduling_constraints
        source_inventory = self.repo.get_source_inventory(identifier).get("inventory")
        source_resources = (source_inventory or {}).get("resources") or []
        draft = migration.get("planning_draft") or {}
        selected = {
            (r.get("apiVersion"), r.get("kind"), r.get("namespace"), r.get("name"))
            for r in (draft.get("resources") or [])
            if isinstance(r, dict) and (r.get("treatment") == "MIGRATE" or (draft.get("workflow") == "SOURCE_FIRST" and r.get("treatment") != "RETIRE"))
        }
        observations = []
        nodes = snapshot.get("nodeCapacity") or []
        coverage = snapshot.get("nodeCapacityCoverage") or {}
        observed_nodes = coverage.get("observedNodes")
        expires_raw = snapshot.get("inventoryExpiresAt") or snapshot.get("expiresAt")
        try:
            evidence_expiry = datetime.fromisoformat(expires_raw.replace("Z", "+00:00")) if isinstance(expires_raw, str) else None
            fresh_nodes = evidence_expiry is not None and evidence_expiry.tzinfo is not None and evidence_expiry > datetime.now(timezone.utc)
        except ValueError:
            fresh_nodes = False
        complete_nodes = fresh_nodes and bool(nodes) and observed_nodes == len(nodes)
        for resource in source_resources:
            if not isinstance(resource, dict):
                continue
            identity = (resource.get("apiVersion"), resource.get("kind"),
                        resource.get("namespace"), resource.get("name"))
            if identity not in selected or resource.get("kind") not in {"Deployment", "StatefulSet", "DaemonSet", "Pod", "Job", "CronJob"}:
                continue
            # Only consume explicit, already-observed aggregate requests.
            # Do not infer pod requests from replicas, limits or node sizes.
            requests = workload_pod_requests(resource) or {}
            constraints = scheduling_constraints(resource)
            result = evaluate_node_capacity(
                requests.get("cpu"), requests.get("memory"), nodes,
                inventory_complete=complete_nodes and not constraints,
            )
            if constraints:
                result["status"] = "PENDING_EVIDENCE"
                result["reason"] = " ".join(constraints) + " " + result["reason"]
                result["missingEvidence"] = constraints
            from .scheduling_evidence import evaluate_node_selector
            selector = evaluate_node_selector(resource, nodes, inventory_complete=complete_nodes)
            if selector["status"] == "REMEDIATION_REQUIRED":
                result["status"] = "REMEDIATION_REQUIRED"
                result["reason"] = selector["reason"]
            result["nodeSelectorEvidence"] = selector
            from .scheduling_evidence import evaluate_node_tolerations
            taints = evaluate_node_tolerations(resource, nodes, inventory_complete=complete_nodes)
            if taints["status"] == "REMEDIATION_REQUIRED":
                result["status"] = "REMEDIATION_REQUIRED"
                result["reason"] = taints["reason"]
            result["taintTolerationEvidence"] = taints
            observations.append({
                "apiVersion": resource.get("apiVersion"),
                "kind": resource.get("kind"),
                "namespace": resource.get("namespace"),
                "name": resource.get("name"),
                **result,
            })
        from .storage_evidence import compare_storage_claims
        storage_observations = compare_storage_claims(
            source_resources, selected, snapshot.get("storageClasses"),
            fresh=fresh_nodes,
            class_details=snapshot.get("storageClassDetails"),
            csi_drivers=snapshot.get("csiDrivers"),
            mappings=draft.get("storageMappings") or [],
        )
        from .api_evidence import evaluate_api_versions
        api_observations = evaluate_api_versions(
            source_resources, selected, snapshot.get("discoveredApiVersions"),
            fresh=fresh_nodes,
            observed_resources=snapshot.get("discoveredApiResources"),
        )
        from .dependency_evidence import discover_dependencies
        dependency_evidence = discover_dependencies(source_resources, selected)
        from .discovery_coverage import build_discovery_coverage
        discovery_coverage = build_discovery_coverage(
            source_inventory, draft, target,
        )
        from .resource_compatibility import evaluate_selected_resources
        resource_evaluations = evaluate_selected_resources(
            source_resources, draft.get("resources") or [],
            findings, api_observations, storage_observations, observations,
            target_current=fresh_nodes,
        )
        from .assessment_report import build_workload_assessment_report
        workload_report = build_workload_assessment_report(
            draft, resource_evaluations, dependency_evidence,
            (target or {}).get("targetClusterId") or
            (migration.get("target_configuration") or {}).get("clusterId"),
        )
        return {
            "workloadAssessmentReport": workload_report,
            "resourceEvaluations": resource_evaluations,
            "dependencyEvidence": dependency_evidence,
            "discoveryCoverage": discovery_coverage,
            "apiEvidence": {
                "status": "PARTIAL" if api_observations and all(
                    item["status"] == "PARTIAL" for item in api_observations
                ) else "PENDING_EVIDENCE",
                "resources": api_observations,
                "reason": "API group/version discovery does not verify resource kinds, CRDs, admission or deprecated fields.",
            },
            "storageEvidence": {
                "status": "PARTIAL" if storage_observations and all(
                    item["status"] == "PARTIAL" for item in storage_observations
                ) else "PENDING_EVIDENCE",
                "claims": storage_observations,
                "reason": "StorageClass name matching does not certify CSI functionality, access modes or volume migration.",
            },
            "schedulingEvidence": {
                "status": "PARTIAL" if observations and all(item["status"] == "PARTIAL" for item in observations) else "PENDING_EVIDENCE",
                "workloads": observations,
                "reason": "Node allocatable capacity is not available headroom; resource requests, tolerations, affinity, utilization and quotas must be verified before migration approval.",
            },
            "migrationId": identifier,
            "assessmentVersion": assessment.get("assessmentVersion"),
            "targetClusterId": (target or {}).get("targetClusterId")
            or (migration.get("target_configuration") or {}).get("clusterId"),
            "evidenceLevel": (target or {}).get("evidenceLevel"),
            "coverageComplete": (bool(snapshot.get("coverageComplete")) and not (snapshot.get("unverified") or []) and
                                 bool(snapshot.get("inventoryExpiresAt") or snapshot.get("expiresAt")) and
                                 path in {"DIRECT", "ASSISTED"}),
            "decision": {"path": path, "reason": reason},
        }

    def create(self, body):
        self.access.require("migration.create")
        self.access.require_customer(body["customerId"])
        self.repo.require_customer_visible(body["customerId"])

        target = body.get("target")
        if body["source"].get("discoveryMode") == "MANUAL" and os.environ.get("MIGRATION_SOURCE_FIRST_ENABLED") != "true":
            raise ApiError(400, "SOURCE_FIRST_DISABLED", "The source-first workflow is not enabled on this instance.")
        if not target:
            if os.environ.get("MIGRATION_SOURCE_FIRST_ENABLED") != "true":
                raise ApiError(400, "TARGET_REQUIRED", "Select the target environment first.")
            body["source"]["discoveryMode"] = "MANUAL"
            source_id = body["source"].get("sourceClusterId")
            if not source_id:
                raise ApiError(400, "SOURCE_CLUSTER_REQUIRED", "Register or select a source cluster first.")
            source = self.repo.get_source_cluster(source_id)
            if source["customer_id"] != body["customerId"] or source["status"] == "REVOKED":
                raise ApiError(409, "SOURCE_CLUSTER_UNAVAILABLE", "Select an available source cluster belonging to this customer.")

        row = {
            "migration_id": "MIG-" + uuid.uuid4().hex,
            "customer_id": body["customerId"],
            "name": body["name"],
            "description": body.get("description"),
            "source_platform": body["source"]["platform"],
            # P0 destination family only; an empty configuration means no
            # target environment or cluster has been selected yet.
            "target_platform": target["platform"] if target else "EKS",
            "source_configuration": body["source"],
            "target_configuration": target or {},
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
        if row["delivery_method"] == "AWS_SSM":
            self.repo.lock_source_installation(row)
            existing = self.repo.find_source_registration(row)
            if existing:
                self.repo.audit_source_cluster(existing["source_cluster_id"], "SOURCE_CLUSTER_REUSED",
                                               self.correlation, {"reason": "Reuse customer source installation"})
                return serialize(existing)
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

    def source_installation_check(self, source):
        result = {
            "canRestore": False,
            "code": "UNAVAILABLE",
            "message": "Recovery is unavailable.",
            "conflicts": [],
        }
        try:
            self.access.require("migration.edit")
            self.access.require_customer(source["customer_id"], source["created_by"])
        except ApiError:
            return {**result, "code": "FORBIDDEN", "message": "Recovery requires edit access to this customer."}
        if source["status"] == "REVOKED":
            return {**result, "code": "REVOKED", "message": "This registration has been revoked."}
        config = source.get("delivery_configuration") or {}
        if (
            source.get("delivery_method") != "AWS_SSM"
            or source.get("location_type") != "CLOUD"
            or source.get("cloud_provider") != "AWS"
            or not all(config.get(key) for key in ("accountId", "region", "managedInstanceId"))
        ):
            return {
                **result,
                "code": "DELIVERY_UNAVAILABLE",
                "message": "Automatic recovery requires the saved AWS Systems Manager host configuration.",
            }
        seen = source.get("connector_last_seen_at")
        if isinstance(seen, str):
            try:
                seen = datetime.fromisoformat(seen.replace("Z", "+00:00"))
            except ValueError:
                seen = None
        if seen and -30 <= (datetime.now(timezone.utc) - seen).total_seconds() < 120:
            return {
                **result,
                "code": "ALREADY_CONNECTED",
                "message": "This registration already has a recent connector heartbeat.",
            }
        # Installation resources are keyed by source registration. Other
        # customers/environments on this host are never overwritten or revoked.
        return {
            "canRestore": True,
            "code": "SOURCE_SCOPED_INSTALL_AVAILABLE",
            "conflicts": [],
            "message": "This registration uses its own connector deployment and credentials. Existing source connections will not be replaced.",
        }

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

        if source_cluster.get("delivery_method") == "AWS_SSM":
            self.repo.lock_source_installation(source_cluster)
            check = self.source_installation_check(source_cluster)
            if not check["canRestore"]:
                raise ApiError(409, check["code"], check["message"])

        if body.get("recoveryMigrationId"):
            migration = self.repo.get(body["recoveryMigrationId"], lock=True)
            self.access.require_customer(migration["customer_id"], migration["created_by"])
            if (migration["customer_id"] != source_cluster["customer_id"]
                    or migration["source_configuration"].get("sourceClusterId") != identifier):
                raise ApiError(409, "SOURCE_RECOVERY_CONTEXT_CHANGED", "The assessment source association changed. Reload before recovery.")
            if migration["status"] not in {"DRAFT", "SOURCE_ENROLLMENT_PENDING", "DISCOVERY_PENDING"}:
                raise ApiError(409, "SOURCE_RECOVERY_NOT_PENDING", "This assessment is not waiting for a source connector.")
            check = self.source_installation_check(source_cluster)
            if not check["canRestore"]:
                raise ApiError(409, check["code"], check["message"])

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
                **({"recoveryMigrationId": body["recoveryMigrationId"]} if body.get("recoveryMigrationId") else {}),
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

        if (os.environ.get("MIGRATION_SOURCE_FIRST_ENABLED") == "true"
                and "target" in body and current["status"] in {"ASSESSMENT_READY", "REJECTED"}):
            return self.select_planning_target(identifier, current, body)

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

    def select_planning_target(self, identifier, current, body):
        if set(body) - {"version", "target", "changeReason"}:
            raise ApiError(400, "TARGET_SELECTION_ONLY", "Save target selection separately from source scope.")
        draft = current.get("planning_draft") or {}
        if draft.get("workflow") != "SOURCE_FIRST" or not any(
            r.get("kind") in {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob", "Pod", "DeploymentConfig"}
            and not r.get("dependency") and r.get("treatment") != "RETIRE" for r in draft.get("resources", [])
        ):
            raise ApiError(409, "SOURCE_SCOPE_REQUIRED", "Save selected application workloads before choosing a target.")
        assessment = self.repo.get_assessment(identifier).get("assessment")
        if not assessment or draft.get("inventoryDigest") != assessment.get("inventoryDigest") or draft.get("assessmentVersion") != assessment.get("assessmentVersion"):
            raise ApiError(409, "PLANNING_EVIDENCE_CHANGED", "Refresh the source assessment and save its scope again.")
        self.repo.require_planning_configuration(identifier, assessment["migrationVersion"], current, source_only=True)
        from navigan.modules.cluster_management.repository import Repository as ClusterRepository
        target = body["target"]
        registered = ClusterRepository(self.repo.db, self.principal).get(target.get("clusterId") or "")
        self.access.require_customer(registered["customer_id"], registered["created_by"])
        if (target.get("targetType") != "EXISTING_CLUSTER" or registered["customer_id"] != current["customer_id"]
                or registered["cluster_name"] != target.get("clusterName") or registered["platform"] != target["platform"]
                or registered["environment_id"] != target["environmentId"]
                or registered["environment_approved_version"] != target["environmentApprovedVersion"]
                or registered["status"] != "ACTIVE"
                or (registered.get("workflow") or {}).get("ownershipStatus") == "ARCHIVED"):
            raise ApiError(409, "TARGET_IDENTITY_MISMATCH", "Choose an active Navigan-managed cluster in this customer's approved environment.")
        row = copy.deepcopy(current)
        row["target_configuration"] = target
        row["target_platform"] = target["platform"]
        row["version"] += 1
        row["updated_by"] = self.principal.user_id
        row["change_reason"] = body["changeReason"]
        self.repo.save(row, current, "MIGRATION_TARGET_SELECTED", self.correlation)
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
        # Namespace selections are planning-draft state, not an edit to the
        # original Source Assessment. Reject unexpected scope expansion.
        saved_namespaces = draft.get("selectedNamespaces")
        if saved_namespaces is not None:
            assessed_namespaces = set(current.get("migration_scope", {}).get("namespaces", []))
            if not set(saved_namespaces).issubset(assessed_namespaces):
                raise ApiError(
                    400, "NAMESPACE_OUTSIDE_ASSESSMENT",
                    "Selected planning namespaces must belong to the assessed source scope.",
                )
        available = {
            (r["apiVersion"], r["kind"], r.get("namespace"), r.get("name")) for r in inventory["resources"]
        }
        if draft.get("workflow") == "SOURCE_FIRST":
            if os.environ.get("MIGRATION_SOURCE_FIRST_ENABLED") != "true":
                raise ApiError(400, "SOURCE_FIRST_DISABLED", "The source-first workflow is not enabled on this instance.")
            self.repo.require_planning_configuration(identifier, assessment["migrationVersion"], current, source_only=True)
        else:
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

        delete_assessment = body.get("deleteAssessment", False)
        if delete_assessment and action != "cancel":
            raise ApiError(400, "INVALID_DELETE_ACTION", "Use the assessment cancellation endpoint to delete an assessment.")

        if not delete_assessment and current["status"] not in allowed:
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

        if (
            action == "submit"
            and current["source_configuration"].get("discoveryMode") == "MANUAL"
            and not current["target_configuration"].get("clusterId")
        ):
            raise ApiError(
                409,
                "TARGET_SELECTION_REQUIRED",
                "Complete source scope and target compatibility before submitting for migration review.",
            )

        connector = None
        if action in {"discover", "assess"}:
            if os.environ.get("MIGRATION_SOURCE_FIRST_ENABLED") == "true" and current["source_configuration"].get("sourceClusterId"):
                from .source_authentication import ready
                source = self.repo.get_source_cluster(current["source_configuration"]["sourceClusterId"])
                delivery = source.get("delivery_configuration") or {}
                if not ready(delivery.get("deploymentDiscovery", {}), delivery.get("deploymentAuthentication", {})):
                    raise ApiError(409, "SOURCE_CONNECTIONS_REQUIRED", "Configure and verify source repositories and registries, or explicitly choose inventory-only discovery.")
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
            "MIGRATION_DELETED" if delete_assessment else "MIGRATION_" + action.upper(),
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

