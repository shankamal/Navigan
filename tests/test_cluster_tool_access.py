from navigan.modules.cluster_management.tool_access import (
    normalize_base_url,
    resolve_tool_access,
)
from navigan.shared.access import EffectiveAccess, Scope


def access(*privileges):
    return EffectiveAccess(
        "user",
        "User",
        1,
        frozenset(privileges),
        (Scope("PLATFORM"),),
    )


def cluster(identity_status="READY", status="ACTIVE"):
    return {
        "cluster_id": "CLU-ab5d1625584e4c7197112c7c590698ae",
        "customer_id": "CUS-test",
        "status": status,
        "identity_status": identity_status,
    }


def components():
    return [
        {"componentCode": code, "status": "READY"}
        for code in ("connector", "headlamp", "grafana", "prometheus", "argocd")
    ]


def test_tools_are_disabled_until_gateway_and_tunnel_are_ready():
    result = resolve_tool_access(
        cluster(),
        access("cluster.dashboard.view", "cluster.webkubectl.open"),
        components(),
        base_url="https://dev.navigan.click/tools",
    )

    assert result["gateway"]["status"] == "NOT_DEPLOYED"
    assert result["tunnel"]["status"] == "NOT_CONNECTED"
    assert all(item["launchUrl"] is None for item in result["tools"])


def test_ready_tools_use_opaque_cluster_id_under_common_environment_url():
    result = resolve_tool_access(
        cluster(),
        access("cluster.dashboard.view", "cluster.webkubectl.open"),
        components(),
        base_url="https://dev.navigan.click/tools",
        gateway_enabled=True,
        tunnel_enabled=True,
        tunnel_connected=True,
    )

    assert result["gateway"]["status"] == "READY"
    assert result["tunnel"]["status"] == "READY"
    assert {
        item["launchUrl"] for item in result["tools"] if item["launchUrl"]
    } == {
        "https://dev.navigan.click/tools/clusters/"
        "CLU-ab5d1625584e4c7197112c7c590698ae/headlamp",
        "https://dev.navigan.click/tools/clusters/"
        "CLU-ab5d1625584e4c7197112c7c590698ae/grafana",
        "https://dev.navigan.click/tools/clusters/"
        "CLU-ab5d1625584e4c7197112c7c590698ae/prometheus",
        "https://dev.navigan.click/tools/clusters/"
        "CLU-ab5d1625584e4c7197112c7c590698ae/argocd",
    }


def test_webkubectl_fails_closed_without_verified_identity():
    result = resolve_tool_access(
        cluster(identity_status="NOT_CONFIGURED"),
        access("cluster.dashboard.view", "cluster.webkubectl.open"),
        components(),
        base_url="https://dev.navigan.click/tools",
        gateway_enabled=True,
        tunnel_enabled=True,
        tunnel_connected=True,
    )

    webkubectl = next(item for item in result["tools"] if item["code"] == "WEBKUBECTL")
    grafana = next(item for item in result["tools"] if item["code"] == "GRAFANA")
    assert webkubectl["launchUrl"] is None
    assert "not enabled" in webkubectl["disabledReason"]
    assert grafana["launchUrl"]


def test_tool_catalogue_is_privilege_filtered():
    result = resolve_tool_access(
        cluster(),
        access("cluster.dashboard.view"),
        components(),
        base_url="https://dev.navigan.click/tools",
        gateway_enabled=True,
        tunnel_enabled=True,
        tunnel_connected=True,
    )

    assert {item["code"] for item in result["tools"]} == {
        "HEADLAMP",
        "GRAFANA",
        "PROMETHEUS",
        "ARGOCD",
    }


def test_base_url_rejects_non_https_or_credentialed_values():
    assert normalize_base_url("http://dev.navigan.click/tools") is None
    assert normalize_base_url("https://user:pass@dev.navigan.click/tools") is None
    assert normalize_base_url("https://dev.navigan.click/tools?cluster=name") is None
