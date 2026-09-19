import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from navigan.modules.cluster_management.connector_installation import ConnectorInstaller
from navigan.shared.errors import ApiError


def test_installer_preflights_capacity_before_rotating_connector_credentials():
    buildspec = Path(
        "infrastructure/bootstrap/aws-connector-installer-v1.0.0/buildspec.yml"
    ).read_text()
    preflight = buildspec.index("Connector scheduling preflight")
    token_fetch = buildspec.index("get-secret-value --secret-id")
    deployment = buildspec.index("kind: Deployment")

    assert preflight < token_fetch < deployment
    assert "No schedulable pod slot is available" in buildspec
    assert "type: Recreate" in buildspec
    assert "key: navigan.io/system-only" in buildspec
    assert 'resources: ["nodes", "namespaces", "pods", "pods/log", "services", "configmaps", "events"]' in buildspec
    assert 'resources: ["deployments", "statefulsets", "daemonsets", "replicasets"]' in buildspec
    assert 'verbs: ["get", "list", "watch", "patch", "update"]' in buildspec


def cluster():
    return {
        "cluster_id": "CLU-test",
        "cluster_name": "private-cluster",
        "provisioning_role_arn": (
            "arn:aws:iam::123456789012:role/NaviganProvisioningRole"
        ),
        "external_id_secret_arn": (
            "arn:aws:secretsmanager:ap-south-1:905418045935:"
            "secret:navigan/provisioning/test"
        ),
    }


def snapshot(installer=True):
    configuration = {"location": {"region": "ap-south-1"}}
    if installer:
        configuration["connectorInstaller"] = {
            "projectName": "NaviganClusterInstaller",
            "serviceRoleArn": (
                "arn:aws:iam::123456789012:role/NaviganClusterInstallerRole"
            ),
            "connectorImage": "123456789012.dkr.ecr.ap-south-1.amazonaws.com/connector@sha256:abc",
            "apiBaseUrl": "https://api.example.test/api/v1",
        }
    return {"configuration": configuration}


def test_installation_requires_platform_deployment_artifacts(monkeypatch):
    monkeypatch.delenv("CONNECTOR_IMAGE_URI", raising=False)
    monkeypatch.delenv("CONNECTOR_API_BASE_URL", raising=False)
    installer = ConnectorInstaller(sts=MagicMock(), secrets=MagicMock())
    with pytest.raises(ApiError) as error:
        installer.start(cluster(), snapshot(False), "KCC-test", "secret-token")
    assert error.value.code == "CONNECTOR_INSTALLER_NOT_CONFIGURED"


def test_token_is_written_to_customer_secret_and_not_build_metadata(monkeypatch):
    monkeypatch.setenv(
        "CONNECTOR_IMAGE_URI",
        "123456789012.dkr.ecr.ap-south-1.amazonaws.com/connector@sha256:abc",
    )
    monkeypatch.setenv(
        "CONNECTOR_API_BASE_URL", "https://api.example.test/api/v1"
    )
    sts = MagicMock()
    sts.assume_role.return_value = {
        "Credentials": {
            "AccessKeyId": "access",
            "SecretAccessKey": "secret",
            "SessionToken": "session",
        }
    }
    platform_secrets = MagicMock()
    platform_secrets.get_secret_value.return_value = {"SecretString": "external-id"}
    customer_secrets = MagicMock()
    customer_secrets.create_secret.return_value = {
        "ARN": "arn:aws:secretsmanager:ap-south-1:123456789012:secret:connector"
    }
    codebuild = MagicMock()
    codebuild.start_build.return_value = {"build": {"id": "build:123"}}
    eks = MagicMock()
    eks.exceptions.ResourceNotFoundException = type(
        "ResourceNotFoundException", (Exception,), {}
    )
    eks.list_associated_access_policies.return_value = {
        "associatedAccessPolicies": []
    }

    def clients(name, **_options):
        return {
            "secretsmanager": customer_secrets,
            "codebuild": codebuild,
            "eks": eks,
        }[name]

    result = ConnectorInstaller(
        sts=sts, secrets=platform_secrets, client_factory=clients
    ).start(cluster(), snapshot(), "KCC-test", "one-time-secret")

    assert result["executionId"] == "build:123"
    assert customer_secrets.create_secret.call_args.kwargs["SecretString"] == (
        "one-time-secret"
    )
    environment = codebuild.start_build.call_args.kwargs[
        "environmentVariablesOverride"
    ][0]
    assert "one-time-secret" not in environment["value"]
    payload = json.loads(environment["value"])
    assert payload["connectorSecretArn"].endswith(":secret:connector")
    assert "token" not in payload
    eks.describe_access_entry.assert_called_once()
    eks.associate_access_policy.assert_called_once()
