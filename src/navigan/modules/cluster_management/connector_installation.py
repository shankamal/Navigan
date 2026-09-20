"""Server-side orchestration for private-cluster connector installation."""
import json
import os

import boto3
from botocore.config import Config

from navigan.shared.errors import ApiError


class ConnectorInstaller:
    """Place the credential in the customer account and start its private installer.

    The one-time credential is never returned to a UI and is never passed as a
    CodeBuild environment variable. The customer-side build receives only the
    Secrets Manager ARN and fetches the value using its own execution role.
    """

    def __init__(self, sts=None, secrets=None, client_factory=None):
        self.sts = sts or boto3.client("sts")
        self.secrets = secrets or boto3.client("secretsmanager")
        self.client_factory = client_factory or boto3.client

    def start(
        self,
        cluster,
        environment_snapshot,
        connector_id,
        token,
        system_repository,
    ):
        configuration = environment_snapshot.get("configuration") or {}
        account_id = cluster["provisioning_role_arn"].split(":")[4]
        partition = cluster["provisioning_role_arn"].split(":")[1]
        installer = configuration.get("connectorInstaller") or {}
        project_name = installer.get("projectName") or "NaviganClusterInstaller"
        service_role_arn = installer.get("serviceRoleArn") or (
            f"arn:{partition}:iam::{account_id}:role/NaviganClusterInstallerRole"
        )
        connector_image = os.environ.get("CONNECTOR_IMAGE_URI", "")
        api_base_url = os.environ.get("CONNECTOR_API_BASE_URL", "")
        tools_base_url = os.environ.get("PLATFORM_TOOLS_BASE_URL", "")
        if not connector_image or not api_base_url:
            raise ApiError(
                409,
                "CONNECTOR_INSTALLER_NOT_CONFIGURED",
                "Connector deployment artifacts are not configured for this Navigan environment.",
            )

        external_id = self.secrets.get_secret_value(
            SecretId=cluster["external_id_secret_arn"]
        )["SecretString"]
        credentials = self.sts.assume_role(
            RoleArn=cluster["provisioning_role_arn"],
            RoleSessionName=f"NaviganConnector-{cluster['cluster_id'][-20:]}"[:64],
            ExternalId=external_id,
            DurationSeconds=1800,
        )["Credentials"]
        options = {
            "region_name": configuration["location"]["region"],
            "aws_access_key_id": credentials["AccessKeyId"],
            "aws_secret_access_key": credentials["SecretAccessKey"],
            "aws_session_token": credentials["SessionToken"],
            "config": Config(retries={"mode": "standard", "max_attempts": 8}),
        }
        customer_secrets = self.client_factory("secretsmanager", **options)
        customer_codebuild = self.client_factory("codebuild", **options)
        customer_eks = self.client_factory("eks", **options)
        self._ensure_cluster_access(
            customer_eks,
            cluster["cluster_name"],
            service_role_arn,
            partition,
            cluster["cluster_id"],
        )
        secret_name = (
            f"navigan/connectors/{cluster['cluster_id']}/{connector_id}"
        )
        bootstrap_credentials = {
            "connectorToken": token,
            "githubToken": system_repository["token"],
            "githubTokenExpiresAt": system_repository.get("tokenExpiresAt"),
        }
        secret = customer_secrets.create_secret(
            Name=secret_name,
            Description="Navigan private cluster connector credential",
            SecretString=json.dumps(
                bootstrap_credentials, sort_keys=True, separators=(",", ":")
            ),
            Tags=[
                {"Key": "ManagedBy", "Value": "Navigan"},
                {"Key": "NaviganClusterId", "Value": cluster["cluster_id"]},
                {"Key": "NaviganConnectorId", "Value": connector_id},
            ],
        )
        payload = {
            "schemaVersion": "1.0",
            "clusterId": cluster["cluster_id"],
            "clusterName": cluster["cluster_name"],
            "connectorId": connector_id,
            "connectorSecretArn": secret["ARN"],
            "connectorImage": connector_image,
            "apiBaseUrl": api_base_url,
            "toolsBaseUrl": tools_base_url,
            "serviceRoleArn": service_role_arn,
            "systemRepositoryUrl": system_repository["url"],
            "systemRepositoryRevision": system_repository["revision"],
            "systemRepositoryCommit": system_repository["commit"],
        }
        try:
            build = customer_codebuild.start_build(
                projectName=project_name,
                environmentVariablesOverride=[
                    {
                        "name": "NAVIGAN_CONNECTOR_INSTALLATION",
                        "value": json.dumps(
                            payload, sort_keys=True, separators=(",", ":")
                        ),
                        "type": "PLAINTEXT",
                    }
                ],
            )["build"]
        except Exception:
            customer_secrets.delete_secret(
                SecretId=secret["ARN"], ForceDeleteWithoutRecovery=True
            )
            raise
        return {
            "executionId": build["id"],
            "secretArn": secret["ARN"],
            "status": "RUNNING",
        }

    @staticmethod
    def _ensure_cluster_access(
        eks, cluster_name, role_arn, partition, cluster_id
    ):
        try:
            eks.describe_access_entry(
                clusterName=cluster_name, principalArn=role_arn
            )
        except eks.exceptions.ResourceNotFoundException:
            eks.create_access_entry(
                clusterName=cluster_name,
                principalArn=role_arn,
                type="STANDARD",
                tags={
                    "ManagedBy": "Navigan",
                    "NaviganClusterId": cluster_id,
                },
            )
        policy_arn = (
            f"arn:{partition}:eks::aws:cluster-access-policy/"
            "AmazonEKSClusterAdminPolicy"
        )
        associated = eks.list_associated_access_policies(
            clusterName=cluster_name, principalArn=role_arn
        ).get("associatedAccessPolicies", [])
        if not any(item.get("policyArn") == policy_arn for item in associated):
            eks.associate_access_policy(
                clusterName=cluster_name,
                principalArn=role_arn,
                policyArn=policy_arn,
                accessScope={"type": "cluster"},
            )
