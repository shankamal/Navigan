#!/usr/bin/env python3
"""Deploy isolated DEV artifact collectors using the existing migration API settings.

The default command reviews repository-worker readiness without modifying AWS.
--repository --apply deploys its dedicated scheduled Lambda. --image --apply
builds/pushes the image collector and deploys a separate private Fargate service.
"""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.request
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = "905418045935"
REGION = "ap-south-1"
STACK = "navigan-ashok-dev"
DATABASE = "navigan_dev"
LABEL = "DEV"
BRANCH = "new_migration_approach_18oct26"
REPOSITORY = "navigan/dev-workspace-image-collector"
HANDLER = "navigan.modules.migration_management.workspace_worker.lambda_handler"
ROLE_PATTERN = r"arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]+"


def collector_source_sha():
    files=sorted((ROOT/'src/navigan').rglob('*.py'))+[ROOT/'src/requirements.txt']
    return hashlib.sha256(b''.join(str(p.relative_to(ROOT)).encode()+b'\0'+p.read_bytes()+b'\0' for p in files)).hexdigest()


def verify_layout_ready(session,parent):
    """Read-only gate: never enable new workspace paths before their writers."""
    def require(condition,message):
        if not condition:raise RuntimeError(message)
    require(parent in {'navigan-ashok-dev','navigan-custmanagement-cfnstk'},'Unexpected workspace environment')
    require(session.client('sts').get_caller_identity()['Account']==ACCOUNT,'Unexpected AWS account')
    cfn=session.client('cloudformation');lam=session.client('lambda');ecs=session.client('ecs');iam=session.client('iam')
    nested=cfn.describe_stack_resource(StackName=parent,LogicalResourceId='MigrationManagement')['StackResourceDetail']['PhysicalResourceId']
    api=cfn.describe_stack_resource(StackName=nested,LogicalResourceId='MigrationFunction')['StackResourceDetail']['PhysicalResourceId']
    def companion(suffix):
        stack=cfn.describe_stacks(StackName=parent+suffix)['Stacks'][0]
        return ({v['OutputKey']:v['OutputValue'] for v in stack.get('Outputs',[])},
                {v['ParameterKey']:v['ParameterValue'] for v in stack.get('Parameters',[])})
    output,_=companion('-workspace-repositories');worker=output['WorkerName']
    require(worker==parent+'-workspace-repositories','Unexpected repository collector')
    configs=[]
    for name in (api,worker):
        response=lam.get_function(FunctionName=name);config=response['Configuration']
        require(config['FunctionArn'].startswith(f'arn:aws:lambda:{REGION}:{ACCOUNT}:function:{parent}-'),'Unexpected Lambda identity')
        with urllib.request.urlopen(response['Code']['Location'],timeout=60) as stream:raw=stream.read()
        require(base64.b64encode(hashlib.sha256(raw).digest()).decode()==config['CodeSha256'],'Lambda checksum mismatch')
        verify_package(raw);configs.append(config)
    env=configs[0]['Environment']['Variables']
    require(all(configs[1]['Environment']['Variables'].get(k)==env.get(k) for k in ('DB_NAME','DB_PROXY_HOST','DB_SECRET_ARN','MIGRATION_WORKSPACE_BUCKET')),'Repository bindings differ from API')
    require(all(sorted(configs[1].get('VpcConfig',{}).get(k,[]))==sorted(configs[0].get('VpcConfig',{}).get(k,[]))
                for k in ('SubnetIds','SecurityGroupIds')),'Repository network differs from API')
    output,params=companion('-workspace-images')
    response=ecs.describe_services(cluster=params['ClusterArn'],services=[output['WorkerServiceName']])
    require(not response.get('failures') and len(response.get('services',[]))==1,'Image collector service missing')
    service=response['services'][0]
    task=ecs.describe_task_definition(taskDefinition=service['taskDefinition'])['taskDefinition']
    containers=[c for c in task['containerDefinitions'] if c['name']=='collector'];require(len(containers)==1,'Unexpected collector task')
    image=containers[0];variables={v['name']:v['value'] for v in image.get('environment',[])}
    require('@sha256:' in image['image'] and variables.get('MIGRATION_COLLECTOR_SOURCE_SHA256')==collector_source_sha(),
            'Rebuild/deploy the image collector from this reviewed source before enabling workspace layout v2')
    require(all(variables.get(k)==env.get(k) for k in ('DB_NAME','DB_PROXY_HOST','DB_SECRET_ARN','MIGRATION_WORKSPACE_BUCKET')),'Image collector bindings differ from API')
    network=service.get('networkConfiguration',{}).get('awsvpcConfiguration',{})
    require(all(sorted(network.get(key,[]))==sorted(configs[0].get('VpcConfig',{}).get(expected_key,[]))
                for key,expected_key in (('subnets','SubnetIds'),('securityGroups','SecurityGroupIds'))),'Image collector network differs from API')
    require(service['desiredCount']==service['runningCount'] and service['pendingCount']==0 and
            len(service.get('deployments',[]))==1 and service['deployments'][0].get('rolloutState')=='COMPLETED','Wait for the collector rollout to complete')
    expected=f"arn:aws:s3:::{env['MIGRATION_WORKSPACE_BUCKET']}/navigan/customers/*/migrations/*/inventories/*/workspaces/*"
    for role,policies in ((configs[0]['Role'],('NaviganMigrationArtifactWorkspace','NaviganMigrationWorkspaceLayoutV2')),
                          (task['taskRoleArn'],('WorkspaceImageCollection',))):
        granted=False
        for policy in policies:
            try:document=iam.get_role_policy(RoleName=role.rsplit('/',1)[1],PolicyName=policy)['PolicyDocument']
            except Exception as error:
                if getattr(error,'response',{}).get('Error',{}).get('Code')=='NoSuchEntity':continue
                raise
            if any(s.get('Effect')=='Allow' and expected in ([s.get('Resource')] if isinstance(s.get('Resource'),str) else s.get('Resource',[]))
                   and any(a in {'s3:PutObject','s3:*','*'} for a in ([s.get('Action')] if isinstance(s.get('Action'),str) else s.get('Action',[])))
                   for s in document.get('Statement',[])):
                granted=True;break
        require(granted,'Deploy layout v2 workspace storage permissions first')


def runtime_settings(config):
    """Copy only runtime settings; never print credentials or unrelated API env."""
    env = config.get("Environment", {}).get("Variables", {})
    if env.get("DB_NAME") != DATABASE:
        raise SystemExit(f"Safety stop: migration API must use {DATABASE}")
    required = ["DB_PROXY_HOST", "DB_SECRET_ARN", "DB_CA_BUNDLE",
                "MIGRATION_WORKSPACE_BUCKET", "MIGRATION_WORKSPACE_KMS_KEY",
                "MIGRATION_WORKSPACE_BUCKET_OWNER"]
    if any(not env.get(key) for key in required):
        raise SystemExit("Deploy workspace storage/API configuration first")
    if env["MIGRATION_WORKSPACE_BUCKET_OWNER"] != ACCOUNT:
        raise SystemExit("Unexpected workspace bucket owner")
    if not config.get("FunctionArn", "").startswith(f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:"):
        raise SystemExit("Unexpected migration API account/region")
    if config.get("Runtime") != "python3.12" or config.get("Architectures", ["x86_64"]) != ["x86_64"]:
        raise SystemExit("Expected the deployed Python 3.12 x86_64 runtime")
    if config.get("State") != "Active" or config.get("LastUpdateStatus") != "Successful":
        raise SystemExit("Wait for the migration API update to complete")
    vpc = config.get("VpcConfig", {})
    if not vpc.get("SubnetIds") or not vpc.get("SecurityGroupIds"):
        raise SystemExit(f"Expected existing private {LABEL} migration network settings")
    optional = ["GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY_SECRET_ARN", "DB_PORT", "MIGRATION_WORKSPACE_LAYOUT_VERSION"]
    return {key: env[key] for key in ["DB_NAME", *required, *optional] if env.get(key)}


def verify_package(content):
    """Use the deployed API ZIP only when its collector implementation is current."""
    with zipfile.ZipFile(io.BytesIO(content)) as package:
        for name in ["workspace_worker.py", "workspace_collection.py", "repository_collector.py",
                     "artifact_workspace.py", "source_authentication.py", "deployment_sources.py",
                     "artifact_recovery.py", "workspace_export.py", "workspace_reuse.py", "image_worker.py"]:
            member = "navigan/modules/migration_management/" + name
            source = ROOT / "src" / member
            if member not in package.namelist() or not source.is_file() or package.read(member) != source.read_bytes():
                raise SystemExit("Migration API collector code differs from checkout; redeploy its migration-only package first")
    if len(content) > 50 * 1024 * 1024:
        raise SystemExit("Repository worker package exceeds the upload limit")


def repository_template(config, env, bucket, object_key, object_version, enabled):
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": f"Isolated {LABEL} repository artifact collector; existing API and connector unchanged",
        "Resources": {
            "WorkerLogs": {"Type": "AWS::Logs::LogGroup", "Properties": {
                "LogGroupName": f"/aws/lambda/{STACK}-workspace-repositories", "RetentionInDays": 14}},
            "Worker": {"Type": "AWS::Lambda::Function", "DependsOn": "WorkerLogs", "Properties": {
                "FunctionName": f"{STACK}-workspace-repositories", "Runtime": "python3.12",
                "Architectures": ["x86_64"], "Handler": HANDLER, "Role": config["Role"],
                "Timeout": 240, "MemorySize": 512, "ReservedConcurrentExecutions": 2,
                "Code": {"S3Bucket": bucket, "S3Key": object_key, "S3ObjectVersion": object_version},
                "Layers": [layer["Arn"] for layer in config.get("Layers", [])],
                "VpcConfig": {key: config["VpcConfig"][key] for key in ["SubnetIds", "SecurityGroupIds"]},
                "Environment": {"Variables": env}}},
            "Poll": {"Type": "AWS::Events::Rule", "Properties": {
                "ScheduleExpression": "rate(1 minute)", "State": "ENABLED" if enabled else "DISABLED",
                "Targets": [{"Arn": {"Fn::GetAtt": ["Worker", "Arn"]}, "Id": "RepositoryCollector"}]}},
            "Invoke": {"Type": "AWS::Lambda::Permission", "Properties": {
                "Action": "lambda:InvokeFunction", "FunctionName": {"Ref": "Worker"},
                "Principal": "events.amazonaws.com", "SourceAccount": ACCOUNT,
                "SourceArn": {"Fn::GetAtt": ["Poll", "Arn"]}}},
        },
        "Outputs": {"WorkerName": {"Value": {"Ref": "Worker"}},
                    "ScheduleName": {"Value": {"Ref": "Poll"}}},
    }


def image_foundation():
    """Dedicated collector build repository, ECS cluster and execution role."""
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Resources": {
            "Repository": {"Type": "AWS::ECR::Repository", "DeletionPolicy": "Retain", "UpdateReplacePolicy": "Retain",
                           "Properties": {"RepositoryName": REPOSITORY, "ImageTagMutability": "IMMUTABLE",
                                          "ImageScanningConfiguration": {"ScanOnPush": True}}},
            "Cluster": {"Type": "AWS::ECS::Cluster"},
            "ExecutionRole": {"Type": "AWS::IAM::Role", "Properties": {
                "AssumeRolePolicyDocument": {"Version": "2012-10-17", "Statement": [{
                    "Effect": "Allow", "Principal": {"Service": "ecs-tasks.amazonaws.com"}, "Action": "sts:AssumeRole"}]},
                "Policies": [{"PolicyName": "CollectorImageAndLogs", "PolicyDocument": {"Version": "2012-10-17", "Statement": [
                    {"Effect": "Allow", "Action": "ecr:GetAuthorizationToken", "Resource": "*"},
                    {"Effect": "Allow", "Action": ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"],
                     "Resource": {"Fn::GetAtt": ["Repository", "Arn"]}},
                    {"Effect": "Allow", "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
                     "Resource": f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:{STACK}-workspace-images-*:*"},
                ]}}]}},
        },
        "Outputs": {"ClusterArn": {"Value": {"Fn::GetAtt": ["Cluster", "Arn"]}},
                    "ExecutionRoleArn": {"Value": {"Fn::GetAtt": ["ExecutionRole", "Arn"]}},
                    "RepositoryUri": {"Value": {"Fn::GetAtt": ["Repository", "RepositoryUri"]}}},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--repository", action="store_true")
    mode.add_argument("--image", action="store_true")
    parser.add_argument("--profile", default="navigan")
    parser.add_argument("--worker-image", help=f"Reuse an existing digest from the dedicated {LABEL} collector repository")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--enable-schedule", action="store_true", help="Run repository collector once per minute")
    parser.add_argument("--start-images", action="store_true", help="Start one image task (default stages service at zero)")
    parser.add_argument("--registry-role-arn", action="append", default=[])
    args = parser.parse_args()
    if (args.enable_schedule and args.image) or (args.start_images and not args.image) or (args.worker_image and not args.image):
        parser.error("Use --enable-schedule with repository mode; --start-images with image mode")
    if args.worker_image and not re.fullmatch(
        rf"{ACCOUNT}\.dkr\.ecr\.{REGION}\.amazonaws\.com/{REPOSITORY}@sha256:[a-f0-9]{{64}}", args.worker_image
    ):
        parser.error(f"Use an immutable digest from the dedicated {LABEL} image collector repository")
    if any(not re.fullmatch(ROLE_PATTERN, role) for role in args.registry_role_arn):
        parser.error("Registry roles must be exact IAM role ARNs")
    command = ["aws", "--profile", args.profile, "--region", REGION, "--output", "json"]

    def aws(*parts):
        result = subprocess.check_output([*command, *parts], text=True)
        return json.loads(result) if result.strip() else {}

    def deploy(template, stack_name, directory, parameters=None):
        path = directory / (stack_name + ".json")
        path.write_text(json.dumps(template))
        invocation = [*command, "cloudformation", "deploy", "--stack-name", stack_name,
                      "--template-file", str(path), "--capabilities", "CAPABILITY_IAM", "--no-fail-on-empty-changeset"]
        if parameters:
            invocation.extend(["--parameter-overrides", *[f"{key}={value}" for key, value in parameters.items()]])
        subprocess.check_call(invocation)
        return {item["OutputKey"]: item["OutputValue"] for item in
                aws("cloudformation", "describe-stacks", "--stack-name", stack_name)["Stacks"][0].get("Outputs", [])}

    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch not in {BRANCH, "main", "fix/prod-migration-collection"}:
        raise SystemExit("Use a reviewed release checkout")
    if aws("sts", "get-caller-identity")["Account"] != ACCOUNT:
        raise SystemExit("Unexpected AWS account")
    stack = aws("cloudformation", "describe-stacks", "--stack-name", STACK)["Stacks"][0]
    nested = next(item["OutputValue"] for item in stack["Outputs"] if item["OutputKey"] == "MigrationManagementStackId")
    if not nested.startswith(f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/"):
        raise SystemExit("Unexpected migration nested stack")
    function = aws("cloudformation", "describe-stack-resource", "--stack-name", nested,
                   "--logical-resource-id", "MigrationFunction")["StackResourceDetail"]["PhysicalResourceId"]
    deployed = aws("lambda", "get-function", "--function-name", function)
    config = deployed["Configuration"]
    env = runtime_settings(config)
    parent_params = {item["ParameterKey"]: item["ParameterValue"] for item in stack.get("Parameters", [])}
    allowed = json.loads(config.get("Environment", {}).get("Variables", {}).get("SOURCE_REGISTRY_ALLOWED_ROLE_ARNS", "[]"))
    if not isinstance(allowed, list) or any(not isinstance(role, str) or not re.fullmatch(ROLE_PATTERN, role) for role in allowed):
        raise SystemExit("Existing registry role allowlist is invalid")
    roles = sorted(set(allowed + args.registry_role_arn))
    print(f"{LABEL} {'image' if args.image else 'repository'} collector: {DATABASE}; existing API/connector will not be updated")
    print("Using the migration API's existing subnets, security groups and workspace storage")
    if args.image:
        if not parent_params.get("SecretsKmsKeyArn"):
            raise SystemExit(f"{LABEL} stack SecretsKmsKeyArn is required")
        if not args.worker_image:
            subprocess.check_call(["docker", "info"], stdout=subprocess.DEVNULL)
        print(f"Build target: {REPOSITORY}; private service desired count: {1 if args.start_images else 0}")
        print(f"Explicit registry pull roles: {len(roles)}; source-role trust must include the new worker task role")
    else:
        package = urllib.request.urlopen(deployed["Code"]["Location"], timeout=60).read()
        verify_package(package)
        print(f"Repository schedule: {'ENABLED' if args.enable_schedule else 'DISABLED'}")
    if not args.apply:
        print("Readiness review complete; no AWS resources modified. Add --apply to deploy")
        return
    with tempfile.TemporaryDirectory(prefix="navigan-workspace-workers-") as temporary:
        directory = Path(temporary)
        directory.chmod(0o700)
        if not args.image:
            sha = hashlib.sha256(package).hexdigest()
            package_path = directory / "repository-worker.zip"
            package_path.write_bytes(package)
            key = f"deployment-packages/repository-worker/{sha}.zip"
            uploaded = aws("s3api", "put-object", "--bucket", env["MIGRATION_WORKSPACE_BUCKET"],
                           "--key", key, "--body", str(package_path), "--expected-bucket-owner", ACCOUNT,
                           "--server-side-encryption", "aws:kms", "--ssekms-key-id", env["MIGRATION_WORKSPACE_KMS_KEY"])
            if not uploaded.get("VersionId"):
                raise SystemExit("Versioned worker package upload required")
            outputs = deploy(repository_template(config, env, env["MIGRATION_WORKSPACE_BUCKET"], key,
                             uploaded["VersionId"], args.enable_schedule), STACK + "-workspace-repositories", directory)
            print("Repository collector deployed: " + outputs["WorkerName"])
            print("In the UI, click Collect / retry repository files, then Refresh workspaces after a minute")
        else:
            foundation = deploy(image_foundation(), STACK + "-workspace-image-runtime", directory)
            expected_repository = f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/{REPOSITORY}"
            if foundation.get("RepositoryUri") != expected_repository:
                raise SystemExit("Unexpected collector repository; image deployment stopped")
            registry = foundation["RepositoryUri"].split("/")[0]
            worker_image = args.worker_image
            source_sha = ""
            if not worker_image:
                source_sha = collector_source_sha()
                docker_env = {**os.environ, "DOCKER_CONFIG": str(directory / "docker-auth")}
                password = subprocess.check_output([*command, "ecr", "get-login-password"], text=True)
                subprocess.run(["docker", "login", "--username", "AWS", "--password-stdin", registry],
                               input=password, text=True, check=True, env=docker_env)
                del password
                tag = "build-" + uuid.uuid4().hex
                image = foundation["RepositoryUri"] + ":" + tag
                subprocess.check_call(["docker", "build", "--platform", "linux/amd64", "--label", "io.navigan.collector.source.sha256="+source_sha, "-f", "workspace_image_worker/Dockerfile", "-t", image, "."], cwd=ROOT, env=docker_env)
                try:
                    subprocess.check_call(["docker", "push", image], env=docker_env, timeout=600)
                except subprocess.TimeoutExpired:
                    raise SystemExit(f"Docker push exceeded 10 minutes. Local image retained: {image}. Finish its push, then resume using --worker-image with the ECR digest.") from None
                digest = aws("ecr", "describe-images", "--repository-name", REPOSITORY,
                             "--image-ids", "imageTag=" + tag)["imageDetails"][0]["imageDigest"]
                if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
                    raise SystemExit("Expected immutable worker image digest")
                worker_image = foundation["RepositoryUri"] + "@" + digest
            print("WorkerImage: " + worker_image)
            parameters = dict(ClusterArn=foundation["ClusterArn"], ExecutionRoleArn=foundation["ExecutionRoleArn"],
                WorkerImage=worker_image,
                SubnetIds=",".join(config["VpcConfig"]["SubnetIds"]), SecurityGroupIds=",".join(config["VpcConfig"]["SecurityGroupIds"]),
                DatabaseProxyHost=env["DB_PROXY_HOST"], DatabaseName=DATABASE, DatabaseSecretArn=env["DB_SECRET_ARN"],
                CollectionLayoutVersion=env.get("MIGRATION_WORKSPACE_LAYOUT_VERSION", "1"),
                CollectionSourceSha=source_sha,
                SecretsKmsKeyArn=parent_params["SecretsKmsKeyArn"], WorkspaceBucketName=env["MIGRATION_WORKSPACE_BUCKET"],
                WorkspaceBucketOwner=ACCOUNT, WorkspaceKmsKeyArn=env["MIGRATION_WORKSPACE_KMS_KEY"],
                AllowedRegistryRoleArns=",".join(roles), DesiredCount=str(1 if args.start_images else 0))
            # CLI deploy accepts YAML directly; do not parse CloudFormation intrinsic tags locally.
            invocation = [*command, "cloudformation", "deploy", "--stack-name", STACK + "-workspace-images",
                "--template-file", str(ROOT / "infrastructure/modules/migration-management/image-collector-service.yaml"),
                "--capabilities", "CAPABILITY_IAM", "--no-fail-on-empty-changeset", "--parameter-overrides",
                *[f"{key}={value}" for key, value in parameters.items()]]
            subprocess.check_call(invocation)
            outputs = aws("cloudformation", "describe-stacks", "--stack-name", STACK + "-workspace-images")["Stacks"][0]["Outputs"]
            for item in outputs:
                print(item["OutputKey"] + ": " + item["OutputValue"])
            print(f"Image service deployed with desired count {1 if args.start_images else 0}. Check source-role trust and private network access before queuing collection")


if __name__ == "__main__":
    main()
