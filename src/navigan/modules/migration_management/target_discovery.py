"""Read-only AWS EKS control-plane target discovery.

EKS DescribeCluster is intentionally not represented as proof of Kubernetes
API access, storage class support, node capacity or workload compatibility.
"""
from datetime import datetime, timezone

import boto3
from botocore.config import Config


def discover_eks_control_plane(*, name, region, client=None):
    if not name or not region:
        raise ValueError("A registered EKS cluster name and region are required")
    eks = client or boto3.client(
        "eks", region_name=region,
        config=Config(connect_timeout=3, read_timeout=7, retries={"max_attempts": 1}),
    )
    cluster = eks.describe_cluster(name=name)["cluster"]
    if cluster.get("name") != name:
        raise ValueError("Unexpected EKS cluster identity")
    return {
        "provider": "AWS",
        "platform": "EKS",
        "clusterName": name,
        "region": region,
        "arn": cluster.get("arn"),
        "kubernetesVersion": cluster.get("version"),
        "clusterStatus": cluster.get("status"),
        "endpointAccess": {
            "public": bool(cluster.get("resourcesVpcConfig", {}).get("endpointPublicAccess")),
            "private": bool(cluster.get("resourcesVpcConfig", {}).get("endpointPrivateAccess")),
        },
        "observedAt": datetime.now(timezone.utc).isoformat(),
        "evidenceLevel": "CONTROL_PLANE_ONLY",
        "coverageComplete": False,
        "unverified": [
            "Kubernetes API authorization", "Node allocatable capacity",
            "StorageClass and CSI compatibility", "Ingress and networking",
            "Workload identity", "Container registry pull access",
            "Admission policies and required operators",
        ],
    }
