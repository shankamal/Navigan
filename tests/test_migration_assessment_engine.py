from navigan.modules.migration_management.assessment_engine import (
    assess,
)


TARGET_READY = {
    "status": "READY",
    "metrics": {
        "nodeCount": 3,
        "readyNodeCount": 3,
    },
}

TARGET = {
    "clusterId": "CLU-demo",
    "clusterName": "demo-eks",
}


def inventory(resources):
    return {
        "schemaVersion": 1,
        "sourceKubernetesVersion": "v1.37.1",
        "inventoryDigest": "a" * 64,
        "resources": resources,
        "sensitiveDataIncluded": False,
    }


def deployment(**pod_changes):
    pod = {
        "serviceAccountName": "default",
        "hostNetwork": False,
        "hostPID": False,
        "hostIPC": False,
        "containers": [],
        "initContainers": [],
        "volumes": [],
    }
    pod.update(pod_changes)

    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "namespace": "retailflow",
        "name": "api",
        "annotationKeys": [],
        "replicas": 2,
        "pod": pod,
    }


def test_scores_portable_workload_as_seamless():
    report = assess(
        inventory([deployment()]),
        TARGET_READY,
        TARGET,
    )

    assert report["compatibilityScore"] == 100
    assert report["containsBlockers"] is False
    assert report["inventorySummary"]["classification"] == {
        "SEAMLESS": 1,
        "AUTOMATED_CHANGE": 0,
        "MANUAL_CHANGE": 0,
        "BLOCKER": 0,
    }
    assert report["findings"] == []


def test_classifies_load_balancer_as_automated_change():
    service = {
        "apiVersion": "v1",
        "kind": "Service",
        "namespace": "retailflow",
        "name": "api",
        "annotationKeys": [],
        "type": "LoadBalancer",
        "selectorKeys": ["app"],
        "ports": [{"port": 443, "targetPort": 8080}],
    }

    report = assess(
        inventory([service]),
        TARGET_READY,
        TARGET,
    )

    assert (
        report["inventorySummary"]["classification"][
            "AUTOMATED_CHANGE"
        ]
        == 1
    )
    assert report["findings"][0]["code"] == (
        "LOAD_BALANCER_TRANSLATION"
    )


def test_classifies_host_storage_and_privilege_as_manual():
    workload = deployment(
        volumes=[{"name": "data", "type": "hostPath"}],
        containers=[
            {
                "name": "api",
                "image": "example/api:v1",
                "environment": [],
                "security": {
                    "privileged": True,
                    "allowPrivilegeEscalation": True,
                },
            }
        ],
    )

    report = assess(
        inventory([workload]),
        TARGET_READY,
        TARGET,
    )

    codes = {item["code"] for item in report["findings"]}
    assert "HOST_PATH_STORAGE_REDESIGN" in codes
    assert "PRIVILEGED_WORKLOAD_REVIEW" in codes
    assert (
        report["inventorySummary"]["classification"][
            "MANUAL_CHANGE"
        ]
        == 1
    )
    assert 0 < report["compatibilityScore"] < 100


def test_blocks_deprecated_api_and_unsupported_architecture():
    resources = [
        {
            **deployment(),
            "apiVersion": "extensions/v1beta1",
        },
        {
            "apiVersion": "v1",
            "kind": "Node",
            "annotationKeys": [],
            "kubernetesVersion": "v1.37.1",
            "operatingSystem": "linux",
            "architecture": "s390x",
        },
    ]

    report = assess(
        inventory(resources),
        TARGET_READY,
        TARGET,
    )

    codes = {item["code"] for item in report["findings"]}
    assert "UNSUPPORTED_KUBERNETES_API" in codes
    assert "UNSUPPORTED_NODE_ARCHITECTURE" in codes
    assert report["containsBlockers"] is True
    assert report["compatibilityScore"] <= 75


def test_blocks_stale_target_runtime_inventory():
    report = assess(
        inventory([deployment()]),
        {
            "status": "STALE",
            "metrics": {
                "nodeCount": 3,
                "readyNodeCount": 3,
            },
        },
        TARGET,
    )

    assert report["containsBlockers"] is True
    assert report["compatibilityScore"] <= 70
    assert report["findings"][0]["code"] == (
        "TARGET_RUNTIME_UNAVAILABLE"
    )


def test_blocks_target_with_unready_nodes():
    report = assess(
        inventory([deployment()]),
        {
            "status": "READY",
            "metrics": {
                "nodeCount": 3,
                "readyNodeCount": 2,
            },
        },
        TARGET,
    )

    assert report["containsBlockers"] is True
    assert any(
        item["code"] == "TARGET_NODES_NOT_READY"
        for item in report["findings"]
    )
