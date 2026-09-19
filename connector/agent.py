"""Minimal outbound-only Navigan cluster connector."""

import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

KUBERNETES_HOST = os.environ.get("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
KUBERNETES_PORT = os.environ.get("KUBERNETES_SERVICE_PORT_HTTPS", "443")
SERVICE_ACCOUNT = "/var/run/secrets/kubernetes.io/serviceaccount"


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
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response) if response.length != 0 else {}


def report(base_url, connector_id, connector_token, revision, names):
    navigan_request(
        base_url, connector_id, connector_token, "/inventory/namespaces", "POST",
        {
            "revision": revision,
            "namespaces": [{"name": name} for name in names],
        },
    )


def deployment_ready(namespace, names):
    payload = kubernetes_request(f"/apis/apps/v1/namespaces/{namespace}/deployments")
    deployments = {
        item.get("metadata", {}).get("name"): item
        for item in payload.get("items", [])
    }
    for name in names:
        deployment = deployments.get(name)
        if not deployment:
            return False
        desired = deployment.get("spec", {}).get("replicas", 1)
        available = deployment.get("status", {}).get("availableReplicas", 0)
        if desired < 1 or available < desired:
            return False
    return True


def platform_components():
    components = [
        {"code": "connector", "status": "READY", "healthStatus": "Healthy"}
    ]
    try:
        argocd_ready = deployment_ready(
            "argocd",
            ["argocd-server", "argocd-repo-server", "argocd-application-controller"],
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
    base_url, connector_id, connector_token, revision, components
):
    navigan_request(
        base_url,
        connector_id,
        connector_token,
        "/inventory/platform-components",
        "POST",
        {"revision": revision, "components": components},
    )


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
    return results


def main():
    base_url = required("NAVIGAN_API_BASE_URL")
    connector_id = required("NAVIGAN_CONNECTOR_ID")
    connector_token = required("NAVIGAN_CONNECTOR_TOKEN")
    interval = max(30, min(int(os.environ.get("SYNC_INTERVAL_SECONDS", "60")), 600))
    while True:
        try:
            names = namespaces()
            report(
                base_url,
                connector_id,
                connector_token,
                int(time.time()),
                names,
            )
            component_inventory = platform_components()
            report_platform_components(
                base_url,
                connector_id,
                connector_token,
                int(time.time() * 1000),
                component_inventory,
            )
            results = reconcile(base_url, connector_id, connector_token)
            print(
                json.dumps(
                    {
                        "event": "namespace_inventory_reported",
                        "namespaceCount": len(names),
                        "platformComponentCount": len(component_inventory),
                        "accessAssignments": len(results),
                    }
                ),
                flush=True,
            )
        except Exception as error:
            print(
                json.dumps(
                    {
                        "event": "namespace_inventory_failed",
                        "errorType": type(error).__name__,
                    }
                ),
                flush=True,
            )
        time.sleep(interval)


if __name__ == "__main__":
    main()
