from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from navigan.shared.auth import Principal
from navigan.shared.errors import ApiError
from navigan.modules.cluster_management.models import CreateCluster, NodeGroup
from navigan.modules.cluster_management.service import Service


def request():
    return {
        "environmentId": "ENV-test",
        "environmentApprovedVersion": 7,
        "platform": "EKS",
        "clusterName": "navigan-dev-01",
        "configuration": {
            "kubernetesVersion": "1.33",
            "endpointAccess": "PRIVATE",
            "nodeGroups": [{
                "name": "general", "instanceTypes": ["m6i.large"],
                "capacityType": "ON_DEMAND", "desiredSize": 2,
                "minSize": 2, "maxSize": 4, "diskSizeGiB": 50,
            }],
            "tags": {"CostCenter": "CC-100"},
        },
        "provisioningRoleArn": "arn:aws:iam::123456789012:role/NaviganProvisioningRole",
        "externalIdSecretArn": (
            "arn:aws:secretsmanager:ap-south-1:123456789012:secret:"
            "navigan/provisioning/customer-abc"
        ),
        "terraformModuleVersion": "1.0.0",
    }


def row(status="DRAFT", user="engineer"):
    value = {
        "cluster_id": "CLU-test", "customer_id": "CUS-test",
        "environment_id": "ENV-test", "environment_approved_version": 7,
        "platform": "EKS", "cluster_name": "navigan-dev-01",
        "configuration": request()["configuration"],
        "provisioning_role_arn": request()["provisioningRoleArn"],
        "external_id_secret_arn": request()["externalIdSecretArn"],
        "terraform_module_version": "1.0.0", "terraform_state_key": "state/key",
        "status": status, "version": 1, "workflow": {}, "outputs": {},
        "plan_artifact_key": None, "plan_sha256": None,
        "provider_execution_id": None, "execution_artifact_prefix": None,
        "created_by": user, "created_at": "now", "updated_by": user, "updated_at": "now",
    }
    return value


def repository(role, value=None, user="engineer"):
    repo = MagicMock()
    repo.principal = Principal(user, frozenset({role}), frozenset(), True)
    repo.get.return_value = value or row()
    repo.active_environment_snapshot.return_value = (
        {"environment_id": "ENV-test", "customer_id": "CUS-test", "approved_version": 7},
        {"configuration": {"location": {"region": "ap-south-1"}}},
    )
    return repo


def test_create_pins_active_environment_approved_version():
    repo = repository("CLOUD_ENGINEER")
    created = Service(repo, "correlation", MagicMock()).create(request())
    assert created["environmentApprovedVersion"] == 7
    assert created["terraformStateKey"].endswith("navigan-dev-01/terraform.tfstate")
    repo.active_environment_snapshot.assert_called_once_with("ENV-test", 7)
    repo.save.assert_called_once()


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
    repo = repository("PLATFORM_ARCHITECT", value, "architect")
    provisioner = MagicMock()
    provisioner.start.return_value = ("build-id", "executions/apply")
    updated = Service(repo, "correlation", provisioner).change(
        "CLU-test", "apply", {"version": 1, "comments": "approved"}
    )
    assert updated["status"] == "APPLYING"
    provisioner.start.assert_called_once()


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
        "plan", value, {"configuration": {"location": {"region": "ap-south-1"}}}
    )


def test_node_group_and_role_validation():
    with pytest.raises(ValidationError):
        NodeGroup.model_validate({
            "name": "bad_name", "instanceTypes": ["m6i.large"],
            "desiredSize": 5, "minSize": 2, "maxSize": 4, "diskSizeGiB": 50,
        })
    with pytest.raises(ValidationError):
        CreateCluster.model_validate({
            **request(),
            "provisioningRoleArn": "arn:aws:iam::123456789012:role/Admin",
        })
