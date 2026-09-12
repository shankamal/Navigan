"""Deterministic EKS blueprint readiness checks with an optional AI explanation layer."""

import json
import os
from fnmatch import fnmatch

from botocore.config import Config

from navigan.shared.errors import ApiError

REQUIRED_CLUSTER_POLICIES = {
    "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy",
}
REQUIRED_NODE_POLICIES = {
    "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
    "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPullOnly",
    "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy",
}
AUTOSCALING_KMS_ACTIONS = {
    "kms:Encrypt",
    "kms:Decrypt",
    "kms:ReEncrypt*",
    "kms:GenerateDataKey*",
    "kms:DescribeKey",
}


def finding(code, field, message, recommendation, severity="BLOCKING"):
    return {
        "code": code,
        "field": field,
        "severity": severity,
        "message": message,
        "recommendation": recommendation,
    }


def _advisor(findings, boto3_module):
    """AI can explain deterministic findings, but it never controls readiness."""
    model_id = os.getenv("BLUEPRINT_ADVISOR_MODEL_ID", "").strip()
    fallback = {
        "mode": "DETERMINISTIC",
        "summary": (
            "Correct every blocking item and validate the blueprint again."
            if findings
            else "The blueprint passed the configured readiness checks."
        ),
    }
    if not model_id or not findings:
        return fallback


def _values(value):
    return value if isinstance(value, list) else [value]


def _allows_actions(statement, required):
    if statement.get("Effect") != "Allow":
        return False
    actions = _values(statement.get("Action", []))
    return all(any(fnmatch(action, pattern) for pattern in actions) for action in required)


def _principal_contains(statement, arn):
    principal = statement.get("Principal", {})
    if not isinstance(principal, dict):
        return False
    return arn in _values(principal.get("AWS", []))


def _kms_allows_autoscaling(policy, account_id, partition="aws"):
    role = (
        f"arn:{partition}:iam::{account_id}:role/aws-service-role/"
        "autoscaling.amazonaws.com/AWSServiceRoleForAutoScaling"
    )
    statements = policy.get("Statement", [])
    use_allowed = any(
        _principal_contains(item, role)
        and _allows_actions(item, AUTOSCALING_KMS_ACTIONS)
        for item in statements
        if isinstance(item, dict)
    )
    grant_allowed = any(
        _principal_contains(item, role)
        and _allows_actions(item, {"kms:CreateGrant"})
        and str(
            item.get("Condition", {})
            .get("Bool", {})
            .get("kms:GrantIsForAWSResource", "")
        ).lower()
        == "true"
        for item in statements
        if isinstance(item, dict)
    )
    return use_allowed and grant_allowed
    try:
        client = boto3_module.client(
            "bedrock-runtime",
            config=Config(connect_timeout=3, read_timeout=8, retries={"total_max_attempts": 1}),
        )
        prompt = (
            "You are an infrastructure readiness advisor. Explain the supplied sanitized findings "
            "for a cloud engineer in at most 120 words. Do not change severity, invent resources, "
            "or claim that validation passed. Mention exact field paths.\n"
            + json.dumps(findings, separators=(",", ":"))
        )
        response = client.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 220, "temperature": 0},
        )
        text = response["output"]["message"]["content"][0]["text"].strip()
        return {"mode": "BEDROCK", "summary": text[:2000], "modelId": model_id}
    except Exception:
        return fallback


def assess_eks_blueprints(configuration, boto3_module=None):
    if boto3_module is None:
        import boto3 as boto3_module

    account_id = configuration.get("account", {}).get("accountId", "")
    region = configuration.get("location", {}).get("region", "")
    iam_configuration = configuration.get("iam", {})
    encryption = configuration.get("encryption", {})
    blueprints = configuration.get("clusters", [])
    findings = []

    if not isinstance(blueprints, list) or not blueprints:
        findings.append(
            finding(
                "BLUEPRINT_REQUIRED",
                "configuration.clusters",
                "At least one cluster blueprint is required.",
                "Add and complete a cluster blueprint.",
            )
        )

    secrets = boto3_module.client(
        "secretsmanager",
        config=Config(connect_timeout=3, read_timeout=5, retries={"total_max_attempts": 2}),
    )
    for index, blueprint in enumerate(blueprints if isinstance(blueprints, list) else []):
        if not isinstance(blueprint, dict):
            continue
        prefix = f"configuration.clusters.{index}"
        provisioning = blueprint.get("provisioning", {})
        role_arn = provisioning.get("roleArn", "") if isinstance(provisioning, dict) else ""
        secret_arn = (
            provisioning.get("externalIdSecretArn", "") if isinstance(provisioning, dict) else ""
        )
        external_id = None
        try:
            external_id = secrets.get_secret_value(SecretId=secret_arn)["SecretString"]
        except Exception:
            findings.append(
                finding(
                    "PROVISIONING_SECRET_NOT_FOUND",
                    prefix + ".provisioning.externalIdSecretArn",
                    "The External ID secret is missing or cannot be read by Navigan.",
                    "Complete the Navigan provisioning bootstrap and select the generated secret.",
                )
            )
        credentials = None
        if role_arn and external_id:
            try:
                credentials = boto3_module.client("sts").assume_role(
                    RoleArn=role_arn,
                    RoleSessionName="NaviganBlueprintReadiness",
                    ExternalId=external_id,
                    DurationSeconds=900,
                )["Credentials"]
            except Exception:
                findings.append(
                    finding(
                        "PROVISIONING_ROLE_UNAVAILABLE",
                        prefix + ".provisioning.roleArn",
                        "Navigan cannot assume the provisioning role using the configured External ID.",
                        "Generate or repair the customer bootstrap, then run AWS discovery again.",
                    )
                )
        if not credentials:
            continue
        options = {
            "region_name": region,
            "aws_access_key_id": credentials["AccessKeyId"],
            "aws_secret_access_key": credentials["SecretAccessKey"],
            "aws_session_token": credentials["SessionToken"],
            "config": Config(connect_timeout=3, read_timeout=5, retries={"total_max_attempts": 2}),
        }
        iam = boto3_module.client("iam", **options)
        for key, required in (
            ("clusterRole", REQUIRED_CLUSTER_POLICIES),
            ("nodeRole", REQUIRED_NODE_POLICIES),
        ):
            selected = iam_configuration.get(key, {}) if isinstance(iam_configuration, dict) else {}
            selected_arn = selected.get("roleArn", "") if isinstance(selected, dict) else ""
            role_name = selected_arn.rsplit("/", 1)[-1]
            field = f"configuration.iam.{key}.roleArn"
            try:
                iam.get_role(RoleName=role_name)
                attached = {
                    item["PolicyArn"]
                    for item in iam.list_attached_role_policies(RoleName=role_name).get(
                        "AttachedPolicies", []
                    )
                }
                missing = sorted(required - attached)
                if missing:
                    findings.append(
                        finding(
                            "IAM_ROLE_POLICIES_MISSING",
                            field,
                            "The selected IAM role is missing required EKS policies.",
                            "Select a dedicated role containing: "
                            + ", ".join(item.rsplit("/", 1)[-1] for item in missing),
                        )
                    )
                if "arn:aws:iam::aws:policy/AdministratorAccess" in attached:
                    findings.append(
                        finding(
                            "IAM_ROLE_OVER_PRIVILEGED",
                            field,
                            "The selected IAM role has AdministratorAccess.",
                            "Replace it with a dedicated least-privilege EKS role.",
                        )
                    )
            except Exception:
                findings.append(
                    finding(
                        "IAM_ROLE_UNVERIFIED",
                        field,
                        "Navigan could not verify the selected IAM role.",
                        "Select a role created by the Navigan bootstrap and validate again.",
                    )
                )
        kms_arn = encryption.get("nodeVolumeKmsKey", {}).get("keyArn", "")
        kms = boto3_module.client("kms", **options)
        kms_metadata_ready = False
        try:
            metadata = kms.describe_key(KeyId=kms_arn)["KeyMetadata"]
            if (
                not metadata.get("Enabled")
                or metadata.get("KeyState") != "Enabled"
                or metadata.get("KeyUsage") != "ENCRYPT_DECRYPT"
                or metadata.get("KeySpec") not in {None, "SYMMETRIC_DEFAULT"}
            ):
                raise ValueError()
            kms_metadata_ready = True
        except Exception:
            findings.append(
                finding(
                    "KMS_KEY_NOT_ENCRYPTION_READY",
                    "configuration.encryption.nodeVolumeKmsKey.keyArn",
                    "The node-volume KMS key is unavailable or does not support encryption.",
                    "Select an enabled symmetric ENCRYPT_DECRYPT KMS key in the environment region.",
                )
            )
        if kms_metadata_ready:
            try:
                policy = json.loads(
                    kms.get_key_policy(KeyId=kms_arn, PolicyName="default")["Policy"]
                )
            except Exception:
                findings.append(
                    finding(
                        "KMS_POLICY_UNVERIFIED",
                        "configuration.encryption.nodeVolumeKmsKey.keyArn",
                        "Navigan cannot verify whether Auto Scaling may use the selected KMS key.",
                        "Grant NaviganProvisioningRole kms:GetKeyPolicy for this approved key.",
                    )
                )
            else:
                partition = (
                    kms_arn.split(":", 2)[1] if kms_arn.startswith("arn:") else "aws"
                )
                if not _kms_allows_autoscaling(policy, account_id, partition):
                    findings.append(
                        finding(
                            "KMS_AUTOSCALING_ACCESS_MISSING",
                            "configuration.encryption.nodeVolumeKmsKey.keyArn",
                            "The KMS key does not allow the Auto Scaling service role to launch encrypted worker volumes.",
                            "Apply the Navigan bootstrap KMS policy, then validate the blueprint again.",
                        )
                    )
        groups = [
            group for group in blueprint.get("nodeGroups", []) if isinstance(group, dict)
        ]
        for group_index, group in enumerate(groups):
            selected = [
                item
                for item in group.get("instanceTypes", [])
                if isinstance(item, str) and item
            ]
            if len(set(selected)) < 2:
                findings.append(
                    finding(
                        "INSTANCE_TYPE_RESILIENCE_REQUIRED",
                        f"{prefix}.nodeGroups.{group_index}.instanceTypes",
                        "The node group uses a single EC2 instance type.",
                        "This keeps nodes uniform, but selecting multiple compatible types can reduce capacity failures.",
                        severity="WARNING",
                    )
                )
        instance_types = sorted(
            {
                instance
                for group in groups
                for instance in group.get("instanceTypes", [])
                if isinstance(instance, str) and instance
            }
        )
        if instance_types:
            try:
                ec2 = boto3_module.client("ec2", **options)
                ec2.describe_instance_types(InstanceTypes=instance_types)
                node_zones = sorted(
                    {
                        item.get("availabilityZone")
                        for item in configuration.get("network", {}).get("nodeSubnets", [])
                        if isinstance(item, dict) and item.get("availabilityZone")
                    }
                )
                for group_index, group in enumerate(groups):
                    selected = sorted(set(group.get("instanceTypes", [])))
                    for zone in node_zones:
                        offered = {
                            item.get("InstanceType")
                            for item in ec2.describe_instance_type_offerings(
                                LocationType="availability-zone",
                                Filters=[
                                    {"Name": "location", "Values": [zone]},
                                    {"Name": "instance-type", "Values": selected},
                                ],
                            ).get("InstanceTypeOfferings", [])
                        }
                        if not offered:
                            findings.append(
                                finding(
                                    "INSTANCE_TYPES_NOT_OFFERED_IN_ZONE",
                                    f"{prefix}.nodeGroups.{group_index}.instanceTypes",
                                    f"None of the selected instance types is offered in {zone}.",
                                    "Choose instance types available across every selected node subnet availability zone.",
                                )
                            )
            except Exception:
                findings.append(
                    finding(
                        "INSTANCE_TYPES_UNAVAILABLE",
                        prefix + ".nodeGroups",
                        "One or more selected EC2 instance types could not be verified.",
                        "Select instance types available in the chosen AWS region.",
                    )
                )
        if blueprint.get("endpointAccess") != "PRIVATE":
            findings.append(
                finding(
                    "PUBLIC_ENDPOINT_REVIEW",
                    prefix + ".endpointAccess",
                    "The EKS API endpoint permits public access.",
                    "Use Private only unless an approved exception exists.",
                    severity="WARNING",
                )
            )

    blocking = [item for item in findings if item["severity"] == "BLOCKING"]
    report = {
        "status": "FAILED" if blocking else "PASSED",
        "score": max(0, 100 - len(blocking) * 20 - (len(findings) - len(blocking)) * 5),
        "blockingCount": len(blocking),
        "warningCount": len(findings) - len(blocking),
        "findings": findings,
    }
    report["advisor"] = _advisor(findings, boto3_module)
    return report


def require_ready(configuration, boto3_module=None):
    report = assess_eks_blueprints(configuration, boto3_module)
    if report["status"] != "PASSED":
        raise ApiError(
            422,
            "BLUEPRINT_NOT_READY",
            "The cluster blueprint did not pass provisioning readiness checks.",
            report,
        )
    return report
