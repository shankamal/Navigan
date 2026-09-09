"""Bounded, read-only AWS inventory used to populate an Environment baseline."""

from datetime import datetime, timezone

from navigan.shared.errors import ApiError


def _items(client, operation, result_key, **kwargs):
    """Return one bounded API page; discovery is deliberately not an account export."""
    try:
        return (
            client.get_paginator(operation)
            .paginate(PaginationConfig={"MaxItems": 100, "PageSize": 100}, **kwargs)
            .build_full_result()
            .get(result_key, [])
        )
    except Exception as error:
        if error.__class__.__name__ in {"OperationNotPageableError", "AttributeError"}:
            return getattr(client, operation)(**kwargs).get(result_key, [])[:100]
        raise


def _name(tags):
    return next((tag.get("Value", "") for tag in tags or [] if tag.get("Key") == "Name"), "")


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

    try:
        assumed = boto3_module.client("sts").assume_role(
            RoleArn=body["roleArn"],
            RoleSessionName="navigan-environment-discovery",
            ExternalId=body["externalId"],
            DurationSeconds=900,
        )
        credentials = assumed["Credentials"]
        session = boto3_module.Session(
            aws_access_key_id=credentials["AccessKeyId"],
            aws_secret_access_key=credentials["SecretAccessKey"],
            aws_session_token=credentials["SessionToken"],
        )
        identity = session.client("sts").get_caller_identity()
        if identity.get("Account") != body["accountId"]:
            raise ApiError(422, "AWS_ACCOUNT_MISMATCH", "The discovery role resolved to another AWS account.")

        iam = session.client("iam")
        roles = []
        for role in _items(iam, "list_roles", "Roles"):
            name = role.get("RoleName", "")
            document = role.get("AssumeRolePolicyDocument", {})
            if "eks.amazonaws.com" in str(document) or "ec2.amazonaws.com" in str(document):
                roles.append({"roleName": name, "roleArn": role.get("Arn", "")})

        discovered_regions = []
        for region in body["regions"]:
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
            kms = session.client("kms", region_name=region)
            partition = body["roleArn"].split(":", 2)[1]
            keys = [
                {
                    "aliasName": item.get("AliasName", ""),
                    "keyArn": f"arn:{partition}:kms:{region}:{body['accountId']}:key/{item['TargetKeyId']}",
                }
                for item in _items(kms, "list_aliases", "Aliases")
                if item.get("TargetKeyId") and not item.get("AliasName", "").startswith("alias/aws/")
            ]
            eks = session.client("eks", region_name=region)
            clusters = [{"name": name} for name in _items(eks, "list_clusters", "clusters")]
            ecr = session.client("ecr", region_name=region)
            repositories = [
                {
                    "repositoryName": item.get("repositoryName", ""),
                    "repositoryArn": item.get("repositoryArn", ""),
                    "imageTagMutability": item.get("imageTagMutability", ""),
                }
                for item in _items(ecr, "describe_repositories", "repositories")
            ]
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
                    "kmsKeys": keys,
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
        return {
            "cloudProvider": "AWS",
            "kubernetesDistribution": "EKS",
            "account": {"accountId": identity["Account"], "principalArn": identity.get("Arn", "")},
            "roleArn": body["roleArn"],
            "regions": discovered_regions,
            "iamRoles": roles,
            "counts": counts,
            "fetchedAt": datetime.now(timezone.utc).isoformat(),
        }
    except ApiError:
        raise
    except Exception as error:
        code = getattr(error, "response", {}).get("Error", {}).get("Code", "")
        if code in {"AccessDenied", "AccessDeniedException", "InvalidClientTokenId"}:
            raise ApiError(
                422,
                "AWS_DISCOVERY_ACCESS_DENIED",
                "Navigan could not assume or use the supplied read-only discovery role.",
            ) from None
        raise ApiError(
            502, "AWS_DISCOVERY_FAILED", "AWS resource discovery could not be completed."
        ) from None
