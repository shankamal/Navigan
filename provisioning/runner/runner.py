import hashlib
import json
import os
import pathlib
import subprocess
import sys
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


def put_result(value):
    s3.put_object(
        Bucket=bucket,
        Key=prefix + "/result.json",
        Body=json.dumps(value, sort_keys=True).encode(),
        ServerSideEncryption="aws:kms",
        SSEKMSKeyId=os.environ["TERRAFORM_STATE_KMS_KEY_ARN"],
        ContentType="application/json",
    )


def assumed_clients(request, baseline, external_id):
    credentials = boto3.client("sts").assume_role(
        RoleArn=request["provisioningRoleArn"],
        RoleSessionName="NaviganPreflight-" + request["clusterId"][-20:],
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
    return {name: boto3.client(name, **options) for name in ("sts", "ec2", "iam", "kms")}


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
    })
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
        "\\n".join([
            f'bucket = "{state["bucket"]}"',
            f'key = "{state["key"]}"',
            f'region = "{state["region"]}"',
            f'kms_key_id = "{state["kmsKeyArn"]}"',
            "encrypt = true",
            "use_lockfile = true",
        ]) + "\\n"
    )
    baseline = request["environment"]["configuration"]
    external_id = secrets.get_secret_value(SecretId=request["externalIdSecretArn"])["SecretString"]
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
        "cluster_role_arn": baseline["iam"]["clusterRole"]["roleArn"],
        "node_role_arn": baseline["iam"]["nodeRole"]["roleArn"],
        "node_volume_kms_key_arn": baseline["encryption"]["nodeVolumeKmsKey"]["keyArn"],
        "cluster_secrets_kms_key_arn": (
            baseline.get("encryption", {}).get("clusterSecretsKmsKey", {}).get("keyArn")
        ),
        "node_groups": request["configuration"]["nodeGroups"],
        "tags": {
            **baseline["tags"], **request["configuration"].get("tags", {}),
            "ManagedBy": "Navigan", "NaviganClusterId": request["clusterId"],
        },
    }
    (work / "terraform.tfvars.json").write_text(json.dumps(variables))
    run("terraform", "init", "-input=false", "-backend-config=backend.hcl")
    if mode == "plan":
        run("terraform", "plan", "-input=false", "-out=terraform.tfplan")
        plan = (work / "terraform.tfplan").read_bytes()
        digest = hashlib.sha256(plan).hexdigest()
        shown = json.loads(subprocess.check_output(
            ["terraform", "show", "-json", "terraform.tfplan"], cwd=work
        ))
        actions = {}
        for change in shown.get("resource_changes", []):
            label = "/".join(change.get("change", {}).get("actions", [])) or "no-op"
            actions[label] = actions.get(label, 0) + 1
        s3.put_object(
            Bucket=bucket, Key=prefix + "/terraform.tfplan", Body=plan,
            ServerSideEncryption="aws:kms",
            SSEKMSKeyId=os.environ["TERRAFORM_STATE_KMS_KEY_ARN"],
            Metadata={"sha256": digest},
        )
        put_result({
            "success": True, "mode": mode, "planSha256": digest,
            "planSummary": {"actions": actions, "resourceCount": sum(actions.values())},
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
    else:
        raise ValueError("Unsupported execution mode.")
except Exception as error:
    put_result({"success": False, "mode": mode, "errorCode": type(error).__name__})
    raise
