"""Read-only deployment discovery. Persist references, never repository/Secret bodies."""

import base64
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from pydantic import BaseModel, ConfigDict, Field, field_validator

WORKLOADS = {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"}
FIELD_MANAGERS = {
    "kubectl", "kubectl-client-side-apply", "kubectl-create", "kubectl-set", "kubectl-patch", "kubectl-rollout",
    "helm", "argocd-controller", "argocd-application-controller",
    "helm-controller", "kustomize-controller", "tigera-operator",
}

SAFE_LABELS = {
    "app.kubernetes.io/name",
    "app.kubernetes.io/instance",
    "app.kubernetes.io/version",
    "app.kubernetes.io/managed-by",
    "helm.sh/chart",
    "argocd.argoproj.io/instance",
    "kustomize.toolkit.fluxcd.io/name",
    "kustomize.toolkit.fluxcd.io/namespace",
    "helm.toolkit.fluxcd.io/name",
    "helm.toolkit.fluxcd.io/namespace",
}
SAFE_ANNOTATIONS = {
    "meta.helm.sh/release-name",
    "meta.helm.sh/release-namespace",
    "argocd.argoproj.io/tracking-id",
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class RepositorySource(StrictModel):
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", max_length=200)
    revision: str = Field(default="main", min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_./-]+$")
    directory: str = Field(default="", max_length=500, pattern=r"^[A-Za-z0-9_./-]*$")

    @field_validator("repository", mode="before")
    @classmethod
    def normalize_repository(cls, value):
        if isinstance(value, str):
            return value.strip().removeprefix("https://github.com/").removesuffix("/").removesuffix(".git")
        return value

    @field_validator("directory")
    @classmethod
    def safe_directory(cls, value):
        if value.startswith("/") or any(p in {".", ".."} for p in value.split("/")):
            raise ValueError("Use a relative repository directory without traversal.")
        return value.rstrip("/")


class DeploymentMapping(StrictModel):
    apiVersion: str = Field(min_length=1, max_length=100)
    kind: str = Field(pattern=r"^(Deployment|StatefulSet|DaemonSet|Job|CronJob)$")
    namespace: str = Field(min_length=1, max_length=63)
    name: str = Field(min_length=1, max_length=253)
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", max_length=200)
    commit: str = Field(pattern=r"^[a-f0-9]{40,64}$")
    filePath: str = Field(min_length=1, max_length=1000)


class SourceCredential(StrictModel):
    key: str = Field(min_length=1, max_length=270)
    mode: str = Field(pattern=r"^(PUBLIC|APP|AWS_ROLE|AWS_EXISTING_ROLE|TOKEN|BEARER)$")
    provider: str = Field(default="", pattern=r"^(|AWS_ECR|AZURE_ACR|GOOGLE_AR|DOCKER_HUB|GHCR|HARBOR|OTHER)$")
    roleArn: str = Field(default="", max_length=2048, pattern=r"^[A-Za-z0-9+=,.@_:/-]*$")
    username: str = Field(default="", max_length=200, pattern=r"^[^\r\n:]*$")
    token: str = Field(default="", max_length=10000, repr=False, pattern=r"^[!-~]*$")


class DeploymentSourcesConfig(StrictModel):
    inventoryOnly: bool = False
    repositories: list[RepositorySource] = Field(default_factory=list, max_length=3)
    registries: list[str] = Field(default_factory=list, max_length=10)
    confirmations: list[DeploymentMapping] = Field(default_factory=list, max_length=2000)

    @field_validator("repositories")
    @classmethod
    def unique_repositories(cls, entries):
        if len({r.repository for r in entries}) != len(entries):
            raise ValueError("Configure each repository once.")
        return entries

    @field_validator("registries")
    @classmethod
    def clean_hosts(cls, hosts):
        if len(set(hosts)) != len(hosts) or any(
            not re.fullmatch(r"[a-z0-9]+(?:[a-z0-9.-]*[a-z0-9])?", h) or len(h) > 253 for h in hosts
        ):
            raise ValueError("Use unique registry hostnames without URLs, paths or credentials.")
        return hosts


class SaveDeploymentSources(StrictModel):
    version: int = Field(gt=0)
    configuration: DeploymentSourcesConfig
    credentials: list[SourceCredential] = Field(default_factory=list, max_length=13)
    verify: bool = False


class AnalyzeDeploymentSources(StrictModel):
    version: int = Field(gt=0)
    refreshCluster: bool = False
    continueAnalysis: bool = False


def validate_deployment_inventory(resource):
    metadata = resource.get("deploymentMetadata", {})
    if not isinstance(metadata, dict) or set(metadata) - {"labels", "annotations", "fieldManagers"}:
        raise ValueError("Invalid deployment metadata.")
    for field, allowlist in (("labels", SAFE_LABELS), ("annotations", SAFE_ANNOTATIONS)):
        entries = metadata.get(field, {})
        if (
            not isinstance(entries, dict)
            or set(entries) - allowlist
            or any(not isinstance(v, str) or len(v) > 500 for v in entries.values())
        ):
            raise ValueError("Deployment metadata must use the approved allowlist.")
    managers = metadata.get("fieldManagers", [])
    if not isinstance(managers, list) or len(managers) > len(FIELD_MANAGERS) or any(not isinstance(value, str) or value not in FIELD_MANAGERS for value in managers) or len(set(managers)) != len(managers):
        raise ValueError("Invalid field manager evidence.")
    runtime = resource.get("runtimeEvidence")
    if runtime is None:
        return
    if (
        not isinstance(runtime, dict)
        or set(runtime) != {"status", "containers"}
        or runtime["status"] not in {"OBSERVED", "PARTIAL", "UNAVAILABLE", "NO_RUNNING_EVIDENCE"}
    ):
        raise ValueError("Invalid runtime image evidence.")
    containers = runtime["containers"]
    if not isinstance(containers, list) or len(containers) > 500:
        raise ValueError("Runtime evidence exceeds the limit.")
    for c in containers:
        if not isinstance(c, dict) or set(c) != {
            "name",
            "containerType",
            "podName",
            "image",
            "imageID",
            "ready",
        }:
            raise ValueError("Invalid runtime container identity.")
        if c["containerType"] not in {"APPLICATION", "INIT"} or type(c["ready"]) is not bool:
            raise ValueError("Invalid runtime container status.")
        for key in ("name", "podName", "image", "imageID"):
            if c[key] is not None and (not isinstance(c[key], str) or len(c[key]) > 1000):
                raise ValueError("Invalid runtime container reference.")


def config_digest(config):
    return hashlib.sha256(
        json.dumps(
            {k: config.get(k, []) for k in ("repositories", "registries")},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def get_json(url, token=None, body=None):
    """Only callers construct URLs for the fixed GitHub/Docker Hub APIs."""
    headers = {
        "Accept": "application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json"
        if "registry-1.docker.io" in url
        else "application/vnd.github+json",
        "User-Agent": "Navigan-Deployment-Discovery",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    data = json.dumps(body).encode() if body is not None else None
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, headers=headers, data=data)
    with urllib.request.build_opener(NoRedirects()).open(request, timeout=3) as response:
        raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("Deployment source response exceeds the limit.")
        payload = json.loads(raw)
        digest = response.headers.get("Docker-Content-Digest", "")
        if "registry-1.docker.io" in url and re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
            payload["_registryDigest"] = digest
        return payload


def repository_read_token(installation_id, repository_name):
    """Reuse customer App identity, minting a single-repository contents:read token."""
    import boto3
    from botocore.config import Config
    from navigan.modules.cluster_management.github_app import GitHubApp

    class ReadOnlyApp(GitHubApp):
        def _request(self, method, path, token, body=None):
            if method != "POST" or not re.fullmatch(r"/app/installations/[0-9]+/access_tokens", path):
                raise ValueError("Only read-token issuance is supported.")
            return get_json("https://api.github.com" + path, token, body)

    secrets = boto3.client(
        "secretsmanager", config=Config(connect_timeout=2, read_timeout=2, retries={"max_attempts": 0})
    )
    return ReadOnlyApp(secrets_client=secrets).repository_token(
        installation_id, repository_name, write=False
    )["token"]


def manifest_identity(doc):
    metadata = doc.get("metadata") or {}
    return {
        "apiVersion": doc.get("apiVersion"),
        "kind": doc.get("kind"),
        "namespace": metadata.get("namespace"),
        "name": metadata.get("name"),
    }


def workload_images(doc):
    spec = doc.get("spec") or {}
    if doc.get("kind") == "CronJob":
        spec = (spec.get("jobTemplate") or {}).get("spec") or {}
    pod = (spec.get("template") or {}).get("spec") or {}
    return [
        c["image"]
        for field in ("containers", "initContainers")
        for c in pod.get(field, [])
        if isinstance(c, dict) and isinstance(c.get("image"), str)
    ]


def analyze_repository(source, token=None, *, fetch=get_json, deadline=None):
    """Pin commit, statically inspect bounded files; templated YAML stays unverified."""
    import yaml

    repo = source["repository"]
    prefix = f"https://api.github.com/repos/{repo}"
    commit = fetch(prefix + "/commits/" + urllib.parse.quote(source["revision"], safe=""), token)
    sha = commit["sha"]
    if not re.fullmatch(r"[a-f0-9]{40,64}", sha):
        raise ValueError("Repository commit identity is unavailable.")
    tree = fetch(prefix + "/git/trees/" + sha + "?recursive=1", token)
    artifacts = []
    directory = source.get("directory", "")
    paths = [
        v
        for v in tree.get("tree", [])
        if v.get("type") == "blob"
        and (not directory or v["path"].startswith(directory + "/"))
        and re.search(r"(?:\.ya?ml|\.sh)$", v["path"], re.I)
        and not re.search(r"(?:^|/)(?:\.git|node_modules|vendor|secrets?)(?:/|\.)", v["path"], re.I)
    ]
    gaps = []
    if tree.get("truncated") or len(paths) > 30:
        gaps.append("Repository scan is partial: tree or file limit reached.")
    for entry in paths[:30]:
        if deadline and time.monotonic() >= deadline:
            gaps.append("Repository scan is partial: time budget reached.")
            break
        path = entry["path"]
        if entry.get("size", 0) > 100_000:
            gaps.append("An oversized deployment file was skipped.")
            continue
        blob = fetch(prefix + "/git/blobs/" + entry["sha"], token)
        content = base64.b64decode(blob.get("content", "")).decode("utf-8")
        if len(content) > 100_000:
            gaps.append("An oversized deployment file was skipped.")
            continue
        common = {"repository": repo, "commit": sha, "filePath": path}
        if path.endswith(".sh"):
            artifacts.append(
                {
                    **common,
                    "format": "SCRIPT",
                    "usesHelm": bool(re.search(r"\bhelm\s", content)),
                    "usesKubectl": bool(re.search(r"\bkubectl\s", content)),
                    "referencedPaths": sorted(
                        set(
                            re.findall(
                                r"(?:\./)?[A-Za-z0-9_./-]+\.(?:yaml|yml|sh)\b|(?:\./)?charts/[A-Za-z0-9_./-]+",
                                content,
                            )
                        )
                    )[:100],
                    "dynamicReferences": bool(re.search(r"\$[({A-Za-z_]", content)),
                }
            )
            continue
        if path.startswith(".github/workflows/"):
            # GitHub expressions (${{ ... }}) are not Helm templates.
            artifacts.append({**common, "format": "GITHUB_ACTIONS"})
            continue
        if "{{" in content or "{%" in content:
            chart_template = "/templates/" in "/" + path and any(
                candidate["path"].endswith("/Chart.yaml")
                and path.startswith(candidate["path"].rsplit("/", 1)[0] + "/templates/")
                for candidate in tree.get("tree", [])
            )
            artifacts.append({
                **common,
                "format": "HELM_TEMPLATE" if chart_template else "TEMPLATE",
                "requiresRendering": True,
            })
            continue
        # Reject aliases/tags before parsing to avoid expansion and custom constructors.
        try:
            if any(
                isinstance(t, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken, yaml.tokens.TagToken))
                for t in yaml.scan(content)
            ):
                gaps.append("A YAML file requires manual review of aliases or tags.")
                continue
            docs = list(yaml.safe_load_all(content))
        except yaml.YAMLError:
            gaps.append("A deployment file could not be parsed; manual review is required.")
            continue
        for doc in docs[:100]:
            if not isinstance(doc, dict):
                continue
            if path.endswith("Chart.yaml"):
                if isinstance(doc.get("name"), str) and isinstance(doc.get("version"), (str, int, float)):
                    artifacts.append(
                        {
                            **common,
                            "format": "HELM",
                            "chartName": doc["name"][:200],
                            "chartVersion": str(doc["version"])[:100],
                        }
                    )
            elif path.rsplit("/", 1)[-1] in {"kustomization.yaml", "kustomization.yml"}:
                artifacts.append({**common, "format": "KUSTOMIZE"})
            elif isinstance(doc.get("kind"), str) and isinstance(doc.get("metadata"), dict):
                identity = manifest_identity(doc)
                if all(isinstance(identity[k], str) for k in ("apiVersion", "kind", "name")):
                    artifacts.append(
                        {
                            **common,
                            "format": "MANIFESTS",
                            "resource": identity,
                            "images": workload_images(doc)[:100] if doc["kind"] in WORKLOADS else [],
                        }
                    )
            elif path.rsplit("/", 1)[-1] in {"kustomization.yaml", "kustomization.yml"}:
                artifacts.append({**common, "format": "KUSTOMIZE"})
        if len(artifacts) >= 500:
            gaps.append("Repository artifact limit reached.")
            break
    return {
        "repository": repo,
        "requestedRevision": source["revision"],
        "commit": sha,
        "directory": directory,
        "status": "PARTIAL" if gaps else "ANALYZED",
        "artifacts": artifacts[:500],
        "gaps": sorted(set(gaps)),
    }


def image_parts(image):
    """Return explicit registry/repository/tag/digest without assuming tag immutability."""
    base, _, digest = image.partition("@")
    first, sep, rest = base.partition("/")
    if sep and ("." in first or ":" in first or first == "localhost"):
        host, repository = first, rest
    else:
        host, repository = "docker.io", base
    if host in {"index.docker.io", "registry-1.docker.io"}:
        host = "docker.io"
    if ":" in repository.rsplit("/", 1)[-1]:
        repository, tag = repository.rsplit(":", 1)
    else:
        tag = None if digest else "latest"
    if host == "docker.io" and "/" not in repository:
        repository = "library/" + repository
    return {"registry": host, "repository": repository, "tag": tag, "digest": digest or None}


def check_image(image, source_account, allowed_hosts, *, boto3_module=None, fetch=get_json, aws_client=None):
    parts = image_parts(image)
    result = {"image": image, **parts, "status": "NOT_CONNECTED", "registryDigest": None, "architectures": []}
    if parts["registry"] not in allowed_hosts:
        result["reason"] = "Connect this registry once under deployment sources to inspect referenced images."
        return result
    ecr = re.fullmatch(r"([0-9]{12})\.dkr\.ecr\.([a-z0-9-]+)\.amazonaws\.com", parts["registry"])
    if ecr:
        if boto3_module is None:
            import boto3 as boto3_module
        image_id = {"imageDigest": parts["digest"]} if parts["digest"] else {"imageTag": parts["tag"]}
        details = (aws_client or boto3_module.client(
            "ecr",
            region_name=ecr[2],
            config=__import__("botocore.config", fromlist=["Config"]).Config(
                connect_timeout=2, read_timeout=3, retries={"max_attempts": 0}
            ),
        )).describe_images(registryId=ecr[1], repositoryName=parts["repository"], imageIds=[image_id])[
            "imageDetails"
        ]
        if details:
            return {
                **result,
                "status": "AVAILABLE",
                "registryDigest": details[0]["imageDigest"],
                "reason": "Image metadata is available. Pull access and runtime compatibility have not been verified.",
            }
        return {**result, "status": "NOT_FOUND", "reason": "Referenced image was not found."}
    if parts["registry"] == "docker.io":
        repository = parts["repository"]
        if not re.fullmatch(r"[a-z0-9][a-z0-9_./-]*", repository):
            raise ValueError("Invalid image repository.")
        auth = fetch(
            "https://auth.docker.io/token?service=registry.docker.io&scope="
            + urllib.parse.quote(f"repository:{repository}:pull", safe="")
        )
        ref = parts["digest"] or parts["tag"]
        manifest = fetch(
            f"https://registry-1.docker.io/v2/{repository}/manifests/" + urllib.parse.quote(ref, safe=""),
            auth["token"],
        )
        architectures = sorted(
            {
                m.get("platform", {}).get("architecture")
                for m in manifest.get("manifests", [])
                if m.get("platform", {}).get("architecture") not in {None, "unknown"}
            }
        )
        # Digest is the response identity when explicitly requested; never hash reformatted JSON.
        return {
            **result,
            "status": "AVAILABLE",
            "registryDigest": manifest.get("_registryDigest") or parts["digest"],
            "architectures": architectures,
            "reason": "Anonymous manifest access succeeded. Architecture coverage may require image configuration inspection.",
        }
    return {
        **result,
        "status": "UNSUPPORTED",
        "reason": "This registry needs an additional authentication adapter. Initial analysis supports source-account AWS ECR and public Docker Hub images.",
    }


def build_report(migration, inventory, source):
    configuration = (source.get("delivery_configuration") or {}).get("deploymentDiscovery") or {
        "repositories": [],
        "registries": [],
    }
    analysis = (source.get("delivery_configuration") or {}).get("deploymentAnalysis") or {}
    current = analysis.get("configurationDigest") == config_digest(configuration)
    repos = analysis.get("repositories", []) if current else []
    registry = analysis.get("images", []) if current else []
    artifacts = [a for repo in repos for a in repo.get("artifacts", [])]
    rows = []
    for resource in (inventory or {}).get("resources", []):
        if resource.get("kind") not in WORKLOADS:
            continue
        metadata = resource.get("deploymentMetadata") or {}
        labels, annotations = metadata.get("labels", {}), metadata.get("annotations", {})
        chart = labels.get("helm.sh/chart")
        manager = labels.get("app.kubernetes.io/managed-by")
        release = annotations.get("meta.helm.sh/release-name")
        delivery = (
            "Argo CD"
            if labels.get("argocd.argoproj.io/instance") or annotations.get("argocd.argoproj.io/tracking-id")
            else "Flux"
            if any("toolkit.fluxcd.io" in k for k in labels)
            else manager or "Unresolved"
        )
        delivery_basis = "CLUSTER_METADATA" if delivery != "Unresolved" else "NOT_OBSERVED"
        if delivery == "Unresolved" and metadata.get("fieldManagers"):
            hints = metadata["fieldManagers"]
            tools = sorted({"kubectl" if value.startswith("kubectl") else "Argo CD" if value.startswith("argocd") else "Flux" if value in {"helm-controller", "kustomize-controller"} else "Helm" if value == "helm" else value for value in hints})
            delivery = ", ".join(tools) + " (field-manager evidence)"
            delivery_basis = "FIELD_MANAGER"
        runtime = resource.get("runtimeEvidence") or {"status": "NOT_COLLECTED", "containers": []}
        containers = []
        for field, container_type in (("containers", "APPLICATION"), ("initContainers", "INIT")):
            for c in (resource.get("pod") or {}).get(field, []):
                image = c.get("image") or ""
                observed = [
                    v
                    for v in runtime.get("containers", [])
                    if v.get("name") == c.get("name") and v.get("containerType") == container_type
                ]
                ids = sorted({v["imageID"] for v in observed if v.get("imageID")})
                image_check = next((v for v in registry if v["image"] == image), None)
                observed_digests = sorted(
                    {match[0] for v in ids if (match := re.findall(r"sha256:[a-f0-9]{64}", v))}
                )
                configured_digest = image_parts(image)["digest"] if image else None
                expected = configured_digest or (image_check or {}).get("registryDigest")
                containers.append(
                    {
                        "name": c.get("name"),
                        "containerType": container_type,
                        "configuredImage": image,
                        "runningImageIDs": ids,
                        "runningImages": sorted({v["image"] for v in observed if v.get("image")}),
                        "observedDigests": observed_digests,
                        "runningPodCount": len({v["podName"] for v in observed}),
                        "multipleRunningVersions": len(ids) > 1,
                        "digestComparison": "DIFFERENT"
                        if expected and observed_digests and any(d != expected for d in observed_digests)
                        else "MATCH"
                        if expected and observed_digests
                        else "UNVERIFIED",
                        "registryEvidence": image_check,
                    }
                )
        candidates = []
        for artifact in artifacts:
            identity = artifact.get("resource") or {}
            same_identity = all(identity.get(key) == resource.get(key) for key in ("apiVersion", "kind", "name"))
            identity_match = same_identity and identity.get("namespace") == resource.get("namespace")
            # Namespace may be supplied by kubectl, Helm or Kustomize at deploy
            # time. Retain a name/kind match as an explicitly unverified candidate.
            namespace_unspecified = same_identity and not identity.get("namespace") and bool(resource.get("namespace"))
            helm_match = (
                chart
                and artifact.get("format") == "HELM"
                and chart == artifact.get("chartName", "") + "-" + artifact.get("chartVersion", "")
            )
            if identity_match or namespace_unspecified or helm_match:
                candidates.append(
                    {
                        **artifact,
                        "match": "RESOURCE_IDENTITY" if identity_match else "NAMESPACE_UNSPECIFIED" if namespace_unspecified else "CHART_METADATA",
                        "deployedCommitVerified": False,
                    }
                )
        confirmed = next(
            (
                m
                for m in configuration.get("confirmations", [])
                if all(m.get(k) == resource.get(k) for k in ("apiVersion", "kind", "namespace", "name"))
                and any(
                    all(m.get(k) == a.get(k) for k in ("repository", "commit", "filePath"))
                    for a in candidates
                )
            ),
            None,
        )
        gaps = []
        if not candidates:
            gaps.append("Original deployment artifact has not been mapped.")
        if any(a["match"] == "NAMESPACE_UNSPECIFIED" for a in candidates):
            gaps.append("Repository manifest omits the namespace. Deployment-time namespace mapping needs confirmation; name matching does not prove ownership.")
        if len(candidates) > 1 and not confirmed:
            gaps.append("Multiple deployment artifacts match; confirm the deployed source.")
        if candidates:
            gaps.append(
                "Repository commit has been inspected, but its deployment to this cluster has not been verified."
            )
        if runtime["status"] != "OBSERVED":
            gaps.append(
                "Running container image evidence is " + runtime["status"].lower().replace("_", " ") + "."
            )
        if any(c["multipleRunningVersions"] for c in containers):
            gaps.append("Multiple running image identities observed; review rollout state.")
        missing_digests = [c["name"] for c in containers if c["runningPodCount"] > 0 and not c["observedDigests"]]
        if missing_digests:
            gaps.append("Running image digest was not reported for: " + ", ".join(str(name) for name in missing_digests) + ". Refresh runtime evidence and inspect container status if this persists.")
        unverified_images = sorted({c["configuredImage"] for c in containers if (c["registryEvidence"] or {}).get("status") != "AVAILABLE"})
        if unverified_images:
            gaps.append("Registry verification is incomplete for one or more referenced images. Review the Container registry tab and configure private access where needed.")
        if delivery_basis == "NOT_OBSERVED":
            gaps.append("Original delivery tool is not recorded in the collected cluster metadata. Connect deployment repositories or pipelines; do not infer a tool from a running Pod.")
        gaps.append("Cluster inventory is sanitized and is not a complete deployable manifest. Secret/configuration values and deployment commands are not exported; a reviewed deployment package is still required.")
        rows.append(
            {
                "workload": {k: resource.get(k) for k in ("apiVersion", "kind", "namespace", "name")},
                "applicationVersion": labels.get("app.kubernetes.io/version"),
                "artifactFormat": "Helm" if chart or release else "Kubernetes manifests (candidate)" if any(a.get("format") == "MANIFESTS" for a in candidates) else "Unresolved",
                "deliveryTool": delivery,
                "deliveryEvidenceBasis": delivery_basis,
                "clusterSnapshot": {
                    "format": "SANITIZED_CLUSTER_INVENTORY",
                    "status": "REVIEW_REQUIRED",
                    "inventoryDigest": (inventory or {}).get("inventoryDigest"),
                    "observedAt": (inventory or {}).get("observedAt"),
                    "resourceIdentity": {key: resource.get(key) for key in ("apiVersion", "kind", "namespace", "name")},
                    "deployable": False,
                },
                "evidenceStatus": "REVIEW_REQUIRED",
                "registryVerified": not unverified_images and bool(containers),
                "helmChart": chart,
                "helmRelease": release,
                "mappingStatus": "CONFIRMED" if confirmed else "CANDIDATE" if candidates else "UNRESOLVED",
                "confirmedSource": confirmed,
                "candidates": candidates,
                "runtimeStatus": runtime["status"],
                "containers": containers,
                "gaps": gaps,
            }
        )
    return {
        "coverage": {
            "status": "WITH_GAPS" if any(row["gaps"] for row in rows) or not inventory else "COLLECTED",
            "workloadCount": len(rows),
            "namespaceCount": len({r.get("namespace") or r.get("name") for r in (inventory or {}).get("resources", []) if r.get("kind") == "Namespace" or r.get("namespace")}),
            "repositoryMappedCount": sum(bool(row["candidates"]) for row in rows),
            "runtimeObservedCount": sum(row["runtimeStatus"] == "OBSERVED" for row in rows),
            "registryVerifiedWorkloadCount": sum(row["registryVerified"] for row in rows),
            "inventorySnapshotCount": len(rows),
            "scope": "All discovered namespaces; filters only change presentation.",
            "limitations": ["Only supported resource kinds are collected. Missing APIs, permissions, credentials and scan limits must remain evidence gaps.", "Sanitized inventory snapshots are review evidence, not deployable artifacts or proof of the original delivery tool."],
        },
        "migrationId": migration["migration_id"],
        "sourceClusterId": source["source_cluster_id"],
        "inventoryDigest": (inventory or {}).get("inventoryDigest"),
        "observedAt": (inventory or {}).get("observedAt"),
        "analyzedAt": analysis.get("analyzedAt") if current else None,
        "configuration": configuration,
        "configurationCurrent": current,
        "repositories": repos,
        "images": registry,
        "workloads": rows,
        "limitations": [
            "Repository matches are candidates; the deployed Git revision and rendered values need confirmation.",
            "Scripts are inspected statically and never executed. No extraction or deployment package has been generated.",
        ],
    }
