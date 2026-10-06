import json

import pytest

from migration_connector.inventory import (
    UnsafeInventory,
    build_inventory,
    sanitize_resource,
)


def deployment():
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": "retailflow",
            "namespace": "retailflow",
            "annotations": {
                "service.beta.kubernetes.io/aws-load-balancer-ssl-cert": (
                    "arn:aws:acm:secret-certificate"
                )
            },
        },
        "spec": {
            "replicas": 2,
            "template": {
                "spec": {
                    "serviceAccountName": "retailflow",
                    "hostNetwork": False,
                    "containers": [
                        {
                            "name": "api",
                            "image": "example/retailflow:v1",
                            "command": ["print-secret"],
                            "env": [
                                {
                                    "name": "PASSWORD",
                                    "value": "super-secret-value",
                                },
                                {
                                    "name": "DATABASE_PASSWORD",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": "database-secret",
                                            "key": "password",
                                        }
                                    },
                                },
                            ],
                            "securityContext": {
                                "privileged": False,
                                "allowPrivilegeEscalation": False,
                            },
                        }
                    ],
                    "volumes": [
                        {
                            "name": "host-data",
                            "hostPath": {
                                "path": "/private/customer/path"
                            },
                        },
                        {
                            "name": "credentials",
                            "secret": {
                                "secretName": "application-secret"
                            },
                        },
                    ],
                }
            },
        },
    }


@pytest.mark.parametrize("kind", ["Secret", "ConfigMap", "Event"])
def test_forbids_sensitive_resource_kinds(kind):
    with pytest.raises(UnsafeInventory):
        sanitize_resource(
            {
                "apiVersion": "v1",
                "kind": kind,
                "metadata": {"name": "sensitive"},
                "data": {"password": "secret"},
            }
        )


def test_workload_inventory_removes_secret_values_and_commands():
    result = sanitize_resource(deployment())
    encoded = json.dumps(result)

    assert "super-secret-value" not in encoded
    assert "database-secret" not in encoded
    assert "application-secret" not in encoded
    assert "/private/customer/path" not in encoded
    assert "arn:aws:acm:secret-certificate" not in encoded
    assert "print-secret" not in encoded

    assert result["annotationKeys"] == [
        "service.beta.kubernetes.io/aws-load-balancer-ssl-cert"
    ]
    assert result["pod"]["containers"][0]["environment"] == [
        {"name": "PASSWORD", "source": "LITERAL"},
        {
            "name": "DATABASE_PASSWORD",
            "source": "secretKeyRef",
        },
    ]
    assert result["pod"]["volumes"] == [
        {"name": "host-data", "type": "hostPath"},
        {"name": "credentials", "type": "secret"},
    ]


def test_ingress_inventory_removes_hosts_and_tls_secret_names():
    result = sanitize_resource(
        {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "Ingress",
            "metadata": {
                "name": "retailflow",
                "namespace": "retailflow",
            },
            "spec": {
                "rules": [
                    {
                        "host": "private.customer.example",
                        "http": {
                            "paths": [
                                {
                                    "path": "/private-api",
                                    "pathType": "Prefix",
                                }
                            ]
                        },
                    }
                ],
                "tls": [
                    {
                        "secretName": "retailflow-tls",
                        "hosts": ["private.customer.example"],
                    }
                ],
            },
        }
    )
    encoded = json.dumps(result)

    assert "private.customer.example" not in encoded
    assert "retailflow-tls" not in encoded
    assert "/private-api" not in encoded
    assert result["ruleCount"] == 1
    assert result["tlsEntryCount"] == 1


def test_node_inventory_removes_identity_and_network_addresses():
    result = sanitize_resource(
        {
            "apiVersion": "v1",
            "kind": "Node",
            "metadata": {"name": "ip-10-42-1-170"},
            "spec": {
                "providerID": "aws:///secret-instance-id",
            },
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
    )
    encoded = json.dumps(result)

    assert "ip-10-42-1-170" not in encoded
    assert "secret-instance-id" not in encoded
    assert "10.42.1.170" not in encoded
    assert result["kubernetesVersion"] == "v1.37.1"


def test_inventory_digest_is_deterministic():
    first = build_inventory(
        [
            deployment(),
            {
                "apiVersion": "v1",
                "kind": "Namespace",
                "metadata": {"name": "retailflow"},
            },
        ]
    )
    second = build_inventory(
        [
            {
                "apiVersion": "v1",
                "kind": "Namespace",
                "metadata": {"name": "retailflow"},
            },
            deployment(),
        ]
    )

    assert first["inventoryDigest"] == second["inventoryDigest"]
    assert first["sensitiveDataIncluded"] is False
