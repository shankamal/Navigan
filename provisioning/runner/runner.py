import hashlib
import json
import os
import pathlib
import subprocess
import time
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

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


def system_node_findings(plan, request):
    """Verify the planned protected pool, including pre-existing no-op groups."""
    resources = {
        change.get("address"): change
        for change in plan.get("resource_changes", [])
        if change.get("type") == "aws_eks_node_group"
        and isinstance(change.get("change", {}).get("after"), dict)
        and "delete" not in change.get("change", {}).get("actions", [])
    }
    findings = []
    for index, group in enumerate(request["configuration"].get("nodeGroups", [])):
        purpose = group.get("purpose", "SYSTEM" if index == 0 else "APPLICATION")
        if purpose != "SYSTEM" or group.get("managementMode", "MANAGED") != "MANAGED":
            continue
        address = 'aws_eks_node_group.this[' + json.dumps(group["name"]) + ']'
        resource = resources.get(address, {})
        planned = resource.get("change", {}).get("after", {})
        labels = planned.get("labels") or {}
        taints = planned.get("taint") or []
        scaling = planned.get("scaling_config") or []
        protected = any(
            taint.get("key") == "navigan.io/system-only"
            and taint.get("value") == "true"
            and taint.get("effect") == "NO_SCHEDULE"
            for taint in taints
        )
        capacity = any(
            isinstance(item.get("min_size"), (int, float))
            and isinstance(item.get("desired_size"), (int, float))
            and item["min_size"] >= 2 and item["desired_size"] >= 2
            for item in scaling
        )
        if not (
            planned.get("node_group_name") == group["name"]
            and labels.get("navigan.io/platform-services") == "true"
            and labels.get("navigan.io/node-purpose") == "system"
            and protected and capacity
        ):
            findings.append({
                "severity": "HIGH",
                "rule": "PROTECTED_SYSTEM_NODE_GROUP",
                "message": "The system node group must have platform-service labels, "
                           "the system-only taint, and minimum/desired capacity of at least two.",
                "resources": [group["name"]],
            })
    return findings


def storage_plan_findings(plan, request):
    """Allow a saved plan to create only the approved storage add-ons."""
    settings = request["configuration"]["ebsCsi"]
    agent_address = 'aws_eks_addon.storage_pod_identity_agent["storage"]'
    driver_address = 'aws_eks_addon.ebs_csi["storage"]'
    expected = {driver_address: ("aws-ebs-csi-driver", settings["addonVersion"])}
    if settings["podIdentityAgentVersion"] is not None:
        expected[agent_address] = ("eks-pod-identity-agent", settings["podIdentityAgentVersion"])
    problems = []
    seen = set()
    if plan.get("errored") or plan.get("complete") is not True or plan.get("action_invocations"):
        problems.append("incomplete or unsupported Terraform plan")
    for resource in plan.get("resource_changes", []):
        change = resource.get("change", {})
        address = resource.get("address", "")
        actions = change.get("actions")
        if resource.get("previous_address") or change.get("importing") or change.get("generated_config"):
            problems.append(address)
            continue
        if address not in expected:
            if actions != ["no-op"] and not (resource.get("mode") == "data" and actions == ["read"]):
                problems.append(address)
            continue
        if address in seen:
            problems.append(address)
        seen.add(address)
        addon, version = expected[address]
        after = change.get("after") or {}
        association = after.get("pod_identity_association") or []
        expected_association = (
            [{"role_arn": settings["controllerRoleArn"], "service_account": "ebs-csi-controller-sa"}]
            if address == driver_address else []
        )
        if (
            resource.get("mode") != "managed"
            or resource.get("type") != "aws_eks_addon"
            or actions not in (["create"], ["no-op"])
            or after.get("cluster_name") != request["clusterName"]
            or after.get("addon_name") != addon
            or after.get("addon_version") != version
            or after.get("resolve_conflicts_on_create") != "NONE"
            or after.get("service_account_role_arn")
            or association != expected_association
        ):
            problems.append(address)
    problems.extend(sorted(expected.keys() - seen))
    return [{
        "severity": "HIGH",
        "rule": "EKS_STORAGE_PLAN_SCOPE",
        "message": "Storage enrollment can only create the approved add-ons on this cluster.",
        "resources": list(dict.fromkeys(problems))[:25],
    }] if problems else []


def security_scan(plan, request):
    if request.get("mode") in {"storage-plan", "storage-apply"}:
        findings = storage_plan_findings(plan, request)
        return {
            "engine": "Navigan Terraform policy checks",
            "status": "FAILED" if findings else "PASSED",
            "blockingFindings": len(findings),
            "findings": findings,
        }
    findings = system_node_findings(plan, request)
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


def addon_configuration_properties(schema, node):
    reference = node.get("$ref", "")
    if reference.startswith("#/"):
        node = schema
        for key in reference[2:].split("/"):
            node = node.get(key, {})
    return node.get("properties", {})


def managed_eks_addon(eks, cluster_name, addon_name):
    try:
        return eks.describe_addon(clusterName=cluster_name, addonName=addon_name)["addon"]
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        return None


def verify_storage_addons_ready(request, eks):
    for name in ("eks-pod-identity-agent", "aws-ebs-csi-driver"):
        addon = managed_eks_addon(eks, request["clusterName"], name)
        if not addon or addon.get("status") != "ACTIVE" or addon.get("health", {}).get("issues"):
            raise ValueError(f"{name} did not report healthy after storage apply.")


def resolve_storage_agent(request, eks, state_addresses):
    settings = request["configuration"]["ebsCsi"]
    cluster = request["clusterName"]
    agent = managed_eks_addon(eks, cluster, "eks-pod-identity-agent")
    driver = managed_eks_addon(eks, cluster, "aws-ebs-csi-driver")
    if driver and 'aws_eks_addon.ebs_csi["storage"]' not in state_addresses:
        raise ValueError("The existing EBS CSI add-on is outside this cluster's Terraform state.")
    agent_managed = 'aws_eks_addon.storage_pod_identity_agent["storage"]' in state_addresses
    if agent and not agent_managed:
        if request["mode"] == "storage-plan":
            settings["podIdentityAgentVersion"] = None
        elif settings["podIdentityAgentVersion"] is not None:
            raise ValueError("An external Pod Identity Agent appeared after planning. Replan storage enrollment.")
    if not agent and settings["podIdentityAgentVersion"] is None:
        raise ValueError("The Pod Identity Agent is absent and no install version was approved.")


def preflight_ebs_csi(request, baseline, clients, account_id):
    ebs_csi = request["configuration"].get("ebsCsi")
    storage_mode = request["mode"] in {"storage-plan", "storage-apply"}
    if ebs_csi is None or request["mode"] not in {"plan", "apply", "storage-plan", "storage-apply"}:
        return
    approved = baseline.get("extensions", {}).get("provisioningContract", {}).get("ebsCsi") or {}
    approved = {**approved, "podIdentityAgentVersion": approved.get("podIdentityAgentVersion")}
    if storage_mode and ebs_csi["podIdentityAgentVersion"] is None:
        approved["podIdentityAgentVersion"] = None
    if ebs_csi != approved:
        raise ValueError("EBS CSI configuration differs from the approved environment.")
    role = ebs_csi["controllerRoleArn"]
    reserved_roles = {baseline["iam"][key]["roleArn"] for key in ("clusterRole", "nodeRole")}
    if f"::{account_id}:role/" not in role or role in reserved_roles | {request["provisioningRoleArn"]}:
        raise ValueError("EBS CSI requires a dedicated controller role in the approved AWS account.")
    observed_role = clients["iam"].get_role(RoleName=role.rsplit("/", 1)[-1])["Role"]["Arn"]
    if observed_role != role:
        raise ValueError("EBS CSI controller IAM role differs from the approved role.")
    if ebs_csi["podIdentityAgentVersion"] is None:
        agent = clients["eks"].describe_addon(
            clusterName=request["clusterName"], addonName="eks-pod-identity-agent",
        )["addon"]
        if agent["status"] != "ACTIVE" or (agent.get("health", {}).get("issues") or []):
            raise ValueError("The existing EKS Pod Identity Agent is not healthy.")
    versions = clients["eks"].get_paginator("describe_addon_versions")
    for addon, version in (
        ("aws-ebs-csi-driver", ebs_csi["addonVersion"]),
        ("eks-pod-identity-agent", ebs_csi["podIdentityAgentVersion"]),
    ):
        if version is None:
            continue
        pages = versions.paginate(addonName=addon, kubernetesVersion=request["configuration"]["kubernetesVersion"])
        if not any(item["addonVersion"] == version for page in pages
                   for found in page["addons"] for item in found["addonVersions"]):
            raise ValueError(f"{addon} has no compatible approved add-on version.")
    schema = json.loads(clients["eks"].describe_addon_configuration(
        addonName="aws-ebs-csi-driver", addonVersion=ebs_csi["addonVersion"],
    )["configurationSchema"])
    controller = addon_configuration_properties(schema, schema).get("controller", {})
    if "tolerations" not in addon_configuration_properties(schema, controller):
        raise ValueError("The approved EBS CSI add-on version cannot tolerate the protected system node taint.")


def preflight(request, baseline, external_id):
    clients = assumed_clients(request, baseline, external_id)
    account_id = clients["sts"].get_caller_identity()["Account"]
    if account_id != baseline["account"]["accountId"]:
        raise ValueError("Provisioning role account does not match the approved environment.")
    if request["mode"] in {"storage-plan", "storage-apply"}:
        eks = clients["eks"]
        cluster = eks.describe_cluster(name=request["clusterName"])["cluster"]
        if (
            cluster.get("status") != "ACTIVE"
            or cluster.get("version") != request["configuration"]["kubernetesVersion"]
            or cluster.get("resourcesVpcConfig", {}).get("vpcId") != baseline["network"]["vpc"]["vpcId"]
            or cluster.get("storageConfig", {}).get("blockStorage", {}).get("enabled") is True
            or cluster.get("computeConfig", {}).get("enabled") is True
        ):
            raise ValueError("Storage enrollment requires the recorded active, standard EKS cluster.")
        addresses = set(subprocess.check_output(["terraform", "state", "list"], cwd=work).decode().splitlines())
        if "aws_eks_cluster.this" not in addresses:
            raise ValueError("The existing cluster is missing from its Terraform state.")
        resolve_storage_agent(request, eks, addresses)
        preflight_ebs_csi(request, baseline, clients, account_id)
        return
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
    preflight_ebs_csi(request, baseline, clients, account_id)
    for key_name in ("nodeVolumeKmsKey", "clusterSecretsKmsKey"):
        key_arn = baseline.get("encryption", {}).get(key_name, {}).get("keyArn")
        if key_arn:
            metadata = clients["kms"].describe_key(KeyId=key_arn)["KeyMetadata"]
            if not metadata.get("Enabled") or metadata.get("KeyUsage") != "ENCRYPT_DECRYPT":
                raise ValueError("Approved KMS key is not enabled for encryption.")


def verify_module_version(request, packaged_version):
    requested_version = request["terraformModuleVersion"]
    ebs_csi_enabled = request["configuration"].get("ebsCsi") is not None
    if ebs_csi_enabled and (requested_version, packaged_version) != ("1.1.0", "1.1.0"):
        raise ValueError("EBS CSI requires EKS Terraform module 1.1.0.")
    if requested_version != packaged_version and (requested_version, packaged_version) != ("1.0.0", "1.1.0"):
        raise ValueError("Requested Terraform module version is not packaged in this runner.")


try:
    request = json.loads(s3.get_object(Bucket=bucket, Key=input_key)["Body"].read())
    if request.get("mode") != mode:
        raise ValueError("Execution mode differs from the recorded Terraform request.")
    normalize_request_identity(request)
    if request["platform"] != "EKS":
        raise ValueError("Only EKS is supported by this runner image.")
    packaged_version = pathlib.Path("/app/module-version").read_text().strip()
    verify_module_version(request, packaged_version)
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
    storage_mode = mode in {"storage-plan", "storage-apply"}
    if storage_mode:
        run("terraform", "init", "-input=false", "-backend-config=backend.hcl")
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
        "ebs_csi": request["configuration"].get("ebsCsi"),
        "tags": {
            **baseline["tags"], **request["configuration"].get("tags", {}),
            "ManagedBy": "Navigan", "NaviganClusterId": request["clusterId"],
        },
    }
    (work / "terraform.tfvars.json").write_text(json.dumps(variables))
    if not storage_mode:
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
    if mode in {"plan", "storage-plan"}:
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
            **({
                "ebsCsi": request["configuration"]["ebsCsi"],
                "storageAddonsToCreate": [
                    item["change"]["after"]["addon_name"] for item in shown.get("resource_changes", [])
                    if item.get("type") == "aws_eks_addon" and item["change"]["actions"] == ["create"]
                ] if scan["status"] == "PASSED" else [],
            } if storage_mode else {}),
        })
    elif mode in {"apply", "storage-apply"}:
        plan_key = request.get("approvedPlanArtifactKey")
        expected = request.get("approvedPlanSha256")
        if not plan_key or not expected:
            raise ValueError("An approved plan artifact and hash are required.")
        plan = s3.get_object(Bucket=bucket, Key=plan_key)["Body"].read()
        if hashlib.sha256(plan).hexdigest() != expected:
            raise ValueError("Approved Terraform plan hash mismatch.")
        (work / "terraform.tfplan").write_bytes(plan)
        shown = run_json("terraform", "show", "-json", "terraform.tfplan")
        if storage_mode and storage_plan_findings(shown, request):
            raise ValueError("Approved plan contains changes outside the EKS storage scope.")
        if not storage_mode and system_node_findings(shown, request):
            raise ValueError("Approved plan does not provision a protected system node group.")
        run("terraform", "apply", "-input=false", "-auto-approve", "terraform.tfplan")
        if storage_mode:
            verify_storage_addons_ready(request, assumed_clients(request, baseline, external_id)["eks"])
            put_result({"success": True, "mode": mode})
        else:
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

