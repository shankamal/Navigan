"""Read-only repository evidence for the Headlamp upgrade adapter."""

import yaml

from navigan.shared.errors import ApiError
from .github_app import GitHubApp


HEADLAMP_PATH = "applications/30-headlamp.yaml"


def headlamp_preflight(repository, current_version, github=None):
    """Validate the registered repository without committing or syncing anything."""
    app = github if github is not None else GitHubApp()
    content = app.read_repository_file(
        repository["installation_id"],
        repository["organization_login"],
        repository["repository_name"],
        HEADLAMP_PATH,
        branch=repository["default_branch"],
    )
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
