import hashlib
import json
import os
import uuid
import boto3
from navigan.shared.errors import ApiError


class Provisioner:
    def __init__(self, s3=None, codebuild=None):
        self.bucket = os.environ.get("TERRAFORM_ARTIFACT_BUCKET", "")
        self.project = os.environ.get("TERRAFORM_CODEBUILD_PROJECT", "")
        self.s3 = s3 or boto3.client("s3")
        self.codebuild = codebuild or boto3.client("codebuild")

    def start(self, mode, cluster, environment_snapshot):
        if not self.bucket or not self.project:
            raise ApiError(503, "PROVISIONER_NOT_CONFIGURED", "Terraform runner is not configured.")
        execution_id = str(uuid.uuid4())
        prefix = f"executions/{cluster['customer_id']}/{cluster['cluster_id']}/{execution_id}"
        payload = {
            "schemaVersion": "1.0",
            "mode": mode,
            "executionId": execution_id,
            "customerId": cluster["customer_id"],
            "clusterId": cluster["cluster_id"],
            "environmentId": cluster["environment_id"],
            "environmentApprovedVersion": cluster["environment_approved_version"],
            "platform": cluster["platform"],
            "clusterName": cluster["cluster_name"],
            "configuration": cluster["configuration"],
            "environment": environment_snapshot,
            "provisioningRoleArn": cluster["provisioning_role_arn"],
            "externalIdSecretArn": cluster["external_id_secret_arn"],
            "terraformModuleVersion": cluster["terraform_module_version"],
            "state": {
                "bucket": self.bucket,
                "key": cluster["terraform_state_key"],
                "region": os.environ.get("AWS_REGION", ""),
                "kmsKeyArn": os.environ.get("TERRAFORM_STATE_KMS_KEY_ARN", ""),
                "useLockfile": True,
            },
            "artifactPrefix": prefix,
            "approvedPlanArtifactKey": cluster.get("plan_artifact_key"),
            "approvedPlanSha256": cluster.get("plan_sha256"),
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        kms = os.environ.get("TERRAFORM_STATE_KMS_KEY_ARN")
        if not kms:
            raise ApiError(503, "PROVISIONER_NOT_CONFIGURED", "Terraform state KMS key is not configured.")
        self.s3.put_object(
            Bucket=self.bucket,
            Key=prefix + "/input.json",
            Body=raw,
            ServerSideEncryption="aws:kms",
            SSEKMSKeyId=kms,
            ContentType="application/json",
            Metadata={"sha256": hashlib.sha256(raw).hexdigest()},
        )
        result = self.codebuild.start_build(
            projectName=self.project,
            environmentVariablesOverride=[
                {"name": "NAVIGAN_MODE", "value": mode, "type": "PLAINTEXT"},
                {"name": "NAVIGAN_INPUT_KEY", "value": prefix + "/input.json", "type": "PLAINTEXT"},
                {"name": "NAVIGAN_ARTIFACT_PREFIX", "value": prefix, "type": "PLAINTEXT"},
            ],
        )
        return result["build"]["id"], prefix
