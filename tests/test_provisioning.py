import json
from unittest.mock import MagicMock

from botocore.exceptions import ClientError

from navigan.modules.cluster_management.provisioning import Provisioner


def cluster():
    return {
        "customer_id": "CUS-test",
        "cluster_id": "CLU-test",
        "environment_id": "ENV-test",
        "environment_approved_version": 1,
        "platform": "EKS",
        "cluster_name": "cluster-test",
        "configuration": {"kubernetesVersion": "1.37", "nodeGroups": []},
        "provisioning_role_arn": "arn:aws:iam::123456789012:role/NaviganProvisioningRole",
        "external_id_secret_arn": "arn:aws:secretsmanager:ap-south-1:123456789012:secret:test",
        "terraform_module_version": "1.0.0",
        "terraform_state_key": "customers/CUS-test/clusters/cluster-test/terraform.tfstate",
        "plan_artifact_key": "executions/old/terraform.tfplan",
        "plan_sha256": "stale-sha",
    }


def configured(monkeypatch):
    monkeypatch.setenv("TERRAFORM_ARTIFACT_BUCKET", "state-bucket")
    monkeypatch.setenv("TERRAFORM_CODEBUILD_PROJECT", "terraform-project")
    monkeypatch.setenv("TERRAFORM_STATE_KMS_KEY_ARN", "arn:aws:kms:ap-south-1:123456789012:key/test")
    monkeypatch.setenv("AWS_REGION", "ap-south-1")
    s3 = MagicMock()
    codebuild = MagicMock()
    codebuild.start_build.return_value = {"build": {"id": "build-1"}}
    return Provisioner(s3=s3, codebuild=codebuild), s3, codebuild


def test_state_exists_checks_exact_configured_backend(monkeypatch):
    provisioner, s3, _ = configured(monkeypatch)
    assert provisioner.state_exists(cluster()) is True
    s3.head_object.assert_called_once_with(
        Bucket="state-bucket",
        Key="customers/CUS-test/clusters/cluster-test/terraform.tfstate",
    )


def test_state_exists_returns_false_only_for_missing_object(monkeypatch):
    provisioner, s3, _ = configured(monkeypatch)
    s3.head_object.side_effect = ClientError(
        {
            "Error": {"Code": "404", "Message": "Not Found"},
            "ResponseMetadata": {"HTTPStatusCode": 404},
        },
        "HeadObject",
    )
    assert provisioner.state_exists(cluster()) is False


def test_non_apply_payload_does_not_carry_stale_approved_plan(monkeypatch):
    provisioner, s3, _ = configured(monkeypatch)
    provisioner.start("plan", cluster(), {"configuration": {}})
    body = json.loads(s3.put_object.call_args.kwargs["Body"])
    assert body["approvedPlanArtifactKey"] is None
    assert body["approvedPlanSha256"] is None
    assert body["state"] == {
        "bucket": "state-bucket",
        "key": "customers/CUS-test/clusters/cluster-test/terraform.tfstate",
        "region": "ap-south-1",
        "kmsKeyArn": "arn:aws:kms:ap-south-1:123456789012:key/test",
        "useLockfile": True,
    }


def test_apply_payload_keeps_exact_certified_plan(monkeypatch):
    provisioner, s3, _ = configured(monkeypatch)
    provisioner.start("apply", cluster(), {"configuration": {}})
    body = json.loads(s3.put_object.call_args.kwargs["Body"])
    assert body["approvedPlanArtifactKey"] == "executions/old/terraform.tfplan"
    assert body["approvedPlanSha256"] == "stale-sha"
