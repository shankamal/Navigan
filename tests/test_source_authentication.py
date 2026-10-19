import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from navigan.modules.migration_management import source_authentication as auth
from navigan.modules.migration_management.deployment_sources import SaveDeploymentSources
from navigan.shared.errors import ApiError


@pytest.fixture
def source():
    return {
        "customer_id": "CUS-db",
        "source_cluster_id": "SRC-db",
        "delivery_configuration": {"accountId": "905418045935"},
    }


@pytest.fixture
def store(monkeypatch):
    class Exists(Exception):
        pass

    class Store:
        exceptions = SimpleNamespace(ResourceExistsException=Exists)
        values = {}

        def create_secret(self, Name, SecretString, ClientRequestToken):
            if any(k[0] == Name for k in self.values):
                raise Exists()
            self.values[Name, ClientRequestToken] = SecretString

        def put_secret_value(self, SecretId, SecretString, ClientRequestToken):
            self.values[SecretId, ClientRequestToken] = SecretString

        def get_secret_value(self, SecretId, VersionId):
            return {"SecretString": self.values[SecretId, VersionId]}

    sm = Store()
    monkeypatch.setattr(auth, "client", lambda: sm)
    return sm


def test_github_url_normalized_and_credential_fields_bounded():
    value = SaveDeploymentSources.model_validate(
        {
            "version": 1,
            "configuration": {
                "repositories": [{"repository": "https://github.com/customer/repo.git", "revision": "main"}]
            },
        }
    )
    assert value.configuration.repositories[0].repository == "customer/repo"
    with pytest.raises(ValidationError):
        SaveDeploymentSources.model_validate(
            {
                "version": 1,
                "configuration": {},
                "credentials": [{"key": "github:c/r", "mode": "TOKEN", "token": "x\r\nAuthorization: bad"}],
            }
        )


def test_secret_is_write_only_versioned_and_customer_scoped(source, store):
    config = {
        "repositories": [{"repository": "customer/repo", "revision": "main", "directory": ""}],
        "registries": [],
    }
    change = {"key": "github:customer/repo", "mode": "TOKEN", "token": "read-only-secret"}
    first = auth.configure(source, config, [change], {}, False, lambda _: None)
    assert "read-only-secret" not in json.dumps(first)
    assert auth.read_credential(source, change["key"], first[change["key"]])["token"] == "read-only-secret"
    second = auth.configure(source, config, [{**change, "token": "rotated"}], first, False, lambda _: None)
    assert first[change["key"]]["secretVersion"] != second[change["key"]]["secretVersion"]
    # A failed DB transaction cannot change the credential used by the previously committed metadata.
    assert auth.read_credential(source, change["key"], first[change["key"]])["token"] == "read-only-secret"
    other = {**source, "customer_id": "CUS-other"}
    with pytest.raises(KeyError):
        auth.read_credential(other, change["key"], first[change["key"]])


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fd00::1", "192.168.1.1", "100.64.0.1"]
)
def test_private_network_registry_denied(monkeypatch, address):
    monkeypatch.setattr(auth.socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", (address, 443))])
    with pytest.raises(ValueError):
        auth.public_addresses("registry.example.com")


def test_mixed_dns_answers_denied(monkeypatch):
    monkeypatch.setattr(
        auth.socket,
        "getaddrinfo",
        lambda *a, **kw: [(2, 1, 6, "", ("8.8.8.8", 443)), (2, 1, 6, "", ("10.0.0.1", 443))],
    )
    with pytest.raises(ValueError):
        auth.public_addresses("registry.example.com")


def test_cross_host_challenge_never_receives_password(monkeypatch):
    calls = []

    def request(url, *args):
        calls.append(url)
        return (
            401,
            {"www-authenticate": 'Bearer realm="https://attacker.example/token",service="registry"'},
            b"",
        )

    monkeypatch.setattr(auth, "request", request)
    with pytest.raises(ValueError):
        auth.registry_read("registry.example.com", {"mode": "TOKEN", "username": "robot", "token": "private"})
    assert calls == ["https://registry.example.com/v2/"]


def test_challenge_scope_is_read_only_and_not_copied_from_server(monkeypatch):
    calls = []

    def request(url, authorization=None, accept=None):
        calls.append((url, authorization))
        if len(calls) == 1:
            return (
                401,
                {
                    "www-authenticate": 'Bearer realm="https://registry.example.com/token",service="registry",scope="repository:other:pull,push"'
                },
                b"",
            )
        if len(calls) == 2:
            return 200, {}, b'{"token":"scoped"}'
        return 200, {"docker-content-digest": "sha256:" + "a" * 64}, b"{}"

    monkeypatch.setattr(auth, "request", request)
    result = auth.registry_read(
        "registry.example.com",
        {"mode": "TOKEN", "username": "robot", "token": "private"},
        "/v2/team/app/manifests/v1",
        "team/app",
    )
    assert "scope=repository%3Ateam%2Fapp%3Apull" in calls[1][0]
    assert "push" not in calls[1][0] and "other" not in calls[1][0]
    assert calls[2][1] == "Bearer scoped"
    assert result["_registryDigest"] == "sha256:" + "a" * 64


def test_failed_access_has_safe_message_and_blocks_discovery(source, monkeypatch):
    config = {"repositories": [], "registries": ["private.example.com"]}

    def fail(*a, **kw):
        raise RuntimeError("UPSTREAM SECRET TOKEN")

    monkeypatch.setattr(auth, "registry_read", fail)
    states = auth.configure(source, config, [], {}, True, lambda _: None)
    assert states["registry:private.example.com"]["status"] == "ACCESS_FAILED"
    assert "UPSTREAM" not in json.dumps(states)
    assert not auth.ready(config, states)
    assert auth.ready({**config, "inventoryOnly": True}, states)


def test_repository_verifies_revision_and_directory_and_reuses_token(source, store, monkeypatch):
    from navigan.modules.migration_management import deployment_sources

    calls = []

    def fetch(url, token=None):
        calls.append((url, token))
        return {"sha": "a" * 40} if "/commits/" in url else []

    monkeypatch.setattr(deployment_sources, "get_json", fetch)
    config = {
        "repositories": [
            {"repository": "customer/repo", "revision": "release/v1", "directory": "deploy/prod"}
        ],
        "registries": [],
    }
    changes = [{"key": "github:customer/repo", "mode": "TOKEN", "token": "readonly"}]
    states = auth.configure(source, config, changes, {}, True, lambda _: None)
    assert states["github:customer/repo"]["status"] == "CONNECTED"
    assert calls[0][0].endswith("/commits/release%2Fv1")
    assert calls[1][0].endswith("/contents/deploy/prod?ref=" + "a" * 40)
    assert all(token == "readonly" for _, token in calls)
    assert not auth.ready(config, states)  # registry access must also be supplied, or inventory-only selected
    changed = auth.configure(source, config, [], states, False, lambda _: None)
    assert changed["github:customer/repo"]["status"] == "NOT_VERIFIED"


def test_registry_account_is_independent_but_unconfigured_secret_is_rejected(source, store):
    config = {"repositories": [], "registries": ["111111111111.dkr.ecr.ap-south-1.amazonaws.com"]}
    states = auth.configure(
        source,
        config,
        [{"key": "registry:" + config["registries"][0], "mode": "AWS_IAM"}],
        {},
        False,
        lambda _: None,
    )
    assert states["registry:" + config["registries"][0]]["accountId"] == "111111111111"
    with pytest.raises(ApiError):
        auth.configure(
            source,
            config,
            [{"key": "github:other/repo", "mode": "TOKEN", "token": "private"}],
            {},
            False,
            lambda _: None,
        )
    assert not store.values


def test_save_returns_only_safe_metadata_and_reuses_versioned_secret(monkeypatch, source, store):
    from copy import deepcopy
    from unittest.mock import MagicMock
    from navigan.modules.migration_management.service import Service
    from navigan.modules.migration_management.repository import serialize

    monkeypatch.setenv("MIGRATION_SOURCE_FIRST_ENABLED", "true")
    source.update(version=1, created_by="engineer")
    repo = MagicMock()
    repo.principal = SimpleNamespace(user_id="engineer")
    repo.get_source_cluster.side_effect = lambda *a, **kw: deepcopy(source)
    repo.deployment_connections.return_value = []

    def save(row, key, value, correlation):
        assert row["version"] == source["version"]
        source["delivery_configuration"][key] = deepcopy(value)
        source["version"] += 1
        return deepcopy(source)

    repo.save_deployment_configuration.side_effect = save
    service = Service(repo, MagicMock(), "corr")
    body = SaveDeploymentSources.model_validate(
        {
            "version": 1,
            "configuration": {"repositories": [{"repository": "customer/repo"}], "registries": []},
            "credentials": [{"key": "github:customer/repo", "mode": "TOKEN", "token": "secret-value"}],
        }
    ).model_dump()
    response = service.save_deployment_sources("SRC-db", body)
    assert response["version"] == 3
    assert response["authentication"]["github:customer/repo"]["secretConfigured"]
    assert "secretVersion" not in json.dumps(response)
    assert "secret-value" not in json.dumps(response)
    assert "deploymentAuthentication" not in serialize(source)["deliveryConfiguration"]
    service.access.require_customer.assert_called_with("CUS-db", "engineer")
    # Stale saves reject before credential operations.
    with pytest.raises(ApiError) as error:
        service.save_deployment_sources("SRC-db", body)
    assert error.value.code == "CONCURRENT_UPDATE"


def test_app_auth_requires_existing_installation(source):
    with pytest.raises(ValueError):
        auth.repository_token(source, "customer/repo", {"mode": "APP"}, lambda _: None)
    assert auth.repository_token(source, "customer/repo", {"mode": "PUBLIC"}, lambda _: "not-used") is None


def test_discovery_and_refresh_are_gated_in_backend(monkeypatch, source):
    from unittest.mock import MagicMock
    from navigan.modules.migration_management.service import Service

    monkeypatch.setenv("MIGRATION_SOURCE_FIRST_ENABLED", "true")
    repo = MagicMock()
    repo.principal = SimpleNamespace(user_id="engineer")
    migration = {
        "migration_id": "MIG-db",
        "customer_id": "CUS-db",
        "created_by": "engineer",
        "source_configuration": {"sourceClusterId": "SRC-db"},
        "status": "DRAFT",
        "version": 1,
    }
    repo.get.return_value = migration
    repo.get_source_cluster.return_value = source
    service = Service(repo, MagicMock(), "corr")
    with pytest.raises(ApiError) as error:
        service.change("MIG-db", "discover", {"version": 1})
    assert error.value.code == "SOURCE_CONNECTIONS_REQUIRED"
    repo.save.assert_not_called()
    repo.create_discovery_connector.assert_not_called()
    migration["status"] = "ASSESSMENT_READY"
    with pytest.raises(ApiError) as error:
        service.analyze_deployment_sources("MIG-db", {"version": 1, "refreshCluster": True})
    assert error.value.code == "SOURCE_CONNECTIONS_REQUIRED"
    repo.save.assert_not_called()


def test_customer_ecr_role_is_bound_to_registry_not_cluster_account(source):
    host = "111111111111.dkr.ecr.us-west-2.amazonaws.com"
    config = {"repositories": [], "registries": [host]}
    key = "registry:" + host
    change = {
        "key": key,
        "mode": "AWS_ROLE",
        "roleArn": "arn:aws:iam::111111111111:role/navigan-source-discovery/RegistryReadOnly",
    }
    first = auth.configure(source, config, [change], {}, False, lambda _: None)
    entry = first[key]
    assert entry["accountId"] == "111111111111"
    assert entry["region"] == "us-west-2"
    assert entry["externalId"].startswith("navigan-")
    second = auth.configure(source, config, [change], first, False, lambda _: None)
    assert second[key]["externalId"] == entry["externalId"]
    other = auth.configure(
        {**source, "customer_id": "CUS-other"}, config, [change], {}, False, lambda _: None
    )
    assert other[key]["externalId"] != entry["externalId"]
    for role in [
        "arn:aws:iam::905418045935:role/navigan-source-discovery/Role",
        "arn:aws:iam::111111111111:role/Admin",
    ]:
        with pytest.raises(ApiError):
            auth.configure(source, config, [{**change, "roleArn": role}], {}, False, lambda _: None)


def test_ecr_role_uses_temporary_session_and_tests_external_id():
    from unittest.mock import MagicMock
    from botocore.exceptions import ClientError

    aws = MagicMock()
    sts = MagicMock()
    ecr = MagicMock()
    aws.client.side_effect = lambda kind, **kw: sts if kind == "sts" else ecr

    def assume(**kwargs):
        if kwargs.get("ExternalId") != "navigan-bound-id":
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "AssumeRole")
        return {
            "Credentials": {
                "AccessKeyId": "temporary-key",
                "SecretAccessKey": "temporary-secret",
                "SessionToken": "temporary-session",
            }
        }

    sts.assume_role.side_effect = assume
    entry = {
        "mode": "AWS_ROLE",
        "roleArn": "arn:aws:iam::111111111111:role/navigan-source-discovery/ReadOnly",
        "externalId": "navigan-bound-id",
    }
    assert (
        auth.ecr_client(
            "111111111111.dkr.ecr.eu-west-1.amazonaws.com", entry, verify_trust=True, boto3_module=aws
        )
        is ecr
    )
    calls = sts.assume_role.call_args_list
    assert len(calls) == 3
    assert "ExternalId" not in calls[0].kwargs
    assert calls[1].kwargs["ExternalId"] != "navigan-bound-id"
    assert calls[2].kwargs["ExternalId"] == "navigan-bound-id"
    policy = json.loads(calls[2].kwargs["Policy"])
    assert policy["Statement"][1]["Resource"] == "arn:aws:ecr:eu-west-1:111111111111:repository/*"
    assert policy["Statement"][1]["Action"] == ["ecr:DescribeImages"]
    assert calls[2].kwargs["DurationSeconds"] == 900
    assert aws.client.call_args.kwargs["aws_session_token"] == "temporary-session"
    assert "temporary" not in json.dumps(entry)


def test_role_without_external_id_enforcement_is_rejected():
    from unittest.mock import MagicMock

    aws = MagicMock()
    entry = {
        "mode": "AWS_ROLE",
        "roleArn": "arn:aws:iam::111111111111:role/navigan-source-discovery/ReadOnly",
        "externalId": "navigan-bound-id",
    }
    with pytest.raises(ValueError, match="trust must require"):
        auth.ecr_client(
            "111111111111.dkr.ecr.eu-west-1.amazonaws.com", entry, verify_trust=True, boto3_module=aws
        )
    assert aws.client.call_count == 1  # STS only; an over-permissive role never becomes an ECR client
    with pytest.raises(ValueError, match="Verify role trust"):
        auth.ecr_client("111111111111.dkr.ecr.eu-west-1.amazonaws.com", entry, boto3_module=aws)


def test_cloud_registry_token_is_independent_of_source_account(source, store, monkeypatch):
    seen = []
    monkeypatch.setattr(auth, "registry_read", lambda host, credential, **kw: seen.append((host, credential)))
    host = "customer.azurecr.io"
    config = {"repositories": [], "registries": [host]}
    states = auth.configure(
        source,
        config,
        [{"key": "registry:" + host, "mode": "TOKEN", "username": "robot", "token": "read-token"}],
        {},
        True,
        lambda _: None,
    )
    assert states["registry:" + host]["status"] == "CONNECTED"
    assert seen[0][0] == host and seen[0][1]["token"] == "read-token"
