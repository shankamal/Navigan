import json
import os
import time
import urllib.error
import urllib.request
from base64 import b64encode

import boto3
import jwt

from navigan.shared.errors import ApiError


class GitHubApp:
    def __init__(self, secrets_client=None):
        self.secrets = secrets_client or boto3.client("secretsmanager")

    def _private_key(self):
        secret_arn = os.environ.get("GITHUB_APP_PRIVATE_KEY_SECRET_ARN", "").strip()
        if not secret_arn:
            raise ApiError(
                503,
                "GITHUB_APP_NOT_CONFIGURED",
                "The platform GitHub App private key is not configured.",
            )
        value = self.secrets.get_secret_value(SecretId=secret_arn)
        secret = value.get("SecretString")
        if not secret:
            raise ApiError(
                503,
                "GITHUB_APP_KEY_UNAVAILABLE",
                "The platform GitHub App private key is unavailable.",
            )
        try:
            parsed = json.loads(secret)
            return parsed.get("privateKey") or parsed.get("private_key") or secret
        except json.JSONDecodeError:
            return secret

    def _jwt(self):
        app_id = os.environ.get("GITHUB_APP_ID", "").strip()
        if not app_id:
            raise ApiError(
                503,
                "GITHUB_APP_NOT_CONFIGURED",
                "The platform GitHub App ID is not configured.",
            )
        now = int(time.time())
        return jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": app_id},
            self._private_key(),
            algorithm="RS256",
        )

    def _request(self, method, path, token, body=None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            f"https://api.github.com{path}",
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2026-03-10",
                "User-Agent": "Navigan-Cluster-Management",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                content = response.read()
                return json.loads(content) if content else {}
        except urllib.error.HTTPError as error:
            details = error.read().decode(errors="replace")[:1000]
            github_error = ApiError(
                error.code,
                "GITHUB_API_REQUEST_FAILED",
                "GitHub rejected the organization repository request.",
            )
            github_error.github_details = details
            raise github_error from None
        except (urllib.error.URLError, TimeoutError):
            raise ApiError(
                502,
                "GITHUB_API_UNAVAILABLE",
                "GitHub could not complete the organization repository request.",
            ) from None

    def installation(self, installation_id):
        try:
            return self._request(
                "GET", f"/app/installations/{installation_id}", self._jwt()
            )
        except ApiError as error:
            if error.status in {401, 403, 404}:
                raise ApiError(
                    422,
                    "GITHUB_INSTALLATION_NOT_VERIFIED",
                    "The selected GitHub App installation could not be verified.",
                ) from None
            raise

    def installation_token_details(
        self, installation_id, *, permissions=None, repositories=None
    ):
        body = {
            "permissions": permissions
            or {"administration": "write", "contents": "write"}
        }
        if repositories:
            body["repositories"] = repositories
        value = self._request(
            "POST",
            f"/app/installations/{installation_id}/access_tokens",
            self._jwt(),
            body,
        )
        token = value.get("token")
        if not token:
            raise ApiError(
                502,
                "GITHUB_INSTALLATION_TOKEN_UNAVAILABLE",
                "GitHub did not issue a repository provisioning token.",
            )
        return {"token": token, "expiresAt": value.get("expires_at")}

    def installation_token(self, installation_id):
        return self.installation_token_details(installation_id)["token"]

    def repository_token(self, installation_id, repository_name, *, write=False):
        return self.installation_token_details(
            installation_id,
            permissions={"contents": "write" if write else "read"},
            repositories=[repository_name],
        )

    def ensure_private_repository(self, installation_id, organization, name):
        token = self.installation_token(installation_id)
        try:
            return self._request(
                "POST",
                f"/orgs/{organization}/repos",
                token,
                {
                    "name": name,
                    "private": True,
                    "has_issues": False,
                    "has_projects": False,
                    "has_wiki": False,
                    "auto_init": True,
                    "description": "Navigan-managed cluster system services",
                },
            )
        except ApiError as error:
            if error.status != 422:
                raise
            repository = self._request(
                "GET", f"/repos/{organization}/{name}", token
            )
            if not repository.get("private"):
                raise ApiError(
                    409,
                    "GITHUB_REPOSITORY_NOT_PRIVATE",
                    "The existing system repository must be private.",
                )
            return repository

    def commit_files(
        self,
        installation_id,
        organization,
        repository_name,
        files,
        *,
        branch="main",
        message="Initialize Navigan system repository",
    ):
        """Atomically create or replace the managed repository files."""
        token = self.repository_token(
            installation_id, repository_name, write=True
        )["token"]
        repository_path = f"/repos/{organization}/{repository_name}"
        try:
            reference = self._request(
                "GET", f"{repository_path}/git/ref/heads/{branch}", token
            )
        except ApiError as error:
            if error.status != 404:
                raise
            repository = self._request("GET", repository_path, token)
            branch = repository.get("default_branch") or branch
            reference = self._request(
                "GET", f"{repository_path}/git/ref/heads/{branch}", token
            )
        parent_sha = reference["object"]["sha"]
        parent = self._request(
            "GET", f"{repository_path}/git/commits/{parent_sha}", token
        )
        entries = []
        for path, content in sorted(files.items()):
            blob = self._request(
                "POST",
                f"{repository_path}/git/blobs",
                token,
                {
                    "content": b64encode(content.encode()).decode(),
                    "encoding": "base64",
                },
            )
            entries.append(
                {
                    "path": path,
                    "mode": "100644",
                    "type": "blob",
                    "sha": blob["sha"],
                }
            )
        tree = self._request(
            "POST",
            f"{repository_path}/git/trees",
            token,
            {"base_tree": parent["tree"]["sha"], "tree": entries},
        )
        commit = self._request(
            "POST",
            f"{repository_path}/git/commits",
            token,
            {
                "message": message,
                "tree": tree["sha"],
                "parents": [parent_sha],
            },
        )
        self._request(
            "PATCH",
            f"{repository_path}/git/refs/heads/{branch}",
            token,
            {"sha": commit["sha"], "force": False},
        )
        return {"revision": commit["sha"], "branch": branch}
