"""Read-only Amazon EKS upgrade discovery for managed clusters."""

from datetime import datetime, timezone
import re

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from navigan.shared.errors import ApiError


READ_CONFIG = Config(
    connect_timeout=3,
    read_timeout=8,
    retries={"mode": "standard", "total_max_attempts": 2},
)
BLOCKING_INSIGHT_STATES = {"ERROR", "UNKNOWN"}
WARNING_INSIGHT_STATES = {"WARNING"}


def iso(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value) if value is not None else None


def health_issues(value):
    return [
        {
            "code": item.get("code"),
            "message": item.get("message"),
            "resourceIds": item.get("resourceIds", []),
        }
        for item in value or []
    ]


def minor_tuple(version):
    match = re.fullmatch(r"(\d+)\.(\d+)", str(version or ""))
    return (int(match.group(1)), int(match.group(2))) if match else None


def next_minor(current):
    value = minor_tuple(current)
    return f"{value[0]}.{value[1] + 1}" if value else None


def normalize_support(value):
    return str(value or "UNKNOWN").replace("-", "_").upper()


class EksUpgradeDiscovery:
    """Assume the existing customer provisioning role and perform read-only calls."""

    def __init__(self, sts=None, secrets=None, client_factory=None):
        self.sts = sts or boto3.client("sts", config=READ_CONFIG)
        self.secrets = secrets or boto3.client("secretsmanager", config=READ_CONFIG)
        self.client_factory = client_factory or boto3.client

    def discover(self, cluster, environment_snapshot):
        if cluster.get("platform") != "EKS":
            raise ApiError(
                422,
                "UPGRADE_PROVIDER_NOT_SUPPORTED",
                "Live upgrade discovery is currently available for Amazon EKS clusters.",
            )
        configuration = environment_snapshot.get("configuration") or {}
        region = (configuration.get("location") or {}).get("region")
        if not region:
            raise ApiError(
                409,
                "UPGRADE_REGION_NOT_CONFIGURED",
                "The approved environment does not contain an AWS Region.",
            )
        try:
            external_id = self.secrets.get_secret_value(
                SecretId=cluster["external_id_secret_arn"]
            )["SecretString"]
            credentials = self.sts.assume_role(
                RoleArn=cluster["provisioning_role_arn"],
                RoleSessionName=f"NaviganUpgradeRead-{cluster['cluster_id'][-20:]}"[:64],
                ExternalId=external_id,
                DurationSeconds=900,
            )["Credentials"]
            eks = self.client_factory(
                "eks",
                region_name=region,
                aws_access_key_id=credentials["AccessKeyId"],
                aws_secret_access_key=credentials["SecretAccessKey"],
                aws_session_token=credentials["SessionToken"],
                config=READ_CONFIG,
            )
            return self._inventory(eks, cluster, region)
        except ApiError:
            raise
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code", "")
            if code in {"AccessDenied", "AccessDeniedException", "UnauthorizedOperation"}:
                raise ApiError(
                    409,
                    "EKS_UPGRADE_DISCOVERY_ACCESS_DENIED",
                    "The customer provisioning role does not permit the required read-only EKS discovery.",
                ) from None
            if code in {"ResourceNotFoundException", "NoSuchEntity"}:
                raise ApiError(
                    404,
                    "EKS_CLUSTER_NOT_FOUND",
                    "The registered Amazon EKS cluster could not be found in its approved account and Region.",
                ) from None
            raise ApiError(
                502,
                "EKS_UPGRADE_DISCOVERY_FAILED",
                "Amazon EKS upgrade evidence could not be collected.",
            ) from None
        except BotoCoreError:
            raise ApiError(
                502,
                "EKS_UPGRADE_DISCOVERY_FAILED",
                "Amazon EKS upgrade evidence could not be collected.",
            ) from None
        except (KeyError, ValueError):
            raise ApiError(
                409,
                "EKS_UPGRADE_DISCOVERY_CONFIGURATION_INVALID",
                "The cluster provisioning identity is incomplete or invalid.",
            ) from None

    def _inventory(self, eks, managed_cluster, region):
        name = managed_cluster["cluster_name"]
        cluster = eks.describe_cluster(name=name)["cluster"]
        current = cluster.get("version")
        versions = self._versions(eks)
        version_by_name = {item["version"]: item for item in versions}
        target_name = next_minor(current)
        target = version_by_name.get(target_name)
        if target and target["supportStatus"] == "UNSUPPORTED":
            target = None

        node_groups = self._node_groups(eks, name)
        addons = self._addons(eks, name, target_name if target else None)
        insights = self._insights(eks, name, target_name if target else None)
        updates = self._updates(eks, name)

        blockers = []
        warnings = []
        if cluster.get("status") != "ACTIVE":
            blockers.append(
                {
                    "code": "CONTROL_PLANE_NOT_ACTIVE",
                    "message": f"EKS control plane status is {cluster.get('status', 'UNKNOWN')}.",
                }
            )
        if not target:
            blockers.append(
                {
                    "code": "NO_SUPPORTED_NEXT_MINOR",
                    "message": "Amazon EKS did not report the next sequential Kubernetes minor version as supported.",
                }
            )
        for node in node_groups:
            if node["status"] != "ACTIVE":
                blockers.append(
                    {
                        "code": "NODE_GROUP_NOT_ACTIVE",
                        "message": f"Managed node group {node['name']} is {node['status']}.",
                    }
                )
            if node["version"] != current:
                blockers.append(
                    {
                        "code": "NODE_GROUP_VERSION_SKEW",
                        "message": f"Managed node group {node['name']} is on {node['version'] or 'an unknown version'}; align it to control plane {current} before the next control-plane upgrade.",
                    }
                )
            for issue in node["healthIssues"]:
                blockers.append(
                    {
                        "code": issue.get("code") or "NODE_GROUP_HEALTH_ISSUE",
                        "message": issue.get("message") or f"Managed node group {node['name']} has a health issue.",
                    }
                )
        for addon in addons:
            if addon["status"] != "ACTIVE":
                blockers.append(
                    {
                        "code": "ADDON_NOT_ACTIVE",
                        "message": f"Managed add-on {addon['name']} is {addon['status']}.",
                    }
                )
            if target and not addon["targetVersion"]:
                warnings.append(
                    {
                        "code": "ADDON_TARGET_NOT_RESOLVED",
                        "message": f"No default {addon['name']} version was resolved for Kubernetes {target_name}.",
                    }
                )
            for issue in addon["healthIssues"]:
                blockers.append(
                    {
                        "code": issue.get("code") or "ADDON_HEALTH_ISSUE",
                        "message": issue.get("message") or f"Managed add-on {addon['name']} has a health issue.",
                    }
                )
        for insight in insights:
            finding = {
                "code": "EKS_UPGRADE_INSIGHT_" + insight["status"],
                "message": insight["name"] + ": " + (insight["reason"] or insight["description"] or "Review the EKS insight."),
                "insightId": insight["id"],
            }
            if insight["status"] in BLOCKING_INSIGHT_STATES:
                blockers.append(finding)
            elif insight["status"] in WARNING_INSIGHT_STATES:
                warnings.append(finding)
        for update in updates:
            if update["status"] in {"InProgress", "Pending"}:
                blockers.append(
                    {
                        "code": "EKS_UPDATE_IN_PROGRESS",
                        "message": f"EKS {update['type'] or 'update'} {update['id']} is {update['status']}.",
                    }
                )

        readiness = "BLOCKED" if blockers else "WARNING" if warnings else "READY"
        current_support = version_by_name.get(current)
        return {
            "clusterId": managed_cluster["cluster_id"],
            "customerId": managed_cluster["customer_id"],
            "provider": "EKS",
            "region": region,
            "source": "AWS_EKS_API",
            "observedAt": datetime.now(timezone.utc).isoformat(),
            "controlPlane": {
                "name": cluster.get("name"),
                "arn": cluster.get("arn"),
                "version": current,
                "platformVersion": cluster.get("platformVersion"),
                "status": cluster.get("status"),
                "support": current_support,
            },
            "recommendedTarget": target,
            "nodeGroups": node_groups,
            "addons": addons,
            "insights": insights,
            "updates": updates,
            "readiness": {
                "status": readiness,
                "blockers": blockers,
                "warnings": warnings,
                "checks": {
                    "controlPlaneActive": cluster.get("status") == "ACTIVE",
                    "nodeGroupsAligned": all(
                        node["status"] == "ACTIVE" and node["version"] == current
                        and not node["healthIssues"] for node in node_groups
                    ),
                    "addonsHealthy": all(
                        addon["status"] == "ACTIVE" and not addon["healthIssues"]
                        for addon in addons
                    ),
                    "upgradeInsightsPassing": all(
                        insight["status"] == "PASSING" for insight in insights
                    ),
                    "noUpdateInProgress": not any(
                        update["status"] in {"InProgress", "Pending"}
                        for update in updates
                    ),
                },
            },
        }

    @staticmethod
    def _versions(eks):
        values = []
        token = None
        for _ in range(10):
            request = {"includeAll": True, "maxResults": 100}
            if token:
                request["nextToken"] = token
            page = eks.describe_cluster_versions(**request)
            for item in page.get("clusterVersions", []):
                values.append(
                    {
                        "version": item.get("clusterVersion"),
                        "supportStatus": normalize_support(
                            item.get("versionStatus") or item.get("status")
                        ),
                        "releaseDate": iso(item.get("releaseDate")),
                        "endOfStandardSupportDate": iso(
                            item.get("endOfStandardSupportDate")
                        ),
                        "endOfExtendedSupportDate": iso(
                            item.get("endOfExtendedSupportDate")
                        ),
                        "defaultPlatformVersion": item.get("defaultPlatformVersion"),
                        "kubernetesPatchVersion": item.get("kubernetesPatchVersion"),
                    }
                )
            token = page.get("nextToken")
            if not token:
                break
        return values

    @staticmethod
    def _node_groups(eks, cluster_name):
        names = []
        token = None
        for _ in range(10):
            request = {"clusterName": cluster_name, "maxResults": 100}
            if token:
                request["nextToken"] = token
            page = eks.list_nodegroups(**request)
            names.extend(page.get("nodegroups", []))
            token = page.get("nextToken")
            if not token:
                break
        result = []
        for name in names:
            item = eks.describe_nodegroup(
                clusterName=cluster_name, nodegroupName=name
            )["nodegroup"]
            result.append(
                {
                    "name": item.get("nodegroupName", name),
                    "version": item.get("version"),
                    "releaseVersion": item.get("releaseVersion"),
                    "status": item.get("status"),
                    "amiType": item.get("amiType"),
                    "capacityType": item.get("capacityType"),
                    "healthIssues": health_issues(
                        (item.get("health") or {}).get("issues")
                    ),
                }
            )
        return result

    @staticmethod
    def _addons(eks, cluster_name, target_version):
        names = []
        token = None
        for _ in range(10):
            request = {"clusterName": cluster_name, "maxResults": 100}
            if token:
                request["nextToken"] = token
            page = eks.list_addons(**request)
            names.extend(page.get("addons", []))
            token = page.get("nextToken")
            if not token:
                break
        result = []
        for name in names:
            item = eks.describe_addon(clusterName=cluster_name, addonName=name)["addon"]
            target = None
            if target_version:
                versions = eks.describe_addon_versions(
                    kubernetesVersion=target_version,
                    addonName=name,
                    maxResults=100,
                ).get("addons", [])
                candidates = [
                    version
                    for addon in versions
                    for version in addon.get("addonVersions", [])
                ]
                target = next(
                    (
                        version.get("addonVersion")
                        for version in candidates
                        if any(
                            compatibility.get("clusterVersion") == target_version
                            and compatibility.get("defaultVersion") is True
                            for compatibility in version.get("compatibilities", [])
                        )
                    ),
                    candidates[0].get("addonVersion") if candidates else None,
                )
            result.append(
                {
                    "name": item.get("addonName", name),
                    "version": item.get("addonVersion"),
                    "status": item.get("status"),
                    "serviceAccountRoleArn": item.get("serviceAccountRoleArn"),
                    "healthIssues": health_issues(
                        (item.get("health") or {}).get("issues")
                    ),
                    "targetVersion": target,
                }
            )
        return result

    @staticmethod
    def _insights(eks, cluster_name, target_version):
        values = []
        token = None
        for _ in range(10):
            request = {
                "clusterName": cluster_name,
                "filter": {
                    "categories": ["UPGRADE_READINESS"],
                    **(
                        {"kubernetesVersions": [target_version]}
                        if target_version
                        else {}
                    ),
                },
                "maxResults": 100,
            }
            if token:
                request["nextToken"] = token
            page = eks.list_insights(**request)
            values.extend(page.get("insights", []))
            token = page.get("nextToken")
            if not token:
                break
        result = []
        for summary in values:
            status = (summary.get("insightStatus") or {}).get("status", "UNKNOWN")
            detail = summary
            if status != "PASSING" and summary.get("id"):
                detail = eks.describe_insight(
                    clusterName=cluster_name, id=summary["id"]
                ).get("insight", summary)
            insight_status = detail.get("insightStatus") or {}
            result.append(
                {
                    "id": detail.get("id"),
                    "name": detail.get("name", "Unnamed EKS insight"),
                    "category": detail.get("category"),
                    "kubernetesVersion": detail.get("kubernetesVersion"),
                    "status": insight_status.get("status", status),
                    "reason": insight_status.get("reason"),
                    "description": detail.get("description"),
                    "recommendation": detail.get("recommendation"),
                    "lastRefreshTime": iso(detail.get("lastRefreshTime")),
                    "resources": [
                        {
                            "arn": resource.get("arn"),
                            "kubernetesResourceUri": resource.get(
                                "kubernetesResourceUri"
                            ),
                            "status": (
                                resource.get("insightStatus") or {}
                            ).get("status"),
                            "reason": (
                                resource.get("insightStatus") or {}
                            ).get("reason"),
                        }
                        for resource in detail.get("resources", [])
                    ],
                }
            )
        return result

    @staticmethod
    def _updates(eks, cluster_name):
        page = eks.list_updates(name=cluster_name, maxResults=10)
        result = []
        for update_id in page.get("updateIds", [])[:10]:
            item = eks.describe_update(name=cluster_name, updateId=update_id).get(
                "update", {}
            )
            if item.get("status") in {"InProgress", "Pending"}:
                result.append(
                    {
                        "id": item.get("id", update_id),
                        "type": item.get("type"),
                        "status": item.get("status"),
                        "createdAt": iso(item.get("createdAt")),
                    }
                )
        return result
