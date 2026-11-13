import hashlib
import json
import os
import uuid
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from navigan.shared.errors import ApiError


class Provisioner:
    def __init__(self, s3=None, codebuild=None):
        self.bucket = os.environ.get("TERRAFORM_ARTIFACT_BUCKET", "")
        self.project = os.environ.get("TERRAFORM_CODEBUILD_PROJECT", "")
        self.s3 = s3 or boto3.client("s3")
        self.codebuild = codebuild or boto3.client("codebuild")

    def state_binding(self, cluster):
        kms = os.environ.get("TERRAFORM_STATE_KMS_KEY_ARN", "")
        region = os.environ.get("AWS_REGION", "")
        if not self.bucket or not kms or not region:
            raise ApiError(
                503,
                "PROVISIONER_NOT_CONFIGURED",
                "Terraform state backend is not configured.",
            )
        current = {
            "bucket": self.bucket,
            "key": cluster["terraform_state_key"],
            "region": region,
            "kmsKeyArn": kms,
            "useLockfile": True,
        }
        pinned = (cluster.get("workflow") or {}).get("terraformBackend")
        if not pinned:
            return current
        if pinned.get("key") != cluster["terraform_state_key"]:
            raise ApiError(
                409,
                "TERRAFORM_BACKEND_BINDING_INVALID",
                "The pinned Terraform backend key does not match the cluster state binding.",
            )
        if pinned.get("bucket") != self.bucket:
            raise ApiError(
                409,
                "TERRAFORM_BACKEND_MIGRATION_REQUIRED",
                "The platform Terraform backend changed after this cluster was created. Migrate and rebind the authoritative state before running Terraform.",
            )
        return {
            "bucket": pinned["bucket"],
            "key": pinned["key"],
            "region": pinned.get("region") or region,
            "kmsKeyArn": pinned.get("kmsKeyArn") or kms,
            "useLockfile": True,
        }

    def state_exists(self, cluster):
        state = self.state_binding(cluster)
        try:
            self.s3.head_object(Bucket=state["bucket"], Key=state["key"])
            return True
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
                return False
            raise ApiError(
                502,
                "TERRAFORM_STATE_CHECK_FAILED",
                "Terraform state availability could not be verified.",
            ) from error
        except BotoCoreError as error:
            raise ApiError(
                502,
                "TERRAFORM_STATE_CHECK_FAILED",
                "Terraform state availability could not be verified.",
            ) from error

    def start(self, mode, cluster, environment_snapshot):
        if not self.bucket or not self.project:
            raise ApiError(503, "PROVISIONER_NOT_CONFIGURED", "Terraform runner is not configured.")
        state = self.state_binding(cluster)
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
            "state": state,
            "artifactPrefix": prefix,
            "approvedPlanArtifactKey": (
                cluster.get("plan_artifact_key") if mode == "apply" else None
            ),
            "approvedPlanSha256": (
                cluster.get("plan_sha256") if mode == "apply" else None
            ),
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        kms = state["kmsKeyArn"]
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
