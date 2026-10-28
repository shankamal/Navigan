"""Source-only credentials and bounded HTTPS registry reads. Never return credential values."""

import base64
import copy
import hashlib
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import time
import urllib.parse
from datetime import datetime, timezone
from uuid import uuid4

from navigan.shared.errors import ApiError

PREFIX = "navigan/source-connections/"


def secret_name(source, key):
    return (
        PREFIX
        + source["customer_id"]
        + "/"
        + source["source_cluster_id"]
        + "/"
        + hashlib.sha256(key.encode()).hexdigest()[:24]
    )


def client():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "secretsmanager", config=Config(connect_timeout=2, read_timeout=3, retries={"max_attempts": 0})
    )


def read_credential(source, key, entry):
    # Never accept a caller-supplied ARN. Each name is derived from authorized customer/source identity.
    if not entry.get("secretConfigured"):
        return {}
    return json.loads(
        client().get_secret_value(
            SecretId=secret_name(source, key),
            **({"VersionId": entry["secretVersion"]} if entry.get("secretVersion") else {}),
        )["SecretString"]
    )


def public_addresses(host):
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("Registry must resolve exclusively to public addresses.")
    return addresses


class PinnedHTTPS(http.client.HTTPSConnection):
    def connect(self):
        # Pin the connection to the vetted DNS result while retaining TLS hostname verification/SNI.
        addresses = public_addresses(self.host)
        address = addresses[0]
        sock = socket.socket(address[0], address[1], address[2])
        sock.settimeout(self.timeout)
        try:
            sock.connect(address[4])
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise


def request(url, authorization=None, accept=None):
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 443}
        or parsed.fragment
    ):
        raise ValueError("Use a public HTTPS registry without credentials in its URL.")
    conn = PinnedHTTPS(parsed.hostname, timeout=3, context=ssl.create_default_context())
    headers = {"Accept": accept or "application/json", "User-Agent": "Navigan-Source-Discovery"}
    if authorization:
        headers["Authorization"] = authorization
    try:
        conn.request("GET", parsed.path + ("?" + parsed.query if parsed.query else ""), headers=headers)
        response = conn.getresponse()
        raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("Registry response exceeds limit.")
        if response.status not in {200, 401}:
            raise ValueError("Registry access failed.")
        return response.status, dict((k.lower(), v) for k, v in response.getheaders()), raw
    finally:
        conn.close()


def registry_provider(host):
    if re.fullmatch(r"[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com", host):
        return "AWS_ECR"
    if host.endswith(".azurecr.io"):
        return "AZURE_ACR"
    if host.endswith((".pkg.dev", ".gcr.io")) or host == "gcr.io":
        return "GOOGLE_AR"
    return {"docker.io": "DOCKER_HUB", "ghcr.io": "GHCR"}.get(host, "OTHER")


def ecr_identity(host):
    match = re.fullmatch(r"([0-9]{12})\.dkr\.ecr\.([a-z0-9-]+)\.amazonaws\.com", host)
    if not match:
        raise ValueError("Use a supported AWS ECR private registry hostname.")
    return match[1], match[2]


def ecr_session_policy(account, region, pull_repository=None):
    if pull_repository and not re.fullmatch(r"[a-z0-9]+(?:[._-]+[a-z0-9]+)*(?:/[a-z0-9]+(?:[._-]+[a-z0-9]+)*)*", pull_repository):
        raise ValueError("Invalid ECR repository")
    return {
        "Version": "2012-10-17",
        "Statement": [
            {"Effect": "Allow", "Action": ["ecr:GetAuthorizationToken"], "Resource": "*"},
            {
                "Effect": "Allow",
                "Action": ["ecr:DescribeImages"] + (["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"] if pull_repository else []),
                "Resource": f"arn:aws:ecr:{region}:{account}:repository/" + (pull_repository or "*"),
            },
        ],
    }


class RegistryRoleAuthorizationRequired(ValueError):
    pass


def registry_role_allowed(role):
    # Additional ARNs are configured by the deployment operator, never by a browser request.
    try:
        allowed = json.loads(os.environ.get("SOURCE_REGISTRY_ALLOWED_ROLE_ARNS", "[]"))
    except (ValueError, TypeError):
        return False
    if not isinstance(allowed, list) or any(not isinstance(v, str) for v in allowed):
        return False
    return bool(
        re.fullmatch(r"arn:aws:iam::[0-9]{12}:role/navigan-source-discovery/[A-Za-z0-9+=,.@_-]+", role)
    ) or role in {v.strip() for v in allowed if v.strip()}


def validate_registry_role(host, role, mode):
    account, _ = ecr_identity(host)
    if not re.fullmatch(
        r"arn:aws:iam::" + account + r":role/[A-Za-z0-9+=,.@_-]+(?:/[A-Za-z0-9+=,.@_-]+)*", role
    ):
        raise ValueError("Enter an IAM role ARN in the registry account.")
    if mode == "AWS_ROLE" and not re.fullmatch(
        r"arn:aws:iam::" + account + r":role/navigan-source-discovery/[A-Za-z0-9+=,.@_-]+", role
    ):
        raise ValueError(
            "New role setup uses the navigan-source-discovery/ IAM path. Choose Existing IAM role to reuse another role."
        )


def ecr_client(host, entry, *, verify_trust=False, boto3_module=None, pull_repository=None):
    if boto3_module is None:
        import boto3 as boto3_module
    from botocore.config import Config

    account, region = ecr_identity(host)
    options = {
        "region_name": region,
        "config": Config(connect_timeout=2, read_timeout=2, retries={"max_attempts": 0}),
    }
    if entry.get("mode") not in {"AWS_ROLE", "AWS_EXISTING_ROLE"}:
        return boto3_module.client("ecr", **options)
    role = entry.get("roleArn", "")
    validate_registry_role(host, role, entry.get("mode"))
    if not entry.get("externalId"):
        raise ValueError("Save the connection to generate an External ID.")
    if not registry_role_allowed(role):
        raise RegistryRoleAuthorizationRequired(
            "The deployment administrator must authorize this exact existing role ARN using --registry-role-arn before verification. Its trust policy must also require the displayed External ID."
        )
    sts = boto3_module.client("sts", **options)
    request = {
        "RoleArn": role,
        "RoleSessionName": "NaviganRegistryDiscovery",
        "DurationSeconds": 900,
        "Policy": json.dumps(ecr_session_policy(account, region, pull_repository)),
    }
    if verify_trust:
        # Reject trusts that ignore the customer-bound External ID. No credentials from negative tests are used.
        for bad_id in (None, "navigan-invalid-" + str(uuid4())):
            try:
                sts.assume_role(**request, **({"ExternalId": bad_id} if bad_id else {}))
            except Exception as error:
                if getattr(error, "response", {}).get("Error", {}).get("Code") not in {
                    "AccessDenied",
                    "AccessDeniedException",
                }:
                    raise
            else:
                raise ValueError("Role trust must require the exact Navigan-generated External ID.")
    elif not entry.get("trustValidated") or entry.get("status") != "CONNECTED":
        raise ValueError("Verify role trust before image analysis.")
    credentials = sts.assume_role(**request, ExternalId=entry["externalId"])["Credentials"]
    return boto3_module.client(
        "ecr",
        **options,
        aws_access_key_id=credentials["AccessKeyId"],
        aws_secret_access_key=credentials["SecretAccessKey"],
        aws_session_token=credentials["SessionToken"],
    )


def registry_read(host, credential, path="/v2/", repository=None, aws=False, aws_client=None):
    endpoint = "registry-1.docker.io" if host == "docker.io" else host
    mode = credential.get("mode", "PUBLIC")
    auth = None
    if aws:
        account, _ = ecr_identity(host)
        data = (aws_client or ecr_client(host, credential)).get_authorization_token(registryIds=[account])[
            "authorizationData"
        ][0]
        auth = "Basic " + data["authorizationToken"]
    elif mode == "TOKEN":
        auth = (
            "Basic "
            + base64.b64encode((credential["username"] + ":" + credential["token"]).encode()).decode()
        )
    elif mode == "BEARER":
        auth = "Bearer " + credential["token"]
    accept = "application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json"
    status, headers, raw = request("https://" + endpoint + path, auth, accept)
    if status == 401:
        challenge = headers.get("www-authenticate", "")
        if not challenge.lower().startswith("bearer "):
            raise ValueError("Registry credentials were rejected.")
        options = dict(re.findall(r'([a-z]+)="([^"\r\n]*)"', challenge[7:]))
        realm = urllib.parse.urlsplit(options.get("realm", ""))
        # Credentials never travel to an arbitrary challenge host. Hosted registries with a separate
        # token server can use a pre-issued bearer token rather than forwarding their password.
        allowed = {endpoint, "auth.docker.io"} if host == "docker.io" else {endpoint}
        if realm.hostname not in allowed or realm.scheme != "https" or realm.query:
            raise ValueError("Separate registry token service requires a read-only bearer token.")
        # GHCR issues anonymous pull tokens for a repository, but rejects the
        # unscoped token request used by a registry-wide setup probe. A valid
        # root challenge establishes endpoint reachability only. Manifest reads
        # still negotiate their own repository-scoped token and require HTTP 200.
        if (
            host == "ghcr.io"
            and mode == "PUBLIC"
            and not aws
            and path == "/v2/"
            and repository is None
            and options.get("realm") == "https://ghcr.io/token"
            and options.get("service") == "ghcr.io"
        ):
            return {"_publicRegistryProbe": "ENDPOINT_REACHABLE"}
        query = {"service": options.get("service", endpoint)}
        if repository:
            query["scope"] = "repository:" + repository + ":pull"
        token_auth = auth if mode == "TOKEN" else None
        token_status, _, token_raw = request(
            urllib.parse.urlunsplit(realm) + "?" + urllib.parse.urlencode(query), token_auth
        )
        if token_status != 200:
            raise ValueError("Registry authentication failed.")
        payload = json.loads(token_raw)
        token = payload.get("token") or payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise ValueError("Registry authentication did not issue an access token.")
        status, headers, raw = request("https://" + endpoint + path, "Bearer " + token, accept)
    if status != 200:
        error = ValueError("Registry access failed.")
        error.registry_status = status
        raise error
    result = json.loads(raw or b"{}")
    if headers.get("docker-content-digest"):
        result["_registryDigest"] = headers["docker-content-digest"]
    return result


def repository_token(source, repository, entry, app_token):
    if entry.get("mode") == "TOKEN":
        return read_credential(source, "github:" + repository, entry)["token"]
    if entry.get("mode") == "PUBLIC":
        return None
    token = app_token(repository)
    if entry.get("mode") == "APP" and not token:
        raise ValueError(
            "Connect a customer GitHub App with access to this repository, or use a read-only token."
        )
    return token


def configure(source, configuration, credentials, previous, verify, app_token):
    """Credentials are write-only. Saved metadata contains mode/status, never token/username."""
    from .deployment_sources import get_json

    deadline = time.monotonic() + 12
    keys = {"github:" + r["repository"] for r in configuration["repositories"]} | {
        "registry:" + h for h in configuration["registries"]
    }
    result = {
        key: copy.deepcopy(
            previous.get(
                key, {"mode": "APP" if key.startswith("github:") else "PUBLIC", "status": "NOT_VERIFIED"}
            )
        )
        for key in keys
    }
    if len({c["key"] for c in credentials}) != len(credentials):
        raise ApiError(400, "DUPLICATE_CONNECTION", "Configure each connection once.")
    for change in credentials:
        if time.monotonic() >= deadline:
            raise ApiError(
                503,
                "CONNECTION_TIME_LIMIT",
                "Connection setup time limit reached. Save fewer credential changes at once and retry.",
            )
        key = change["key"]
        if key not in keys:
            raise ApiError(
                400, "INVALID_CONNECTION", "Save credentials only for a configured repository or registry."
            )
        mode = change["mode"]
        github = key.startswith("github:")
        if (github and mode not in {"PUBLIC", "APP", "TOKEN"}) or (
            not github and mode not in {"PUBLIC", "AWS_ROLE", "AWS_EXISTING_ROLE", "TOKEN", "BEARER"}
        ):
            raise ApiError(
                400, "INVALID_AUTHENTICATION", "Choose an authentication method supported by this connection."
            )
        old = result[key]
        provider = ""
        if not github:
            detected = registry_provider(key[9:])
            provider = change.get("provider") or old.get("provider") or detected
            if provider not in {
                "AWS_ECR",
                "AZURE_ACR",
                "GOOGLE_AR",
                "DOCKER_HUB",
                "GHCR",
                "HARBOR",
                "OTHER",
            } or (detected != "OTHER" and provider != detected):
                raise ApiError(
                    400, "REGISTRY_PROVIDER_MISMATCH", "Select the provider matching the registry hostname."
                )
            if (
                (provider == "AWS_ECR" and mode not in {"AWS_ROLE", "AWS_EXISTING_ROLE"})
                or (provider != "AWS_ECR" and mode in {"AWS_ROLE", "AWS_EXISTING_ROLE"})
                or (provider == "GOOGLE_AR" and mode == "BEARER")
            ):
                raise ApiError(
                    400,
                    "INVALID_AUTHENTICATION",
                    "Select a connection method supported by this registry provider.",
                )
            if (
                provider == "GOOGLE_AR"
                and mode == "TOKEN"
                and change.get("token")
                and change.get("username") != "oauth2accesstoken"
            ):
                raise ApiError(
                    400,
                    "INVALID_REGISTRY_USERNAME",
                    "Google access-token authentication uses username oauth2accesstoken.",
                )
        secret = change.get("token", "")
        if mode in {"TOKEN", "BEARER"}:
            if not secret and (old.get("mode") != mode or not old.get("secretConfigured")):
                raise ApiError(
                    400, "CREDENTIAL_REQUIRED", "Enter a read-only token for the selected connection."
                )
            if secret:
                if not github and mode == "TOKEN" and not change.get("username"):
                    raise ApiError(400, "USERNAME_REQUIRED", "Enter the registry username for this token.")
                # Deterministic, customer/source-scoped names permit rotation without dangling new secrets.
                sm = client()
                value = json.dumps({"token": secret, "username": change.get("username", ""), "mode": mode})
                name = secret_name(source, key)
                version = str(uuid4())
                try:
                    sm.create_secret(Name=name, SecretString=value, ClientRequestToken=version)
                except sm.exceptions.ResourceExistsException:
                    sm.put_secret_value(SecretId=name, SecretString=value, ClientRequestToken=version)
            else:
                version = old.get("secretVersion")
            result[key] = {
                "mode": mode,
                "secretConfigured": True,
                "secretVersion": version,
                "status": "NOT_VERIFIED",
            }
        else:
            role_data = {}
            if mode in {"AWS_ROLE", "AWS_EXISTING_ROLE"}:
                host = key.removeprefix("registry:")
                try:
                    account, region = ecr_identity(host)
                except ValueError:
                    raise ApiError(
                        400,
                        "INVALID_ECR_HOST",
                        "Use an AWS ECR private registry hostname for IAM authentication.",
                    ) from None
                role_data.update(accountId=account, region=region)
                if mode in {"AWS_ROLE", "AWS_EXISTING_ROLE"}:
                    role = change.get("roleArn") or old.get("roleArn", "")
                    try:
                        validate_registry_role(host, role, mode)
                    except ValueError as error:
                        raise ApiError(400, "INVALID_REGISTRY_ROLE", str(error)) from None
                    role_data.update(
                        roleArn=role, externalId=old.get("externalId") or "navigan-" + str(uuid4())
                    )
            result[key] = {"mode": mode, "secretConfigured": False, "status": "NOT_VERIFIED", **role_data}
        if not github:
            result[key]["provider"] = provider
    # Revision/directory changes invalidate repository verification, even if credentials are unchanged.
    before = (source.get("delivery_configuration") or {}).get("deploymentDiscovery", {})
    for entry in configuration["repositories"]:
        if entry not in before.get("repositories", []):
            connection = result["github:" + entry["repository"]]
            connection["status"] = "NOT_VERIFIED"
            connection.pop("verifiedAt", None)
            connection.pop("message", None)
    if verify:
        for key in sorted(result):
            entry = result[key]
            if time.monotonic() >= deadline:
                entry.update(status="NOT_VERIFIED", message="Verification time limit reached. Verify again.")
                continue
            try:
                if key.startswith("github:"):
                    name = key[7:]
                    repo = next(r for r in configuration["repositories"] if r["repository"] == name)
                    token = repository_token(source, name, entry, app_token)
                    prefix = "https://api.github.com/repos/" + name
                    commit = get_json(
                        prefix + "/commits/" + urllib.parse.quote(repo["revision"], safe=""), token
                    )["sha"]
                    get_json(
                        prefix
                        + "/contents/"
                        + urllib.parse.quote(repo["directory"], safe="/")
                        + "?ref="
                        + commit,
                        token,
                    )
                    message = "Repository contents, revision and directory are accessible."
                else:
                    if entry["mode"] == "AWS_IAM":
                        raise ValueError("Replace legacy platform IAM access with a customer registry role.")
                    host = key[9:]
                    credential = {"mode": entry["mode"], **read_credential(source, key, entry)}
                    aws_mode = entry["mode"] in {"AWS_IAM", "AWS_ROLE", "AWS_EXISTING_ROLE"}
                    aws_client = ecr_client(host, entry, verify_trust=True) if aws_mode else None
                    probe = registry_read(host, credential, aws=aws_mode, aws_client=aws_client)
                    if entry["mode"] in {"AWS_ROLE", "AWS_EXISTING_ROLE"}:
                        entry["trustValidated"] = True
                    message = (
                        "Public registry endpoint reachable. Access to each referenced image is checked during analysis."
                        if isinstance(probe, dict) and probe.get("_publicRegistryProbe") == "ENDPOINT_REACHABLE"
                        else "Registry API access verified. Each referenced image is checked during discovery."
                    )
                entry.update(
                    status="CONNECTED", message=message, verifiedAt=datetime.now(timezone.utc).isoformat()
                )
            except RegistryRoleAuthorizationRequired as error:
                entry.update(status="ROLE_AUTHORIZATION_REQUIRED", message=str(error))
                entry.pop("verifiedAt", None)
            except Exception:
                entry.update(
                    status="ACCESS_FAILED",
                    message="Access could not be verified. Check credentials, permissions, endpoint and network access.",
                )
                entry.pop("verifiedAt", None)
    return result


def ready(configuration, authentication):
    return bool(configuration.get("inventoryOnly")) or bool(
        configuration.get("repositories")
        and configuration.get("registries")
        and all(
            authentication.get(key, {}).get("status") == "CONNECTED"
            and authentication.get(key, {}).get("mode") != "AWS_IAM"
            for key in [
                *("github:" + r["repository"] for r in configuration["repositories"]),
                *("registry:" + h for h in configuration["registries"]),
            ]
        )
    )
