from unittest.mock import MagicMock
from pathlib import Path

import pytest

from navigan.shared.auth import Principal
from navigan.shared.errors import ApiError
from navigan.modules.cluster_management.service import Service
from navigan.modules.cluster_management.repository import Repository, serialize
from navigan.modules.cluster_management.handler import identity_subjects


def request():
    return {
        "environmentId": "ENV-test",
        "environmentApprovedVersion": 7,
        "blueprintName": "default",
        "clusterName": "navigan-dev-01",
        "kubernetesVersion": "1.33",
        "endpointAccess": "PRIVATE",
        "nodeGroups": blueprint_configuration()["nodeGroups"],
        "tags": {"CostCenter": "CC-100"},
        "provisioningRoleArn": provisioning_configuration()["roleArn"],
        "externalIdSecretArn": provisioning_configuration()["externalIdSecretArn"],
        "githubOrganization": "customer-platform",
    }


def provisioning_configuration():
    return {
        "roleArn": "arn:aws:iam::123456789012:role/NaviganProvisioningRole",
        "externalIdSecretArn": (
            "arn:aws:secretsmanager:ap-south-1:123456789012:secret:"
            "navigan/provisioning/customer-abc"
        ),
    }


def blueprint_configuration(name="default"):
    return {
        "name": name,
        "kubernetesVersion": "1.33",
        "endpointAccess": "PRIVATE",
        "nodeGroups": [{
            "name": "general", "instanceTypes": ["m6i.large", "m6a.large"],
            "capacityType": "ON_DEMAND", "desiredSize": 2,
            "minSize": 2, "maxSize": 4, "diskSizeGiB": 50,
        }],
        "tags": {"CostCenter": "CC-100"},
        "provisioning": provisioning_configuration(),
    }


def environment_snapshot(missing_cluster=False):
    configuration = {
        "account": {"accountId": "123456789012"},
        "location": {"region": "ap-south-1"},
        "extensions": {
            "provisioningContract": {
                "kubernetesVersions": ["1.33", "1.34"],
                "instanceTypes": [
                    {"instanceType": "m6i.large"},
                    {"instanceType": "m6a.large"},
                ],
            }
        },
    }
    if not missing_cluster:
        configuration["clusters"] = [blueprint_configuration()]
    return {"configuration": configuration}


def row(status="DRAFT", user="engineer"):
    value = {
        "cluster_id": "CLU-test", "customer_id": "CUS-test",
        "environment_id": "ENV-test", "environment_approved_version": 7,
        "platform": "EKS", "cluster_name": "navigan-dev-01",
        "description": "Blue-green migration cluster for checkout service.",
        "configuration": {
            "blueprintName": "default",
            "kubernetesVersion": "1.33",
            "endpointAccess": "PRIVATE",
            "nodeGroups": blueprint_configuration()["nodeGroups"],
            "tags": {"CostCenter": "CC-100"},
        },
        "provisioning_role_arn": provisioning_configuration()["roleArn"],
        "external_id_secret_arn": provisioning_configuration()["externalIdSecretArn"],
        "terraform_module_version": "1.0.0", "terraform_state_key": "state/key",
        "status": status, "version": 1, "workflow": {}, "outputs": {},
        "plan_artifact_key": None, "plan_sha256": None,
        "provider_execution_id": None, "execution_artifact_prefix": None,
        "created_by": user, "created_at": "now", "updated_by": user, "updated_at": "now",
    }
    return value


def repository(role, value=None, user="engineer", missing_cluster=False):
    repo = MagicMock()
    repo.principal = Principal(user, frozenset({role}), frozenset(), True)
    repo.get.return_value = value or row()
    repo.active_environment_snapshot.return_value = (
        {
            "environment_id": "ENV-test",
            "customer_id": "CUS-test",
            "customer_name": "Customer Platform",
            "approved_version": 7,
        },
        environment_snapshot(missing_cluster),
    )
    repo.pinned_environment_snapshot.return_value = (
        {"environment_id": "ENV-test", "customer_id": "CUS-test", "approved_version": 9},
        environment_snapshot(missing_cluster),
    )
    repo.active_application_node_groups.return_value = []
    repo.active_github_connection.return_value = {
        "connection_id": "GHC-test",
        "installation_id": 123,
    }
    return repo


def test_create_pins_active_environment_approved_version():
    repo = repository("CLOUD_ENGINEER")
    created = Service(repo, "correlation", MagicMock()).create(request())
    assert created["environmentApprovedVersion"] == 7
    assert created["terraformStateKey"].endswith("navigan-dev-01/terraform.tfstate")
    repo.active_environment_snapshot.assert_called_once_with("ENV-test", 7)
    repo.save.assert_called_once()
    repo.create_system_repository.assert_called_once_with(
        created["clusterId"],
        "CUS-test",
        "customer-platform",
        "customer-platform-navigan-dev-01-system",
    )


def test_active_approved_baseline_remains_usable_during_revision():
    db = MagicMock()
    db.execute.return_value.fetchone.side_effect = [
        {
            "environment_id": "ENV-test",
            "customer_id": "CUS-test",
            "customer_status": "ACTIVE",
            "status": "DRAFT",
            "approved_status": "ACTIVE",
            "approved_version": 7,
        },
        {"snapshot": environment_snapshot()},
    ]
    principal = Principal("engineer", frozenset({"CLOUD_ENGINEER"}), frozenset(), True)
    environment, snapshot = Repository(db, principal).active_environment_snapshot("ENV-test", 7)
    assert environment["approved_version"] == 7
    assert snapshot == environment_snapshot()


def test_cluster_serialization_exposes_sanitized_identity_state():
    value = row("ACTIVE")
    value.update(
        {
            "identity_status": "FAILED",
            "identity_last_verified_at": None,
            "identity_failure_code": "OIDC_PROVIDER_UNAVAILABLE",
        }
    )

    result = serialize(value)

    assert result["identityIntegration"] == {
        "status": "FAILED",
        "lastVerifiedAt": None,
        "failureCode": "OIDC_PROVIDER_UNAVAILABLE",
    }
    assert "identityStatus" not in result


def test_missing_identity_record_returns_not_configured():
    db = MagicMock()
    db.execute.return_value.fetchone.side_effect = [
        {**row("ACTIVE"), "customer_name": "Customer", "environment_name": "Environment"},
        None,
    ]
    principal = Principal(
        "engineer",
        frozenset({"CLOUD_ENGINEER"}),
        frozenset({"CUS-test"}),
        False,
    )

    result = Repository(db, principal).identity("CLU-test")

    assert result["status"] == "NOT_CONFIGURED"
    assert result["customerId"] == "CUS-test"


def test_save_never_writes_joined_identity_fields_to_cluster_table():
    db = MagicMock()
    principal = Principal(
        "engineer",
        frozenset({"CLOUD_ENGINEER"}),
        frozenset({"CUS-test"}),
        False,
    )
    value = row("ACTIVE")
    value.update(
        {
            "customer_name": "Customer",
            "environment_name": "Environment",
            "identity_status": "READY",
            "identity_last_verified_at": "now",
            "identity_failure_code": None,
        }
    )

    Repository(db, principal).save(value)

    sql = db.execute.call_args.args[0]
    assert "identity_status=" not in sql
    assert "identity_last_verified_at=" not in sql
    assert "identity_failure_code=" not in sql


def test_kubernetes_access_assignment_is_created_pending_and_audited():
    db = MagicMock()
    db.execute.return_value.fetchone.side_effect = [
        {**row("ACTIVE"), "customer_name": "Customer", "environment_name": "Environment"},
        {
            "profile_id": "KAP-NAMESPACE-VIEWER",
            "profile_code": "NAMESPACE_VIEWER",
            "profile_name": "Namespace Viewer",
            "scope_type": "NAMESPACE",
        },
        {"namespace": "apps"},
        None,
    ]
    principal = Principal(
        "architect",
        frozenset({"PLATFORM_ARCHITECT"}),
        frozenset(),
        True,
    )

    result = Repository(db, principal).create_kubernetes_access(
        "CLU-test",
        {
            "subjectType": "GROUP",
            "subjectId": "NAVIGAN_CUSTOMER_CUS-test",
            "profileCode": "NAMESPACE_VIEWER",
            "namespace": "apps",
            "reason": "Application support",
        },
        "correlation",
    )

    assert result["status"] == "PENDING"
    assert result["namespace"] == "apps"
    statements = [call.args[0] for call in db.execute.call_args_list]
    assert any("kubernetes_access_assignments" in sql and "INSERT" in sql for sql in statements)
    assert any("access_audit_log" in sql and "INSERT" in sql for sql in statements)


def test_namespace_profile_requires_namespace():
    db = MagicMock()
    db.execute.return_value.fetchone.side_effect = [
        {**row("ACTIVE"), "customer_name": "Customer", "environment_name": "Environment"},
        {
            "profile_id": "KAP-NAMESPACE-VIEWER",
            "profile_code": "NAMESPACE_VIEWER",
            "profile_name": "Namespace Viewer",
            "scope_type": "NAMESPACE",
        },
    ]
    principal = Principal(
        "architect",
        frozenset({"PLATFORM_ARCHITECT"}),
        frozenset(),
        True,
    )

    with pytest.raises(ApiError) as error:
        Repository(db, principal).create_kubernetes_access(
            "CLU-test",
            {
                "subjectType": "GROUP",
                "subjectId": "NAVIGAN_CUSTOMER_CUS-test",
                "profileCode": "NAMESPACE_VIEWER",
                "reason": "Application support",
            },
            "correlation",
        )

    assert error.value.code == "NAMESPACE_REQUIRED"


def test_namespace_profile_rejects_namespace_not_in_verified_inventory():
    db = MagicMock()
    db.execute.return_value.fetchone.side_effect = [
        {**row("ACTIVE"), "customer_name": "Customer", "environment_name": "Environment"},
        {
            "profile_id": "KAP-NAMESPACE-VIEWER",
            "profile_code": "NAMESPACE_VIEWER",
            "profile_name": "Namespace Viewer",
            "scope_type": "NAMESPACE",
        },
        None,
    ]
    principal = Principal(
        "architect",
        frozenset({"PLATFORM_ARCHITECT"}),
        frozenset(),
        True,
    )

    with pytest.raises(ApiError) as error:
        Repository(db, principal).create_kubernetes_access(
            "CLU-test",
            {
                "subjectType": "GROUP",
                "subjectId": "NAVIGAN_CUSTOMER_CUS-test",
                "profileCode": "NAMESPACE_VIEWER",
                "namespace": "unknown",
                "reason": "Application support",
            },
            "correlation",
        )

    assert error.value.code == "NAMESPACE_NOT_DISCOVERED"


def test_namespace_inventory_is_not_configured_until_connector_reports():
    db = MagicMock()
    db.execute.return_value.fetchone.side_effect = [
        {**row("ACTIVE"), "customer_name": "Customer", "environment_name": "Environment"},
        None,
    ]
    principal = Principal(
        "architect",
        frozenset({"PLATFORM_ARCHITECT"}),
        frozenset(),
        True,
    )

    result = Repository(db, principal).kubernetes_namespaces("CLU-test")

    assert result["status"] == "NOT_CONFIGURED"
    assert result["namespaces"] == []


def test_cognito_directory_uses_stable_user_subjects(monkeypatch):
    client = MagicMock()
    client.list_users.return_value = {
        "Users": [
            {
                "Username": "person@example.com",
                "Enabled": True,
                "UserStatus": "CONFIRMED",
                "Attributes": [
                    {"Name": "sub", "Value": "stable-user-subject"},
                    {"Name": "email", "Value": "person@example.com"},
                    {"Name": "name", "Value": "Example Person"},
                ],
            }
        ]
    }
    client.list_groups.return_value = {
        "Groups": [
            {
                "GroupName": "NAVIGAN_CUSTOMER_CUS-test",
                "Description": "Customer engineering team",
            }
        ]
    }
    monkeypatch.setenv("IDENTITY_USER_POOL_ID", "ap-south-1_example")
    monkeypatch.setattr(
        "navigan.modules.cluster_management.handler.boto3.client",
        lambda service: client,
    )

    result = identity_subjects()

    assert result["users"][0]["id"] == "stable-user-subject"
    assert result["users"][0]["displayName"] == "Example Person"
    assert "person@example.com" in result["users"][0]["aliases"]
    assert result["groups"][0]["id"] == "NAVIGAN_CUSTOMER_CUS-test"
    assert result["truncated"] is False


def test_create_owns_configuration_and_provisioning_on_cluster_request():
    repo = repository("CLOUD_ENGINEER")
    created = Service(repo, "correlation", MagicMock()).create(request())
    assert created["configuration"]["kubernetesVersion"] == "1.33"
    assert created["configuration"]["blueprintName"] == "default"
    assert created["configuration"]["nodeGroups"][0]["purpose"] == "SYSTEM"
    assert created["provisioningRoleArn"].endswith("NaviganProvisioningRole")
    assert created["externalIdSecretArn"] == provisioning_configuration()["externalIdSecretArn"]


def test_create_accepts_another_version_from_the_approved_contract():
    repo = repository("CLOUD_ENGINEER")
    created = Service(repo, "correlation", MagicMock()).create(
        {**request(), "kubernetesVersion": "1.34"}
    )
    assert created["configuration"]["kubernetesVersion"] == "1.34"


def test_create_rejects_version_outside_the_approved_contract():
    repo = repository("CLOUD_ENGINEER")
    with pytest.raises(ApiError) as error:
        Service(repo, "correlation", MagicMock()).create(
            {**request(), "kubernetesVersion": "1.35"}
        )
    assert error.value.code == "KUBERNETES_VERSION_NOT_APPROVED"


def test_private_blueprint_rejects_public_endpoint_access():
    repo = repository("CLOUD_ENGINEER")
    with pytest.raises(ApiError) as error:
        Service(repo, "correlation", MagicMock()).create(
            {**request(), "endpointAccess": "PUBLIC_AND_PRIVATE"}
        )
    assert error.value.code == "ENDPOINT_ACCESS_NOT_APPROVED"


def test_create_captures_optional_description():
    repo = repository("CLOUD_ENGINEER")
    created = Service(repo, "correlation", MagicMock()).create(
        {**request(), "description": "Blue-green migration cluster."}
    )
    assert created["description"] == "Blue-green migration cluster."

    repo_without = repository("CLOUD_ENGINEER")
    created_without = Service(repo_without, "correlation", MagicMock()).create(request())
    assert created_without["description"] is None


def test_create_requires_environment_cluster_blueprint():
    repo = repository("CLOUD_ENGINEER", missing_cluster=True)
    with pytest.raises(ApiError) as error:
        Service(repo, "correlation", MagicMock()).create(request())
    assert error.value.code == "CLUSTER_BLUEPRINT_NOT_APPROVED"


def test_create_uses_approved_environment_catalogue_without_named_blueprint():
    repo = repository("CLOUD_ENGINEER", missing_cluster=True)
    created = Service(repo, "correlation", MagicMock()).create(
        {**request(), "blueprintName": "environment-default"}
    )
    assert created["configuration"]["blueprintName"] == "environment-default"
    assert created["configuration"]["kubernetesVersion"] == "1.33"
    assert created["configuration"]["nodeGroups"][0]["instanceTypes"] == [
        "m6i.large",
        "m6a.large",
    ]


def test_create_rejects_undersized_system_node_group():
    repo = repository("CLOUD_ENGINEER")
    snapshot = environment_snapshot()
    snapshot["configuration"]["clusters"][0]["nodeGroups"][0].update(
        {"minSize": 1, "desiredSize": 1}
    )
    repo.active_environment_snapshot.return_value = (
        {"approved_version": 7, "customer_id": "CUS-test", "environment_id": "ENV-test"},
        snapshot,
    )

    with pytest.raises(ApiError) as error:
        Service(repo, "correlation", MagicMock()).create(request())

    assert error.value.code == "SYSTEM_NODE_GROUP_CAPACITY_REQUIRED"


def test_create_rejects_micro_system_node_group():
    repo = repository("CLOUD_ENGINEER")
    snapshot = environment_snapshot()
    snapshot["configuration"]["clusters"][0]["nodeGroups"][0]["instanceTypes"] = [
        "t3.micro"
    ]
    repo.active_environment_snapshot.return_value = (
        {"approved_version": 7, "customer_id": "CUS-test", "environment_id": "ENV-test"},
        snapshot,
    )

    with pytest.raises(ApiError) as error:
        Service(repo, "correlation", MagicMock()).create(request())

    assert error.value.code == "SYSTEM_NODE_GROUP_INSTANCE_TYPE_UNSUPPORTED"


def application_node_group():
    return {
        "name": "checkout-workers",
        "purpose": "APPLICATION",
        "instanceTypes": ["m6i.large", "m6a.large"],
        "capacityType": "ON_DEMAND",
        "minSize": 1,
        "desiredSize": 2,
        "maxSize": 4,
        "diskSizeGiB": 80,
    }


def node_group_request_row(status="DRAFT", user="engineer"):
    return {
        "request_id": "KNG-0123456789abcdef0123456789abcdef",
        "cluster_id": "CLU-test",
        "customer_id": "CUS-test",
        "node_group": application_node_group(),
        "reason": "Checkout application onboarding",
        "status": status,
        "version": 1,
        "plan_artifact_key": None,
        "plan_sha256": None,
        "provider_execution_id": None,
        "execution_artifact_prefix": None,
        "workflow": {},
        "created_by": user,
        "created_at": "now",
        "updated_by": user,
        "updated_at": "now",
    }


def test_cloud_engineer_can_create_application_node_group_request():
    repo = repository("CLOUD_ENGINEER", row("ACTIVE"))

    created = Service(repo, "correlation", MagicMock()).create_node_group_request(
        "CLU-test",
        {
            "nodeGroup": application_node_group(),
            "reason": "Checkout application onboarding",
        },
    )

    assert created["status"] == "DRAFT"
    assert created["nodeGroup"]["purpose"] == "APPLICATION"
    repo.save_node_group_request.assert_called_once()


def test_node_group_request_requires_active_cluster():
    repo = repository("CLOUD_ENGINEER", row("BOOTSTRAPPING"))

    with pytest.raises(ApiError) as error:
        Service(repo, "correlation", MagicMock()).create_node_group_request(
            "CLU-test",
            {
                "nodeGroup": application_node_group(),
                "reason": "Checkout application onboarding",
            },
        )

    assert error.value.code == "CLUSTER_NOT_READY"


def test_node_group_approval_plans_existing_and_proposed_groups():
    cluster = row("ACTIVE")
    request_row = node_group_request_row("SUBMITTED")
    repo = repository("PLATFORM_ARCHITECT", cluster, "architect")
    repo.get_node_group_request.return_value = request_row
    provisioner = MagicMock()
    provisioner.start.return_value = ("build-id", "executions/node-group")

    updated = Service(repo, "correlation", provisioner).change_node_group_request(
        "CLU-test",
        request_row["request_id"],
        "approve",
        {"version": 1, "comments": "Approved application capacity"},
    )

    assert updated["status"] == "PLAN_RUNNING"
    execution_cluster = provisioner.start.call_args.args[1]
    assert [group["name"] for group in execution_cluster["configuration"]["nodeGroups"]] == [
        "general",
        "checkout-workers",
    ]
    repo.pinned_environment_snapshot.assert_called_once_with("ENV-test", 7)


def test_system_node_group_migration_preserves_application_groups():
    cluster = row("ACTIVE")
    cluster["configuration"]["nodeGroups"].append(
        {
            "name": "app-node-grp1",
            "purpose": "APPLICATION",
            "instanceTypes": ["t3.micro"],
            "capacityType": "ON_DEMAND",
            "desiredSize": 1,
            "minSize": 1,
            "maxSize": 3,
            "diskSizeGiB": 50,
        }
    )
    repo = repository("PLATFORM_ARCHITECT", cluster, "architect")
    provisioner = MagicMock()
    provisioner.start.return_value = ("build-id", "executions/system-migration")

    updated = Service(repo, "correlation", provisioner).migrate_system_node_group(
        "CLU-test",
        {
            "version": 1,
            "legacyNodeGroupName": "general",
            "targetNodeGroup": {
                "name": "navigan-system-v1",
                "purpose": "SYSTEM",
                "managementMode": "ADOPTED",
                "instanceTypes": ["t3.medium"],
                "capacityType": "ON_DEMAND",
                "desiredSize": 2,
                "minSize": 2,
                "maxSize": 4,
                "diskSizeGiB": 40,
            },
            "reason": "Adopt the approved system node group",
        },
    )

    groups = updated["configuration"]["nodeGroups"]
    assert [group["name"] for group in groups] == [
        "navigan-system-v1",
        "app-node-grp1",
    ]
    assert groups[0]["managementMode"] == "ADOPTED"
    assert updated["status"] == "PLAN_RUNNING"
    execution = provisioner.start.call_args.args[1]
    assert execution["configuration"]["systemNodeGroupMigration"][
        "legacyNodeGroupName"
    ] == "general"


def test_system_node_group_migration_accepts_legacy_first_group_without_purpose():
    cluster = row("ACTIVE")
    cluster["configuration"]["nodeGroups"][0].pop("purpose", None)
    repo = repository("PLATFORM_ARCHITECT", cluster, "architect")
    provisioner = MagicMock()
    provisioner.start.return_value = ("build-id", "executions/system-migration")

    updated = Service(repo, "correlation", provisioner).migrate_system_node_group(
        "CLU-test",
        {
            "version": 1,
            "legacyNodeGroupName": "general",
            "targetNodeGroup": {
                "name": "navigan-system-v1",
                "purpose": "SYSTEM",
                "managementMode": "ADOPTED",
                "instanceTypes": ["t3.medium"],
                "capacityType": "ON_DEMAND",
                "desiredSize": 2,
                "minSize": 2,
                "maxSize": 4,
                "diskSizeGiB": 40,
            },
            "reason": "Replace the implicit legacy system group",
        },
    )

    assert updated["configuration"]["nodeGroups"][0]["name"] == "navigan-system-v1"


def test_system_migration_preserves_active_application_request_capacity():
    cluster = row("ACTIVE")
    repo = repository("PLATFORM_ARCHITECT", cluster, "architect")
    repo.active_application_node_groups.return_value = [
        {
            "name": "app-node-grp1",
            "purpose": "APPLICATION",
            "instanceTypes": ["t3.micro"],
            "capacityType": "ON_DEMAND",
            "desiredSize": 1,
            "minSize": 1,
            "maxSize": 3,
            "diskSizeGiB": 50,
        }
    ]
    provisioner = MagicMock()
    provisioner.start.return_value = ("build-id", "executions/system-migration")

    Service(repo, "correlation", provisioner).migrate_system_node_group(
        "CLU-test",
        {
            "version": 1,
            "legacyNodeGroupName": "general",
            "targetNodeGroup": {
                "name": "navigan-system-v1",
                "purpose": "SYSTEM",
                "managementMode": "ADOPTED",
                "instanceTypes": ["t3.medium"],
                "capacityType": "ON_DEMAND",
                "desiredSize": 2,
                "minSize": 2,
                "maxSize": 4,
                "diskSizeGiB": 40,
            },
            "reason": "Preserve active application capacity during migration",
        },
    )

    execution = provisioner.start.call_args.args[1]
    assert [group["name"] for group in execution["configuration"]["nodeGroups"]] == [
        "navigan-system-v1",
        "app-node-grp1",
    ]


def test_eks_module_attaches_a_shared_managed_security_group_to_every_node_pool():
    module = (
        Path(__file__).parents[1] / "terraform" / "modules" / "aws-eks" / "main.tf"
    ).read_text(encoding="utf-8")

    assert 'resource "aws_security_group" "managed_nodes"' in module
    assert "managed_nodes_self" in module
    assert "distinct(concat(" in module
    assert "[aws_security_group.managed_nodes.id]" in module


def test_create_rejects_provisioning_role_from_another_account():
    repo = repository("CLOUD_ENGINEER")
    with pytest.raises(ApiError) as error:
        Service(repo, "correlation", MagicMock()).create(
            {
                **request(),
                "provisioningRoleArn":
                    "arn:aws:iam::999999999999:role/NaviganProvisioningRole",
            }
        )
    assert error.value.status == 422
    assert error.value.code == "PROVISIONING_ROLE_ACCOUNT_MISMATCH"


def test_architect_cannot_author_cluster_request():
    repo = repository("PLATFORM_ARCHITECT", user="architect")
    with pytest.raises(ApiError) as error:
        Service(repo, "correlation", MagicMock()).create(request())
    assert error.value.status == 403


def test_request_author_cannot_review_own_request():
    value = row("SUBMITTED", "maker")
    value["workflow"] = {"submitted": {"by": "maker"}}
    repo = repository("PLATFORM_ARCHITECT", value, "maker")
    with pytest.raises(ApiError) as error:
        Service(repo, "correlation", MagicMock()).change("CLU-test", "review", {"version": 1})
    assert error.value.code == "INDEPENDENT_REVIEW_REQUIRED"


def test_apply_uses_only_the_saved_plan():
    value = row("PLAN_READY")
    value["plan_artifact_key"] = "executions/plan/terraform.tfplan"
    value["plan_sha256"] = "a" * 64
    value["workflow"]["certification"] = {"status": "PASSED"}
    repo = repository("PLATFORM_ARCHITECT", value, "architect")
    provisioner = MagicMock()
    provisioner.start.return_value = ("build-id", "executions/apply")
    updated = Service(repo, "correlation", provisioner).change(
        "CLU-test", "apply", {"version": 1, "comments": "approved"}
    )
    assert updated["status"] == "APPLYING"
    provisioner.start.assert_called_once()


def test_apply_rejects_uncertified_plan():
    value = row("PLAN_READY")
    value["plan_artifact_key"] = "executions/plan/terraform.tfplan"
    value["plan_sha256"] = "a" * 64
    repo = repository("PLATFORM_ARCHITECT", value, "architect")

    with pytest.raises(ApiError) as error:
        Service(repo, "correlation", MagicMock()).change(
            "CLU-test", "apply", {"version": 1, "comments": "approved"}
        )

    assert error.value.code == "PLAN_NOT_CERTIFIED"


@pytest.mark.parametrize(
    ("action", "initial", "target"),
    [("stop", "ACTIVE", "STOPPING"), ("start", "STOPPED", "STARTING")],
)
def test_cluster_capacity_lifecycle_actions(action, initial, target):
    value = row(initial)
    repo = repository("PLATFORM_ARCHITECT", value, "architect")
    provisioner = MagicMock()
    provisioner.start.return_value = ("build-id", f"executions/{action}")
    updated = Service(repo, "correlation", provisioner).change(
        "CLU-test", action, {"version": 1, "comments": "approved operation"}
    )
    assert updated["status"] == target
    assert updated["workflow"]["currentExecution"]["mode"] == action
    assert updated["workflow"]["currentExecution"]["buildId"] == "build-id"
    provisioner.start.assert_called_once()


def test_delete_requires_reason_and_uses_recorded_state():
    value = row("ACTIVE")
    repo = repository("PLATFORM_ARCHITECT", value, "architect")
    with pytest.raises(ApiError) as error:
        Service(repo, "correlation", MagicMock()).change(
            "CLU-test", "delete", {"version": 1}
        )
    assert error.value.code == "REASON_REQUIRED"

    provisioner = MagicMock()
    provisioner.start.return_value = ("build-id", "executions/delete")
    updated = Service(repo, "correlation", provisioner).change(
        "CLU-test", "delete", {"version": 1, "reason": "Obsolete test cluster"}
    )
    assert updated["status"] == "DELETING"
    repo.pinned_environment_snapshot.assert_called_once_with("ENV-test", 7)
    repo.active_environment_snapshot.assert_not_called()


def test_approval_automatically_starts_terraform_plan():
    value = row("UNDER_REVIEW")
    value["created_by"] = "engineer"
    value["workflow"] = {"submitted": {"by": "engineer"}}
    repo = repository("PLATFORM_ARCHITECT", value, "architect")
    provisioner = MagicMock()
    provisioner.start.return_value = ("build-plan", "executions/plan")

    updated = Service(repo, "correlation", provisioner).change(
        "CLU-test", "approve", {"version": 1, "comments": "approved"}
    )

    assert updated["status"] == "PLAN_RUNNING"
    assert updated["planArtifactKey"] == "executions/plan/terraform.tfplan"
    provisioner.start.assert_called_once_with(
        "plan", value, environment_snapshot()
    )


def test_new_cluster_approval_pauses_for_github_organization_authorization():
    value = row("UNDER_REVIEW")
    value["created_by"] = "engineer"
    value["workflow"] = {"submitted": {"by": "engineer"}}
    value["configuration"]["platformBaseline"] = {
        "repository": {
            "organization": "customer-platform",
            "name": "customer-platform-navigan-dev-01-system",
            "connectionStatus": "AUTHORIZATION_REQUIRED",
        }
    }
    repo = repository("PLATFORM_ARCHITECT", value, "architect")
    repo.active_github_connection.return_value = None

    provisioner = MagicMock()
    updated = Service(repo, "correlation", provisioner).change(
        "CLU-test", "approve", {"version": 1, "comments": "approved"}
    )

    assert updated["status"] == "APPROVED"
    assert (
        updated["configuration"]["platformBaseline"]["repository"][
            "connectionStatus"
        ]
        == "AUTHORIZATION_REQUIRED"
    )
    provisioner.start.assert_not_called()


def test_approval_can_start_directly_from_submitted():
    value = row("SUBMITTED")
    value["created_by"] = "engineer"
    value["workflow"] = {"submitted": {"by": "engineer"}}
    repo = repository("PLATFORM_ARCHITECT", value, "architect")
    provisioner = MagicMock()
    provisioner.start.return_value = ("build-plan", "executions/plan")

    updated = Service(repo, "correlation", provisioner).change(
        "CLU-test", "approve", {"version": 1, "comments": "approved"}
    )

    assert updated["status"] == "PLAN_RUNNING"


def test_update_can_only_rename_the_cluster():
    repo = repository("CLOUD_ENGINEER")
    updated = Service(repo, "correlation", MagicMock()).change(
        "CLU-test", "update",
        {"version": 1, "clusterName": "navigan-dev-02", "description": "Updated context."},
    )
    assert updated["clusterName"] == "navigan-dev-02"
    assert updated["description"] == "Updated context."
    assert updated["configuration"]["kubernetesVersion"] == "1.33"
