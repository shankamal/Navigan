"""Source-only credentials and bounded HTTPS registry reads. Never return credential values."""

import base64
import copy
import hashlib
import http.client
import ipaddress
import json
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


def registry_read(host, credential, path="/v2/", repository=None, aws=False):
    endpoint = "registry-1.docker.io" if host == "docker.io" else host
    mode = credential.get("mode", "PUBLIC")
    auth = None
    if aws:
        import boto3

        match = re.fullmatch(r"([0-9]{12})\.dkr\.ecr\.([a-z0-9-]+)\.amazonaws\.com", host)
        if not match:
            raise ValueError("Invalid ECR registry.")
        from botocore.config import Config

        data = boto3.client(
            "ecr",
            region_name=match[2],
            config=Config(connect_timeout=2, read_timeout=3, retries={"max_attempts": 0}),
        ).get_authorization_token(registryIds=[match[1]])["authorizationData"][0]
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
        raise ValueError("Registry access failed.")
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
            not github and mode not in {"PUBLIC", "AWS_IAM", "TOKEN", "BEARER"}
        ):
            raise ApiError(
                400, "INVALID_AUTHENTICATION", "Choose an authentication method supported by this connection."
            )
        old = result[key]
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
            if mode == "AWS_IAM":
                host = key.removeprefix("registry:")
                match = re.fullmatch(r"([0-9]{12})\.dkr\.ecr\.([a-z0-9-]+)\.amazonaws\.com", host)
                if not match or match[1] != (source.get("delivery_configuration") or {}).get("accountId"):
                    raise ApiError(
                        400,
                        "REGISTRY_ACCOUNT_MISMATCH",
                        "Use an ECR registry in the registered source AWS account.",
                    )
            result[key] = {"mode": mode, "secretConfigured": False, "status": "NOT_VERIFIED"}
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
                    host = key[9:]
                    credential = {"mode": entry["mode"], **read_credential(source, key, entry)}
                    registry_read(host, credential, aws=entry["mode"] == "AWS_IAM")
                    message = (
                        "Registry API access verified. Each referenced image is checked during discovery."
                    )
                entry.update(
                    status="CONNECTED", message=message, verifiedAt=datetime.now(timezone.utc).isoformat()
                )
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
            for key in [
                *("github:" + r["repository"] for r in configuration["repositories"]),
                *("registry:" + h for h in configuration["registries"]),
            ]
        )
    )
