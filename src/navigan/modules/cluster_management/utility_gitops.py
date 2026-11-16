"""Headlamp repository evidence and staged, guarded GitOps publication."""

import yaml
from base64 import b64decode
from urllib.parse import quote

from navigan.shared.errors import ApiError
from .github_app import GitHubApp


HEADLAMP_PATH = "applications/30-headlamp.yaml"


def read_utility_manifest(app, repository):
    """Use the existing production repo-scoped token without changing GitHubApp."""
    if callable(getattr(app, "read_repository_file", None)):
        return app.read_repository_file(
            repository["installation_id"],
            repository["organization_login"],
            repository["repository_name"],
            HEADLAMP_PATH,
            branch=repository["default_branch"],
        )
    token = app.repository_token(repository["installation_id"], repository["repository_name"])["token"]
    owner = quote(repository["organization_login"], safe="")
    name = quote(repository["repository_name"], safe="")
    branch = quote(repository["default_branch"], safe="")
    result = app._request("GET", f"/repos/{owner}/{name}/contents/{HEADLAMP_PATH}?ref={branch}", token)
    if result.get("type") != "file" or result.get("encoding") != "base64":
        raise ApiError(
            409,
            "UTILITY_GITOPS_MANIFEST_INVALID",
            "Headlamp requires a readable registered application manifest.",
        )
    try:
        return b64decode("".join(result["content"].split()), validate=True).decode("utf-8")
    except (KeyError, ValueError, UnicodeDecodeError, AttributeError, TypeError):
        raise ApiError(
            409, "UTILITY_GITOPS_MANIFEST_INVALID", "Headlamp manifest is not valid UTF-8/base64."
        ) from None


def headlamp_preflight(repository, current_version, github=None, *, content=None):
    """Validate the registered repository without committing or syncing anything."""
    app = github if github is not None else GitHubApp()
    content = read_utility_manifest(app, repository) if content is None else content
    try:
        if len(content.encode("utf-8")) > 100_000:
            raise ValueError("Manifest exceeds limit")
        manifest = yaml.safe_load(content)
        if not isinstance(manifest, dict):
            raise ValueError("Application required")
        metadata, spec = manifest["metadata"], manifest["spec"]
        sources = spec["sources"]
        if not isinstance(sources, list) or not all(isinstance(s, dict) for s in sources):
            raise ValueError("Invalid sources")
        charts = [s for s in sources if "chart" in s]
        values = [s for s in sources if s.get("ref") == "values"]
        valid = (
            manifest.get("apiVersion") == "argoproj.io/v1alpha1"
            and manifest.get("kind") == "Application"
            and metadata.get("name") == "navigan-dashboard"
            and metadata.get("namespace") == "argocd"
            and spec.get("project") == "navigan-platform"
            and spec.get("destination")
            == {"server": "https://kubernetes.default.svc", "namespace": "navigan-dashboard"}
            and len(sources) == 2
            and len(charts) == 1
            and len(values) == 1
            and charts[0].get("chart") == "headlamp"
            and charts[0].get("repoURL") == "https://kubernetes-sigs.github.io/headlamp"
            and charts[0].get("helm", {}).get("releaseName") == "navigan-dashboard"
            and charts[0].get("helm", {}).get("valueFiles") == ["$values/values/headlamp.yaml"]
            and values[0].get("repoURL") == repository["repository_url"]
            and values[0].get("targetRevision") == repository["default_branch"]
        )
        if not valid:
            raise ValueError("Unexpected application identity")
        desired = charts[0].get("targetRevision")
    except (yaml.YAMLError, ValueError, TypeError, KeyError, AttributeError):
        raise ApiError(
            409,
            "UTILITY_GITOPS_MANIFEST_INVALID",
            "The registered Headlamp application does not match the supported Navigan layout. Review the system repository before planning.",
        ) from None
    if desired != current_version:
        raise ApiError(
            409,
            "UTILITY_GITOPS_VERSION_DRIFT",
            "Headlamp's repository chart version differs from the observed installed version. Reconcile GitOps and refresh connector evidence before planning.",
        )
    return {
        "status": "VERIFIED",
        "path": HEADLAMP_PATH,
        "repositoryUrl": repository["repository_url"],
        "branch": repository["default_branch"],
        "currentVersion": desired,
        "application": "navigan-dashboard",
    }


class HeadlampGitOps:
    """Bounded Headlamp adapter. Preparing git objects never updates a branch."""

    ADAPTER = "HEADLAMP_045_TO_046_V1"
    TARGET = "0.46.0"
    ARTIFACT_SHA = "faa471a8c5c55125b3dceed1cf73000e1ced18f07e2088e5e12e75292fb9ae62"
    DURATION = 120

    def __init__(self, repository, github=None):
        self.repository = repository
        self.app = github if github is not None else GitHubApp()
        self.root = (
            "/repos/"
            + quote(repository["organization_login"], safe="")
            + "/"
            + quote(repository["repository_name"], safe="")
        )
        self.branch = repository["default_branch"]
        self.tokens = {}

    def request(self, method, path, body=None):
        write = method != "GET"
        if write not in self.tokens:
            self.tokens[write] = self.app.repository_token(
                self.repository["installation_id"], self.repository["repository_name"], write=write
            )["token"]
        token = self.tokens[write]
        return (
            self.app._request(method, self.root + path, token, body)
            if body is not None
            else self.app._request(method, self.root + path, token)
        )

    def head(self):
        return self.request("GET", "/git/ref/heads/" + quote(self.branch, safe=""))["object"]["sha"]

    def file(self, path, revision):
        result = self.request("GET", "/contents/" + path + "?ref=" + quote(revision, safe=""))
        if (
            result.get("type") != "file"
            or result.get("encoding") != "base64"
            or result.get("size", 0) > 100_000
        ):
            raise ApiError(
                409,
                "UTILITY_GITOPS_MANIFEST_INVALID",
                "The registered Headlamp files must be readable and bounded.",
            )
        try:
            content = b64decode("".join(result["content"].split()), validate=True)
            if len(content) > 100_000:
                raise ValueError()
            return content.decode("utf-8"), result["sha"]
        except (KeyError, ValueError, UnicodeDecodeError, TypeError):
            raise ApiError(
                409, "UTILITY_GITOPS_MANIFEST_INVALID", "Invalid Headlamp repository file."
            ) from None

    @staticmethod
    def artifact():
        """Verify the exact reviewed upstream chart; never accept a caller URL."""
        import hashlib
        import io
        import tarfile
        import urllib.request

        url = "https://github.com/kubernetes-sigs/headlamp/releases/download/headlamp-helm-0.46.0/headlamp-0.46.0.tgz"
        try:
            with urllib.request.urlopen(url, timeout=8) as response:
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000 or hashlib.sha256(raw).hexdigest() != HeadlampGitOps.ARTIFACT_SHA:
                raise ValueError()
            with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
                members = archive.getmembers()
                if (
                    len(members) > 200
                    or sum(m.size for m in members) > 4_000_000
                    or any(
                        not m.name.startswith("headlamp/")
                        or ".." in m.name.split("/")
                        or not (m.isfile() or m.isdir())
                        for m in members
                    )
                ):
                    raise ValueError()
                chart = yaml.safe_load(archive.extractfile("headlamp/Chart.yaml").read())
                if (
                    chart.get("name") != "headlamp"
                    or chart.get("version") != "0.46.0"
                    or chart.get("appVersion") != "0.46.0"
                    or chart.get("dependencies")
                    or chart.get("kubeVersion")
                ):
                    raise ValueError()
            return {
                "chartVersion": "0.46.0",
                "applicationVersion": "0.46.0",
                "sha256": HeadlampGitOps.ARTIFACT_SHA,
            }
        except (OSError, ValueError, KeyError, AttributeError, tarfile.TarError, yaml.YAMLError):
            raise ApiError(
                409,
                "UTILITY_ARTIFACT_UNVERIFIED",
                "The reviewed Headlamp chart could not be verified. Retry package preflight; no branch was changed.",
            ) from None

    def snapshot(self, current_version):
        import hashlib

        revision = self.head()
        manifest, manifest_sha = self.file(HEADLAMP_PATH, revision)
        headlamp_preflight(self.repository, current_version, self.app, content=manifest)
        values, values_sha = self.file("values/headlamp.yaml", revision)
        parsed = yaml.safe_load(manifest)
        settings = yaml.safe_load(values)
        if not isinstance(settings, dict):
            raise ApiError(409, "UTILITY_VALUES_UNSUPPORTED", "Headlamp values must be a mapping.")
        chart = next(s for s in parsed["spec"]["sources"] if s.get("chart") == "headlamp")
        image = settings.get("image") or {}
        automated = parsed["spec"].get("syncPolicy", {}).get("automated")
        if (
            not isinstance(image, dict)
            or image.get("tag")
            or image.get("digest")
            or image.get("registry", "ghcr.io") != "ghcr.io"
            or image.get("repository", "headlamp-k8s/headlamp") != "headlamp-k8s/headlamp"
            or set(chart.get("helm", {})) - {"releaseName", "valueFiles"}
            or not isinstance(automated, dict)
            or automated.get("enabled") is False
        ):
            raise ApiError(
                409,
                "UTILITY_VALUES_UNSUPPORTED",
                "Execution requires chart-managed Headlamp images, the reviewed values file, and automated Argo sync. Review custom overrides separately.",
            )
        return {
            "repositoryUrl": self.repository["repository_url"],
            "branch": self.branch,
            "baseCommit": revision,
            "manifestSha": manifest_sha,
            "valuesSha": values_sha,
            "manifestHash": hashlib.sha256(manifest.encode()).hexdigest(),
            "valuesHash": hashlib.sha256(values.encode()).hexdigest(),
        }

    def evidence(self, current_version, target_version):
        if (current_version, target_version) != ("0.45.0", self.TARGET):
            raise ApiError(
                409,
                "UTILITY_EXECUTION_PATH_UNSUPPORTED",
                "The first execution adapter supports Headlamp chart 0.45.0 to 0.46.0. Other paths require a reviewed adapter.",
            )
        return {
            "adapter": self.ADAPTER,
            "durationMinutes": self.DURATION,
            "snapshot": self.snapshot(current_version),
            "artifact": self.artifact(),
        }

    def prepare(self, policy, target_version, operation):
        import hashlib
        import json

        if target_version != self.TARGET:
            raise ApiError(409, "UTILITY_EXECUTION_PATH_UNSUPPORTED", "Unsupported Headlamp target.")
        snapshot = self.snapshot("0.45.0")
        if snapshot != policy.get("snapshot") or self.artifact() != policy.get("artifact"):
            raise ApiError(
                409,
                "UTILITY_APPROVAL_DRIFT",
                "Repository or artifact changed after review. Reschedule and submit a new review.",
            )
        manifest, _ = self.file(HEADLAMP_PATH, snapshot["baseCommit"])
        node = yaml.compose(manifest)

        def field(node, name):
            return next(value for key, value in node.value if key.value == name)

        sources = field(field(node, "spec"), "sources")
        chart = next(
            n for n in sources.value if any(k.value == "chart" and v.value == "headlamp" for k, v in n.value)
        )
        target = field(chart, "targetRevision")
        updated = (
            manifest[: target.start_mark.index]
            + json.dumps(target_version)
            + manifest[target.end_mark.index :]
        )
        expected = yaml.safe_load(manifest)
        next(s for s in expected["spec"]["sources"] if s.get("chart") == "headlamp")["targetRevision"] = (
            target_version
        )
        if yaml.safe_load(updated) != expected:
            raise ApiError(409, "UTILITY_DIFF_INVALID", "Unrelated manifest changes rejected.")
        commit = self.request("GET", "/git/commits/" + snapshot["baseCommit"])
        blob = self.request("POST", "/git/blobs", {"content": updated, "encoding": "utf-8"})
        tree = self.request(
            "POST",
            "/git/trees",
            {
                "base_tree": commit["tree"]["sha"],
                "tree": [{"path": HEADLAMP_PATH, "mode": "100644", "type": "blob", "sha": blob["sha"]}],
            },
        )
        result = self.request(
            "POST",
            "/git/commits",
            {
                "message": "Navigan Headlamp upgrade " + operation,
                "tree": tree["sha"],
                "parents": [snapshot["baseCommit"]],
            },
        )
        return {
            "commit": result["sha"],
            "baseCommit": snapshot["baseCommit"],
            "targetManifestHash": hashlib.sha256(updated.encode()).hexdigest(),
        }

    def publication_state(self, policy, intent):
        import hashlib

        if (
            policy["snapshot"]["repositoryUrl"] != self.repository["repository_url"]
            or policy["snapshot"]["branch"] != self.branch
        ):
            raise ApiError(
                409, "UTILITY_EXECUTION_DRIFT", "The registered repository binding changed after approval."
            )
        head = self.head()
        if head == intent["baseCommit"]:
            snapshot = self.snapshot("0.45.0")
            if snapshot != policy["snapshot"]:
                raise ApiError(409, "UTILITY_APPROVAL_DRIFT", "Repository changed before publication.")
            return "UNPUBLISHED"
        manifest, _ = self.file(HEADLAMP_PATH, head)
        values, _ = self.file("values/headlamp.yaml", head)
        if (
            hashlib.sha256(manifest.encode()).hexdigest() != intent["targetManifestHash"]
            or hashlib.sha256(values.encode()).hexdigest() != policy["snapshot"]["valuesHash"]
        ):
            raise ApiError(
                409,
                "UTILITY_EXECUTION_DRIFT",
                "Headlamp desired state changed. Review GitOps before continuing.",
            )
        if head != intent["commit"]:
            comparison = self.request("GET", "/compare/" + intent["commit"] + "..." + head)
            if comparison.get("status") != "ahead":
                raise ApiError(
                    409,
                    "UTILITY_EXECUTION_DRIFT",
                    "The prepared upgrade commit is not on the registered branch.",
                )
        return "PUBLISHED"

    def publish(self, intent, deadline):
        from datetime import datetime, timezone

        # Reserve the two bounded GitHub calls (token and ref update) inside the
        # approved window. Branch protection errors are never bypassed.
        if (deadline - datetime.now(timezone.utc)).total_seconds() <= 30:
            raise ApiError(
                409,
                "UTILITY_WINDOW_CLOSING",
                "The maintenance window is closing. The prepared change was not published.",
            )
        # Non-fast-forward updates fail instead of overwriting a concurrent commit.
        try:
            self.request(
                "PATCH",
                "/git/refs/heads/" + quote(self.branch, safe=""),
                {"sha": intent["commit"], "force": False},
            )
        except ApiError as error:
            if error.status in {403, 409, 422}:
                raise ApiError(
                    409,
                    "UTILITY_PUBLICATION_BLOCKED",
                    "Branch protection, repository permissions or a concurrent Git change blocked publication. The prepared intent is retained; no protection was bypassed.",
                ) from None
            raise
