import base64
import io
import threading
import urllib.error

import pytest

from connector import agent


def test_headlamp_uses_helm_release_service_name():
    assert agent.DEFAULT_TOOL_SERVICES["headlamp"] == (
        "http://navigan-dashboard-headlamp."
        "navigan-dashboard.svc.cluster.local:80"
    )


def test_argocd_proxy_removes_public_prefix(monkeypatch):
    observed = {}

    class Response:
        status = 200
        headers = {"Content-Type": "text/html"}

        def read(self, _limit):
            return b"ok"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    def urlopen(request, timeout):
        observed["url"] = request.full_url
        observed["prefix"] = request.headers["X-forwarded-prefix"]
        observed["x-grpc-web"] = request.headers["X-grpc-web"]
        observed["x-user-agent"] = request.headers["X-user-agent"]
        observed["grpc-timeout"] = request.headers["Grpc-timeout"]
        observed["origin"] = request.headers["Origin"]
        assert timeout == 25
        return Response()

    monkeypatch.setattr(agent, "open_tool_request", urlopen)

    result = agent.tool_request(
        "argocd",
        "/tools/clusters/CLU-123/argocd/applications",
        "view=tree",
        "GET",
        {
            "X-Grpc-Web": "1",
            "X-User-Agent": "grpc-web-javascript/0.1",
            "Grpc-Timeout": "30S",
            "Origin": "https://dev.navigan.click",
        },
        "",
    )

    assert observed["url"] == (
        "http://argocd-server.argocd.svc.cluster.local:80/"
        "applications?view=tree"
    )
    assert observed["prefix"] == "/tools/clusters/CLU-123/argocd"
    assert result["status"] == 200
    assert observed["x-grpc-web"] == "1"
    assert observed["x-user-agent"] == "grpc-web-javascript/0.1"
    assert observed["grpc-timeout"] == "30S"
    assert observed["origin"] == "https://dev.navigan.click"


def test_grafana_proxy_removes_public_prefix(monkeypatch):
    observed = {}

    class Response:
        status = 200
        headers = {"Content-Type": "application/json"}

        def read(self, _limit):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    def urlopen(request, timeout):
        observed["url"] = request.full_url
        observed["prefix"] = request.headers["X-forwarded-prefix"]
        assert timeout == 25
        return Response()

    monkeypatch.setattr(agent, "open_tool_request", urlopen)

    result = agent.tool_request(
        "grafana",
        "/tools/clusters/CLU-123/grafana/api/ds/query",
        "",
        "POST",
        {"Content-Type": "application/json"},
        base64.b64encode(b"{}").decode(),
    )

    assert observed == {
        "url": (
            "http://navigan-monitoring-grafana."
            "navigan-monitoring.svc.cluster.local:80/api/ds/query"
        ),
        "prefix": "/tools/clusters/CLU-123/grafana",
    }
    assert result["status"] == 200


def test_headlamp_proxy_supplies_trusted_user_identity(monkeypatch):
    observed = {}

    class Response:
        status = 200
        headers = {"Content-Type": "text/html"}

        def read(self, _limit):
            return b"ok"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    def urlopen(request, timeout):
        observed.update(request.headers)
        assert timeout == 25
        return Response()

    monkeypatch.setattr(agent, "open_tool_request", urlopen)

    agent.tool_request(
        "headlamp",
        "/tools/clusters/CLU-123/headlamp/",
        "",
        "GET",
        {"X-Forwarded-User": "untrusted-browser-value"},
        "",
    )

    assert observed["X-forwarded-user"] == "navigan-tool-session"


def test_grafana_redirect_is_returned_to_browser(monkeypatch):
    def redirect(request, timeout):
        assert timeout == 25
        raise urllib.error.HTTPError(
            request.full_url,
            302,
            "Found",
            {"Location": "/login"},
            io.BytesIO(b""),
        )

    monkeypatch.setattr(agent, "open_tool_request", redirect)

    result = agent.tool_request(
        "grafana",
        "/tools/clusters/CLU-123/grafana/",
        "",
        "GET",
        {},
        "",
    )

    assert result["status"] == 302
    assert result["headers"]["location"] == "/login"


def test_prometheus_live_notifications_are_disabled_without_streaming():
    result = agent.tool_request(
        "prometheus",
        "/tools/clusters/CLU-123/prometheus/api/v1/notifications/live",
        "",
        "GET",
        {},
        "",
    )

    assert result == {
        "status": 204,
        "headers": {"cache-control": "no-store"},
        "body": "",
    }


def test_tool_tunnel_keeps_receiving_heartbeats_while_proxy_request_runs(
    monkeypatch,
):
    release_request = threading.Event()
    response_sent = threading.Event()
    sent = []

    class Client:
        receives = 0

        def __init__(self, _url, _headers):
            pass

        def receive(self):
            self.receives += 1
            if self.receives == 1:
                return {
                    "type": "request",
                    "id": "request-1",
                    "tool": "argocd",
                    "path": "/applications",
                }
            if self.receives == 2:
                return {"type": "ping"}
            release_request.set()
            assert response_sent.wait(1)
            raise RuntimeError("end test connection")

        def send(self, value):
            sent.append(value)
            if value.get("type") == "response":
                response_sent.set()

        def close(self):
            pass

    def request(*_args):
        assert release_request.wait(1)
        return {"status": 200, "headers": {}, "body": ""}

    monkeypatch.setattr(agent, "WebSocketClient", Client)
    monkeypatch.setattr(agent, "tool_request", request)
    monkeypatch.setenv("NAVIGAN_TOOLS_TUNNEL_URL", "wss://tools.example.test/tunnel")
    monkeypatch.setattr(
        agent.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(StopIteration()),
    )

    with pytest.raises(StopIteration):
        agent.tools_tunnel("KCC-" + ("a" * 32), "x" * 40)

    assert sum(item.get("type") == "heartbeat" for item in sent) == 2
    assert any(item.get("type") == "response" for item in sent)


def test_argocd_readiness_accepts_stateful_application_controller(monkeypatch):
    responses = [
        {
            "items": [
                {
                    "metadata": {"name": "argocd-server"},
                    "spec": {"replicas": 1},
                    "status": {"availableReplicas": 1},
                },
                {
                    "metadata": {"name": "argocd-repo-server"},
                    "spec": {"replicas": 1},
                    "status": {"availableReplicas": 1},
                },
            ]
        },
        {
            "items": [
                {
                    "metadata": {"name": "argocd-application-controller"},
                    "spec": {"replicas": 1},
                    "status": {"readyReplicas": 1},
                }
            ]
        },
    ]
    monkeypatch.setattr(agent, "kubernetes_request", lambda _path: responses.pop(0))

    assert agent.workloads_ready(
        "argocd",
        deployments=["argocd-server", "argocd-repo-server"],
        statefulsets=["argocd-application-controller"],
    )


def test_error_detail_is_single_line_and_bounded():
    detail = agent.error_detail(RuntimeError("first line\n" + ("x" * 600)))

    assert "\n" not in detail
    assert len(detail) == 500


def test_runtime_inventory_reports_bounded_cluster_health(monkeypatch):
    responses = [
        {
            "items": [
                {
                    "metadata": {"name": "node-1"},
                    "status": {
                        "conditions": [{"type": "Ready", "status": "True"}]
                    },
                }
            ]
        },
        {
            "items": [
                {
                    "metadata": {"name": "api", "namespace": "apps"},
                    "spec": {"replicas": 2},
                    "status": {"availableReplicas": 2},
                }
            ]
        },
        {
            "items": [
                {
                    "metadata": {"name": "database", "namespace": "apps"},
                    "spec": {"replicas": 1},
                    "status": {"readyReplicas": 1},
                }
            ]
        },
        {
            "items": [
                {
                    "metadata": {"name": "falco", "namespace": "falco"},
                    "status": {
                        "desiredNumberScheduled": 2,
                        "numberReady": 2,
                    },
                }
            ]
        },
        {
            "items": [
                {
                    "metadata": {"name": "api-1", "namespace": "apps"},
                    "status": {
                        "phase": "Running",
                        "conditions": [{"type": "Ready", "status": "True"}],
                        "containerStatuses": [{"restartCount": 3}],
                    },
                }
            ]
        },
        {
            "items": [
                {
                    "metadata": {"name": "api", "namespace": "apps"},
                    "status": {},
                }
            ]
        },
        {
            "items": [
                {
                    "metadata": {
                        "namespace": "apps",
                        "creationTimestamp": "2026-09-19T10:00:00Z",
                    },
                    "reason": "BackOff",
                    "message": "Container restarted",
                    "count": 2,
                    "involvedObject": {"kind": "Pod", "name": "api-1"},
                }
            ]
        },
    ]
    paths = []

    def request(path):
        paths.append(path)
        return responses.pop(0)

    monkeypatch.setattr(agent, "kubernetes_request", request)

    inventory = agent.runtime_inventory()

    daemonset = next(
        item for item in inventory["resources"] if item["kind"] == "DaemonSet"
    )
    service = next(
        item for item in inventory["resources"] if item["kind"] == "Service"
    )
    assert daemonset["desired"] == 2
    assert daemonset["ready"] == 2
    assert service["status"] == "HEALTHY"
    assert service["ready"] == 1
    assert inventory["metrics"] == {
        "nodeCount": 1,
        "readyNodeCount": 1,
        "podCount": 1,
        "readyPodCount": 1,
        "containerRestartCount": 3,
        "warningEventCount": 1,
    }
    assert inventory["warningEvents"][0]["reason"] == "BackOff"
    assert "fieldSelector=type%3DWarning" in paths[-1]
