import json
from unittest.mock import MagicMock

from navigan.modules.migration_management.source_connector_installation import (
    SourceConnectorInstaller,
)


def test_aws_delivery_uses_approved_role_and_hides_token_from_command(
    monkeypatch,
):
    role_arn = (
        "arn:aws:iam::905418045935:"
        "role/NaviganSourceConnectorDeliveryRole"
    )
    monkeypatch.setenv("SOURCE_CONNECTOR_DELIVERY_ROLE_ARN", role_arn)
    monkeypatch.setenv(
        "MIGRATION_CONNECTOR_API_BASE_URL",
        "https://api.example.test/v1/api/v1",
    )
    monkeypatch.setenv(
        "MIGRATION_CONNECTOR_IMAGE_REPOSITORY",
        "905418045935.dkr.ecr.ap-south-1.amazonaws.com/connector",
    )
    monkeypatch.setenv(
        "MIGRATION_CONNECTOR_IMAGE_DIGEST",
        "sha256:" + "a" * 64,
    )

    sts = MagicMock()
    sts.assume_role.return_value = {
        "Credentials": {
            "AccessKeyId": "access",
            "SecretAccessKey": "secret",
            "SessionToken": "session",
        }
    }
    ssm = MagicMock()
    ssm.send_command.return_value = {
        "Command": {"CommandId": "11111111-2222-3333-4444-555555555555"}
    }

    def client(service, **options):
        assert service in {"sts", "ssm"}
        if service == "ssm":
            assert options["region_name"] == "ap-south-1"
            return ssm
        return sts

    token = "short-lived-" + "x" * 43
    result = SourceConnectorInstaller(client_factory=client).start(
        {
            "source_cluster_id": "SRC-" + "b" * 32,
            "delivery_method": "AWS_SSM",
            "delivery_configuration": {
                "accountId": "905418045935",
                "region": "ap-south-1",
                "managedInstanceId": "i-08e28d9b2242cbd53",
                "kubeconfigPath": "/etc/kubernetes/admin.conf",
            },
        },
        token,
    )

    sts.assume_role.assert_called_once_with(
        RoleArn=role_arn,
        RoleSessionName="NaviganSourceConnector-" + "b" * 12,
        ExternalId="SRC-" + "b" * 32,
        DurationSeconds=900,
    )
    secret_value = json.loads(ssm.put_parameter.call_args.kwargs["Value"])
    assert secret_value["enrollmentToken"] == token
    commands = "\n".join(
        ssm.send_command.call_args.kwargs["Parameters"]["commands"]
    )
    assert token not in commands
    assert commands.startswith("set -eu\n")
    assert "pipefail" not in commands
    assert "get-parameter --with-decryption" in commands
    assert "delete-parameter" in commands
    assert result["status"] == "INSTALLATION_STARTED"
