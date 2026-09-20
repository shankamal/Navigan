"""Environment-neutral access contract for private cluster tools."""

from dataclasses import dataclass
from urllib.parse import quote, urlsplit


@dataclass(frozen=True)
class ToolDefinition:
    code: str
    label: str
    component: str | None
    privilege: str
    path: str
    interactive: bool = False
    implemented: bool = True


TOOLS = (
    ToolDefinition(
        "HEADLAMP",
        "Kubernetes dashboard",
        "headlamp",
        "cluster.dashboard.view",
        "headlamp",
    ),
    ToolDefinition(
        "GRAFANA",
        "Grafana",
        "grafana",
        "cluster.dashboard.view",
        "grafana",
    ),
    ToolDefinition(
        "PROMETHEUS",
        "Prometheus",
        "prometheus",
        "cluster.dashboard.view",
        "prometheus",
    ),
    ToolDefinition(
        "ARGOCD",
        "Argo CD",
        "argocd",
        "cluster.dashboard.view",
        "argocd",
    ),
    ToolDefinition(
        "WEBKUBECTL",
        "WebKubectl",
        None,
        "cluster.webkubectl.open",
        "webkubectl",
        interactive=True,
        implemented=False,
    ),
)


def normalize_base_url(value):
    """Accept only an origin plus a path, never credentials, query or fragment."""
    value = str(value or "").strip().rstrip("/")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        return None
    return value


def _component_status(components, code):
    if not code:
        return "READY"
    component = next(
        (item for item in components if item.get("componentCode") == code),
        None,
    )
    return str((component or {}).get("status") or "MISSING").upper()


def resolve_tool_access(
    cluster,
    access,
    components,
    *,
    base_url,
    gateway_enabled=False,
    tunnel_enabled=False,
    tunnel_connected=False,
):
    """Resolve launch readiness without trusting frontend role inference."""
    normalized_base = normalize_base_url(base_url)
    gateway_ready = bool(normalized_base and gateway_enabled)
    connector_ready = _component_status(components, "connector") == "READY"
    tunnel_ready = bool(
        gateway_ready and tunnel_enabled and tunnel_connected and connector_ready
    )
    identity_status = str(
        cluster.get("identity_status") or "NOT_CONFIGURED"
    ).upper()
    cluster_active = str(cluster.get("status") or "").upper() in {
        "ACTIVE",
        "READY",
        "RUNNING",
    }
    items = []
    for tool in TOOLS:
        if not access.has(tool.privilege):
            continue
        component_status = _component_status(components, tool.component)
        reason = None
        if not cluster_active:
            reason = "The cluster must be active before tools can be opened."
        elif not tool.implemented:
            reason = "The WebKubectl interactive terminal is not enabled in this release."
        elif component_status != "READY":
            reason = (
                f"{tool.label} is not ready in this cluster "
                f"(current status: {component_status.replace('_', ' ').title()})."
            )
        elif not gateway_ready:
            reason = "The shared platform tools gateway is not deployed in this environment."
        elif not tunnel_ready:
            reason = "The cluster has not connected to the shared tools gateway."
        elif tool.interactive and identity_status != "READY":
            reason = (
                "Verified identity and Kubernetes authorization are required "
                f"(current status: {identity_status.replace('_', ' ').title()})."
            )
        enabled = reason is None
        launch_url = (
            f"{normalized_base}/clusters/{quote(cluster['cluster_id'], safe='')}/{tool.path}"
            if enabled
            else None
        )
        items.append(
            {
                "code": tool.code,
                "label": tool.label,
                "status": "READY" if enabled else "UNAVAILABLE",
                "componentStatus": component_status,
                "interactive": tool.interactive,
                "launchUrl": launch_url,
                "disabledReason": reason,
            }
        )
    return {
        "clusterId": cluster["cluster_id"],
        "customerId": cluster["customer_id"],
        "gateway": {
            "status": "READY" if gateway_ready else "NOT_DEPLOYED",
            "baseUrl": normalized_base,
        },
        "tunnel": {
            "status": "READY" if tunnel_ready else "NOT_CONNECTED",
            "connectorReady": connector_ready,
        },
        "tools": items,
    }
