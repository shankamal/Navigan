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
    preflight = buildspec.index("At least two Ready protected system nodes")
    coredns = buildspec.index("rollout status deployment/coredns")
    token_fetch = buildspec.index("get-secret-value --secret-id")
    helm_checksum = buildspec.index('sha256sum --check "${HELM_ARCHIVE}.sha256sum"')
    argocd = buildspec.index(
        "/tmp/helm --kubeconfig /tmp/navigan-kubeconfig upgrade --install argocd"
    )
    root_application = buildspec.index("name: navigan-system")

    assert helm_checksum < preflight < coredns < token_fetch < argocd < root_application
    assert "navigan.io/platform-services=true" in buildspec
    assert "navigan-system-repository" in buildspec
    assert "jq -rj '.connectorToken'" in buildspec
    assert "jq -rj '.githubToken'" in buildspec
    assert "did not create the connector deployment within 10 minutes" in buildspec
    assert "rollout status deployment/navigan-cluster-connector" in buildspec
    assert "kind: Deployment" not in buildspec


def test_customer_installer_configures_private_tools_for_shared_gateway():
    buildspec = Path(
        "infrastructure/bootstrap/aws-customer-v1.2.0/"
        "connector-installer-buildspec.yml"
    ).read_text()

    assert "CLUSTER_ID=" in buildspec
    assert "jq -r '.clusterId'" in buildspec
    assert 'server.basehref: "/tools/clusters/${CLUSTER_ID}/argocd"' in buildspec
    assert 'users.anonymous.enabled: "true"' in buildspec
    assert "policy.default: role:readonly" in buildspec


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
        installer.start(
            cluster(),
            snapshot(False),
            "KCC-test",
            "secret-token",
            {
                "url": "https://github.com/customer/system",
                "revision": "main",
                "commit": "abc",
                "token": "github-token",
                "tokenExpiresAt": "2026-09-19T12:00:00Z",
            },
        )
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
    ).start(
        cluster(),
        snapshot(),
        "KCC-test",
        "one-time-secret",
        {
            "url": "https://github.com/customer/system",
            "revision": "main",
            "commit": "abc",
            "token": "github-token",
            "tokenExpiresAt": "2026-09-19T12:00:00Z",
        },
    )

    assert result["executionId"] == "build:123"
    secret_value = json.loads(
        customer_secrets.create_secret.call_args.kwargs["SecretString"]
    )
    assert secret_value["connectorToken"] == "one-time-secret"
    assert secret_value["githubToken"] == "github-token"
    environment = codebuild.start_build.call_args.kwargs[
        "environmentVariablesOverride"
    ][0]
    assert "one-time-secret" not in environment["value"]
    payload = json.loads(environment["value"])
    assert payload["connectorSecretArn"].endswith(":secret:connector")
    assert payload["systemRepositoryUrl"] == "https://github.com/customer/system"
    assert "token" not in payload
    eks.describe_access_entry.assert_called_once()
    eks.associate_access_policy.assert_called_once()
