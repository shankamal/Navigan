import pytest
from pydantic import ValidationError

from navigan.modules.migration_management.models import (
    AssessmentReport,
    CreateMigration,
    SourceCatalogueReport,
)


def request_payload():
    return {
        "customerId": "CUS-demo",
        "name": "RetailFlow migration",
        "description": "Assess RetailFlow for migration to EKS.",
        "source": {
            "platform": "SELF_MANAGED_KUBERNETES",
            "clusterName": "migration-lab",
            "distribution": "kubeadm",
            "kubernetesVersion": "1.37.1",
            "accessMode": "READ_ONLY_CONNECTOR",
        },
        "target": {
            "platform": "EKS",
            "environmentId": "ENV-demo",
            "environmentApprovedVersion": 1,
            "awsRegion": "ap-south-1",
            "clusterId": "CLU-demo",
            "clusterName": "retailflow-eks",
            "endpointAccess": "PRIVATE",
        },
        "scope": {
            "namespaces": ["retailflow"],
            "excludeNamespaces": [
                "kube-node-lease",
                "kube-public",
                "kube-system",
            ],
            "includeClusterScopedResources": False,
            "includePersistentData": False,
        },
    }


def test_accepts_self_managed_kubernetes_to_eks_assessment():
    value = CreateMigration.model_validate(request_payload())

    assert value.source.platform == "SELF_MANAGED_KUBERNETES"
    assert value.target.platform == "EKS"
    assert value.target.endpointAccess == "PRIVATE"


def test_rejects_unsupported_source_path_in_first_release():
    payload = request_payload()
    payload["source"]["platform"] = "EKS"

    with pytest.raises(ValidationError, match="first release"):
        CreateMigration.model_validate(payload)


def test_rejects_system_namespace_migration():
    payload = request_payload()
    payload["scope"]["namespaces"] = ["kube-system"]
    payload["scope"]["excludeNamespaces"] = []

    with pytest.raises(ValidationError, match="System namespaces"):
        CreateMigration.model_validate(payload)


def test_rejects_embedded_kubeconfig_or_credentials():
    payload = request_payload()
    payload["source"]["kubeconfig"] = "sensitive-value"

    with pytest.raises(ValidationError, match="Extra inputs"):
        CreateMigration.model_validate(payload)


def test_accepts_sanitized_assessment():
    report = AssessmentReport.model_validate(
        {
            "version": 1,
            "migrationVersion": 3,
            "observedAt": "2026-10-05T08:00:00Z",
            "sourceKubernetesVersion": "1.37.1",
            "inventoryDigest": "a" * 64,
            "compatibilityScore": 85,
            "inventorySummary": {
                "namespaces": 1,
                "deployments": 2,
                "services": 2,
            },
            "findings": [
                {
                    "code": "LOAD_BALANCER_REVIEW",
                    "severity": "WARNING",
                    "category": "NETWORK",
                    "namespace": "retailflow",
                    "resourceKind": "Service",
                    "resourceName": "retailflow",
                    "message": "Review target load-balancer annotations.",
                    "remediation": "Map the service to approved EKS ingress.",
                }
            ],
            "sensitiveDataIncluded": False,
        }
    )

    assert report.compatibilityScore == 85


def test_rejects_sensitive_assessment_payload():
    payload = {
        "version": 1,
        "migrationVersion": 3,
        "observedAt": "2026-10-05T08:00:00Z",
        "sourceKubernetesVersion": "1.37.1",
        "inventoryDigest": "b" * 64,
        "compatibilityScore": 90,
        "inventorySummary": {},
        "findings": [],
        "sensitiveDataIncluded": True,
    }

    with pytest.raises(ValidationError):
        AssessmentReport.model_validate(payload)


def test_accepts_minimal_staged_migration_draft():
    value = CreateMigration.model_validate(
        {
            "customerId": "CUS-demo",
            "name": "RetailFlow staged assessment",
            "source": {
                "platform": "SELF_MANAGED_KUBERNETES",
            },
            "target": {
                "platform": "EKS",
                "targetType": "EXISTING_CLUSTER",
                "environmentId": "ENV-demo",
                "environmentApprovedVersion": 1,
            },
        }
    )

    assert value.source.clusterName is None
    assert value.target.clusterId is None
    assert value.target.clusterName is None
    assert value.scope.namespaces == []


def test_requires_existing_target_id_and_name_together():
    payload = request_payload()
    payload["target"].pop("clusterName")

    with pytest.raises(ValidationError, match="supplied together"):
        CreateMigration.model_validate(payload)


def source_catalogue_payload():
    return {
        "version": 1,
        "migrationVersion": 2,
        "observedAt": "2026-10-05T12:30:00Z",
        "sourceKubernetesVersion": "v1.37.1",
        "inventoryDigest": "c" * 64,
        "nodeCount": 3,
        "architectures": ["amd64"],
        "namespaces": [
            {
                "name": "retailflow",
                "resourceCounts": {
                    "Deployment": 3,
                    "Service": 2,
                    "StatefulSet": 1,
                },
            }
        ],
        "sensitiveDataIncluded": False,
    }


def test_accepts_sanitized_source_catalogue():
    report = SourceCatalogueReport.model_validate(
        source_catalogue_payload()
    )

    assert report.nodeCount == 3
    assert report.namespaces[0].name == "retailflow"
    assert report.namespaces[0].resourceCounts["Deployment"] == 3


def test_rejects_system_namespace_in_source_catalogue():
    payload = source_catalogue_payload()
    payload["namespaces"][0]["name"] = "kube-system"

    with pytest.raises(ValidationError, match="System namespaces"):
        SourceCatalogueReport.model_validate(payload)


def test_rejects_sensitive_source_catalogue():
    payload = source_catalogue_payload()
    payload["sensitiveDataIncluded"] = True

    with pytest.raises(ValidationError):
        SourceCatalogueReport.model_validate(payload)
