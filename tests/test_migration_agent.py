import json

import pytest

from migration_connector.agent import (
    collect_inventory,
    secure_base_url,
)


def assignment(namespaces=None):
    return {
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
