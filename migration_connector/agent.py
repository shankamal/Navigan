"""Outbound-only Kubernetes migration discovery agent."""

import json
import os
import ssl
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
)

CLUSTER_RESOURCE_PATHS = (
    "/apis/storage.k8s.io/v1/storageclasses",
    "/apis/apiextensions.k8s.io/v1/customresourcedefinitions",
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
        with urllib.request.urlopen(
            request,
            context=context,
            timeout=20,
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
):
    base_url = secure_base_url(base_url)
    request = urllib.request.Request(
        (
            f"{base_url}/migration-connectors/"
            f"{connector_id}/{path.lstrip('/')}"
        ),
        method="GET",
        headers={
            "Authorization": f"Bearer {connector_token}",
            "Accept": "application/json",
            "User-Agent": "navigan-migration-connector/0.1.0",
        },
    )

    try:
        with urllib.request.urlopen(
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
        sanitized.append(sanitize_resource(raw))

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
            for raw in resource_items(request(path)):
                sanitized.append(sanitize_resource(raw))
                if len(sanitized) > MAX_RESOURCES:
                    raise UnsafeInventory(
                        "Inventory resource limit exceeded."
                    )

    if scope.get("includeClusterScopedResources") is True:
        for path in CLUSTER_RESOURCE_PATHS:
            for raw in resource_items(request(path)):
                sanitized.append(sanitize_resource(raw))
                if len(sanitized) > MAX_RESOURCES:
                    raise UnsafeInventory(
                        "Inventory resource limit exceeded."
                    )

    return finalize_inventory(sanitized)


def fetch_assignment():
    return navigan_request(
        required("NAVIGAN_API_BASE_URL"),
        required("NAVIGAN_MIGRATION_CONNECTOR_ID"),
        required("NAVIGAN_MIGRATION_CONNECTOR_TOKEN"),
        "assignment",
    )
