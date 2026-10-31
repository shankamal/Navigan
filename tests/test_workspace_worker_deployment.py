"""DEV worker rollout boundaries; no live AWS or Docker operations."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("worker_deploy", ROOT / "scripts/deploy-workspace-workers-dev.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def configuration():
    return dict(FunctionArn=f"arn:aws:lambda:{module.REGION}:{module.ACCOUNT}:function:dev",
                Role=f"arn:aws:iam::{module.ACCOUNT}:role/dev-migration", Runtime="python3.12", State="Active",
                LastUpdateStatus="Successful", VpcConfig=dict(SubnetIds=["subnet-private"], SecurityGroupIds=["sg-db"]),
                Layers=[{"Arn": "arn:aws:lambda:ap-south-1:905418045935:layer:ca:1"}],
                Environment={"Variables": dict(DB_NAME="navigan_dev", DB_PROXY_HOST="db", DB_SECRET_ARN="secret",
                    DB_CA_BUNDLE="/opt/certs/global-bundle.pem", MIGRATION_WORKSPACE_BUCKET="private-workspace",
                    MIGRATION_WORKSPACE_KMS_KEY="key", MIGRATION_WORKSPACE_BUCKET_OWNER=module.ACCOUNT,
                    GITHUB_APP_ID="app", UNRELATED_TOKEN="must-not-copy")})


def test_runtime_copies_only_required_settings():
    env = module.runtime_settings(configuration())
    assert env["DB_NAME"] == "navigan_dev"
    assert env["GITHUB_APP_ID"] == "app"
    assert "UNRELATED_TOKEN" not in env


@pytest.mark.parametrize("mutation", ["prod", "owner", "region", "network", "updating", "storage"])
def test_invalid_runtime_stops_before_writes(mutation):
    config = configuration()
    if mutation == "prod": config["Environment"]["Variables"]["DB_NAME"] = "navigan"
    if mutation == "owner": config["Environment"]["Variables"]["MIGRATION_WORKSPACE_BUCKET_OWNER"] = "111111111111"
    if mutation == "region": config["FunctionArn"] = "arn:aws:lambda:us-east-1:111111111111:function:prod"
    if mutation == "network": config["VpcConfig"] = {}
    if mutation == "updating": config["LastUpdateStatus"] = "InProgress"
    if mutation == "storage": del config["Environment"]["Variables"]["MIGRATION_WORKSPACE_BUCKET"]
    with pytest.raises(SystemExit): module.runtime_settings(config)


def test_repository_stack_is_separate_and_reuses_only_runtime_dependencies():
    config = configuration()
    for enabled in (False, True):
        template = module.repository_template(config, module.runtime_settings(config), "bucket", "key", "version", enabled)
        resources = template["Resources"]
        assert {r["Type"] for r in resources.values()} == {"AWS::Lambda::Function", "AWS::Logs::LogGroup", "AWS::Events::Rule", "AWS::Lambda::Permission"}
        worker = resources["Worker"]["Properties"]
        assert worker["Handler"] == module.HANDLER
        assert worker["Timeout"] == 240
        assert worker["Code"]["S3ObjectVersion"] == "version"
        assert worker["VpcConfig"] == config["VpcConfig"]
        assert worker["Role"] == config["Role"]
        assert resources["Poll"]["Properties"]["State"] == ("ENABLED" if enabled else "DISABLED")
        assert resources["Invoke"]["Properties"]["SourceAccount"] == module.ACCOUNT


def test_image_foundation_has_exact_repository_pull_scope_and_retention():
    resources = module.image_foundation()["Resources"]
    assert resources["Repository"]["Properties"]["ImageTagMutability"] == "IMMUTABLE"
    assert resources["Repository"]["DeletionPolicy"] == "Retain"
    statements = resources["ExecutionRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    assert statements[0]["Action"] == "ecr:GetAuthorizationToken"
    assert statements[1]["Resource"] == {"Fn::GetAtt": ["Repository", "Arn"]}
    assert "secretsmanager:GetSecretValue" not in str(statements)


def test_stale_deployed_worker_package_is_rejected():
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as package:
        package.writestr("navigan/modules/migration_management/workspace_worker.py", "old implementation")
    with pytest.raises(SystemExit, match="differs from checkout"):
        module.verify_package(content.getvalue())


def layout_gate_fixture(monkeypatch,change=None):
    import base64
    import hashlib
    parent='navigan-custmanagement-cfnstk';api=parent+'-MigrationFunction-demo';worker=parent+'-workspace-repositories'
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as package:
        for path in (ROOT/'src/navigan/modules/migration_management').glob('*.py'):
            package.writestr('navigan/modules/migration_management/'+path.name,path.read_bytes())
    raw=buffer.getvalue();cfg=configuration();cfg['Role']=f'arn:aws:iam::{module.ACCOUNT}:role/ProdApiRole'
    cfg['Environment']['Variables']['DB_NAME']='navigan'
    cfg['CodeSha256']=base64.b64encode(hashlib.sha256(raw).digest()).decode()
    configs={}
    for name in (api,worker):
        configs[name]=copy.deepcopy(cfg);configs[name]['FunctionArn']=f'arn:aws:lambda:{module.REGION}:{module.ACCOUNT}:function:'+name
    if change=='repository-binding':configs[worker]['Environment']['Variables']['DB_PROXY_HOST']='stale-db'
    if change=='repository-network':configs[worker]['VpcConfig']['SubnetIds']=['other-subnet']
    cfn,lam,ecs,iam,sts=(__import__('unittest.mock',fromlist=['Mock']).Mock() for _ in range(5))
    sts.get_caller_identity.return_value={'Account':module.ACCOUNT}
    cfn.describe_stack_resource.side_effect=lambda **kw:{'StackResourceDetail':{'PhysicalResourceId':'nested' if kw['LogicalResourceId']=='MigrationManagement' else api}}
    def stacks(**kw):
        outputs=({'WorkerName':worker} if kw['StackName'].endswith('workspace-repositories') else {'WorkerServiceName':'image-service'})
        return {'Stacks':[{'Outputs':[{'OutputKey':k,'OutputValue':v} for k,v in outputs.items()],
                           'Parameters':[{'ParameterKey':'ClusterArn','ParameterValue':'cluster'}]}]}
    cfn.describe_stacks.side_effect=stacks
    lam.get_function.side_effect=lambda **kw:{'Configuration':configs[kw['FunctionName']],'Code':{'Location':'https://packages/'+kw['FunctionName']}}
    service={'taskDefinition':'task','desiredCount':1,'runningCount':1,'pendingCount':0,'deployments':[{'rolloutState':'COMPLETED'}],
        'networkConfiguration':{'awsvpcConfiguration':{'subnets':['subnet-private'],'securityGroups':['sg-db']}}}
    if change=='image-network':service['networkConfiguration']['awsvpcConfiguration']['subnets']=['other']
    if change=='rollout':service['deployments'][0]['rolloutState']='IN_PROGRESS'
    ecs.describe_services.return_value={'services':[service]}
    variables={**cfg['Environment']['Variables'],'MIGRATION_COLLECTOR_SOURCE_SHA256':module.collector_source_sha()}
    if change=='old-image':variables['MIGRATION_COLLECTOR_SOURCE_SHA256']='0'*64
    ecs.describe_task_definition.return_value={'taskDefinition':{'taskRoleArn':f'arn:aws:iam::{module.ACCOUNT}:role/image-worker',
        'containerDefinitions':[{'name':'collector','image':'repository@sha256:'+'a'*64,
                                'environment':[{'name':k,'value':v} for k,v in variables.items()]}]}}
    resource='arn:aws:s3:::private-workspace/navigan/customers/*/migrations/*/inventories/*/workspaces/*'
    iam.get_role_policy.return_value={'PolicyDocument':{'Statement':[{'Effect':'Allow','Action':['s3:PutObject'],'Resource':[resource]}]}}
    if change=='storage':iam.get_role_policy.return_value={'PolicyDocument':{'Statement':[]}}
    def download(url,**kw):
        if change=='worker-package' and url.endswith(worker):return io.BytesIO(b'wrong-package')
        return io.BytesIO(raw)
    monkeypatch.setattr(module.urllib.request,'urlopen',download)
    clients={'cloudformation':cfn,'lambda':lam,'ecs':ecs,'iam':iam,'sts':sts}
    sdk=__import__('types').SimpleNamespace(client=lambda name:clients[name])
    return sdk,parent,clients


def test_layout_gate_reads_only_and_accepts_consistent_upgraded_collectors(monkeypatch):
    sdk,parent,clients=layout_gate_fixture(monkeypatch)
    module.verify_layout_ready(sdk,parent)
    assert all(call[0].startswith(('get_','describe_')) for client in clients.values() for call in client.method_calls)


@pytest.mark.parametrize('change',['repository-binding','repository-network','image-network','old-image','rollout','storage','worker-package'])
def test_layout_gate_blocks_new_paths_when_a_writer_is_not_ready(monkeypatch,change):
    sdk,parent,_=layout_gate_fixture(monkeypatch,change)
    with pytest.raises((RuntimeError,SystemExit)):module.verify_layout_ready(sdk,parent)


def test_repository_review_is_read_only_and_does_not_require_docker(monkeypatch):
    config = configuration()
    writes = []
    monkeypatch.setattr(sys, "argv", ["deploy", "--repository", "--enable-schedule"])
    monkeypatch.setattr(module, "verify_package", lambda content: None)
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(b"package"))
    def output(command, **kwargs):
        if command[0] == "git": return module.BRANCH
        assert command[0] == "aws"
        if "get-caller-identity" in command: return json.dumps({"Account": module.ACCOUNT})
        if "describe-stacks" in command: return json.dumps({"Stacks": [{"Outputs": [{"OutputKey": "MigrationManagementStackId", "OutputValue": f"arn:aws:cloudformation:{module.REGION}:{module.ACCOUNT}:stack/dev/id"}]}]})
        if "describe-stack-resource" in command: return json.dumps({"StackResourceDetail": {"PhysicalResourceId": "dev-migration"}})
        if "get-function" in command: return json.dumps({"Configuration": config, "Code": {"Location": "https://lambda.example/package"}})
        pytest.fail(f"Unexpected API operation: {command}")
    monkeypatch.setattr(module.subprocess, "check_output", output)
    monkeypatch.setattr(module.subprocess, "check_call", lambda command, **kwargs: writes.append(command))
    module.main()
    assert writes == []


def test_image_mode_rejects_non_dev_image_before_any_aws_call(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["deploy", "--image", "--worker-image", "external.example/worker:latest"])
    monkeypatch.setattr(module.subprocess, "check_output", lambda *args, **kwargs: pytest.fail("Unexpected AWS call"))
    with pytest.raises(SystemExit): module.main()


def test_repository_apply_updates_only_new_stack_with_versioned_encrypted_code(monkeypatch):
    config = configuration()
    calls = []
    templates = []
    monkeypatch.setattr(sys, "argv", ["deploy", "--repository", "--enable-schedule", "--apply"])
    monkeypatch.setattr(module, "verify_package", lambda content: None)
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(b"package"))
    def output(command, **kwargs):
        calls.append(command)
        if command[0] == "git": return module.BRANCH
        if "get-caller-identity" in command: return json.dumps({"Account": module.ACCOUNT})
        if "describe-stacks" in command:
            name = command[command.index("--stack-name") + 1]
            outputs = ([{"OutputKey": "MigrationManagementStackId", "OutputValue": f"arn:aws:cloudformation:{module.REGION}:{module.ACCOUNT}:stack/dev/id"}]
                       if name == module.STACK else [{"OutputKey": "WorkerName", "OutputValue": "new-worker"}])
            return json.dumps({"Stacks": [{"Outputs": outputs}]})
        if "describe-stack-resource" in command: return json.dumps({"StackResourceDetail": {"PhysicalResourceId": "dev-migration"}})
        if "get-function" in command: return json.dumps({"Configuration": config, "Code": {"Location": "https://lambda.example/package"}})
        if "put-object" in command:
            assert command[command.index("--server-side-encryption") + 1] == "aws:kms"
            assert command[command.index("--expected-bucket-owner") + 1] == module.ACCOUNT
            return json.dumps({"VersionId": "stored-version"})
        pytest.fail(f"Unexpected operation: {command}")
    def apply(command, **kwargs):
        calls.append(command)
        assert command[command.index("--stack-name") + 1] == module.STACK + "-workspace-repositories"
        templates.append(json.loads(Path(command[command.index("--template-file") + 1]).read_text()))
    monkeypatch.setattr(module.subprocess, "check_output", output)
    monkeypatch.setattr(module.subprocess, "check_call", apply)
    module.main()
    assert len(templates) == 1
    assert templates[0]["Resources"]["Worker"]["Properties"]["Code"]["S3ObjectVersion"] == "stored-version"
    assert not any("update-function-code" in call or "update-function-configuration" in call for call in calls)


def test_image_apply_reuses_digest_and_stages_service_at_zero(monkeypatch):
    config = configuration()
    image = f"{module.ACCOUNT}.dkr.ecr.{module.REGION}.amazonaws.com/{module.REPOSITORY}@sha256:" + "a" * 64
    monkeypatch.setattr(sys, "argv", ["deploy", "--image", "--worker-image", image, "--apply"])
    deployments = []
    def output(command, **kwargs):
        if command[0] == "git": return module.BRANCH
        assert command[0] == "aws", "Reusing a digest must not build or authenticate Docker"
        if "get-caller-identity" in command: return json.dumps({"Account": module.ACCOUNT})
        if "describe-stack-resource" in command: return json.dumps({"StackResourceDetail": {"PhysicalResourceId": "api"}})
        if "get-function" in command: return json.dumps({"Configuration": config})
        if "describe-stacks" in command:
            name = command[command.index("--stack-name") + 1]
            if name == module.STACK:
                return json.dumps({"Stacks": [{"Outputs": [{"OutputKey": "MigrationManagementStackId", "OutputValue": f"arn:aws:cloudformation:{module.REGION}:{module.ACCOUNT}:stack/dev/id"}], "Parameters": [{"ParameterKey": "SecretsKmsKeyArn", "ParameterValue": "secrets-key"}]}]})
            values = {"ClusterArn": "new-cluster", "ExecutionRoleArn": "new-execution-role", "RepositoryUri": image.split("@")[0]} if name.endswith("-image-runtime") else {"WorkerTaskRoleArn": "new-task-role"}
            return json.dumps({"Stacks": [{"Outputs": [{"OutputKey": key, "OutputValue": value} for key, value in values.items()]}]})
        pytest.fail(f"Unexpected AWS operation: {command}")
    def apply(command, **kwargs):
        assert command[0] == "aws"
        assert "cloudformation" in command and "deploy" in command
        deployments.append(command)
    monkeypatch.setattr(module.subprocess, "check_output", output)
    monkeypatch.setattr(module.subprocess, "check_call", apply)
    module.main()
    assert len(deployments) == 2
    params = deployments[1][deployments[1].index("--parameter-overrides") + 1:]
    assert "DesiredCount=0" in params
    assert "DatabaseName=navigan_dev" in params
    assert "WorkerImage=" + image in params
    assert "ClusterArn=new-cluster" in params
