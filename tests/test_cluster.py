from unittest.mock import MagicMock

import pytest

from navigan.shared.auth import Principal
from navigan.shared.errors import ApiError
from navigan.modules.cluster_management.service import Service
from navigan.modules.cluster_management.repository import Repository


def request():
    return {
        "environmentId": "ENV-test",
        "environmentApprovedVersion": 7,
        "clusterName": "navigan-dev-01",
        "kubernetesVersion": "1.33",
        "endpointAccess": "PRIVATE",
        "nodeGroups": blueprint_configuration()["nodeGroups"],
        "tags": {"CostCenter": "CC-100"},
        "provisioningRoleArn": provisioning_configuration()["roleArn"],
        "externalIdSecretArn": provisioning_configuration()["externalIdSecretArn"],
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
        {"environment_id": "ENV-test", "customer_id": "CUS-test", "approved_version": 7},
        environment_snapshot(missing_cluster),
    )
    return repo


def test_create_pins_active_environment_approved_version():
    repo = repository("CLOUD_ENGINEER")
    created = Service(repo, "correlation", MagicMock()).create(request())
    assert created["environmentApprovedVersion"] == 7
    assert created["terraformStateKey"].endswith("navigan-dev-01/terraform.tfstate")
    repo.active_environment_snapshot.assert_called_once_with("ENV-test", 7)
    repo.save.assert_called_once()


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


def test_create_owns_configuration_and_provisioning_on_cluster_request():
    repo = repository("CLOUD_ENGINEER")
    created = Service(repo, "correlation", MagicMock()).create(request())
    assert created["configuration"]["kubernetesVersion"] == "1.33"
    assert "blueprintName" not in created["configuration"]
    assert created["provisioningRoleArn"].endswith("NaviganProvisioningRole")
    assert created["externalIdSecretArn"] == provisioning_configuration()["externalIdSecretArn"]


def test_create_captures_optional_description():
    repo = repository("CLOUD_ENGINEER")
    created = Service(repo, "correlation", MagicMock()).create(
        {**request(), "description": "Blue-green migration cluster."}
    )
    assert created["description"] == "Blue-green migration cluster."

    repo_without = repository("CLOUD_ENGINEER")
    created_without = Service(repo_without, "correlation", MagicMock()).create(request())
    assert created_without["description"] is None


def test_create_does_not_require_environment_cluster_blueprint():
    repo = repository("CLOUD_ENGINEER", missing_cluster=True)
    created = Service(repo, "correlation", MagicMock()).create(request())
    assert created["configuration"]["kubernetesVersion"] == "1.33"


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
