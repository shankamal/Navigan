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


def test_generated_installations_have_disjoint_deployments_credentials_selectors_and_rbac(tmp_path, monkeypatch):
    import io
    import subprocess
    import sys
    import urllib.request
    import yaml
    from navigan.modules.migration_management.source_connector_installation import INSTALLER

    applied = []
    rollouts = []
    def run(command, **kwargs):
        if command[-3:] == ['apply', '-f', '-']:
            applied.append(list(yaml.safe_load_all(kwargs['input'])))
        else:
            rollouts.append(command)
    monkeypatch.setattr(subprocess, 'run', run)
    monkeypatch.setattr(subprocess, 'check_output', lambda *args, **kwargs: 'test-ecr-password')
    monkeypatch.setattr(urllib.request, 'urlopen', lambda *args, **kwargs: io.BytesIO(json.dumps({
        'connectorId': 'SCC-' + 'c' * 32, 'connectorToken': 't' * 43,
    }).encode()))
    for suffix in ['a' * 32, 'b' * 32, 'a' * 32]:
        bootstrap = tmp_path / 'bootstrap.json'
        bootstrap.write_text(json.dumps({
            'sourceClusterId': 'SRC-' + suffix, 'enrollmentToken': 'e' * 43,
            'apiBaseUrl': 'https://api.example.test/v1/api/v1',
            'imageRepository': '905418045935.dkr.ecr.ap-south-1.amazonaws.com/connector',
            'imageDigest': 'sha256:' + 'd' * 64, 'kubeconfigPath': '/etc/kubernetes/admin.conf',
        }))
        monkeypatch.setattr(sys, 'argv', ['installer.py', str(bootstrap)])
        exec(compile(INSTALLER, 'installer.py', 'exec'), {})
        assert bootstrap.read_text() == ''

    def keys(documents):
        return {(d['kind'], d['metadata'].get('namespace'), d['metadata']['name'])
                for d in documents if d['kind'] != 'Namespace'}
    assert not keys(applied[0]) & keys(applied[1])
    assert keys(applied[0]) == keys(applied[2])  # Retry the same registration, no duplicate agent.
    for documents, rollout in zip(applied, rollouts):
        docs = {d['kind']: d for d in documents if d['kind'] != 'Secret'}
        name = docs['Deployment']['metadata']['name']
        pod = docs['Deployment']['spec']['template']
        assert name.startswith('navigan-source-') and name != 'navigan-source-connector'
        assert docs['Deployment']['spec']['selector']['matchLabels'] == pod['metadata']['labels']
        assert pod['spec']['serviceAccountName'] == docs['ServiceAccount']['metadata']['name'] == name
        assert docs['ClusterRoleBinding']['metadata']['name'] == name
        assert docs['ClusterRoleBinding']['roleRef']['name'] == docs['ClusterRole']['metadata']['name'] == name
        assert docs['ClusterRoleBinding']['subjects'][0]['name'] == name
        secrets = {d['metadata']['name'] for d in documents if d['kind'] == 'Secret'}
        assert secrets == {name + '-credentials', name + '-image-pull'}
        assert pod['spec']['imagePullSecrets'] == [{'name': name + '-image-pull'}]
        token_env = next(e for e in pod['spec']['containers'][0]['env'] if e['name'] == 'NAVIGAN_SOURCE_CONNECTOR_TOKEN')
        assert token_env['valueFrom']['secretKeyRef']['name'] == name + '-credentials'
        assert 'deployment/' + name in rollout
        assert all(verb in {'get', 'list'} for rule in docs['ClusterRole']['rules'] for verb in rule['verbs'])
