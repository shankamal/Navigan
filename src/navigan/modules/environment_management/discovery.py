"""Bounded, read-only AWS inventory used to populate an Environment baseline."""

from datetime import datetime, timezone

from navigan.shared.errors import ApiError
from .readiness import REQUIRED_CLUSTER_POLICIES, REQUIRED_NODE_POLICIES


def _items(client, operation, result_key, *, max_items=100, **kwargs):
    """Return a bounded result set; discovery is deliberately not an account export."""
    try:
        return (
            client.get_paginator(operation)
            .paginate(
                PaginationConfig={
                    "MaxItems": max_items,
                    "PageSize": min(max_items, 100),
                },
                **kwargs,
            )
            .build_full_result()
            .get(result_key, [])
        )
    except Exception as error:
        if error.__class__.__name__ in {"OperationNotPageableError", "AttributeError"}:
            return getattr(client, operation)(**kwargs).get(result_key, [])[:max_items]
        raise


def _name(tags):
    return next((tag.get("Value", "") for tag in tags or [] if tag.get("Key") == "Name"), "")


def _chunks(values, size=100):
    for index in range(0, len(values), size):
        yield values[index:index + size]


def _subnet_routes(route_tables):
    """Map each subnet to its effective route table, including the VPC main table."""
    explicit, main = {}, {}
    for table in route_tables:
        for association in table.get("Associations", []):
            if association.get("SubnetId"):
                explicit[association["SubnetId"]] = table
            if association.get("Main"):
                main[table.get("VpcId")] = table
    return explicit, main


def _route_profile(table):
    default = next(
        (
            route
            for route in (table or {}).get("Routes", [])
            if route.get("DestinationCidrBlock") == "0.0.0.0/0"
            or route.get("DestinationIpv6CidrBlock") == "::/0"
        ),
        {},
    )
    target = next(
        (
            default.get(key)
            for key in ["NatGatewayId", "GatewayId", "TransitGatewayId", "NetworkInterfaceId"]
            if default.get(key)
        ),
        "",
    )
    subnet_type = "PUBLIC" if target.startswith("igw-") else "PRIVATE"
    return subnet_type, target


def discover_aws(body, boto3_module=None):
    """Assume the fixed-name customer role and return references safe to show or persist."""
    if boto3_module is None:
        import boto3 as boto3_module

    access_stage = "assume_role"
    try:
        assumed = boto3_module.client("sts").assume_role(
            RoleArn=body["roleArn"],
            RoleSessionName=f"navigan-{body['customerId']}"[:64],
            ExternalId=body["externalId"],
            DurationSeconds=900,
        )
        credentials = assumed["Credentials"]
        session = boto3_module.Session(
            aws_access_key_id=credentials["AccessKeyId"],
            aws_secret_access_key=credentials["SecretAccessKey"],
            aws_session_token=credentials["SessionToken"],
        )
        access_stage = "verify_assumed_identity"
        identity = session.client("sts").get_caller_identity()
        if identity.get("Account") != body["accountId"]:
            raise ApiError(422, "AWS_ACCOUNT_MISMATCH", "The discovery role resolved to another AWS account.")

        access_stage = "read_iam_inventory"
        iam = session.client("iam")
        roles = []
        provisioning_roles = []
        # IAM-heavy enterprise accounts commonly exceed 100 roles. Scan up to
        # the default IAM account quota so eligible Navigan/EKS roles are not
        # silently omitted by alphabetical pagination.
        for role in _items(iam, "list_roles", "Roles", max_items=1000):
            name = role.get("RoleName", "")
            document = role.get("AssumeRolePolicyDocument", {})
            trust = str(document)
            role_type = (
                "CLUSTER"
                if "eks.amazonaws.com" in trust
                else "NODE"
                if "ec2.amazonaws.com" in trust
                else "OTHER"
            )
            if role_type != "OTHER":
                eligibility, reason = "READY", "Required managed policies are attached."
                try:
                    attached = {
                        item["PolicyArn"]
                        for item in _items(
                            iam,
                            "list_attached_role_policies",
                            "AttachedPolicies",
                            RoleName=name,
                        )
                    }
                    required = (
                        REQUIRED_CLUSTER_POLICIES
                        if role_type == "CLUSTER"
                        else REQUIRED_NODE_POLICIES
                    )
                    missing = required - attached
                    if "arn:aws:iam::aws:policy/AdministratorAccess" in attached:
                        eligibility = "BLOCKED"
                        reason = "AdministratorAccess is not permitted for a Navigan blueprint."
                    elif missing:
                        eligibility = "BLOCKED"
                        reason = "Missing: " + ", ".join(
                            sorted(item.rsplit("/", 1)[-1] for item in missing)
                        )
                except Exception:
                    eligibility = "WARNING"
                    reason = (
                        "NaviganDiscoveryRole needs iam:GetRole and "
                        "iam:ListAttachedRolePolicies to verify this role."
                    )
                roles.append(
                    {
                        "roleName": name,
                        "roleArn": role.get("Arn", ""),
                        "roleType": role_type,
                        "eligibility": eligibility,
                        "eligibilityReason": reason,
                    }
                )
            if name.endswith("NaviganProvisioningRole"):
                provisioning_roles.append({"roleName": name, "roleArn": role.get("Arn", "")})

        access_stage = "list_provisioning_secrets"
        provisioning_secrets = []
        secrets = boto3_module.client("secretsmanager")
        prefix = f"navigan/provisioning/{body['customerId']}/"
        for secret in _items(
            secrets, "list_secrets", "SecretList", Filters=[{"Key": "name", "Values": [prefix]}]
        ):
            provisioning_secrets.append({"name": secret.get("Name", ""), "arn": secret.get("ARN", "")})

        discovered_regions = []
        for region in body["regions"]:
            access_stage = f"read_network_inventory:{region}"
            ec2 = session.client("ec2", region_name=region)
            vpcs = [
                {
                    "vpcId": item["VpcId"],
                    "name": _name(item.get("Tags")),
                    "cidrBlock": item.get("CidrBlock"),
                    "isDefault": item.get("IsDefault", False),
                }
                for item in _items(ec2, "describe_vpcs", "Vpcs")
            ]
            route_tables = _items(ec2, "describe_route_tables", "RouteTables")
            explicit_routes, main_routes = _subnet_routes(route_tables)
            subnets = [
                {
                    "subnetId": item["SubnetId"],
                    "name": _name(item.get("Tags")),
                    "vpcId": item["VpcId"],
                    "availabilityZone": item["AvailabilityZone"],
                    "cidrBlock": item.get("CidrBlock"),
                    "availableIpAddressCount": item.get("AvailableIpAddressCount", 0),
                    "mapPublicIpOnLaunch": item.get("MapPublicIpOnLaunch", False),
                    "routeTableId": (
                        explicit_routes.get(item["SubnetId"], main_routes.get(item["VpcId"], {})).get(
                            "RouteTableId", ""
                        )
                    ),
                    "type": _route_profile(
                        explicit_routes.get(item["SubnetId"], main_routes.get(item["VpcId"], {}))
                    )[0],
                    "egressTarget": _route_profile(
                        explicit_routes.get(item["SubnetId"], main_routes.get(item["VpcId"], {}))
                    )[1],
                }
                for item in _items(ec2, "describe_subnets", "Subnets")
            ]
            groups = [
                {
                    "securityGroupId": item["GroupId"],
                    "name": item.get("GroupName", ""),
                    "description": item.get("Description", ""),
                    "vpcId": item.get("VpcId"),
                }
                for item in _items(ec2, "describe_security_groups", "SecurityGroups")
            ]
            zones = [
                {"name": item["ZoneName"], "state": item.get("State", "unknown")}
                for item in ec2.describe_availability_zones(
                    Filters=[{"Name": "opt-in-status", "Values": ["opt-in-not-required", "opted-in"]}]
                ).get("AvailabilityZones", [])
            ]
            endpoints = [
                {"vpcEndpointId": item["VpcEndpointId"], "serviceName": item.get("ServiceName", "")}
                for item in _items(ec2, "describe_vpc_endpoints", "VpcEndpoints")
            ]
            nat_gateways = [
                {
                    "natGatewayId": item["NatGatewayId"],
                    "vpcId": item.get("VpcId", ""),
                    "subnetId": item.get("SubnetId", ""),
                    "state": item.get("State", "unknown"),
                }
                for item in _items(ec2, "describe_nat_gateways", "NatGateways")
            ]
            access_stage = f"read_instance_types:{region}"
            offered_types = sorted(
                {
                    item.get("InstanceType", "")
                    for item in _items(
                        ec2,
                        "describe_instance_type_offerings",
                        "InstanceTypeOfferings",
                        max_items=1000,
                        LocationType="region",
                        Filters=[{"Name": "location", "Values": [region]}],
                    )
                    if item.get("InstanceType")
                }
            )
            instance_types = []
            for names in _chunks(offered_types):
                for item in ec2.describe_instance_types(InstanceTypes=names).get(
                    "InstanceTypes", []
                ):
                    instance_types.append(
                        {
                            "instanceType": item["InstanceType"],
                            "vCpu": item.get("VCpuInfo", {}).get("DefaultVCpus", 0),
                            "memoryMiB": item.get("MemoryInfo", {}).get("SizeInMiB", 0),
                            "architectures": item.get("ProcessorInfo", {}).get(
                                "SupportedArchitectures", []
                            ),
                            "currentGeneration": bool(item.get("CurrentGeneration", False)),
                            "burstablePerformanceSupported": bool(
                                item.get("BurstablePerformanceSupported", False)
                            ),
                        }
                    )
            instance_types.sort(key=lambda item: item["instanceType"])
            access_stage = f"read_kms_inventory:{region}"
            kms = session.client("kms", region_name=region)
            partition = body["roleArn"].split(":", 2)[1]
            keys = []
            for item in _items(kms, "list_aliases", "Aliases"):
                if not item.get("TargetKeyId") or item.get("AliasName", "").startswith("alias/aws/"):
                    continue
                key_arn = (
                    f"arn:{partition}:kms:{region}:{body['accountId']}:key/{item['TargetKeyId']}"
                )
                eligibility, reason = "BLOCKED", "Key metadata could not be verified."
                try:
                    metadata = kms.describe_key(KeyId=item["TargetKeyId"])["KeyMetadata"]
                    ready = (
                        metadata.get("Enabled")
                        and metadata.get("KeyState") == "Enabled"
                        and metadata.get("KeyUsage") == "ENCRYPT_DECRYPT"
                        and metadata.get("KeySpec") == "SYMMETRIC_DEFAULT"
                    )
                    eligibility = "READY" if ready else "BLOCKED"
                    reason = (
                        "Enabled symmetric encryption key."
                        if ready
                        else "EBS requires an enabled SYMMETRIC_DEFAULT ENCRYPT_DECRYPT key."
                    )
                except Exception:
                    reason = (
                        "NaviganDiscoveryRole needs kms:DescribeKey to verify "
                        "that this key supports EBS encryption."
                    )
                keys.append(
                    {
                        "aliasName": item.get("AliasName", ""),
                        "keyArn": key_arn,
                        "eligibility": eligibility,
                        "eligibilityReason": reason,
                    }
                )
            access_stage = f"read_eks_inventory:{region}"
            eks = session.client("eks", region_name=region)
            cluster_versions = []
            try:
                for item in _items(
                    eks,
                    "describe_cluster_versions",
                    "clusterVersions",
                    includeAll=True,
                ):
                    version = item.get("clusterVersion", "")
                    status = item.get("versionStatus", "")
                    if version and status != "UNSUPPORTED":
                        cluster_versions.append(
                            {
                                "version": version,
                                "support": status,
                                "default": bool(item.get("defaultVersion")),
                            }
                        )
                cluster_versions.sort(
                    key=lambda item: tuple(int(part) for part in item["version"].split(".")),
                    reverse=True,
                )
            except Exception:
                cluster_versions = []
            clusters = [{"name": name} for name in _items(eks, "list_clusters", "clusters")]
            access_stage = f"read_ecr_inventory:{region}"
            ecr = session.client("ecr", region_name=region)
            repositories = [
                {
                    "repositoryName": item.get("repositoryName", ""),
                    "repositoryArn": item.get("repositoryArn", ""),
                    "imageTagMutability": item.get("imageTagMutability", ""),
                }
                for item in _items(ecr, "describe_repositories", "repositories")
            ]
            access_stage = f"read_service_quotas:{region}"
            quotas = session.client("service-quotas", region_name=region)
            service_quotas = []
            for service_code in ["eks", "ec2"]:
                service_quotas.extend(
                    {
                        "serviceCode": service_code,
                        "quotaCode": item.get("QuotaCode", ""),
                        "quotaName": item.get("QuotaName", ""),
                        "value": item.get("Value", 0),
                        "adjustable": item.get("Adjustable", False),
                    }
                    for item in _items(
                        quotas,
                        "list_service_quotas",
                        "Quotas",
                        ServiceCode=service_code,
                    )
                )
            access_stage = f"read_ebs_encryption:{region}"
            ebs_encryption = ec2.get_ebs_encryption_by_default().get("EbsEncryptionByDefault", False)
            discovered_regions.append(
                {
                    "region": region,
                    "availabilityZones": zones,
                    "vpcs": vpcs,
                    "subnets": subnets,
                    "securityGroups": groups,
                    "vpcEndpoints": endpoints,
                    "natGateways": nat_gateways,
                    "instanceTypes": instance_types,
                    "kmsKeys": keys,
                    "kubernetesVersions": cluster_versions,
                    "eksClusters": clusters,
                    "ecrRepositories": repositories,
                    "serviceQuotas": service_quotas,
                    "ebsEncryptionByDefault": ebs_encryption,
                }
            )
        counts = {
            key: sum(len(region[key]) for region in discovered_regions)
            for key in [
                "vpcs",
                "subnets",
                "securityGroups",
                "vpcEndpoints",
                "natGateways",
                "kmsKeys",
                "eksClusters",
                "ecrRepositories",
                "serviceQuotas",
            ]
        }
        counts["iamRoles"] = len(roles)
        counts["provisioningRoles"] = len(provisioning_roles)
        counts["provisioningSecrets"] = len(provisioning_secrets)
        return {
            "cloudProvider": "AWS",
            "kubernetesDistribution": "EKS",
            "account": {"accountId": identity["Account"], "principalArn": identity.get("Arn", "")},
            "roleArn": body["roleArn"],
            "regions": discovered_regions,
            "iamRoles": roles,
            "provisioningRoles": provisioning_roles,
            "provisioningSecrets": provisioning_secrets,
            "counts": counts,
            "fetchedAt": datetime.now(timezone.utc).isoformat(),
        }
    except ApiError:
        raise
    except Exception as error:
        code = getattr(error, "response", {}).get("Error", {}).get("Code", "")
        if code in {"AccessDenied", "AccessDeniedException", "InvalidClientTokenId"}:
            messages = {
                "assume_role": (
                    "AWS denied the discovery session. Verify its trusted Lambda role "
                    "and customer External ID."
                ),
                "verify_assumed_identity": (
                    "The discovery role was assumed, but AWS denied identity verification."
                ),
                "read_iam_inventory": (
                    "The discovery role was assumed, but it cannot read IAM roles and policy attachments."
                ),
                "list_provisioning_secrets": (
                    "The discovery role was assumed, but the Navigan Lambda cannot list provisioning references."
                ),
            }
            service = access_stage.split(":", 1)[0]
            regional_messages = {
                "read_network_inventory": "The discovery role cannot read VPC, subnet, route or security-group inventory.",
                "read_instance_types": "The discovery role cannot read regional EC2 instance-type offerings.",
                "read_kms_inventory": "The discovery role cannot read customer-managed KMS key inventory.",
                "read_eks_inventory": "The discovery role cannot read EKS versions or clusters.",
                "read_ecr_inventory": "The discovery role cannot read ECR repository inventory.",
                "read_service_quotas": "The discovery role cannot read EKS and EC2 service quotas.",
                "read_ebs_encryption": "The discovery role cannot read the EBS encryption default.",
            }
            raise ApiError(
                422,
                "AWS_DISCOVERY_ACCESS_DENIED",
                messages.get(access_stage)
                or regional_messages.get(service)
                or "AWS denied a read-only discovery operation.",
                {"stage": access_stage},
            ) from None
        raise ApiError(
            502, "AWS_DISCOVERY_FAILED", "AWS resource discovery could not be completed."
        ) from None
