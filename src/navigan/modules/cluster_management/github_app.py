import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from base64 import b64encode, b64decode
from pathlib import PurePosixPath
from urllib.parse import quote

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

    def read_repository_file(self, installation_id, organization, repository_name, path, *, branch="main"):
        """Read an existing file with a token restricted to the selected system repo."""
        token = self.repository_token(installation_id, repository_name)["token"]
        safe_path = "/".join(quote(part, safe="") for part in path.split("/"))
        result = self._request(
            "GET",
            f"/repos/{quote(organization, safe='')}/{quote(repository_name, safe='')}/contents/{safe_path}?ref={quote(branch, safe='')}",
            token,
        )
        if result.get("type") != "file" or result.get("encoding") != "base64":
            raise ApiError(409, "GITOPS_VALUES_INVALID", "Existing connector values must be a readable file.")
        try:
            return b64decode(result["content"]).decode("utf-8")
        except (KeyError, ValueError, UnicodeDecodeError):
            raise ApiError(409, "GITOPS_VALUES_INVALID", "Existing connector values are not valid UTF-8.") from None

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
        revision = self._create_commit(
            repository_path, token, reference["object"]["sha"], files, message
        )
        self._request(
            "PATCH",
            f"{repository_path}/git/refs/heads/{branch}",
            token,
            {"sha": revision, "force": False},
        )
        return {"revision": revision, "branch": branch}

    def _create_commit(self, repository_path, token, parent_sha, files, message):
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
        return commit["sha"]

    def prepare_storage_review(self, repository, files, *, application_path, storage_directory):
        """Publish an additions-only change to a review branch in the selected repository."""
        organization = repository["organization_login"]
        name = repository["repository_name"]
        repository_url = f"https://github.com/{organization}/{name}"
        if repository["repository_url"].casefold() != repository_url.casefold():
            raise ApiError(409, "SYSTEM_REPOSITORY_MISMATCH", "The approved system repository URL differs.")
        base = repository["default_branch"]
        review = "navigan/ebs-csi-storage"
        conflict = ApiError(
            409,
            "EBS_CSI_GITOPS_CONFLICT",
            "The system repository already has different storage manifests or review changes.",
        )
        if base == review:
            raise conflict
        token = self.repository_token(repository["installation_id"], name, write=True)["token"]
        path = f"/repos/{quote(organization, safe='')}/{quote(name, safe='')}"
        base_sha = self._request("GET", f"{path}/git/ref/heads/{quote(base, safe='/')}", token)["object"]["sha"]
        base_commit = self._request("GET", f"{path}/git/commits/{base_sha}", token)
        tree_sha = base_commit["tree"]["sha"]
        snapshot = self._request("GET", f"{path}/git/trees/{tree_sha}?recursive=1", token)
        if snapshot.get("truncated"):
            raise ApiError(
                409, "EBS_CSI_GITOPS_TREE_TRUNCATED",
                "GitHub could not verify the complete storage manifest tree.",
            )
        existing = {entry["path"]: entry for entry in snapshot["tree"]}
        expected = {}
        for filename, content in files.items():
            for directory in PurePosixPath(filename).parents:
                entry = existing.get(directory.as_posix())
                if entry and entry["mode"] != "040000":
                    raise conflict
            data = content.encode()
            expected[filename] = hashlib.sha1(
                f"blob {len(data)}\0".encode() + data, usedforsecurity=False
            ).hexdigest()
            entry = existing.get(filename)
            if entry and (entry["mode"] != "100644" or entry["sha"] != expected[filename]):
                raise conflict
        missing = {filename: content for filename, content in files.items() if filename not in existing}
        if not missing:
            return {"status": "MANIFESTS_PRESENT", "baseBranch": base}
        if application_path in missing and any(
            filename.startswith(storage_directory + "/") and filename not in files
            for filename in existing
        ):
            raise conflict

        review_ref = f"{path}/git/ref/heads/{review}"
        try:
            review_sha = self._request("GET", review_ref, token)["object"]["sha"]
        except ApiError as error:
            if error.status != 404:
                raise
            review_sha = self._create_commit(path, token, base_sha, missing, "Add Navigan EBS storage")
            try:
                self._request("POST", f"{path}/git/refs", token, {
                    "ref": f"refs/heads/{review}",
                    "sha": review_sha,
                })
            except ApiError as race:
                if race.status not in {409, 422}:
                    raise
                try:
                    review_sha = self._request("GET", review_ref, token)["object"]["sha"]
                except ApiError as lookup:
                    if lookup.status == 404:
                        raise race from None
                    raise

        compare = self._request("GET", f"{path}/compare/{base_sha}...{review_sha}", token)
        changes = {entry["filename"]: entry for entry in compare.get("files", [])}
        if (
            compare.get("total_commits") != 1
            or not missing.keys() <= changes.keys() <= expected.keys()
            or any(
                entry["status"] != "added" or entry["sha"] != expected[name]
                for name, entry in changes.items()
            )
        ):
            raise conflict
        return {
            "status": "REVIEW_READY",
            "baseBranch": base,
            "reviewBranch": review,
            "reviewUrl": f"{repository_url}/compare/{quote(base, safe='')}...{quote(review, safe='/')}?expand=1",
        }
