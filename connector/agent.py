"""Minimal outbound-only Navigan cluster connector."""

import base64
import concurrent.futures
import hashlib
import hmac
import json
import os
import socket
import ssl
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

KUBERNETES_HOST = os.environ.get("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
KUBERNETES_PORT = os.environ.get("KUBERNETES_SERVICE_PORT_HTTPS", "443")
SERVICE_ACCOUNT = "/var/run/secrets/kubernetes.io/serviceaccount"
READY_FILE = os.environ.get("NAVIGAN_READY_FILE", "/var/run/navigan/ready")
CONNECTOR_DEPLOYMENT = os.environ.get(
    "NAVIGAN_CONNECTOR_DEPLOYMENT", "navigan-cluster-connector"
)
MAX_RUNTIME_RESOURCES_PER_KIND = 50
MAX_WARNING_EVENTS = 50
MAX_TUNNEL_MESSAGE_BYTES = 8 * 1024 * 1024
DEFAULT_TOOL_SERVICES = {
    "headlamp": "http://navigan-dashboard-headlamp.navigan-dashboard.svc.cluster.local:80",
    "grafana": "http://navigan-monitoring-grafana.navigan-monitoring.svc.cluster.local:80",
    "prometheus": "http://navigan-monitoring-prometheus.navigan-monitoring.svc.cluster.local:9090",
    "argocd": "http://argocd-server.argocd.svc.cluster.local:80",
}


class PreserveRedirectResponse(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


TOOL_HTTP = urllib.request.build_opener(PreserveRedirectResponse)


def open_tool_request(request, timeout):
    return TOOL_HTTP.open(request, timeout=timeout)


def required(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def read(path):
    with open(path, encoding="utf-8") as stream:
        return stream.read().strip()


def kubernetes_request(path, method="GET", body=None, content_type="application/json"):
    token = read(f"{SERVICE_ACCOUNT}/token")
    context = ssl.create_default_context(cafile=f"{SERVICE_ACCOUNT}/ca.crt")
    request = urllib.request.Request(
        f"https://{KUBERNETES_HOST}:{KUBERNETES_PORT}{path}",
        data=json.dumps(body, separators=(",", ":")).encode() if body is not None else None,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": content_type,
        },
    )
    try:
        with urllib.request.urlopen(request, context=context, timeout=20) as response:
            return json.load(response) if response.length != 0 else {}
    except urllib.error.HTTPError as error:
        detail = error.read(512).decode("utf-8", "replace")
        raise RuntimeError(f"kubernetes API returned HTTP {error.code}: {detail}") from error


def namespaces():
    payload = kubernetes_request("/api/v1/namespaces")
    return sorted(
        {
            item.get("metadata", {}).get("name")
            for item in payload.get("items", [])
            if item.get("metadata", {}).get("name")
        }
    )


def navigan_request(base_url, connector_id, connector_token, path, method="GET", body=None):
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/connectors/{connector_id}{path}",
        data=json.dumps(body, separators=(",", ":")).encode() if body is not None else None,
        method=method,
        headers={
            "Authorization": f"Bearer {connector_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "navigan-cluster-connector/0.2.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response) if response.length != 0 else {}
    except urllib.error.HTTPError as error:
        detail = error.read(512).decode("utf-8", "replace")
        raise RuntimeError(
            f"Navigan API returned HTTP {error.code}: {detail}"
        ) from error


def tool_services():
    configured = os.environ.get("NAVIGAN_TOOL_SERVICE_MAP", "").strip()
    if not configured:
        return DEFAULT_TOOL_SERVICES
    value = json.loads(configured)
    if (
        not isinstance(value, dict)
        or set(value) - set(DEFAULT_TOOL_SERVICES)
        or any(
            not isinstance(name, str)
            or not isinstance(target, str)
            or not target.startswith("http://")
            for name, target in value.items()
        )
    ):
        raise RuntimeError("NAVIGAN_TOOL_SERVICE_MAP is invalid")
    return {**DEFAULT_TOOL_SERVICES, **value}


def tool_request(tool, path, query, method, headers, body):
    target = tool_services().get(tool)
    if not target:
        return {
            "status": 501,
            "headers": {"content-type": "text/plain; charset=utf-8"},
            "body": base64.b64encode(b"Tool is not supported.").decode(),
        }
    safe_path = path if path.startswith("/") else "/" + path
    public_prefix = ""
    path_parts = safe_path.split("/", 6)
    if (
        len(path_parts) >= 6
        and path_parts[1:3] == ["tools", "clusters"]
        and path_parts[4] == tool
    ):
        public_prefix = "/" + "/".join(path_parts[1:5])
    # Grafana and Argo CD generate browser URLs for their configured external
    # subpaths while their supported reverse-proxy setup removes that prefix
    # before forwarding requests to the internal HTTP server.
    if tool in {"grafana", "argocd"} and public_prefix:
        safe_path = safe_path[len(public_prefix):] or "/"
    # Alertmanager is intentionally disabled in the baseline. Prometheus keeps
    # this EventSource open indefinitely, which cannot be represented by the
    # bounded request/response tunnel. HTTP 204 tells the browser not to retry.
    if tool == "prometheus" and safe_path.endswith(
        "/api/v1/notifications/live"
    ):
        return {
            "status": 204,
            "headers": {"cache-control": "no-store"},
            "body": "",
        }
    url = target.rstrip("/") + safe_path
    if query:
        url += "?" + query
    request_headers = {
        str(name): str(value)
        for name, value in (headers or {}).items()
        if str(name).lower()
        in {
            "accept",
            "accept-encoding",
            "accept-language",
            "content-type",
            "if-none-match",
            "if-modified-since",
            "range",
            "user-agent",
            "grpc-timeout",
            "origin",
            "x-grpc-web",
            "x-user-agent",
        }
    }
    request_headers["X-Forwarded-Proto"] = "https"
    if public_prefix:
        request_headers["X-Forwarded-Prefix"] = public_prefix
    # Headlamp is private and can only be reached after the gateway validates a
    # Navigan tool session. Supply the trusted proxy identity here rather than
    # accepting a spoofable value from the browser.
    if tool == "headlamp":
        request_headers["X-Forwarded-User"] = "navigan-tool-session"
    request = urllib.request.Request(
        url,
        data=base64.b64decode(body, validate=True) if body else None,
        method=method,
        headers=request_headers,
    )
    try:
        response = open_tool_request(request, timeout=25)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        response_body = response.read(MAX_TUNNEL_MESSAGE_BYTES + 1)
        if len(response_body) > MAX_TUNNEL_MESSAGE_BYTES:
            raise RuntimeError("tool response exceeds tunnel limit")
        response_headers = {
            name.lower(): value
            for name, value in response.headers.items()
            if name.lower()
            not in {
                "connection",
                "content-length",
                "set-cookie",
                "transfer-encoding",
                "upgrade",
            }
        }
        return {
            "status": response.status,
            "headers": response_headers,
            "body": base64.b64encode(response_body).decode(),
        }


class WebSocketClient:
    def __init__(self, url, headers):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "wss" or not parsed.hostname:
            raise RuntimeError("NAVIGAN_TOOLS_TUNNEL_URL must use wss")
        self.parsed = parsed
        raw = socket.create_connection((parsed.hostname, parsed.port or 443), timeout=30)
        self.socket = ssl.create_default_context().wrap_socket(
            raw, server_hostname=parsed.hostname
        )
        self.socket.settimeout(60)
        self.send_lock = threading.Lock()
        key = base64.b64encode(os.urandom(16)).decode()
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        request_headers = {
            "Host": parsed.netloc,
            "Upgrade": "websocket",
            "Connection": "Upgrade",
            "Sec-WebSocket-Key": key,
            "Sec-WebSocket-Version": "13",
            **headers,
        }
        request = (
            f"GET {path} HTTP/1.1\r\n"
            + "".join(f"{name}: {value}\r\n" for name, value in request_headers.items())
            + "\r\n"
        )
        self.socket.sendall(request.encode())
        response = b""
        while b"\r\n\r\n" not in response:
            response += self.socket.recv(4096)
            if len(response) > 65536:
                raise RuntimeError("invalid websocket handshake")
        header, self.buffer = response.split(b"\r\n\r\n", 1)
        lines = header.decode("iso-8859-1").split("\r\n")
        if " 101 " not in lines[0]:
            raise RuntimeError("tools gateway rejected tunnel")
        received = {
            name.strip().lower(): value.strip()
            for name, value in (
                line.split(":", 1) for line in lines[1:] if ":" in line
            )
        }
        expected = base64.b64encode(
            hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
            ).digest()
        ).decode()
        if not hmac.compare_digest(received.get("sec-websocket-accept", ""), expected):
            raise RuntimeError("invalid websocket handshake")

    def _read(self, size):
        while len(self.buffer) < size:
            value = self.socket.recv(max(4096, size - len(self.buffer)))
            if not value:
                raise RuntimeError("tools gateway closed tunnel")
            self.buffer += value
        value, self.buffer = self.buffer[:size], self.buffer[size:]
        return value

    def receive(self):
        while True:
            first, second = self._read(2)
            opcode = first & 0x0F
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read(8))[0]
            if length > MAX_TUNNEL_MESSAGE_BYTES:
                raise RuntimeError("gateway tunnel message exceeds limit")
            masked = second & 0x80
            mask = self._read(4) if masked else None
            payload = bytearray(self._read(length))
            if mask:
                for index in range(length):
                    payload[index] ^= mask[index % 4]
            if opcode == 0x8:
                raise RuntimeError("tools gateway closed tunnel")
            if opcode == 0x9:
                self.send_frame(bytes(payload), 0xA)
                continue
            if opcode == 0x1:
                return json.loads(bytes(payload).decode())

    def send_frame(self, payload, opcode=0x1):
        mask = os.urandom(4)
        length = len(payload)
        header = bytearray([0x80 | opcode])
        if length < 126:
            header.append(0x80 | length)
        elif length <= 65535:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        masked = bytearray(payload)
        for index in range(length):
            masked[index] ^= mask[index % 4]
        with self.send_lock:
            self.socket.sendall(bytes(header) + mask + bytes(masked))

    def send(self, value):
        self.send_frame(json.dumps(value, separators=(",", ":")).encode())

    def close(self):
        try:
            self.socket.close()
        except OSError:
            pass


def tools_tunnel(connector_id, connector_token):
    tunnel_url = required("NAVIGAN_TOOLS_TUNNEL_URL")
    while True:
        client = None
        workers = None
        try:
            client = WebSocketClient(
                tunnel_url,
                {
                    "Authorization": f"Bearer {connector_token}",
                    "X-Navigan-Connector-Id": connector_id,
                    "User-Agent": "navigan-cluster-connector/0.3.0",
                },
            )
            workers = concurrent.futures.ThreadPoolExecutor(
                max_workers=8,
                thread_name_prefix="navigan-tool-proxy",
            )
            client.send({"type": "heartbeat", "at": int(time.time() * 1000)})
            while True:
                message = client.receive()
                if message.get("type") == "ping":
                    client.send({"type": "heartbeat", "at": int(time.time() * 1000)})
                    continue
                if message.get("type") != "request":
                    continue
                workers.submit(handle_tool_request, client, message)
        except Exception as error:
            print(
                json.dumps(
                    {
                        "event": "tools_tunnel_disconnected",
                        "errorType": type(error).__name__,
                        "error": error_detail(error),
                    }
                ),
                flush=True,
            )
        finally:
            if workers:
                workers.shutdown(wait=False, cancel_futures=True)
            if client:
                client.close()
        time.sleep(5)


def handle_tool_request(client, message):
    request_id = message.get("id")
    try:
        result = tool_request(
            message.get("tool", ""),
            message.get("path", "/"),
            message.get("query", ""),
            message.get("method", "GET"),
            message.get("headers", {}),
            message.get("body", ""),
        )
    except Exception as error:
        result = {
            "status": 502,
            "headers": {"content-type": "text/plain; charset=utf-8"},
            "body": base64.b64encode(
                b"Private cluster service is unavailable."
            ).decode(),
        }
        print(
            json.dumps(
                {
                    "event": "tool_proxy_failed",
                    "tool": message.get("tool"),
                    "errorType": type(error).__name__,
                    "error": error_detail(error),
                }
            ),
            flush=True,
        )
    try:
        client.send({"type": "response", "id": request_id, **result})
    except Exception as error:
        print(
            json.dumps(
                {
                    "event": "tool_response_failed",
                    "tool": message.get("tool"),
                    "errorType": type(error).__name__,
                    "error": error_detail(error),
                }
            ),
            flush=True,
        )


def report(base_url, connector_id, connector_token, revision, names):
    navigan_request(
        base_url, connector_id, connector_token, "/inventory/namespaces", "POST",
        {
            "revision": revision,
            "namespaces": [{"name": name} for name in names],
        },
    )


def workloads_ready(namespace, deployments=(), statefulsets=()):
    payload = kubernetes_request(f"/apis/apps/v1/namespaces/{namespace}/deployments")
    available_deployments = {
        item.get("metadata", {}).get("name"): item
        for item in payload.get("items", [])
    }
    for name in deployments:
        deployment = available_deployments.get(name)
        if not deployment:
            return False
        desired = deployment.get("spec", {}).get("replicas", 1)
        available = deployment.get("status", {}).get("availableReplicas", 0)
        if desired < 1 or available < desired:
            return False
    payload = kubernetes_request(f"/apis/apps/v1/namespaces/{namespace}/statefulsets")
    available_statefulsets = {
        item.get("metadata", {}).get("name"): item
        for item in payload.get("items", [])
    }
    for name in statefulsets:
        statefulset = available_statefulsets.get(name)
        if not statefulset:
            return False
        desired = statefulset.get("spec", {}).get("replicas", 1)
        ready = statefulset.get("status", {}).get("readyReplicas", 0)
        if desired < 1 or ready < desired:
            return False
    return True


def platform_components():
    components = [
        {"code": "connector", "status": "READY", "healthStatus": "Healthy"}
    ]
    try:
        argocd_ready = workloads_ready(
            "argocd",
            deployments=["argocd-server", "argocd-repo-server"],
            statefulsets=["argocd-application-controller"],
        )
    except RuntimeError:
        argocd_ready = False
    components.append(
        {
            "code": "argocd",
            "status": "READY" if argocd_ready else "MISSING",
            "healthStatus": "Healthy" if argocd_ready else "Missing",
        }
    )
    try:
        payload = kubernetes_request(
            "/apis/argoproj.io/v1alpha1/namespaces/argocd/applications"
        )
        applications = {
            item.get("metadata", {}).get("name"): item
            for item in payload.get("items", [])
        }
    except RuntimeError:
        applications = {}
    mapping = {
        "navigan-monitoring": ["prometheus", "grafana"],
        "navigan-falco": ["falco"],
        "navigan-dashboard": ["headlamp"],
    }
    for application_name, codes in mapping.items():
        application = applications.get(application_name, {})
        sync_status = application.get("status", {}).get("sync", {}).get("status")
        health_status = application.get("status", {}).get("health", {}).get("status")
        sources = application.get("spec", {}).get("sources", [])
        version = sources[0].get("targetRevision") if sources else None
        ready = sync_status == "Synced" and health_status == "Healthy"
        status = (
            "READY"
            if ready
            else "PROGRESSING"
            if health_status == "Progressing"
            else "DEGRADED"
            if application
            else "MISSING"
        )
        for code in codes:
            item = {
                "code": code,
                "status": status,
                "syncStatus": sync_status or "Unknown",
                "healthStatus": health_status or "Missing",
            }
            if version:
                item["version"] = version
            components.append(item)
    return components


def report_platform_components(
    base_url, connector_id, connector_token, revision, components, runtime
):
    navigan_request(
        base_url,
        connector_id,
        connector_token,
        "/inventory/platform-components",
        "POST",
        {"revision": revision, "components": components, "runtime": runtime},
    )


def runtime_inventory():
    resources = []

    def collect(path, kind, desired_key=None, ready_key=None, desired_source="spec"):
        payload = kubernetes_request(path)
        for item in payload.get("items", [])[:MAX_RUNTIME_RESOURCES_PER_KIND]:
            metadata = item.get("metadata", {})
            spec = item.get("spec", {})
            status = item.get("status", {})
            desired_values = status if desired_source == "status" else spec
            desired = desired_values.get(desired_key, 1) if desired_key else 1
            ready = status.get(ready_key, 0) if ready_key else 0
            if kind == "Node":
                ready = int(
                    any(
                        condition.get("type") == "Ready"
                        and condition.get("status") == "True"
                        for condition in status.get("conditions", [])
                    )
                )
            elif kind == "Pod":
                ready = int(
                    any(
                        condition.get("type") == "Ready"
                        and condition.get("status") == "True"
                        for condition in status.get("conditions", [])
                    )
                )
                desired = 1
            elif kind == "Service":
                ready = 1
                desired = 1
            resources.append(
                {
                    "kind": kind,
                    "namespace": metadata.get("namespace"),
                    "name": metadata.get("name"),
                    "status": (
                        status.get("phase")
                        or ("HEALTHY" if ready >= desired and desired > 0 else "DEGRADED")
                    ),
                    "ready": int(ready or 0),
                    "desired": int(desired or 0),
                    "restarts": sum(
                        value.get("restartCount", 0)
                        for value in status.get("containerStatuses", [])
                    ),
                }
            )

    collect("/api/v1/nodes", "Node")
    collect("/apis/apps/v1/deployments", "Deployment", "replicas", "availableReplicas")
    collect("/apis/apps/v1/statefulsets", "StatefulSet", "replicas", "readyReplicas")
    collect(
        "/apis/apps/v1/daemonsets",
        "DaemonSet",
        "desiredNumberScheduled",
        "numberReady",
        "status",
    )
    collect("/api/v1/pods", "Pod")
    collect("/api/v1/services", "Service")

    event_query = urllib.parse.urlencode({"fieldSelector": "type=Warning"})
    event_payload = kubernetes_request(f"/api/v1/events?{event_query}")
    warning_events = []
    for item in event_payload.get("items", [])[-MAX_WARNING_EVENTS:]:
        metadata = item.get("metadata", {})
        involved = item.get("involvedObject", {})
        warning_events.append(
            {
                "namespace": metadata.get("namespace"),
                "reason": item.get("reason") or "Warning",
                "resourceKind": involved.get("kind"),
                "resourceName": involved.get("name"),
                "message": (item.get("message") or "")[:500],
                "count": int(item.get("count") or 1),
                "lastObservedAt": (
                    item.get("eventTime")
                    or item.get("lastTimestamp")
                    or metadata.get("creationTimestamp")
                ),
            }
        )
    nodes = [item for item in resources if item["kind"] == "Node"]
    pods = [item for item in resources if item["kind"] == "Pod"]
    return {
        "resources": resources,
        "warningEvents": warning_events,
        "metrics": {
            "nodeCount": len(nodes),
            "readyNodeCount": sum(item["ready"] for item in nodes),
            "podCount": len(pods),
            "readyPodCount": sum(item["ready"] for item in pods),
            "containerRestartCount": sum(item["restarts"] for item in pods),
            "warningEventCount": len(warning_events),
        },
    }


def refresh_github_repository_credential(
    base_url, connector_id, connector_token
):
    credential = navigan_request(
        base_url,
        connector_id,
        connector_token,
        "/github/credentials",
    )
    data = {
        "username": base64.b64encode(
            credential["username"].encode()
        ).decode(),
        "password": base64.b64encode(
            credential["token"].encode()
        ).decode(),
        "url": base64.b64encode(
            credential["repositoryUrl"].encode()
        ).decode(),
        "type": base64.b64encode(b"git").decode(),
    }
    kubernetes_request(
        "/api/v1/namespaces/argocd/secrets/navigan-system-repository",
        "PATCH",
        {"data": data},
        "application/merge-patch+json",
    )
    return credential.get("expiresAt")


def resource_name(assignment_id):
    return "navigan-" + assignment_id.removeprefix("KAA-").lower()


def apply_resource(path, value):
    name = value["metadata"]["name"]
    target = f"{path}/{name}?fieldManager=navigan-connector&force=true"
    kubernetes_request(target, "PATCH", value, "application/apply-patch+yaml")


def delete_resource(path, name):
    try:
        kubernetes_request(f"{path}/{name}", "DELETE", {"propagationPolicy": "Background"})
    except RuntimeError as error:
        if "HTTP 404" not in str(error):
            raise


def connector_namespace():
    configured = os.environ.get("NAVIGAN_CONNECTOR_NAMESPACE", "").strip()
    return configured or read(f"{SERVICE_ACCOUNT}/namespace")


def reconcile_connector_runtime(policy):
    desired_image = (policy or {}).get("desiredImage", "").strip()
    if not desired_image:
        return False
    if (
        len(desired_image) > 2048
        or any(character.isspace() for character in desired_image)
        or "\x00" in desired_image
    ):
        raise RuntimeError("desired connector image is invalid")

    namespace = connector_namespace()
    path = (
        f"/apis/apps/v1/namespaces/{urllib.parse.quote(namespace, safe='')}/"
        f"deployments/{urllib.parse.quote(CONNECTOR_DEPLOYMENT, safe='')}"
    )
    deployment = kubernetes_request(path)
    containers = deployment.get("spec", {}).get("template", {}).get("spec", {}).get(
        "containers", []
    )
    connector = next(
        (item for item in containers if item.get("name") == "connector"),
        None,
    )
    if connector is None:
        raise RuntimeError("connector container was not found in its deployment")
    if connector.get("image") == desired_image:
        return False

    kubernetes_request(
        path,
        "PATCH",
        {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "navigan.io/connector-updated-at": str(int(time.time()))
                        }
                    },
                    "spec": {
                        "containers": [
                            {"name": "connector", "image": desired_image}
                        ]
                    },
                }
            }
        },
        "application/strategic-merge-patch+json",
    )
    print(
        json.dumps(
            {
                "event": "connector_runtime_upgrade_requested",
                "deployment": CONNECTOR_DEPLOYMENT,
                "namespace": namespace,
            }
        ),
        flush=True,
    )
    return True


def reconcile_assignment(assignment):
    name = resource_name(assignment["assignmentId"])
    labels = {
        "app.kubernetes.io/managed-by": "navigan",
        "navigan.io/assignment-id": assignment["assignmentId"],
    }
    subject = {
        "apiGroup": "rbac.authorization.k8s.io",
        "kind": "User" if assignment["subjectType"] == "USER" else "Group",
        "name": "navigan:" + assignment["subjectId"],
    }
    namespaced = assignment["scopeType"] == "NAMESPACE"
    namespace = assignment.get("namespace")
    role_kind = "Role" if namespaced else "ClusterRole"
    role_path = (
        f"/apis/rbac.authorization.k8s.io/v1/namespaces/{namespace}/roles"
        if namespaced else "/apis/rbac.authorization.k8s.io/v1/clusterroles"
    )
    binding_path = (
        f"/apis/rbac.authorization.k8s.io/v1/namespaces/{namespace}/rolebindings"
        if namespaced else "/apis/rbac.authorization.k8s.io/v1/clusterrolebindings"
    )
    metadata = {"name": name, "labels": labels}
    if namespaced:
        metadata["namespace"] = namespace
    apply_resource(role_path, {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": role_kind,
        "metadata": metadata,
        "rules": assignment["rules"],
    })
    apply_resource(binding_path, {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": role_kind + "Binding",
        "metadata": metadata,
        "roleRef": {
            "apiGroup": "rbac.authorization.k8s.io",
            "kind": role_kind,
            "name": name,
        },
        "subjects": [subject],
    })


def managed_resources(path):
    query = urllib.parse.urlencode({"labelSelector": "app.kubernetes.io/managed-by=navigan"})
    return kubernetes_request(f"{path}?{query}").get("items", [])


def prune(desired_ids):
    paths = [
        "/apis/rbac.authorization.k8s.io/v1/rolebindings",
        "/apis/rbac.authorization.k8s.io/v1/roles",
        "/apis/rbac.authorization.k8s.io/v1/clusterrolebindings",
        "/apis/rbac.authorization.k8s.io/v1/clusterroles",
    ]
    for path in paths:
        for item in managed_resources(path):
            metadata = item.get("metadata", {})
            assignment_id = metadata.get("labels", {}).get("navigan.io/assignment-id")
            if assignment_id and assignment_id not in desired_ids:
                namespace = metadata.get("namespace")
                resource_path = path
                if namespace and "/namespaces/" not in path:
                    kind = path.rsplit("/", 1)[-1]
                    resource_path = (
                        f"/apis/rbac.authorization.k8s.io/v1/namespaces/{namespace}/{kind}"
                    )
                delete_resource(resource_path, metadata["name"])


def reconcile(base_url, connector_id, connector_token):
    desired = navigan_request(
        base_url, connector_id, connector_token, "/access/desired",
    )
    results = []
    assignments = desired.get("assignments", [])
    for assignment in assignments:
        try:
            reconcile_assignment(assignment)
            results.append({"assignmentId": assignment["assignmentId"], "status": "APPLIED"})
        except Exception as error:
            results.append({
                "assignmentId": assignment["assignmentId"],
                "status": "FAILED",
                "errorCode": type(error).__name__.upper(),
            })
    prune({assignment["assignmentId"] for assignment in assignments})
    navigan_request(
        base_url, connector_id, connector_token, "/access/status", "POST",
        {"revision": desired["revision"], "results": results},
    )
    try:
        reconcile_connector_runtime(desired.get("connector"))
    except Exception as error:
        # Runtime upgrades are deliberately isolated from access reconciliation:
        # a chart/RBAC/version issue must never leave a permission grant pending.
        print(
            json.dumps(
                {
                    "event": "connector_runtime_upgrade_failed",
                    "errorType": type(error).__name__,
                    "error": error_detail(error),
                }
            ),
            flush=True,
        )
    return results


def error_detail(error):
    detail = " ".join(str(error).split())
    return detail[:500] if detail else type(error).__name__


def mark_ready():
    with open(READY_FILE, "w", encoding="utf-8") as stream:
        stream.write(str(int(time.time())))


def main():
    base_url = required("NAVIGAN_API_BASE_URL")
    connector_id = required("NAVIGAN_CONNECTOR_ID")
    connector_token = required("NAVIGAN_CONNECTOR_TOKEN")
    if os.environ.get("NAVIGAN_TOOLS_TUNNEL_URL", "").strip():
        threading.Thread(
            target=tools_tunnel,
            args=(connector_id, connector_token),
            name="navigan-tools-tunnel",
            daemon=True,
        ).start()
    interval = max(30, min(int(os.environ.get("SYNC_INTERVAL_SECONDS", "60")), 600))
    next_github_refresh = 0
    while True:
        results = []
        try:
            # Access reconciliation is the connector's primary control-plane
            # responsibility. Run it before telemetry collection so a failure
            # in optional inventory or health reporting cannot leave a newly
            # granted or revoked assignment waiting indefinitely.
            results = reconcile(base_url, connector_id, connector_token)
        except Exception as error:
            print(
                json.dumps(
                    {
                        "event": "access_reconciliation_failed",
                        "errorType": type(error).__name__,
                        "error": error_detail(error),
                    }
                ),
                flush=True,
            )
        try:
            now = time.time()
            if now >= next_github_refresh:
                try:
                    refresh_github_repository_credential(
                        base_url, connector_id, connector_token
                    )
                    next_github_refresh = now + 40 * 60
                except Exception as error:
                    next_github_refresh = now + 5 * 60
                    print(
                        json.dumps(
                            {
                                "event": "github_credential_refresh_failed",
                                "errorType": type(error).__name__,
                                "error": error_detail(error),
                            }
                        ),
                        flush=True,
                    )
            names = namespaces()
            report(
                base_url,
                connector_id,
                connector_token,
                int(time.time()),
                names,
            )
            component_inventory = platform_components()
            runtime = runtime_inventory()
            report_platform_components(
                base_url,
                connector_id,
                connector_token,
                int(time.time() * 1000),
                component_inventory,
                runtime,
            )
            mark_ready()
            print(
                json.dumps(
                    {
                        "event": "namespace_inventory_reported",
                        "namespaceCount": len(names),
                        "platformComponentCount": len(component_inventory),
                        "runtimeResourceCount": len(runtime["resources"]),
                        "accessAssignments": len(results),
                    }
                ),
                flush=True,
            )
        except Exception as error:
            print(
                json.dumps(
                    {
                        "event": "platform_inventory_failed",
                        "errorType": type(error).__name__,
                        "error": error_detail(error),
                    }
                ),
                flush=True,
            )
        time.sleep(interval)


if __name__ == "__main__":
    main()
