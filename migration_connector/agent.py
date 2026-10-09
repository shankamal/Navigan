"""Outbound-only Kubernetes migration discovery agent."""

from datetime import datetime, timezone
import hashlib
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from .inventory import (
    MAX_RESOURCES,
    UnsafeInventory,
    finalize_inventory,
    sanitize_resource,
)


SERVICE_ACCOUNT = "/var/run/secrets/kubernetes.io/serviceaccount"
MAX_API_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_ITEMS_PER_REQUEST = 2_000

DEFAULT_EXCLUDED_NAMESPACES = {
    "argocd",
    "falco",
    "kube-node-lease",
    "kube-public",
    "kube-system",
    "navigan-dashboard",
    "navigan-monitoring",
    "navigan-system",
}

NAMESPACED_RESOURCE_PATHS = (
    "/apis/apps/v1/namespaces/{namespace}/deployments",
    "/apis/apps/v1/namespaces/{namespace}/statefulsets",
    "/apis/apps/v1/namespaces/{namespace}/daemonsets",
    "/apis/batch/v1/namespaces/{namespace}/jobs",
    "/apis/batch/v1/namespaces/{namespace}/cronjobs",
    "/api/v1/namespaces/{namespace}/services",
    "/api/v1/namespaces/{namespace}/persistentvolumeclaims",
    "/apis/networking.k8s.io/v1/namespaces/{namespace}/ingresses",
    "/apis/networking.k8s.io/v1/namespaces/{namespace}/networkpolicies",
    "/apis/autoscaling/v2/namespaces/{namespace}/horizontalpodautoscalers",
    "/apis/policy/v1/namespaces/{namespace}/poddisruptionbudgets",
    "/api/v1/namespaces/{namespace}/serviceaccounts",
    "/apis/rbac.authorization.k8s.io/v1/namespaces/{namespace}/roles",
    "/apis/rbac.authorization.k8s.io/v1/namespaces/{namespace}/rolebindings",
    "/api/v1/namespaces/{namespace}/configmaps",
    "/api/v1/namespaces/{namespace}/secrets",
)

CLUSTER_RESOURCE_PATHS = (
    "/apis/storage.k8s.io/v1/storageclasses",
    "/apis/apiextensions.k8s.io/v1/customresourcedefinitions",
    "/apis/rbac.authorization.k8s.io/v1/clusterroles",
    "/apis/rbac.authorization.k8s.io/v1/clusterrolebindings",
    "/apis/admissionregistration.k8s.io/v1/mutatingwebhookconfigurations",
    "/apis/admissionregistration.k8s.io/v1/validatingwebhookconfigurations",
)

CATALOGUE_RESOURCE_PATHS = (
    (NAMESPACED_RESOURCE_PATHS[0], "Deployment"),
    (NAMESPACED_RESOURCE_PATHS[1], "StatefulSet"),
    (NAMESPACED_RESOURCE_PATHS[2], "DaemonSet"),
    (NAMESPACED_RESOURCE_PATHS[3], "Job"),
    (NAMESPACED_RESOURCE_PATHS[4], "CronJob"),
    (NAMESPACED_RESOURCE_PATHS[5], "Service"),
    (NAMESPACED_RESOURCE_PATHS[6], "PersistentVolumeClaim"),
    (NAMESPACED_RESOURCE_PATHS[7], "Ingress"),
    (NAMESPACED_RESOURCE_PATHS[8], "NetworkPolicy"),
    (NAMESPACED_RESOURCE_PATHS[9], "HorizontalPodAutoscaler"),
    (NAMESPACED_RESOURCE_PATHS[10], "PodDisruptionBudget"),
)

RESOURCE_TYPE_BY_PATH = {
    NAMESPACED_RESOURCE_PATHS[0]: ("apps/v1", "Deployment"),
    NAMESPACED_RESOURCE_PATHS[1]: ("apps/v1", "StatefulSet"),
    NAMESPACED_RESOURCE_PATHS[2]: ("apps/v1", "DaemonSet"),
    NAMESPACED_RESOURCE_PATHS[3]: ("batch/v1", "Job"),
    NAMESPACED_RESOURCE_PATHS[4]: ("batch/v1", "CronJob"),
    NAMESPACED_RESOURCE_PATHS[5]: ("v1", "Service"),
    NAMESPACED_RESOURCE_PATHS[6]: (
        "v1",
        "PersistentVolumeClaim",
    ),
    NAMESPACED_RESOURCE_PATHS[7]: (
        "networking.k8s.io/v1",
        "Ingress",
    ),
    NAMESPACED_RESOURCE_PATHS[8]: (
        "networking.k8s.io/v1",
        "NetworkPolicy",
    ),
    NAMESPACED_RESOURCE_PATHS[9]: (
        "autoscaling/v2",
        "HorizontalPodAutoscaler",
    ),
    NAMESPACED_RESOURCE_PATHS[10]: (
        "policy/v1",
        "PodDisruptionBudget",
    ),
    NAMESPACED_RESOURCE_PATHS[11]: ("v1", "ServiceAccount"),
    NAMESPACED_RESOURCE_PATHS[12]: (
        "rbac.authorization.k8s.io/v1",
        "Role",
    ),
    NAMESPACED_RESOURCE_PATHS[13]: (
        "rbac.authorization.k8s.io/v1",
        "RoleBinding",
    ),
    NAMESPACED_RESOURCE_PATHS[14]: ("v1", "ConfigMap"),
    NAMESPACED_RESOURCE_PATHS[15]: ("v1", "Secret"),
    CLUSTER_RESOURCE_PATHS[0]: (
        "storage.k8s.io/v1",
        "StorageClass",
    ),
    CLUSTER_RESOURCE_PATHS[1]: (
        "apiextensions.k8s.io/v1",
        "CustomResourceDefinition",
    ),
    CLUSTER_RESOURCE_PATHS[2]: (
        "rbac.authorization.k8s.io/v1",
        "ClusterRole",
    ),
    CLUSTER_RESOURCE_PATHS[3]: (
        "rbac.authorization.k8s.io/v1",
        "ClusterRoleBinding",
    ),
    CLUSTER_RESOURCE_PATHS[4]: (
        "admissionregistration.k8s.io/v1",
        "MutatingWebhookConfiguration",
    ),
    CLUSTER_RESOURCE_PATHS[5]: (
        "admissionregistration.k8s.io/v1",
        "ValidatingWebhookConfiguration",
    ),
}


class RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        request,
        response,
        code,
        message,
        headers,
        new_url,
    ):
        return None


def open_request(request, timeout, context=None):
    handlers = [RejectRedirects()]
    if context is not None:
        handlers.append(
            urllib.request.HTTPSHandler(context=context)
        )
    return urllib.request.build_opener(*handlers).open(
        request,
        timeout=timeout,
    )


def required(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def read_text(path):
    with open(path, encoding="utf-8") as stream:
        return stream.read().strip()


def secure_base_url(value):
    parsed = urllib.parse.urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError(
            "Navigan API base URL must be a clean HTTPS URL."
        )
    return value.rstrip("/")


def read_json_response(response, maximum=MAX_API_RESPONSE_BYTES):
    payload = response.read(maximum + 1)
    if len(payload) > maximum:
        raise RuntimeError("API response size limit exceeded.")

    value = json.loads(payload.decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("API response must be an object.")
    return value


def kubernetes_request(path):
    if not path.startswith("/") or "://" in path:
        raise RuntimeError("Invalid Kubernetes API path.")

    host = required("KUBERNETES_SERVICE_HOST")
    port = os.environ.get(
        "KUBERNETES_SERVICE_PORT_HTTPS",
        "443",
    )
    token = read_text(f"{SERVICE_ACCOUNT}/token")
    context = ssl.create_default_context(
        cafile=f"{SERVICE_ACCOUNT}/ca.crt"
    )

    request = urllib.request.Request(
        f"https://{host}:{port}{path}",
        method="GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "navigan-migration-connector/0.1.0",
        },
    )

    try:
        with open_request(
            request,
            timeout=20,
            context=context,
        ) as response:
            return read_json_response(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(
            f"Kubernetes API returned HTTP {error.code}."
        ) from error


def navigan_request(
    base_url,
    connector_id,
    connector_token,
    path,
    method="GET",
    body=None,
):
    base_url = secure_base_url(base_url)

    if re.fullmatch(r"MGC-[0-9a-f]{32}", connector_id):
        connector_path = "migration-connectors"
    elif re.fullmatch(r"SCC-[0-9a-f]{32}", connector_id):
        connector_path = "source-connectors"
    else:
        raise RuntimeError("Migration connector ID is invalid.")

    if method not in {"GET", "POST"}:
        raise RuntimeError("Unsupported Navigan API method.")

    encoded_body = None
    headers = {
        "Authorization": f"Bearer {connector_token}",
        "Accept": "application/json",
        "User-Agent": "navigan-migration-connector/0.1.0",
    }

    if body is not None:
        if method != "POST" or not isinstance(body, dict):
            raise RuntimeError("Navigan request body is invalid.")

        encoded_body = json.dumps(
            body,
            separators=(",", ":"),
        ).encode("utf-8")

        if len(encoded_body) > 1_048_576:
            raise RuntimeError(
                "Navigan request body size limit exceeded."
            )

        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        (
            f"{base_url}/{connector_path}/"
            f"{connector_id}/{path.lstrip('/')}"
        ),
        data=encoded_body,
        method=method,
        headers=headers,
    )

    try:
        with open_request(
            request,
            timeout=20,
        ) as response:
            return read_json_response(response, 1_048_576)
    except urllib.error.HTTPError as error:
        raise RuntimeError(
            f"Navigan API returned HTTP {error.code}."
        ) from error


def resource_items(payload):
    items = payload.get("items")
    if not isinstance(items, list):
        raise RuntimeError(
            "Kubernetes list response does not contain items."
        )
    if len(items) > MAX_ITEMS_PER_REQUEST:
        raise UnsafeInventory(
            "Kubernetes resource list limit exceeded."
        )
    return items


def resource_from_endpoint(resource, api_version, kind):
    """Restore omitted Kubernetes TypeMeta from an allowlisted endpoint."""
    if not isinstance(resource, dict):
        return resource

    observed_api_version = resource.get("apiVersion")
    observed_kind = resource.get("kind")
    if observed_api_version not in {None, api_version}:
        raise UnsafeInventory(
            "Kubernetes API returned an unexpected resource version."
        )
    if observed_kind not in {None, kind}:
        raise UnsafeInventory(
            "Kubernetes API returned an unexpected resource kind."
        )

    typed = dict(resource)
    typed.setdefault("apiVersion", api_version)
    typed.setdefault("kind", kind)
    return typed


def selected_namespaces(assignment, request):
    scope = assignment.get("scope")
    if not isinstance(scope, dict):
        raise RuntimeError("Migration scope is missing.")

    requested = set(scope.get("namespaces") or [])
    excluded = (
        set(scope.get("excludeNamespaces") or [])
        | DEFAULT_EXCLUDED_NAMESPACES
    )

    available = {
        item.get("metadata", {}).get("name")
        for item in resource_items(
            request("/api/v1/namespaces")
        )
        if isinstance(item, dict)
        and isinstance(item.get("metadata"), dict)
        and item["metadata"].get("name")
    }

    selected = available - excluded
    if requested:
        missing = requested - available
        if missing:
            raise RuntimeError(
                "A requested namespace was not found."
            )
        selected &= requested

    return sorted(selected)


def collect_inventory(assignment, request=kubernetes_request):
    if assignment.get("executionMode") != "ASSESSMENT_ONLY":
        raise RuntimeError(
            "Only assessment-only discovery is supported."
        )

    source = assignment.get("source")
    if (
        not isinstance(source, dict)
        or source.get("platform")
        != "SELF_MANAGED_KUBERNETES"
    ):
        raise RuntimeError(
            "Unsupported source platform assignment."
        )

    scope = assignment.get("scope")
    if not isinstance(scope, dict):
        raise RuntimeError("Migration scope is missing.")

    sanitized = []

    for raw in resource_items(request("/api/v1/nodes")):
        sanitized.append(
            sanitize_resource(
                resource_from_endpoint(raw, "v1", "Node")
            )
        )

    namespaces = selected_namespaces(assignment, request)
    for namespace in namespaces:
        sanitized.append(
            sanitize_resource(
                {
                    "apiVersion": "v1",
                    "kind": "Namespace",
                    "metadata": {"name": namespace},
                }
            )
        )

        encoded_namespace = urllib.parse.quote(
            namespace,
            safe="",
        )
        for template in NAMESPACED_RESOURCE_PATHS:
            path = template.format(
                namespace=encoded_namespace
            )
            api_version, kind = RESOURCE_TYPE_BY_PATH[template]
            for raw in resource_items(request(path)):
                sanitized.append(
                    sanitize_resource(
                        resource_from_endpoint(
                            raw,
                            api_version,
                            kind,
                        )
                    )
                )
                if len(sanitized) > MAX_RESOURCES:
                    raise UnsafeInventory(
                        "Inventory resource limit exceeded."
                    )

    if scope.get("includeClusterScopedResources") is True:
        for path in CLUSTER_RESOURCE_PATHS:
            api_version, kind = RESOURCE_TYPE_BY_PATH[path]
            for raw in resource_items(request(path)):
                sanitized.append(
                    sanitize_resource(
                        resource_from_endpoint(
                            raw,
                            api_version,
                            kind,
                        )
                    )
                )
                if len(sanitized) > MAX_RESOURCES:
                    raise UnsafeInventory(
                        "Inventory resource limit exceeded."
                    )

    return finalize_inventory(sanitized)


def fetch_assignment():
    return navigan_request(
        required("NAVIGAN_API_BASE_URL"),
        required("NAVIGAN_SOURCE_CONNECTOR_ID"),
        required("NAVIGAN_SOURCE_CONNECTOR_TOKEN"),
        "assignment",
    )

def collect_source_catalogue(
    assignment,
    request=kubernetes_request,
    observed_at=None,
):
    if assignment.get("assignmentType") != "SOURCE_CATALOGUE":
        raise RuntimeError(
            "Unsupported migration connector assignment."
        )

    if assignment.get("executionMode") != "ASSESSMENT_ONLY":
        raise RuntimeError(
            "Only assessment-only discovery is supported."
        )

    source = assignment.get("source")
    if (
        not isinstance(source, dict)
        or source.get("platform")
        != "SELF_MANAGED_KUBERNETES"
    ):
        raise RuntimeError(
            "Unsupported source platform assignment."
        )

    migration_version = assignment.get("migrationVersion")
    if (
        not isinstance(migration_version, int)
        or migration_version < 1
    ):
        raise RuntimeError("Migration version is invalid.")

    version_payload = request("/version")
    kubernetes_version = version_payload.get("gitVersion")
    if not isinstance(kubernetes_version, str):
        raise RuntimeError(
            "Kubernetes version could not be determined."
        )

    nodes = resource_items(request("/api/v1/nodes"))
    architectures = sorted(
        {
            architecture.strip().lower()
            for node in nodes
            if isinstance(node, dict)
            for architecture in [
                node.get("status", {})
                .get("nodeInfo", {})
                .get("architecture")
            ]
            if isinstance(architecture, str)
            and architecture.strip()
        }
    )

    namespace_catalogue = []
    for namespace in selected_namespaces(
        assignment,
        request,
    ):
        encoded_namespace = urllib.parse.quote(
            namespace,
            safe="",
        )
        resource_counts = {}

        for template, kind in CATALOGUE_RESOURCE_PATHS:
            items = resource_items(
                request(
                    template.format(
                        namespace=encoded_namespace
                    )
                )
            )
            if items:
                resource_counts[kind] = len(items)

        namespace_catalogue.append(
            {
                "name": namespace,
                "resourceCounts": resource_counts,
            }
        )

    catalogue = {
        "schemaVersion": 1,
        "sourceKubernetesVersion": kubernetes_version,
        "nodeCount": len(nodes),
        "architectures": architectures,
        "namespaces": namespace_catalogue,
        "sensitiveDataIncluded": False,
    }

    digest = hashlib.sha256(
        json.dumps(
            catalogue,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    timestamp = observed_at
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    if isinstance(timestamp, datetime):
        timestamp = timestamp.isoformat().replace(
            "+00:00",
            "Z",
        )
    if not isinstance(timestamp, str):
        raise RuntimeError("Observation timestamp is invalid.")

    return {
        "version": 1,
        "migrationVersion": migration_version,
        "observedAt": timestamp,
        "sourceKubernetesVersion": kubernetes_version,
        "inventoryDigest": digest,
        "nodeCount": len(nodes),
        "architectures": architectures,
        "namespaces": namespace_catalogue,
        "sensitiveDataIncluded": False,
    }


def submit_source_catalogue(report):
    return navigan_request(
        required("NAVIGAN_API_BASE_URL"),
        required("NAVIGAN_SOURCE_CONNECTOR_ID"),
        required("NAVIGAN_SOURCE_CONNECTOR_TOKEN"),
        "inventory",
        method="POST",
        body=report,
    )


def collect_source_inventory(
    assignment,
    request=kubernetes_request,
    observed_at=None,
):
    if assignment.get("assignmentType") != "SOURCE_INVENTORY":
        raise RuntimeError(
            "Unsupported migration connector assignment."
        )

    migration_version = assignment.get("migrationVersion")
    if (
        not isinstance(migration_version, int)
        or migration_version < 1
    ):
        raise RuntimeError("Migration version is invalid.")

    version_payload = request("/version")
    kubernetes_version = version_payload.get("gitVersion")
    if not isinstance(kubernetes_version, str):
        raise RuntimeError(
            "Kubernetes version could not be determined."
        )

    inventory = collect_inventory(assignment, request)

    timestamp = observed_at
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    if isinstance(timestamp, datetime):
        timestamp = timestamp.isoformat().replace(
            "+00:00",
            "Z",
        )
    if not isinstance(timestamp, str):
        raise RuntimeError("Observation timestamp is invalid.")

    return {
        **inventory,
        "migrationVersion": migration_version,
        "observedAt": timestamp,
        "sourceKubernetesVersion": kubernetes_version,
    }


def submit_source_inventory(report):
    return navigan_request(
        required("NAVIGAN_API_BASE_URL"),
        required("NAVIGAN_SOURCE_CONNECTOR_ID"),
        required("NAVIGAN_SOURCE_CONNECTOR_TOKEN"),
        "source-inventory",
        method="POST",
        body=report,
    )


def run_once(
    fetch=fetch_assignment,
    collect=None,
    submit=None,
):
    assignment = fetch()
    assignment_type = assignment.get("assignmentType")

    if assignment_type == "NONE":
        return {
            **assignment,
            "status": assignment.get("status", "IDLE"),
        }
    if assignment_type == "SOURCE_CATALOGUE":
        collector = collect or collect_source_catalogue
        submitter = submit or submit_source_catalogue
        expected_status = "INVENTORY_READY"
    elif assignment_type == "SOURCE_INVENTORY":
        collector = collect or collect_source_inventory
        submitter = submit or submit_source_inventory
        expected_status = "ASSESSMENT_READY"
    else:
        raise RuntimeError(
            "Unsupported migration connector assignment."
        )

    report = collector(assignment)
    result = submitter(report)

    if result.get("status") != expected_status:
        raise RuntimeError(
            "Navigan did not accept the connector evidence."
        )

    return result


def run_forever(
    run=run_once,
    sleep=time.sleep,
    poll_seconds=None,
):
    interval = poll_seconds
    if interval is None:
        raw_interval = os.environ.get("NAVIGAN_POLL_SECONDS", "30")
        try:
            interval = int(raw_interval)
        except ValueError as exc:
            raise RuntimeError(
                "NAVIGAN_POLL_SECONDS must be an integer."
            ) from exc
    if not 5 <= interval <= 300:
        raise RuntimeError(
            "NAVIGAN_POLL_SECONDS must be between 5 and 300."
        )

    while True:
        try:
            run()
        except Exception as error:
            print(
                json.dumps(
                    {
                        "level": "error",
                        "event": "connector_cycle_failed",
                        "errorType": type(error).__name__,
                    }
                ),
                flush=True,
            )
        sleep(interval)


def main():
    run_forever()


if __name__ == "__main__":
    main()
