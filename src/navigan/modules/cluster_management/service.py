import copy
import re
import hashlib
import os
import secrets
import uuid
from datetime import datetime, timezone
from navigan.shared.errors import ApiError
from .repository import serialize
from .provisioning import Provisioner
from .github_app import GitHubApp


TRANSITIONS = {
    "submit": ({"DRAFT", "REJECTED"}, "SUBMITTED", "CLOUD_ENGINEER"),
    "review": ({"SUBMITTED"}, "UNDER_REVIEW", "PLATFORM_ARCHITECT"),
    "approve": ({"SUBMITTED", "UNDER_REVIEW"}, "APPROVED", "PLATFORM_ARCHITECT"),
    "reject": ({"SUBMITTED", "UNDER_REVIEW"}, "REJECTED", "PLATFORM_ARCHITECT"),
}


class Service:
    def __init__(self, repo, correlation, provisioner=None):
        self.repo, self.principal, self.correlation = repo, repo.principal, correlation
        self.provisioner = provisioner

    def reconcile_active_application_node_groups(self, cluster):
        configuration = copy.deepcopy(cluster["configuration"])
        groups = [
            item
            for item in configuration.get("nodeGroups", [])
            if isinstance(item, dict)
        ]
        names = {item.get("name") for item in groups}
        for node_group in self.repo.active_application_node_groups(
            cluster["cluster_id"]
        ):
            if node_group.get("name") not in names:
                groups.append(copy.deepcopy(node_group))
                names.add(node_group.get("name"))
        configuration["nodeGroups"] = groups
        cluster["configuration"] = configuration
        return cluster

    def create(self, body):
        self.principal.require("CLOUD_ENGINEER")
        environment, snapshot = self.repo.active_environment_snapshot(
            body["environmentId"], body.get("environmentApprovedVersion")
        )
        approved = environment["approved_version"]
        account_id = str(((snapshot or {}).get("configuration") or {}).get("account", {}).get("accountId", ""))
        if f"::{account_id}:role/" not in body["provisioningRoleArn"]:
            raise ApiError(
                422,
                "PROVISIONING_ROLE_ACCOUNT_MISMATCH",
                "The provisioning role must belong to the approved environment AWS account.",
            )
        if f":{account_id}:secret:" not in body["externalIdSecretArn"]:
            raise ApiError(
                422,
                "PROVISIONING_SECRET_ACCOUNT_MISMATCH",
                "The provisioning secret must belong to the approved environment AWS account.",
            )
        baseline = (snapshot or {}).get("configuration") or {}
        approved_blueprints = [
            item
            for item in baseline.get("clusters", [])
            if isinstance(item, dict)
        ]
        default_blueprints = [
            item
            for item in approved_blueprints
            if item.get("isDefault") is True
            or str(item.get("name", "")).lower() == "default"
        ]
        contract = (
            baseline.get("extensions", {}).get("provisioningContract", {})
            if isinstance(baseline.get("extensions"), dict)
            else {}
        )
        if len(default_blueprints) > 1 or (
            len(approved_blueprints) > 1 and not default_blueprints
        ):
            raise ApiError(
                422,
                "DEFAULT_CLUSTER_BLUEPRINT_AMBIGUOUS",
                "The approved environment must identify exactly one default cluster blueprint.",
            )
        blueprint = (
            default_blueprints[0]
            if default_blueprints
            else approved_blueprints[0]
            if len(approved_blueprints) == 1
            else None
        )
        expected_blueprint_name = (
            blueprint.get("name") if blueprint else "environment-default"
        )
        if body["blueprintName"] != expected_blueprint_name:
            raise ApiError(
                422,
                "CLUSTER_BLUEPRINT_NOT_APPROVED",
                "The approved cluster configuration changed. Reload the request and try again.",
            )
        using_environment_default = blueprint is None
        if blueprint is None:
            blueprint = {
                "name": "environment-default",
                "endpointAccess": "PRIVATE",
                "nodeGroups": body["nodeGroups"],
            }
        contract_versions = contract.get("kubernetesVersions", [])
        allowed_versions = {
            value
            for value in (
                contract_versions
                if isinstance(contract_versions, list)
                else []
            )
            if isinstance(value, str)
        }
        if not allowed_versions and isinstance(blueprint.get("kubernetesVersion"), str):
            allowed_versions.add(blueprint["kubernetesVersion"])
        if body["kubernetesVersion"] not in allowed_versions:
            raise ApiError(
                422,
                "KUBERNETES_VERSION_NOT_APPROVED",
                "Select a Kubernetes version from the approved environment contract.",
            )
        blueprint_endpoint_access = blueprint.get("endpointAccess", "PRIVATE")
        allowed_endpoint_access = {"PRIVATE"}
        if blueprint_endpoint_access == "PUBLIC_AND_PRIVATE":
            allowed_endpoint_access.add("PUBLIC_AND_PRIVATE")
        if body["endpointAccess"] not in allowed_endpoint_access:
            raise ApiError(
                422,
                "ENDPOINT_ACCESS_NOT_APPROVED",
                "The selected endpoint access is not permitted by this approved blueprint.",
            )
        blueprint_groups = blueprint.get("nodeGroups") or []
        if len(blueprint_groups) != 1:
            raise ApiError(
                422,
                "SYSTEM_NODE_GROUP_REQUIRED",
                "The approved cluster blueprint must define exactly one initial system node group.",
            )
        system_group = {
            **blueprint_groups[0],
            "purpose": "SYSTEM",
            "capacityType": "ON_DEMAND",
        }
        if using_environment_default:
            approved_instance_types = {
                (
                    item
                    if isinstance(item, str)
                    else item.get("instanceType")
                    if isinstance(item, dict)
                    else None
                )
                for item in contract.get("instanceTypes", [])
            }
            approved_instance_types.discard(None)
            if not approved_instance_types:
                raise ApiError(
                    422,
                    "ENVIRONMENT_CAPACITY_CATALOG_MISSING",
                    "The approved environment has no instance-type catalogue for cluster creation.",
                )
            if not set(system_group.get("instanceTypes", [])).issubset(
                approved_instance_types
            ):
                raise ApiError(
                    422,
                    "INSTANCE_TYPE_NOT_APPROVED",
                    "Select system capacity from the approved environment catalogue.",
                )
        if system_group.get("minSize", 0) < 2 or system_group.get("desiredSize", 0) < 2:
            raise ApiError(
                422,
                "SYSTEM_NODE_GROUP_CAPACITY_REQUIRED",
                "The approved system node group must keep at least two nodes ready.",
            )
        if any(
            instance_type.endswith((".nano", ".micro"))
            for instance_type in system_group.get("instanceTypes", [])
        ):
            raise ApiError(
                422,
                "SYSTEM_NODE_GROUP_INSTANCE_TYPE_UNSUPPORTED",
                "The EKS system node group cannot use nano or micro instance types.",
            )
        customer_slug = self._repository_slug(environment.get("customer_name") or environment["customer_id"])
        cluster_slug = self._repository_slug(body["clusterName"])
        repository_name = f"{customer_slug}-{cluster_slug}-system"[:100].rstrip("-")
        github_organization = body["githubOrganization"].lower()
        connection = self.repo.active_github_connection(
            environment["customer_id"], github_organization
        )
        configuration = {
            "blueprintName": body["blueprintName"],
            "kubernetesVersion": body["kubernetesVersion"],
            "endpointAccess": body["endpointAccess"],
            "nodeGroups": [system_group],
            "platformBaseline": {
                "status": "PENDING",
                "installationMode": "AUTOMATIC",
                "readinessContract": "PLATFORM_COMPONENTS_V1",
                "components": [
                    "navigan-connector",
                    "argocd",
                    "falco",
                    "prometheus",
                    "grafana",
                    "headlamp",
                ],
                "repository": {
                    "strategy": "PER_CLUSTER",
                    "provider": "GITHUB",
                    "organization": github_organization,
                    "name": repository_name,
                    "revisionPolicy": "SIGNED_IMMUTABLE",
                    "connectionStatus": "ACTIVE" if connection else "AUTHORIZATION_REQUIRED",
                    **(
                        {"connectionId": connection["connection_id"]}
                        if connection
                        else {}
                    ),
                },
                "artifactPolicy": {
                    "approvedRegistryRequired": True,
                    "immutableDigestRequired": True,
                },
            },
            "tags": body.get("tags", {}),
        }
        now = datetime.now(timezone.utc)
        row = {
            "cluster_id": "CLU-" + uuid.uuid4().hex,
            "customer_id": environment["customer_id"],
            "environment_id": environment["environment_id"],
            "environment_approved_version": approved,
            "platform": "EKS",
            "cluster_name": body["clusterName"],
            "description": body.get("description"),
            "configuration": configuration,
            "provisioning_role_arn": body["provisioningRoleArn"],
            "external_id_secret_arn": body["externalIdSecretArn"],
            "terraform_module_version": "1.0.0",
            "terraform_state_key": (
                f"customers/{environment['customer_id']}/environments/"
                f"{environment['environment_id']}/clusters/{body['clusterName']}/terraform.tfstate"
            ),
            "status": "DRAFT", "version": 1, "plan_artifact_key": None,
            "plan_sha256": None, "provider_execution_id": None,
            "execution_artifact_prefix": None, "outputs": {}, "workflow": {},
            "created_by": self.principal.user_id, "created_at": now,
            "updated_by": self.principal.user_id, "updated_at": now,
        }
        self.repo.save(row, create=True)
        self.repo.create_system_repository(
            row["cluster_id"],
            row["customer_id"],
            github_organization,
            repository_name,
        )
        self.repo.record(None, row, "ClusterCreated", body, self.correlation)
        return serialize(row)

    @staticmethod
    def _repository_slug(value):
        slug = re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")
        return slug or "cluster"

    def begin_github_authorization(self, identifier, body):
        cluster = self.repo.get(identifier, lock=True)
        if cluster["version"] != body["version"]:
            raise ApiError(409, "CONCURRENT_UPDATE", "Reload the latest cluster request.")
        if cluster["status"] not in {"SUBMITTED", "UNDER_REVIEW", "APPROVED"}:
            raise ApiError(
                409,
                "GITHUB_AUTHORIZATION_NOT_AVAILABLE",
                "GitHub organization authorization is available for a submitted or approved request.",
            )
        app_slug = os.environ.get("GITHUB_APP_SLUG", "").strip()
        if not app_slug:
            raise ApiError(
                503,
                "GITHUB_APP_NOT_CONFIGURED",
                "The platform GitHub App is not configured.",
            )
        state = secrets.token_urlsafe(32)
        details = self.repo.begin_github_authorization(
            cluster, hashlib.sha256(state.encode()).hexdigest()
        )
        return {
            **details,
            "status": "AUTHORIZATION_REQUIRED",
            "authorizationUrl": (
                f"https://github.com/apps/{app_slug}/installations/new"
                f"?state={state}"
            ),
            "state": state,
            "expiresInSeconds": 900,
        }

    def complete_github_authorization(self, identifier, body, github_app=None):
        cluster = self.repo.get(identifier, lock=True)
        if cluster["version"] != body["version"]:
            raise ApiError(409, "CONCURRENT_UPDATE", "Reload the latest cluster request.")
        expected_organization = cluster["configuration"]["platformBaseline"][
            "repository"
        ]["organization"]
        installation = (github_app or GitHubApp()).installation(
            body["installationId"]
        )
        account = installation.get("account") or {}
        if (
            installation.get("target_type") != "Organization"
            or str(account.get("login", "")).lower()
            != str(expected_organization).lower()
        ):
            raise ApiError(
                422,
                "GITHUB_ORGANIZATION_MISMATCH",
                "The GitHub App must be installed on the organization selected in this cluster request.",
            )
        permissions = installation.get("permissions") or {}
        if (
            permissions.get("administration") != "write"
            or permissions.get("contents") != "write"
        ):
            raise ApiError(
                422,
                "GITHUB_APP_PERMISSIONS_INSUFFICIENT",
                "The GitHub App installation must allow repository administration and contents write access.",
            )
        value = self.repo.complete_github_authorization(
            cluster,
            hashlib.sha256(body["state"].encode()).hexdigest(),
            body["installationId"],
            permissions,
        )
        old = copy.deepcopy(cluster)
        repository = cluster["configuration"]["platformBaseline"]["repository"]
        repository.update(
            {
                "connectionId": value["connectionId"],
                "connectionStatus": "ACTIVE",
            }
        )
        system_repository = self.repo.system_repository(identifier, lock=True)
        github_repository = (github_app or GitHubApp()).ensure_private_repository(
            body["installationId"],
            value["organization"],
            system_repository["repository_name"],
        )
        self.repo.mark_system_repository_active(identifier, github_repository)
        repository.update(
            {
                "status": "ACTIVE",
                "url": github_repository["html_url"],
            }
        )
        if cluster["status"] == "APPROVED":
            _, snapshot = self.repo.active_environment_snapshot(
                cluster["environment_id"], cluster["environment_approved_version"]
            )
            build_id, prefix = (self.provisioner or Provisioner()).start(
                "plan", cluster, snapshot
            )
            cluster["provider_execution_id"] = build_id
            cluster["execution_artifact_prefix"] = prefix
            cluster["plan_artifact_key"] = prefix + "/terraform.tfplan"
            cluster["plan_sha256"] = None
            cluster["status"] = "PLAN_RUNNING"
        cluster["version"] += 1
        cluster["updated_by"] = self.principal.user_id
        cluster["updated_at"] = datetime.now(timezone.utc)
        self.repo.save(cluster)
        self.repo.record(
            old,
            cluster,
            "ClusterGitHubOrganizationAuthorized",
            {"installationId": value["installationId"]},
            self.correlation,
        )
        return {**value, "clusterVersion": cluster["version"]}

    def change(self, identifier, action, body):
        row = self.repo.get(identifier, lock=True)
        if row["version"] != body["version"]:
            raise ApiError(409, "CONCURRENT_UPDATE", "Reload the latest cluster request.")
        old = copy.deepcopy(row)
        if action == "update":
            self.principal.require("CLOUD_ENGINEER")
            if row["status"] not in {"DRAFT", "REJECTED"}:
                raise ApiError(409, "INVALID_STATUS_TRANSITION", "Only draft or rejected requests can be edited.")
            if body.get("clusterName") is not None:
                row["cluster_name"] = body["clusterName"]
            if body.get("description") is not None:
                row["description"] = body["description"]
        elif action in TRANSITIONS:
            states, target, role = TRANSITIONS[action]
            self.principal.require(role)
            if row["status"] not in states:
                raise ApiError(409, "INVALID_STATUS_TRANSITION", "Action is not allowed in the current status.")
            submitted = row.get("workflow", {}).get("submitted", {}).get("by")
            if action in {"review", "approve", "reject"} and self.principal.user_id in {
                row["created_by"], submitted,
            }:
                raise ApiError(403, "INDEPENDENT_REVIEW_REQUIRED", "The request author cannot review it.")
            if action == "reject" and not body.get("reason"):
                raise ApiError(422, "REASON_REQUIRED", "Provide a rejection reason.")
            self.repo.active_environment_snapshot(
                row["environment_id"], row["environment_approved_version"]
            )
            row["status"] = target
            field = {"submit": "submitted", "review": "reviewStarted", "approve": "approved", "reject": "rejected"}[action]
            row["workflow"][field] = {
                "by": self.principal.user_id, "at": datetime.now(timezone.utc).isoformat(),
                "reason": body.get("reason"), "comments": body.get("comments"),
            }
            # Approval is the immutable hand-off to Terraform planning.  Applying
            # infrastructure remains a separate architect action after the exact
            # plan artifact and SHA-256 digest have been reviewed.
            if action == "approve":
                repository_configuration = (
                    row.get("configuration", {})
                    .get("platformBaseline", {})
                    .get("repository", {})
                )
                organization = repository_configuration.get("organization")
                if organization:
                    connection = self.repo.active_github_connection(
                        row["customer_id"], organization
                    )
                    if connection:
                        self.repo.bind_system_repository_connection(
                            row["cluster_id"], connection["connection_id"]
                        )
                        system_repository = self.repo.system_repository(
                            row["cluster_id"], lock=True
                        )
                        github_repository = GitHubApp().ensure_private_repository(
                            connection["installation_id"],
                            organization,
                            system_repository["repository_name"],
                        )
                        self.repo.mark_system_repository_active(
                            row["cluster_id"], github_repository
                        )
                        repository_configuration.update(
                            {
                                "connectionId": connection["connection_id"],
                                "connectionStatus": "ACTIVE",
                                "status": "ACTIVE",
                                "url": github_repository["html_url"],
                            }
                        )
                    else:
                        repository_configuration["connectionStatus"] = (
                            "AUTHORIZATION_REQUIRED"
                        )
                if not organization or connection:
                    _, snapshot = self.repo.active_environment_snapshot(
                        row["environment_id"], row["environment_approved_version"]
                    )
                    build_id, prefix = (self.provisioner or Provisioner()).start(
                        "plan", row, snapshot
                    )
                    row["provider_execution_id"] = build_id
                    row["execution_artifact_prefix"] = prefix
                    row["plan_artifact_key"] = prefix + "/terraform.tfplan"
                    row["plan_sha256"] = None
                    row["status"] = "PLAN_RUNNING"
        elif action in {"plan", "apply", "stop", "start", "delete"}:
            self.principal.require("PLATFORM_ARCHITECT")
            expected = {
                "plan": {"FAILED", "PLAN_READY"},
                "apply": {"PLAN_READY"},
                "stop": {"ACTIVE"},
                "start": {"STOPPED"},
                "delete": {"ACTIVE", "STOPPED", "FAILED"},
            }[action]
            if row["status"] not in expected:
                raise ApiError(409, "INVALID_STATUS_TRANSITION", f"{action} is not allowed in the current status.")
            if action == "delete" and not body.get("reason"):
                raise ApiError(422, "REASON_REQUIRED", "Provide a deletion reason.")
            if action == "apply":
                certification = row.get("workflow", {}).get("certification", {})
                if certification.get("status") != "PASSED":
                    raise ApiError(
                        409,
                        "PLAN_NOT_CERTIFIED",
                        "Terraform validation and security checks must pass before apply.",
                    )
            _, snapshot = self.repo.pinned_environment_snapshot(
                row["environment_id"], row["environment_approved_version"]
            )
            if (
                action == "plan"
                and row["configuration"].get("systemNodeGroupMigration")
            ):
                row = self.reconcile_active_application_node_groups(row)
            build_id, prefix = (self.provisioner or Provisioner()).start(action, row, snapshot)
            row["provider_execution_id"] = build_id
            row["execution_artifact_prefix"] = prefix
            row["workflow"]["currentExecution"] = {
                "mode": action,
                "buildId": build_id,
                "startedBy": self.principal.user_id,
                "startedAt": datetime.now(timezone.utc).isoformat(),
            }
            row["status"] = {
                "plan": "PLAN_RUNNING",
                "apply": "APPLYING",
                "stop": "STOPPING",
                "start": "STARTING",
                "delete": "DELETING",
            }[action]
            if action == "plan":
                row["plan_artifact_key"] = prefix + "/terraform.tfplan"
                row["plan_sha256"] = None
        else:
            raise ApiError(404, "ACTION_NOT_FOUND", "Cluster action not found.")
        row["version"] += 1
        row["updated_by"], row["updated_at"] = self.principal.user_id, datetime.now(timezone.utc)
        self.repo.save(row)
        self.repo.record(old, row, "Cluster" + action.title(), body, self.correlation)
        return serialize(row)

    def create_node_group_request(self, cluster_id, body):
        if not self.principal.roles.intersection(
            {"CLOUD_ENGINEER", "PLATFORM_ADMINISTRATOR"}
        ):
            raise ApiError(403, "FORBIDDEN", "This operation is not permitted for your role.")
        cluster = self.repo.get(cluster_id, lock=True)
        if cluster["status"] != "ACTIVE":
            raise ApiError(
                409,
                "CLUSTER_NOT_READY",
                "Application node groups can be requested only for an active cluster.",
            )
        node_group = body["nodeGroup"]
        existing = {
            item.get("name")
            for item in cluster["configuration"].get("nodeGroups", [])
            if isinstance(item, dict)
        }
        if node_group["name"] in existing:
            raise ApiError(
                409,
                "NODE_GROUP_NAME_EXISTS",
                "A node group with this name already exists.",
            )
        now = datetime.now(timezone.utc)
        row = {
            "request_id": "KNG-" + uuid.uuid4().hex,
            "cluster_id": cluster_id,
            "customer_id": cluster["customer_id"],
            "node_group": node_group,
            "reason": body["reason"],
            "status": "DRAFT",
            "version": 1,
            "plan_artifact_key": None,
            "plan_sha256": None,
            "provider_execution_id": None,
            "execution_artifact_prefix": None,
            "workflow": {},
            "created_by": self.principal.user_id,
            "created_at": now,
            "updated_by": self.principal.user_id,
            "updated_at": now,
        }
        self.repo.save_node_group_request(row, create=True)
        self.repo.record_node_group_request(
            None, row, "ClusterNodeGroupRequestCreated", self.correlation
        )
        return serialize(row)

    def migrate_system_node_group(self, cluster_id, body):
        if not self.principal.roles.intersection(
            {"PLATFORM_ARCHITECT", "PLATFORM_ADMINISTRATOR"}
        ):
            raise ApiError(403, "FORBIDDEN", "This operation is not permitted for your role.")
        cluster = self.repo.get(cluster_id, lock=True)
        if cluster["version"] != body["version"]:
            raise ApiError(409, "CONCURRENT_UPDATE", "Reload the latest cluster request.")
        if cluster["status"] != "ACTIVE":
            raise ApiError(
                409,
                "CLUSTER_NOT_READY",
                "The cluster must be active before its system node group is migrated.",
            )
        cluster = self.reconcile_active_application_node_groups(cluster)
        configuration = copy.deepcopy(cluster["configuration"])
        groups = [
            item
            for item in configuration.get("nodeGroups", [])
            if isinstance(item, dict)
        ]
        legacy_name = body["legacyNodeGroupName"]
        target = body["targetNodeGroup"]
        legacy = next((item for item in groups if item.get("name") == legacy_name), None)
        if not legacy:
            raise ApiError(
                404,
                "LEGACY_NODE_GROUP_NOT_FOUND",
                "The legacy node group is not recorded in this cluster.",
            )
        legacy_index = groups.index(legacy)
        explicitly_system = [
            item for item in groups if item.get("purpose") == "SYSTEM"
        ]
        legacy_is_system = legacy.get("purpose") == "SYSTEM" or (
            legacy_index == 0
            and legacy.get("purpose") in {None, ""}
            and not explicitly_system
        )
        if not legacy_is_system:
            raise ApiError(
                409,
                "LEGACY_NODE_GROUP_NOT_SYSTEM",
                "Only the recorded legacy system node group can be retired.",
            )
        if any(item.get("name") == target["name"] for item in groups):
            raise ApiError(
                409,
                "TARGET_NODE_GROUP_ALREADY_RECORDED",
                "The target system node group is already recorded in this cluster.",
            )
        configuration["nodeGroups"] = [
            target if item.get("name") == legacy_name else item for item in groups
        ]
        configuration["systemNodeGroupMigration"] = {
            "targetNodeGroupName": target["name"],
            "legacyNodeGroupName": legacy_name,
            "status": "PLANNING",
            "requestedBy": self.principal.user_id,
            "requestedAt": datetime.now(timezone.utc).isoformat(),
            "reason": body["reason"],
        }
        old = copy.deepcopy(cluster)
        cluster["configuration"] = configuration
        _, snapshot = self.repo.pinned_environment_snapshot(
            cluster["environment_id"], cluster["environment_approved_version"]
        )
        build_id, prefix = (self.provisioner or Provisioner()).start(
            "plan", cluster, snapshot
        )
        cluster["provider_execution_id"] = build_id
        cluster["execution_artifact_prefix"] = prefix
        cluster["plan_artifact_key"] = prefix + "/terraform.tfplan"
        cluster["plan_sha256"] = None
        cluster["workflow"]["currentExecution"] = {
            "mode": "plan",
            "kind": "SYSTEM_NODE_GROUP_MIGRATION",
            "buildId": build_id,
            "startedBy": self.principal.user_id,
            "startedAt": datetime.now(timezone.utc).isoformat(),
        }
        cluster["status"] = "PLAN_RUNNING"
        cluster["version"] += 1
        cluster["updated_by"] = self.principal.user_id
        cluster["updated_at"] = datetime.now(timezone.utc)
        self.repo.save(cluster)
        self.repo.record(
            old,
            cluster,
            "ClusterSystemNodeGroupMigrationRequested",
            body,
            self.correlation,
        )
        return serialize(cluster)

    @staticmethod
    def node_group_execution_cluster(cluster, request):
        value = copy.deepcopy(cluster)
        configuration = copy.deepcopy(cluster["configuration"])
        configuration["nodeGroups"] = [
            *configuration.get("nodeGroups", []),
            request["node_group"],
        ]
        value["configuration"] = configuration
        value["plan_artifact_key"] = request.get("plan_artifact_key")
        value["plan_sha256"] = request.get("plan_sha256")
        return value

    def change_node_group_request(self, cluster_id, request_id, action, body):
        cluster = self.repo.get(cluster_id, lock=True)
        request = self.repo.get_node_group_request(cluster_id, request_id, lock=True)
        if request["version"] != body["version"]:
            raise ApiError(
                409, "CONCURRENT_UPDATE", "Reload the latest node-group request."
            )
        old = copy.deepcopy(request)
        now = datetime.now(timezone.utc)
        if action == "submit":
            if not self.principal.roles.intersection(
                {"CLOUD_ENGINEER", "PLATFORM_ADMINISTRATOR"}
            ):
                raise ApiError(403, "FORBIDDEN", "This operation is not permitted for your role.")
            if request["status"] not in {"DRAFT", "REJECTED"}:
                raise ApiError(
                    409, "INVALID_STATUS_TRANSITION", "Request cannot be submitted."
                )
            request["status"] = "SUBMITTED"
            request["workflow"]["submitted"] = {
                "by": self.principal.user_id,
                "at": now.isoformat(),
                "comments": body.get("comments"),
            }
        elif action == "approve":
            if not self.principal.roles.intersection(
                {"PLATFORM_ARCHITECT", "PLATFORM_ADMINISTRATOR"}
            ):
                raise ApiError(403, "FORBIDDEN", "This operation is not permitted for your role.")
            if request["status"] != "SUBMITTED":
                raise ApiError(
                    409, "INVALID_STATUS_TRANSITION", "Request cannot be approved."
                )
            if self.principal.user_id == request["created_by"]:
                raise ApiError(
                    403,
                    "INDEPENDENT_REVIEW_REQUIRED",
                    "The request author cannot approve it.",
                )
            _, snapshot = self.repo.pinned_environment_snapshot(
                cluster["environment_id"], cluster["environment_approved_version"]
            )
            execution_cluster = self.node_group_execution_cluster(cluster, request)
            build_id, prefix = (self.provisioner or Provisioner()).start(
                "plan", execution_cluster, snapshot
            )
            request["status"] = "PLAN_RUNNING"
            request["provider_execution_id"] = build_id
            request["execution_artifact_prefix"] = prefix
            request["plan_artifact_key"] = prefix + "/terraform.tfplan"
            request["plan_sha256"] = None
            request["workflow"]["approved"] = {
                "by": self.principal.user_id,
                "at": now.isoformat(),
                "comments": body.get("comments"),
            }
        elif action == "reject":
            if not self.principal.roles.intersection(
                {"PLATFORM_ARCHITECT", "PLATFORM_ADMINISTRATOR"}
            ):
                raise ApiError(403, "FORBIDDEN", "This operation is not permitted for your role.")
            if request["status"] != "SUBMITTED":
                raise ApiError(
                    409, "INVALID_STATUS_TRANSITION", "Request cannot be rejected."
                )
            if not body.get("reason"):
                raise ApiError(422, "REASON_REQUIRED", "Provide a rejection reason.")
            if self.principal.user_id == request["created_by"]:
                raise ApiError(
                    403,
                    "INDEPENDENT_REVIEW_REQUIRED",
                    "The request author cannot reject it.",
                )
            request["status"] = "REJECTED"
            request["workflow"]["rejected"] = {
                "by": self.principal.user_id,
                "at": now.isoformat(),
                "reason": body["reason"],
            }
        elif action == "apply":
            if not self.principal.roles.intersection(
                {"PLATFORM_ARCHITECT", "PLATFORM_ADMINISTRATOR"}
            ):
                raise ApiError(403, "FORBIDDEN", "This operation is not permitted for your role.")
            if request["status"] != "PLAN_READY":
                raise ApiError(
                    409, "INVALID_STATUS_TRANSITION", "Request is not ready to apply."
                )
            if request.get("workflow", {}).get("certification", {}).get("status") != "PASSED":
                raise ApiError(
                    409,
                    "PLAN_NOT_CERTIFIED",
                    "Terraform validation and security checks must pass before apply.",
                )
            _, snapshot = self.repo.pinned_environment_snapshot(
                cluster["environment_id"], cluster["environment_approved_version"]
            )
            execution_cluster = self.node_group_execution_cluster(cluster, request)
            build_id, prefix = (self.provisioner or Provisioner()).start(
                "apply", execution_cluster, snapshot
            )
            request["status"] = "APPLYING"
            request["provider_execution_id"] = build_id
            request["execution_artifact_prefix"] = prefix
            request["workflow"]["currentExecution"] = {
                "mode": "apply",
                "buildId": build_id,
                "startedBy": self.principal.user_id,
                "startedAt": now.isoformat(),
            }
        elif action == "retry":
            if not self.principal.roles.intersection(
                {"PLATFORM_ARCHITECT", "PLATFORM_ADMINISTRATOR"}
            ):
                raise ApiError(403, "FORBIDDEN", "This operation is not permitted for your role.")
            if request["status"] != "FAILED":
                raise ApiError(
                    409,
                    "INVALID_STATUS_TRANSITION",
                    "Only a failed node-group request can be retried.",
                )
            _, snapshot = self.repo.pinned_environment_snapshot(
                cluster["environment_id"], cluster["environment_approved_version"]
            )
            execution_cluster = self.node_group_execution_cluster(cluster, request)
            build_id, prefix = (self.provisioner or Provisioner()).start(
                "plan", execution_cluster, snapshot
            )
            request["status"] = "PLAN_RUNNING"
            request["provider_execution_id"] = build_id
            request["execution_artifact_prefix"] = prefix
            request["plan_artifact_key"] = prefix + "/terraform.tfplan"
            request["plan_sha256"] = None
            request["workflow"]["certification"] = {"status": "PENDING"}
            request["workflow"]["currentExecution"] = {
                "mode": "plan",
                "buildId": build_id,
                "startedBy": self.principal.user_id,
                "startedAt": now.isoformat(),
                "retryOf": old.get("provider_execution_id"),
            }
        else:
            raise ApiError(404, "ACTION_NOT_FOUND", "Node-group action not found.")
        request["version"] += 1
        request["updated_by"] = self.principal.user_id
        request["updated_at"] = now
        self.repo.save_node_group_request(request)
        self.repo.record_node_group_request(
            old,
            request,
            "ClusterNodeGroupRequest" + action.title(),
            self.correlation,
        )
        return serialize(request)
