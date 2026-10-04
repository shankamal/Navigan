from navigan.modules.environment_management.provisioning_options import (
    register_provisioning_external_id,
    trusted_external_ids,
)


def test_extracts_external_id_from_provisioning_role_trust():
    assert trusted_external_ids(
        {
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": "sts:AssumeRole",
                    "Condition": {
                        "StringEquals": {
                            "sts:ExternalId": "customer-provisioning-id"
                        }
                    },
                }
            ]
        }
    ) == {"customer-provisioning-id"}


def test_ignores_trust_without_an_external_id():
    assert trusted_external_ids(
        {"Statement": {"Effect": "Allow", "Action": "sts:AssumeRole"}}
    ) == set()


class FakeSecrets:
    class exceptions:
        class ResourceNotFoundException(Exception):
            pass

    def get_secret_value(self, SecretId):
        raise self.exceptions.ResourceNotFoundException()

    def create_secret(self, **kwargs):
        self.created = kwargs
        return {"ARN": f"arn:aws:secretsmanager:region:account:secret:{kwargs['Name']}"}


class FakeBoto:
    def __init__(self):
        self.secrets = FakeSecrets()

    def client(self, service):
        assert service == "secretsmanager"
        return self.secrets


def test_registers_account_scoped_external_id():
    boto = FakeBoto()
    result = register_provisioning_external_id(
        "CUS-example",
        "123456789012",
        "trusted-value",
        boto,
    )
    assert result["name"] == (
        "navigan/provisioning/CUS-example/123456789012/external-id"
    )
    assert boto.secrets.created["SecretString"] == "trusted-value"
