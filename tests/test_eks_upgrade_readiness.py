from datetime import datetime, timezone
from unittest.mock import MagicMock

from navigan.modules.cluster_management.upgrade_readiness import EksUpgradeDiscovery


def managed_cluster():
    return {
        "cluster_id": "CLU-test",
        "customer_id": "CUS-test",
        "environment_id": "ENV-test",
        "environment_approved_version": 7,
        "platform": "EKS",
        "cluster_name": "navigan-prod",
        "provisioning_role_arn": (
            "arn:aws:iam::123456789012:role/NaviganProvisioningRole"
        ),
        "external_id_secret_arn": (
            "arn:aws:secretsmanager:ap-south-1:123456789012:secret:"
            "navigan/provisioning/customer"
        ),
    }


def environment():
    return {"configuration": {"location": {"region": "ap-south-1"}}}


def eks_client(insight_status="PASSING", node_version="1.33"):
    client = MagicMock()
    client.describe_cluster.return_value = {
        "cluster": {
            "name": "navigan-prod",
            "arn": "arn:aws:eks:ap-south-1:123456789012:cluster/navigan-prod",
            "version": "1.33",
            "platformVersion": "eks.18",
            "status": "ACTIVE",
        }
    }
    client.describe_cluster_versions.return_value = {
        "clusterVersions": [
            {
                "clusterVersion": "1.33",
                "versionStatus": "STANDARD_SUPPORT",
                "endOfStandardSupportDate": datetime(2027, 1, 1, tzinfo=timezone.utc),
                "endOfExtendedSupportDate": datetime(2028, 1, 1, tzinfo=timezone.utc),
            },
            {
                "clusterVersion": "1.34",
                "versionStatus": "STANDARD_SUPPORT",
                "releaseDate": datetime(2026, 8, 1, tzinfo=timezone.utc),
                "endOfStandardSupportDate": datetime(2027, 8, 1, tzinfo=timezone.utc),
                "endOfExtendedSupportDate": datetime(2028, 8, 1, tzinfo=timezone.utc),
            },
            {
                "clusterVersion": "1.35",
                "versionStatus": "STANDARD_SUPPORT",
            },
        ]
    }
    client.list_nodegroups.return_value = {"nodegroups": ["system"]}
    client.describe_nodegroup.return_value = {
        "nodegroup": {
            "nodegroupName": "system",
            "version": node_version,
            "releaseVersion": "1.33.7-20261001",
            "status": "ACTIVE",
            "amiType": "AL2023_x86_64_STANDARD",
            "capacityType": "ON_DEMAND",
            "health": {"issues": []},
        }
    }
    client.list_addons.return_value = {"addons": ["coredns"]}
    client.describe_addon.return_value = {
        "addon": {
            "addonName": "coredns",
            "addonVersion": "v1.11.4-eksbuild.20",
            "status": "ACTIVE",
            "health": {"issues": []},
        }
    }
    client.describe_addon_versions.return_value = {
        "addons": [
            {
                "addonName": "coredns",
                "addonVersions": [
                    {
                        "addonVersion": "v1.12.3-eksbuild.1",
                        "compatibilities": [
                            {"clusterVersion": "1.34", "defaultVersion": True}
                        ],
                    }
                ],
            }
        ]
    }
    client.list_insights.return_value = {
        "insights": [
            {
                "id": "insight-1",
                "name": "Kubelet version skew",
                "category": "UPGRADE_READINESS",
                "kubernetesVersion": "1.34",
                "description": "Checks managed node versions.",
                "insightStatus": {
                    "status": insight_status,
                    "reason": "Node versions are evaluated.",
                },
            }
        ]
    }
    client.describe_insight.return_value = {
        "insight": {
            "id": "insight-1",
            "name": "Kubelet version skew",
            "category": "UPGRADE_READINESS",
            "kubernetesVersion": "1.34",
            "description": "Checks managed node versions.",
            "recommendation": "Align managed node groups.",
            "insightStatus": {
                "status": insight_status,
                "reason": "Node versions are evaluated.",
            },
            "resources": [],
        }
    }
    client.list_updates.return_value = {"updateIds": []}
    return client


def discovery(client):
    sts = MagicMock()
    sts.assume_role.return_value = {
        "Credentials": {
            "AccessKeyId": "access",
            "SecretAccessKey": "secret",
            "SessionToken": "token",
        }
    }
    secrets = MagicMock()
    secrets.get_secret_value.return_value = {"SecretString": "external"}
    return EksUpgradeDiscovery(
        sts=sts,
        secrets=secrets,
        client_factory=lambda service, **_options: client,
    )


def test_discovers_next_sequential_version_and_readiness_evidence():
    client = eks_client()

    result = discovery(client).discover(managed_cluster(), environment())

    assert result["controlPlane"]["version"] == "1.33"
    assert result["recommendedTarget"]["version"] == "1.34"
    assert result["recommendedTarget"]["supportStatus"] == "STANDARD_SUPPORT"
    assert result["nodeGroups"][0]["version"] == "1.33"
    assert result["addons"][0]["targetVersion"] == "v1.12.3-eksbuild.1"
    assert result["insights"][0]["status"] == "PASSING"
    assert result["readiness"]["status"] == "READY"
    assert result["readiness"]["blockers"] == []
    client.describe_cluster_versions.assert_called_once_with(
        includeAll=True, maxResults=100
    )
    client.list_insights.assert_called_once_with(
        clusterName="navigan-prod",
        filter={
            "categories": ["UPGRADE_READINESS"],
            "kubernetesVersions": ["1.34"],
        },
        maxResults=100,
    )


def test_blocks_when_node_groups_are_skewed_and_insight_is_error():
    result = discovery(
        eks_client(insight_status="ERROR", node_version="1.32")
    ).discover(managed_cluster(), environment())

    assert result["readiness"]["status"] == "BLOCKED"
    assert {item["code"] for item in result["readiness"]["blockers"]} >= {
        "NODE_GROUP_VERSION_SKEW",
        "EKS_UPGRADE_INSIGHT_ERROR",
    }
    assert result["readiness"]["checks"]["nodeGroupsAligned"] is False
    assert result["readiness"]["checks"]["upgradeInsightsPassing"] is False


def test_only_recommends_the_immediate_next_minor_version():
    client = eks_client()
    client.describe_cluster_versions.return_value["clusterVersions"] = [
        {
            "clusterVersion": "1.33",
            "versionStatus": "STANDARD_SUPPORT",
        },
        {
            "clusterVersion": "1.35",
            "versionStatus": "STANDARD_SUPPORT",
        },
    ]

    result = discovery(client).discover(managed_cluster(), environment())

    assert result["recommendedTarget"] is None
    assert "NO_SUPPORTED_NEXT_MINOR" in {
        item["code"] for item in result["readiness"]["blockers"]
    }


def test_discovery_never_calls_an_eks_mutation_api():
    client = eks_client()

    discovery(client).discover(managed_cluster(), environment())

    called = {call[0] for call in client.method_calls}
    assert not called.intersection(
        {
            "update_cluster_version",
            "update_cluster_config",
            "update_nodegroup_version",
            "update_nodegroup_config",
            "update_addon",
            "create_addon",
            "delete_addon",
        }
    )
