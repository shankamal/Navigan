import hashlib
import json
import os
import pathlib
import subprocess
import time
import boto3
from botocore.config import Config

bucket = os.environ["TERRAFORM_ARTIFACT_BUCKET"]
input_key = os.environ["NAVIGAN_INPUT_KEY"]
prefix = os.environ["NAVIGAN_ARTIFACT_PREFIX"]
mode = os.environ["NAVIGAN_MODE"]
s3 = boto3.client("s3")
secrets = boto3.client("secretsmanager")
work = pathlib.Path("/workspace")
work.mkdir(exist_ok=True)


def run(*args):
    subprocess.run(args, cwd=work, check=True)


def run_json(*args):
    return json.loads(subprocess.check_output(args, cwd=work))


def security_scan(plan, request):
    findings = []
    configuration = request["configuration"]
    if configuration.get("endpointAccess") != "PRIVATE":
        findings.append({
            "severity": "HIGH",
            "rule": "EKS_PRIVATE_ENDPOINT",
            "message": "The Kubernetes API endpoint must use private-only access.",
        })
    destructive = []
    for resource in plan.get("resource_changes", []):
        actions = resource.get("change", {}).get("actions", [])
        if "delete" in actions:
            destructive.append(resource.get("address", "unknown"))
    migration = configuration.get("systemNodeGroupMigration") or {}
    legacy_name = migration.get("legacyNodeGroupName")
    allowed_destructive = {
        f'aws_eks_node_group.this["{legacy_name}"]',
        f'aws_launch_template.node["{legacy_name}"]',
    } if legacy_name else set()
    unexpected_destructive = [
        address for address in destructive if address not in allowed_destructive
    ]
    if unexpected_destructive:
        findings.append({
            "severity": "HIGH",
            "rule": "NO_DESTRUCTIVE_CHANGES",
            "message": "The plan contains destructive resource changes.",
            "resources": unexpected_destructive[:25],
        })
    if destructive and set(destructive) != allowed_destructive:
        findings.append({
            "severity": "HIGH",
            "rule": "SYSTEM_NODE_GROUP_MIGRATION_SCOPE",
            "message": "The migration must retire exactly the legacy node group and its launch template.",
            "resources": destructive[:25],
        })
    return {
        "engine": "Navigan Terraform policy checks",
        "status": "PASSED" if not findings else "FAILED",
        "blockingFindings": len(findings),
        "findings": findings,
    }


def put_result(value):
    s3.put_object(
        Bucket=bucket,
        Key=prefix + "/result.json",
        Body=json.dumps(value, sort_keys=True).encode(),
        ServerSideEncryption="aws:kms",
        SSEKMSKeyId=os.environ["TERRAFORM_STATE_KMS_KEY_ARN"],
        ContentType="application/json",
    )


def normalize_request_identity(request):
    """Support pre-upgrade requests while preserving tenant-bound execution."""
    artifact_prefix = request.get("artifactPrefix") or prefix
    parts = artifact_prefix.split("/")
    if len(parts) != 4 or parts[0] != "executions":
        raise ValueError("Execution artifact prefix is invalid.")
    prefix_customer_id, prefix_cluster_id = parts[1], parts[2]
    customer_id = request.get("customerId") or prefix_customer_id
    cluster_id = request.get("clusterId") or prefix_cluster_id
    if customer_id != prefix_customer_id or cluster_id != prefix_cluster_id:
        raise ValueError("Request identity does not match its immutable artifact prefix.")
    request["customerId"] = customer_id
    request["clusterId"] = cluster_id


def assumed_clients(request, baseline, external_id):
    customer_suffix = request["customerId"][-20:]
    cluster_suffix = request["clusterId"][-20:]
    credentials = boto3.client("sts").assume_role(
        RoleArn=request["provisioningRoleArn"],
        RoleSessionName=f"Navigan-{customer_suffix}-{cluster_suffix}"[:64],
        ExternalId=external_id,
        DurationSeconds=3600,
    )["Credentials"]
    options = {
        "region_name": baseline["location"]["region"],
        "aws_access_key_id": credentials["AccessKeyId"],
        "aws_secret_access_key": credentials["SecretAccessKey"],
        "aws_session_token": credentials["SessionToken"],
        "config": Config(retries={"mode": "standard", "max_attempts": 8}),
    }
    return {
        name: boto3.client(name, **options)
        for name in ("sts", "ec2", "iam", "kms", "eks")
    }


def preflight(request, baseline, external_id):
    clients = assumed_clients(request, baseline, external_id)
    account_id = clients["sts"].get_caller_identity()["Account"]
    if account_id != baseline["account"]["accountId"]:
        raise ValueError("Provisioning role account does not match the approved environment.")
    network = baseline["network"]
    subnet_refs = network["clusterSubnets"] + network["nodeSubnets"]
    subnet_ids = sorted({item["subnetId"] for item in subnet_refs})
    subnets = clients["ec2"].describe_subnets(SubnetIds=subnet_ids)["Subnets"]
    if len(subnets) != len(subnet_ids):
        raise ValueError("One or more approved subnets no longer exist.")
    vpc_id = network["vpc"]["vpcId"]
    if any(item["VpcId"] != vpc_id for item in subnets):
        raise ValueError("Approved subnets are not in the approved VPC.")
    node_ids = {item["subnetId"] for item in network["nodeSubnets"]}
    node_azs = {item["AvailabilityZone"] for item in subnets if item["SubnetId"] in node_ids}
    if len(node_azs) < 2:
        raise ValueError("Managed nodes require approved subnets in at least two availability zones.")
    security = baseline["security"]
    group_ids = sorted({
        item["securityGroupId"]
        for item in security["clusterSecurityGroups"] + security["nodeSecurityGroups"]
    } | {
        baseline.get("connectorInstaller", {}).get("securityGroupId")
    } - {None})
    groups = clients["ec2"].describe_security_groups(GroupIds=group_ids)["SecurityGroups"]
    if len(groups) != len(group_ids) or any(item["VpcId"] != vpc_id for item in groups):
        raise ValueError("Approved security groups are unavailable or belong to another VPC.")
    for role in (baseline["iam"]["clusterRole"]["roleArn"], baseline["iam"]["nodeRole"]["roleArn"]):
        clients["iam"].get_role(RoleName=role.rsplit("/", 1)[-1])
    for key_name in ("nodeVolumeKmsKey", "clusterSecretsKmsKey"):
        key_arn = baseline.get("encryption", {}).get(key_name, {}).get("keyArn")
        if key_arn:
            metadata = clients["kms"].describe_key(KeyId=key_arn)["KeyMetadata"]
            if not metadata.get("Enabled") or metadata.get("KeyUsage") != "ENCRYPT_DECRYPT":
                raise ValueError("Approved KMS key is not enabled for encryption.")


try:
    request = json.loads(s3.get_object(Bucket=bucket, Key=input_key)["Body"].read())
    normalize_request_identity(request)
    if request["platform"] != "EKS":
        raise ValueError("Only EKS is supported by this runner image.")
    packaged_version = pathlib.Path("/app/module-version").read_text().strip()
    if request["terraformModuleVersion"] != packaged_version:
        raise ValueError("Requested Terraform module version is not packaged in this runner.")
    source = pathlib.Path("/app/modules/aws-eks")
    for item in source.iterdir():
        (work / item.name).write_bytes(item.read_bytes())
    state = request["state"]
    (work / "backend.hcl").write_text(
        "\n".join([
            f'bucket = "{state["bucket"]}"',
            f'key = "{state["key"]}"',
            f'region = "{state["region"]}"',
            f'kms_key_id = "{state["kmsKeyArn"]}"',
            "encrypt = true",
            "use_lockfile = true",
        ]) + "\n"
    )
    baseline = request["environment"]["configuration"]
    external_id = secrets.get_secret_value(SecretId=request["externalIdSecretArn"])["SecretString"]
    # Destruction must remain possible when the original environment resources
    # are degraded or superseded. Terraform state and the recorded provider
    # identity are authoritative for decommissioning.
    if mode != "delete":
        preflight(request, baseline, external_id)
    variables = {
        "region": baseline["location"]["region"],
        "provisioning_role_arn": request["provisioningRoleArn"],
        "external_id": external_id,
        "cluster_name": request["clusterName"],
        "kubernetes_version": request["configuration"]["kubernetesVersion"],
        "endpoint_access": request["configuration"]["endpointAccess"],
        "vpc_id": baseline["network"]["vpc"]["vpcId"],
        "cluster_subnet_ids": [x["subnetId"] for x in baseline["network"]["clusterSubnets"]],
        "node_subnet_ids": [x["subnetId"] for x in baseline["network"]["nodeSubnets"]],
        "cluster_security_group_ids": [
            x["securityGroupId"] for x in baseline["security"]["clusterSecurityGroups"]
        ],
        "node_security_group_ids": [
            x["securityGroupId"] for x in baseline["security"]["nodeSecurityGroups"]
        ],
        "installer_security_group_id": (
            baseline.get("connectorInstaller", {}).get("securityGroupId")
        ),
        "cluster_role_arn": baseline["iam"]["clusterRole"]["roleArn"],
        "node_role_arn": baseline["iam"]["nodeRole"]["roleArn"],
        "node_volume_kms_key_arn": baseline["encryption"]["nodeVolumeKmsKey"]["keyArn"],
        "cluster_secrets_kms_key_arn": (
            baseline.get("encryption", {}).get("clusterSecretsKmsKey", {}).get("keyArn")
        ),
        "node_groups": [
            {
                **group,
                "purpose": group.get(
                    "purpose", "SYSTEM" if index == 0 else "APPLICATION"
                ),
            }
            for index, group in enumerate(request["configuration"]["nodeGroups"])
        ],
        "tags": {
            **baseline["tags"], **request["configuration"].get("tags", {}),
            "ManagedBy": "Navigan", "NaviganClusterId": request["clusterId"],
        },
    }
    (work / "terraform.tfvars.json").write_text(json.dumps(variables))
    run("terraform", "init", "-input=false", "-backend-config=backend.hcl")
    run("terraform", "fmt", "-check", "-recursive")
    validation = run_json("terraform", "validate", "-json")
    if not validation.get("valid"):
        put_result({
            "success": False,
            "mode": mode,
            "errorCode": "TerraformValidationFailed",
            "validation": validation,
        })
        raise ValueError("Terraform configuration validation failed.")
    if mode == "plan":
        run("terraform", "plan", "-input=false", "-out=terraform.tfplan")
        plan = (work / "terraform.tfplan").read_bytes()
        digest = hashlib.sha256(plan).hexdigest()
        shown = run_json("terraform", "show", "-json", "terraform.tfplan")
        actions = {}
        for change in shown.get("resource_changes", []):
            label = "/".join(change.get("change", {}).get("actions", [])) or "no-op"
            actions[label] = actions.get(label, 0) + 1
        scan = security_scan(shown, request)
        certification = {
            "status": (
                "PASSED"
                if validation.get("valid") and scan["status"] == "PASSED"
                else "FAILED"
            ),
            "terraformValidated": bool(validation.get("valid")),
            "securityChecksPassed": scan["status"] == "PASSED",
            "planSha256": digest,
        }
        s3.put_object(
            Bucket=bucket, Key=prefix + "/terraform.tfplan", Body=plan,
            ServerSideEncryption="aws:kms",
            SSEKMSKeyId=os.environ["TERRAFORM_STATE_KMS_KEY_ARN"],
            Metadata={"sha256": digest},
        )
        put_result({
            "success": True, "mode": mode, "planSha256": digest,
            "planSummary": {"actions": actions, "resourceCount": sum(actions.values())},
            "validation": {
                "valid": bool(validation.get("valid")),
                "errorCount": validation.get("error_count", 0),
                "warningCount": validation.get("warning_count", 0),
            },
            "securityScan": scan,
            "certification": certification,
        })
    elif mode == "apply":
        plan_key = request.get("approvedPlanArtifactKey")
        expected = request.get("approvedPlanSha256")
        if not plan_key or not expected:
            raise ValueError("An approved plan artifact and hash are required.")
        plan = s3.get_object(Bucket=bucket, Key=plan_key)["Body"].read()
        if hashlib.sha256(plan).hexdigest() != expected:
            raise ValueError("Approved Terraform plan hash mismatch.")
        (work / "terraform.tfplan").write_bytes(plan)
        run("terraform", "apply", "-input=false", "-auto-approve", "terraform.tfplan")
        raw = subprocess.check_output(["terraform", "output", "-json"], cwd=work)
        put_result({"success": True, "mode": mode, "outputs": json.loads(raw)})
    elif mode in {"stop", "start"}:
        clients = assumed_clients(request, baseline, external_id)
        updates = []
        for group in request["configuration"]["nodeGroups"]:
            scaling = (
                {"minSize": 0, "desiredSize": 0, "maxSize": group["maxSize"]}
                if mode == "stop"
                else {
                    "minSize": group["minSize"],
                    "desiredSize": group["desiredSize"],
                    "maxSize": group["maxSize"],
                }
            )
            response = clients["eks"].update_nodegroup_config(
                clusterName=request["clusterName"],
                nodegroupName=group["name"],
                scalingConfig=scaling,
            )
            update_id = response["update"]["id"]
            for _ in range(120):
                update = clients["eks"].describe_update(
                    name=request["clusterName"],
                    nodegroupName=group["name"],
                    updateId=update_id,
                )["update"]
                if update["status"] == "Successful":
                    break
                if update["status"] in {"Failed", "Cancelled"}:
                    errors = ", ".join(
                        item.get("errorCode", "UnknownError")
                        for item in update.get("errors", [])
                    )
                    raise RuntimeError(
                        f"EKS node group {mode} update {update['status']}: "
                        f"{errors or 'No error code returned'}"
                    )
                time.sleep(30)
            else:
                raise TimeoutError(
                    f"EKS node group {mode} update did not finish within 60 minutes."
                )
            updates.append({"nodeGroup": group["name"], "updateId": update_id})
        put_result({"success": True, "mode": mode, "nodeGroupUpdates": updates})
    elif mode == "delete":
        run("terraform", "destroy", "-input=false", "-auto-approve")
        put_result({"success": True, "mode": mode})
    else:
        raise ValueError("Unsupported execution mode.")
except Exception as error:
    put_result({"success": False, "mode": mode, "errorCode": type(error).__name__})
    raise
