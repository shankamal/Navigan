from migration_connector import agent
import hashlib
import json

import pytest

from migration_connector.agent import (
    collect_inventory,
    collect_source_catalogue,
    navigan_request,
    run_forever,
    run_once,
    secure_base_url,
)


def assignment(namespaces=None):
    return {
        "assignmentType": "SOURCE_CATALOGUE",
        "migrationId": "MIG-" + "a" * 32,
        "migrationVersion": 3,
        "executionMode": "ASSESSMENT_ONLY",
        "source": {
            "platform": "SELF_MANAGED_KUBERNETES",
            "clusterName": "migration-lab",
        },
        "target": {
            "platform": "EKS",
            "awsRegion": "ap-south-1",
        },
        "scope": {
            "namespaces": namespaces or ["retailflow"],
            "excludeNamespaces": [
                "kube-system",
                "kube-public",
                "kube-node-lease",
            ],
            "includeClusterScopedResources": False,
            "includePersistentData": False,
        },
    }


def node():
    return {
        "apiVersion": "v1",
        "kind": "Node",
        "metadata": {"name": "private-node-name"},
        "spec": {"providerID": "private-provider-id"},
        "status": {
            "addresses": [
                {
                    "type": "InternalIP",
                    "address": "10.42.1.170",
                }
            ],
            "nodeInfo": {
                "kubeletVersion": "v1.37.1",
                "operatingSystem": "linux",
                "architecture": "amd64",
            },
        },
    }


def deployment():
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": "retailflow",
            "namespace": "retailflow",
        },
        "spec": {
            "replicas": 2,
            "template": {
                "spec": {
                    "containers": [
                        {
                            "name": "api",
                            "image": "example/retailflow:v1",
                            "env": [
                                {
                                    "name": "PASSWORD",
                                    "value": "never-store-this",
                                }
                            ],
                        }
                    ]
                }
            },
        },
    }


def test_requires_clean_https_navigan_endpoint():
    assert (
        secure_base_url("https://api.example.test/v1/api/v1/")
        == "https://api.example.test/v1/api/v1"
    )

    for value in (
        "http://api.example.test",
        "https://user:password@example.test",
        "https://api.example.test?token=secret",
    ):
        with pytest.raises(RuntimeError):
            secure_base_url(value)


def test_collects_only_selected_namespaces_and_safe_resources():
    observed = []

    def request(path):
        observed.append(path)
        if path == "/api/v1/nodes":
            return {"items": [node()]}
        if path == "/api/v1/namespaces":
            return {
                "items": [
                    {"metadata": {"name": "retailflow"}},
                    {"metadata": {"name": "other-app"}},
                    {"metadata": {"name": "kube-system"}},
                ]
            }
        if path.endswith("/deployments"):
            return {"items": [deployment()]}
        return {"items": []}

    result = collect_inventory(assignment(), request)
    encoded = json.dumps(result)

    assert "retailflow" in encoded
    assert "other-app" not in encoded
    assert "kube-system" not in encoded
    assert "never-store-this" not in encoded
    assert "private-provider-id" not in encoded
    assert "10.42.1.170" not in encoded

    requested_paths = " ".join(observed).lower()
    for forbidden in (
        "secrets",
        "configmaps",
        "events",
        "/pods",
        "roles",
        "rolebindings",
    ):
        assert forbidden not in requested_paths


def test_rejects_missing_requested_namespace():
    def request(path):
        if path == "/api/v1/nodes":
            return {"items": [node()]}
        if path == "/api/v1/namespaces":
            return {
                "items": [
                    {"metadata": {"name": "different-app"}}
                ]
            }
        return {"items": []}

    with pytest.raises(
        RuntimeError,
        match="requested namespace was not found",
    ):
        collect_inventory(assignment(), request)


def test_rejects_non_assessment_assignment():
    value = assignment()
    value["executionMode"] = "EXECUTE"

    with pytest.raises(
        RuntimeError,
        match="assessment-only",
    ):
        collect_inventory(value, lambda _path: {"items": []})


def test_collects_minimal_source_catalogue_with_canonical_digest():
    def request(path):
        if path == "/version":
            return {"gitVersion": "v1.37.1"}
        if path == "/api/v1/nodes":
            return {"items": [node(), node(), node()]}
        if path == "/api/v1/namespaces":
            return {
                "items": [
                    {"metadata": {"name": "retailflow"}},
                    {"metadata": {"name": "kube-system"}},
                ]
            }
        if path.endswith("/deployments"):
            return {"items": [{}, {}]}
        if path.endswith("/services"):
            return {"items": [{}]}
        return {"items": []}

    report = collect_source_catalogue(
        assignment(),
        request,
        observed_at="2026-10-05T12:30:00Z",
    )

    catalogue = {
        "schemaVersion": 1,
        "sourceKubernetesVersion": "v1.37.1",
        "nodeCount": 3,
        "architectures": ["amd64"],
        "namespaces": [
            {
                "name": "retailflow",
                "resourceCounts": {
                    "Deployment": 2,
                    "Service": 1,
                },
            }
        ],
        "sensitiveDataIncluded": False,
    }
    expected_digest = hashlib.sha256(
        json.dumps(
            catalogue,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()

    assert report["inventoryDigest"] == expected_digest
    assert report["migrationVersion"] == 3
    assert report["namespaces"] == catalogue["namespaces"]
    assert "resources" not in report
    assert "private-provider-id" not in json.dumps(report)


def test_rejects_non_catalogue_assignment():
    value = assignment()
    value["assignmentType"] = "DETAILED_ASSESSMENT"

    with pytest.raises(
        RuntimeError,
        match="Unsupported migration connector assignment",
    ):
        collect_source_catalogue(
            value,
            lambda _path: {},
        )


def test_posts_catalogue_without_putting_token_in_url(monkeypatch):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, _maximum):
            return b'{"status":"INVENTORY_READY"}'

    def open_request(request, timeout, context=None):
        captured["request"] = request
        captured["timeout"] = timeout
        captured["context"] = context
        return Response()

    monkeypatch.setattr(
        "migration_connector.agent.open_request",
        open_request,
    )

    result = navigan_request(
        "https://api.example.test/api/v1",
        "MGC-" + "a" * 32,
        "short-lived-secret-token",
        "inventory",
        method="POST",
        body={"version": 1},
    )

    request = captured["request"]
    assert result["status"] == "INVENTORY_READY"
    assert request.get_method() == "POST"
    assert request.full_url.endswith("/inventory")
    assert "short-lived-secret-token" not in request.full_url
    assert request.get_header("Authorization") == (
        "Bearer short-lived-secret-token"
    )
    assert json.loads(request.data) == {"version": 1}


def test_run_once_requires_inventory_ready_response():
    value = assignment()
    report = {"version": 1}

    with pytest.raises(
        RuntimeError,
        match="did not accept",
    ):
        run_once(
            fetch=lambda: value,
            collect=lambda observed: report,
            submit=lambda observed: {"status": "FAILED"},
        )


def test_run_once_dispatches_detailed_source_inventory():
    observed = {}

    def fetch():
        return {
            "assignmentType": "SOURCE_INVENTORY",
            "migrationVersion": 4,
        }

    def collect(assignment):
        observed["assignment"] = assignment
        return {"inventoryDigest": "a" * 64}

    def submit(report):
        observed["report"] = report
        return {"status": "ASSESSMENT_READY"}

    result = agent.run_once(
        fetch=fetch,
        collect=collect,
        submit=submit,
    )

    assert result["status"] == "ASSESSMENT_READY"
    assert observed["assignment"]["migrationVersion"] == 4
    assert observed["report"]["inventoryDigest"] == "a" * 64


def test_run_once_treats_no_assignment_as_idle():
    result = run_once(fetch=lambda: {"assignmentType": "NONE"})

    assert result["status"] == "IDLE"


def test_persistent_connector_polls_repeatedly():
    calls = []
    run_count = 0

    def run():
        nonlocal run_count
        run_count += 1
        calls.append("run")
        if run_count == 3:
            raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        run_forever(
            run=run,
            sleep=lambda seconds: calls.append(seconds),
            poll_seconds=5,
        )

    assert calls == ["run", 5, "run", 5, "run"]
