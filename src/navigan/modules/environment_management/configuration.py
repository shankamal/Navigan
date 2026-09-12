"""Versioned provider schemas shared by validation, metadata APIs and dynamic forms."""

import copy
import json
import re
from functools import lru_cache
from pathlib import Path
from jsonschema import Draft202012Validator
from navigan.shared.errors import ApiError

DISTRIBUTIONS = {"AWS": "EKS", "AZURE": "AKS", "GCP": "GKE", "OCI": "OKE"}

NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
KUBERNETES_VERSION_PATTERN = re.compile(r"^1\.[0-9]{2}$")
PROVISIONING_ROLE_ARN_PATTERN = re.compile(
    r"^arn:(aws|aws-us-gov|aws-cn):iam::[0-9]{12}:role/(?:[A-Za-z0-9+=,.@_-]+/)*NaviganProvisioningRole$"
)
PROVISIONING_SECRET_ARN_PATTERN = re.compile(
    r"^arn:(aws|aws-us-gov|aws-cn):secretsmanager:[a-z0-9-]+:[0-9]{12}:secret:[A-Za-z0-9/_+=.@-]+$"
)


@lru_cache(maxsize=16)
def schema(distribution, version):
    if distribution not in DISTRIBUTIONS.values() or version != "1.0":
        raise ApiError(422, "CONFIGURATION_SCHEMA_UNSUPPORTED", "Unsupported distribution or schema version.")
    return json.loads(
        (Path(__file__).parent / "schemas" / f"{distribution.lower()}-{version}.json").read_text()
    )


def partial(node):
    if isinstance(node, dict):
        return {
            k: partial(v)
            for k, v in node.items()
            if k not in {"required", "minItems", "minLength", "allOf", "uniqueItems"}
        }
    if isinstance(node, list):
        return [partial(v) for v in node]
    return node


def check_secrets(value, depth=0):
    if depth > 20:
        raise ApiError(422, "INVALID_CONFIGURATION", "Configuration nesting exceeds 20 levels.")
    if isinstance(value, dict):
        for k, v in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", k.lower())
            if normalized in {
                "password",
                "passwd",
                "secret",
                "clientsecret",
                "accesskey",
                "accesskeyid",
                "secretaccesskey",
                "sessiontoken",
                "token",
                "bearertoken",
                "privatekey",
                "credentials",
                "kubeconfig",
                "authorization",
            }:
                raise ApiError(
                    422, "INVALID_CONFIGURATION", "Store infrastructure references, never credentials."
                )
            check_secrets(v, depth + 1)
    elif isinstance(value, list):
        for v in value:
            check_secrets(v, depth + 1)
    elif isinstance(value, str):
        if re.search(
            r"-----BEGIN .*PRIVATE KEY-----|\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|://[^/\s]+:[^/\s]+@|\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+",
            value,
        ):
            raise ApiError(
                422, "INVALID_CONFIGURATION", "Credential material is not permitted in configuration."
            )


def validate(configuration, distribution, version, submitting=False):
    check_secrets(configuration)
    selected = copy.deepcopy(schema(distribution, version))
    errors = []
    for error in Draft202012Validator(selected if submitting else partial(selected)).iter_errors(
        configuration
    ):
        path = "configuration" + "".join("." + str(p) for p in error.absolute_path)
        # Do not include jsonschema's message: it can echo submitted data.
        errors.append({"field": path, "message": f"Check {error.validator} constraint."})
    if submitting and distribution == "EKS":
        account_id = configuration.get("account", {}).get("accountId", "")
        region = configuration.get("location", {}).get("region", "")
        network = configuration.get("network", {})
        vpc_id = network.get("vpc", {}).get("vpcId") if isinstance(network, dict) else None
        for key in ["clusterSubnets", "nodeSubnets"]:
            subnets = network.get(key, []) if isinstance(network, dict) else []
            if isinstance(subnets, list):
                zones = {
                    s.get("availabilityZone")
                    for s in subnets
                    if isinstance(s, dict) and s.get("availabilityZone")
                }
                ids = [s.get("subnetId") for s in subnets if isinstance(s, dict)]
                if len(zones) < 2 or len(set(ids)) != len(ids):
                    errors.append(
                        {
                            "field": "configuration.network." + key,
                            "message": "Use distinct subnets across at least two availability zones.",
                        }
                    )
                mismatched_vpcs = {
                    s.get("vpcId")
                    for s in subnets
                    if isinstance(s, dict) and s.get("vpcId") and s.get("vpcId") != vpc_id
                }
                if mismatched_vpcs:
                    errors.append(
                        {
                            "field": "configuration.network." + key,
                            "message": "Every selected subnet must belong to the selected VPC.",
                        }
                    )
        for key in ["clusterSecurityGroups", "nodeSecurityGroups"]:
            groups = configuration.get("security", {}).get(key, [])
            if any(
                isinstance(group, dict) and group.get("vpcId") and group.get("vpcId") != vpc_id
                for group in groups
            ):
                errors.append(
                    {
                        "field": "configuration.security." + key,
                        "message": "Every selected security group must belong to the selected VPC.",
                    }
                )
        for key in ["clusterRole", "nodeRole"]:
            role_arn = configuration.get("iam", {}).get(key, {}).get("roleArn", "")
            if role_arn and f"::{account_id}:role/" not in role_arn:
                errors.append(
                    {
                        "field": "configuration.iam." + key + ".roleArn",
                        "message": "The IAM role must belong to the selected AWS account.",
                    }
                )
        key_arn = configuration.get("encryption", {}).get("nodeVolumeKmsKey", {}).get("keyArn", "")
        if key_arn and (f":kms:{region}:{account_id}:key/" not in key_arn):
            errors.append(
                {
                    "field": "configuration.encryption.nodeVolumeKmsKey.keyArn",
                    "message": "The KMS key must belong to the selected account and region.",
                }
            )
        blueprints = configuration.get("clusters", [])
        if isinstance(blueprints, list):
            blueprint_names = [b.get("name") for b in blueprints if isinstance(b, dict)]
            if len(set(blueprint_names)) != len(blueprint_names):
                errors.append(
                    {
                        "field": "configuration.clusters",
                        "message": "Cluster blueprint names must be unique.",
                    }
                )
            for bi, blueprint in enumerate(blueprints):
                if not isinstance(blueprint, dict):
                    continue
                name = blueprint.get("name", "")
                if name and not NAME_PATTERN.match(name):
                    errors.append(
                        {
                            "field": f"configuration.clusters.{bi}.name",
                            "message": "Check pattern constraint.",
                        }
                    )
                kubernetes_version = blueprint.get("kubernetesVersion", "")
                if kubernetes_version and not KUBERNETES_VERSION_PATTERN.match(kubernetes_version):
                    errors.append(
                        {
                            "field": f"configuration.clusters.{bi}.kubernetesVersion",
                            "message": "Check pattern constraint.",
                        }
                    )
                node_groups = blueprint.get("nodeGroups", [])
                if isinstance(node_groups, list):
                    names = [g.get("name") for g in node_groups if isinstance(g, dict)]
                    if len(set(names)) != len(names):
                        errors.append(
                            {
                                "field": f"configuration.clusters.{bi}.nodeGroups",
                                "message": "Node group names must be unique.",
                            }
                        )
                    for ni, group in enumerate(node_groups):
                        if not isinstance(group, dict):
                            continue
                        group_name = group.get("name", "")
                        if group_name and not NAME_PATTERN.match(group_name):
                            errors.append(
                                {
                                    "field": f"configuration.clusters.{bi}.nodeGroups.{ni}.name",
                                    "message": "Check pattern constraint.",
                                }
                            )
                        min_size, desired, max_size = (
                            group.get("minSize"),
                            group.get("desiredSize"),
                            group.get("maxSize"),
                        )
                        if None not in (min_size, desired, max_size) and not (min_size <= desired <= max_size):
                            errors.append(
                                {
                                    "field": f"configuration.clusters.{bi}.nodeGroups.{ni}",
                                    "message": "Node group size must satisfy min <= desired <= max.",
                                }
                            )
                provisioning_role_arn = blueprint.get("provisioning", {}).get("roleArn", "")
                if provisioning_role_arn and not PROVISIONING_ROLE_ARN_PATTERN.match(provisioning_role_arn):
                    errors.append(
                        {
                            "field": f"configuration.clusters.{bi}.provisioning.roleArn",
                            "message": "Check pattern constraint.",
                        }
                    )
                if provisioning_role_arn and f"::{account_id}:role/" not in provisioning_role_arn:
                    errors.append(
                        {
                            "field": f"configuration.clusters.{bi}.provisioning.roleArn",
                            "message": "The provisioning role must belong to the selected AWS account.",
                        }
                    )
                provisioning_secret_arn = blueprint.get("provisioning", {}).get("externalIdSecretArn", "")
                if provisioning_secret_arn and not PROVISIONING_SECRET_ARN_PATTERN.match(provisioning_secret_arn):
                    errors.append(
                        {
                            "field": f"configuration.clusters.{bi}.provisioning.externalIdSecretArn",
                            "message": "Check pattern constraint.",
                        }
                    )
    if errors:
        raise ApiError(
            422,
            "ENVIRONMENT_VALIDATION_FAILED" if submitting else "INVALID_CONFIGURATION",
            "Check the environment configuration.",
            {"fields": errors[:50]},
        )
