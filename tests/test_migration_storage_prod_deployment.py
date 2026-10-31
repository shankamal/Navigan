"""Production release boundaries: read-only preflight, scoped changes, private storage."""
import importlib.util
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace

from botocore.exceptions import ClientError, WaiterError
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("prod_storage", ROOT / "scripts/deploy-migration-storage-prod.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def configuration():
    return {"FunctionArn": f"arn:aws:lambda:{release.REGION}:{release.ACCOUNT}:function:{release.PARENT}-MigrationFunction-example",
            "State": "Active", "LastUpdateStatus": "Successful", "RevisionId": "revision",
            "Role": f"arn:aws:iam::{release.ACCOUNT}:role/path/ProductionMigrationRole",
            "Environment": {"Variables": {"DB_NAME": "navigan"}}}


class PreflightCFN:
    def describe_stacks(self, **kwargs):
        return {"Stacks": [{"StackStatus": "UPDATE_COMPLETE", "Parameters": [
            {"ParameterKey": "DatabaseName", "ParameterValue": "navigan"},
            {"ParameterKey": "ApiDatabaseSecretArn", "ParameterValue": "secret-reference"}]}]}

    def describe_stack_resource(self, **kwargs):
        resource = (f"arn:aws:cloudformation:{release.REGION}:{release.ACCOUNT}:stack/{release.PARENT}-MigrationManagement-example/id"
                    if kwargs["LogicalResourceId"] == "MigrationManagement" else "prod-migration")
        return {"StackResourceDetail": {"PhysicalResourceId": resource}}


class DataAPI:
    def __init__(self, missing=False, grants=True):
        self.calls = []
        self.missing = missing
        self.grants = grants

    def execute_statement(self, **kwargs):
        self.calls.append(kwargs)
        assert kwargs["database"] == "navigan"
        assert kwargs["sql"].startswith("SELECT ")
        if "current_database" in kwargs["sql"]:
            row = {"database_name": "navigan", **{t: None if self.missing else t for t in release.TABLES}}
        else:
            row = {"runtime_grants": self.grants}
        return {"formattedRecords": json.dumps([row])}


def session(config=None, data=None, account=release.ACCOUNT):
    config = config or configuration()
    def missing_policy(**kwargs):
        raise ClientError({'Error':{'Code':'NoSuchEntity'}},'GetRolePolicy')
    clients = {
        "sts": SimpleNamespace(get_caller_identity=lambda: {"Account": account}),
        "cloudformation": PreflightCFN(),
        "lambda": SimpleNamespace(get_function_configuration=lambda **kw: config),
        "rds": SimpleNamespace(describe_db_clusters=lambda **kw: {"DBClusters": [{
            "DBClusterArn": f"arn:aws:rds:{release.REGION}:{release.ACCOUNT}:cluster:aws-infra-platform-db",
            "HttpEndpointEnabled": True}]}),
        "rds-data": data or DataAPI(),
        "iam":SimpleNamespace(get_role_policy=missing_policy),
    }
    return SimpleNamespace(client=lambda service, **kw: clients[service])


def test_preflight_verifies_prod_identity_tables_and_each_grant():
    data = DataAPI()
    settings = release.preflight(session(data=data))
    assert settings["role"] == "ProductionMigrationRole"
    assert len(data.calls) == 2
    for table in release.TABLES:
        assert table in data.calls[0]["sql"]
        for privilege in ("SELECT", "INSERT", "UPDATE"):
            assert f"has_table_privilege('navigan_api', 'migration_management.{table}', '{privilege}')" in data.calls[1]["sql"]


@pytest.mark.parametrize("options,message", [({"missing": True}, "tables are missing"),
                                             ({"grants": False}, "grants are missing")])
def test_preflight_blocks_incomplete_schema(options, message):
    with pytest.raises(RuntimeError, match=message):
        release.preflight(session(data=DataAPI(**options)))


@pytest.mark.parametrize("field,value,message", [
    ("State", "Pending", "become stable"), ("LastUpdateStatus", "Failed", "become stable"),
    ("Role", "arn:aws:iam::000000000000:role/dev", "API role"),
    ("FunctionArn", "arn:aws:lambda:ap-south-1:905418045935:function:navigan-ashok-dev", "production Lambda"),
    ("Environment", {"Variables": {"DB_NAME": "navigan_dev"}}, "PROD database"),
])
def test_preflight_rejects_wrong_or_unstable_runtime(field, value, message):
    config = configuration()
    config[field] = value
    with pytest.raises(RuntimeError, match=message):
        release.preflight(session(config=config))


def test_wrong_account_stops_before_other_aws_calls():
    fake = SimpleNamespace(client=lambda name: SimpleNamespace(get_caller_identity=lambda: {"Account": "other"})
                           if name == "sts" else pytest.fail("Unexpected AWS lookup"))
    with pytest.raises(RuntimeError, match="AWS account"):
        release.preflight(fake)


def change(action="Add", logical="WorkspaceBucket", kind="AWS::S3::Bucket", replacement="False"):
    return {"ResourceChange": {"Action": action, "LogicalResourceId": logical,
                              "ResourceType": kind, "Replacement": replacement}}


@pytest.mark.parametrize("item", [change("Remove"), change("Import"), change(replacement="True"),
    change(replacement="Conditional"), change(logical="MigrationFunction", kind="AWS::Lambda::Function"),
    change(kind="AWS::IAM::Role"), change(logical="UnrelatedNestedStack", kind="AWS::CloudFormation::Stack")])
def test_change_set_rejects_destructive_or_unrelated_changes(item):
    with pytest.raises(RuntimeError):
        release.validate_changes([item], release.SPECS["artifact-workspace"]["resources"])


def test_allowed_additions_and_nonreplacement_updates():
    release.validate_changes([change(), change("Modify")], release.SPECS["artifact-workspace"]["resources"])


class ChangeCFN:
    def __init__(self, existing=None, changes=None, no_changes=False):
        self.existing = existing
        self.changes = changes if changes is not None else [change()]
        self.no_changes = no_changes
        self.request = None
        self.executed = []

    def describe_stacks(self, **kwargs):
        if self.existing:
            return {"Stacks": [self.existing]}
        raise ClientError({"Error": {"Code": "ValidationError", "Message": "Stack does not exist"}}, "DescribeStacks")

    def get_template(self, **kwargs):
        return {"TemplateBody": {"Resources": {}}}

    def create_change_set(self, **kwargs):
        self.request = kwargs
        return {"Id": "change-set"}

    def get_waiter(self, name):
        def wait(**kwargs):
            if self.no_changes and name == "change_set_create_complete":
                raise WaiterError(name=name, reason="failed", last_response={})
        return SimpleNamespace(wait=wait)

    def describe_change_set(self, **kwargs):
        if self.no_changes:
            return {"Status": "FAILED", "StatusReason": "The submitted information didn't contain changes."}
        return {"Changes": self.changes}

    def execute_change_set(self, **kwargs):
        self.executed.append(kwargs)


def existing(status="UPDATE_COMPLETE", role="ProductionMigrationRole"):
    return {"StackStatus": status, "Parameters": [{"ParameterKey": "MigrationFunctionRoleName", "ParameterValue": role}]}


def test_storage_preparation_uses_only_prod_role_and_does_not_execute(tmp_path):
    cfn = ChangeCFN()
    plan = release.change_set(cfn, release.PARENT + "-artifact-workspace", release.SPECS["artifact-workspace"],
                              "template", "ProductionMigrationRole", tmp_path)
    assert plan["create"] is True and not cfn.executed
    assert cfn.request["ChangeSetType"] == "CREATE"
    assert cfn.request["Parameters"] == [{"ParameterKey": "MigrationFunctionRoleName", "ParameterValue": "ProductionMigrationRole"}]
    assert cfn.request["StackName"] != release.PARENT


def test_storage_resume_unexecuted_create(tmp_path):
    cfn = ChangeCFN(existing=existing("REVIEW_IN_PROGRESS"))
    release.change_set(cfn, "stack", release.SPECS["artifact-workspace"], "template", "ProductionMigrationRole", tmp_path)
    assert cfn.request["ChangeSetType"] == "CREATE"


def test_storage_noop_update_is_idempotent(tmp_path):
    cfn = ChangeCFN(existing=existing(), no_changes=True)
    assert release.change_set(cfn, "stack", release.SPECS["artifact-workspace"], "template", "ProductionMigrationRole", tmp_path) is None
    assert not cfn.executed


def test_existing_stack_cannot_grant_access_to_another_role(tmp_path):
    cfn = ChangeCFN(existing=existing(role="DevRole"))
    with pytest.raises(RuntimeError, match="different role"):
        release.change_set(cfn, "stack", release.SPECS["artifact-workspace"], "template", "ProductionMigrationRole", tmp_path)
    assert cfn.request is None and not cfn.executed


def test_default_main_is_read_only(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["release"])
    monkeypatch.setattr(release, "check_checkout", lambda: None)
    monkeypatch.setattr(release.boto3, "Session", lambda **kw: session())
    monkeypatch.setattr(release, "change_set", lambda *a: pytest.fail("Mutated AWS in read-only mode"))
    assert release.main() == 0


def test_unsafe_plan_cannot_execute(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["release", "--apply"])
    monkeypatch.setattr(release, "check_checkout", lambda: None)
    monkeypatch.setattr(release.boto3, "Session", lambda **kw: session())
    monkeypatch.setattr(release.tempfile, "mkdtemp", lambda **kw: str(tmp_path))
    def prepare(*args):
        raise RuntimeError("plan unsafe")
    monkeypatch.setattr(release, "change_set", prepare)
    monkeypatch.setattr(release, "execute", lambda *a: pytest.fail("Executed before plan validated"))
    with pytest.raises(RuntimeError, match="plan unsafe"):
        release.main()


def test_storage_verification_rejects_public_bucket():
    cfn = SimpleNamespace(describe_stacks=lambda **kw: {"Stacks": [{"StackStatus": "CREATE_COMPLETE", "Outputs": [
        {"OutputKey": "WorkspaceBucketName", "OutputValue": "private-bucket"}]}]})
    s3 = SimpleNamespace(head_bucket=lambda **kw: None, get_public_access_block=lambda **kw: {
        "PublicAccessBlockConfiguration": {"BlockPublicAcls": False}})
    fake = SimpleNamespace(client=lambda name: cfn if name == "cloudformation" else s3)
    with pytest.raises(RuntimeError, match="public-access"):
        release.verify_storage(fake, "artifact-workspace")


def test_apply_provisions_only_one_workspace_stack(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["release", "--apply"])
    monkeypatch.setattr(release, "check_checkout", lambda: None)
    monkeypatch.setattr(release.boto3, "Session", lambda **kw: session())
    monkeypatch.setattr(release.tempfile, "mkdtemp", lambda **kw: str(tmp_path))
    prepared, executed, verified = [], [], []
    def prepare(cfn, stack, spec, template, role, directory):
        prepared.append(stack)
        assert "RecoveryBucket" not in template
        assert "WorkspaceBucket" in template
        return {"id": "workspace"}
    monkeypatch.setattr(release, "change_set", prepare)
    monkeypatch.setattr(release, "execute", lambda cfn, plan: executed.append(plan["id"]))
    monkeypatch.setattr(release, "verify_storage", lambda session, suffix: verified.append(suffix) or {})
    assert release.main() == 0
    assert prepared == [release.PARENT + "-artifact-workspace"]
    assert executed == ["workspace"]
    assert verified == ["artifact-workspace"]


def test_legacy_recovery_storage_is_outside_release_scope():
    with pytest.raises(RuntimeError, match="release scope"):
        release.verify_storage(None, "source-recovery")


def deployed_template():
    return {'Parameters':{'MigrationFunctionRoleName':{'Type':'String'}},
        'Resources':{
            'WorkspaceBucket':{'Type':'AWS::S3::Bucket','DeletionPolicy':'Retain',
                'Properties':{'BucketName':'existing-bucket','VersioningConfiguration':{'Status':'Enabled'},
                              'Tags':[{'Key':'preserve-live-setting','Value':'unchanged'}]}},
            'WorkspaceKey':{'Type':'AWS::KMS::Key','Properties':{'EnableKeyRotation':True}},
            'WorkspaceBucketPolicy':{'Type':'AWS::S3::BucketPolicy','Properties':{'Bucket':{'Ref':'WorkspaceBucket'},
                'PolicyDocument':{'Statement':[{'Sid':'PreserveDeployedPolicy'}]}}},
            'WorkspaceStoragePolicy':{'Type':'AWS::IAM::Policy','Properties':{'PolicyName':'existing-policy','Roles':['ProductionMigrationRole']}}},
        'Outputs':{'KeepOutput':{'Value':{'Fn::GetAtt':['WorkspaceBucket','Arn']}}}}


def test_existing_json_template_only_gains_layout_policy_without_bucket_changes():
    original=deployed_template();before=copy.deepcopy(original)
    candidate=json.loads(release.policy_only_template(original))
    assert original==before
    assert set(candidate['Resources'])==set(original['Resources'])|{release.LAYOUT_POLICY}
    assert candidate['Resources'].pop(release.LAYOUT_POLICY)==release.layout_policy()
    assert candidate==original
    assert json.loads(release.policy_only_template(json.dumps(original)))['Resources'][release.LAYOUT_POLICY]==release.layout_policy()


def test_existing_yaml_is_preserved_outside_one_additive_json_flow_resource():
    original="""AWSTemplateFormatVersion: '2010-09-09'
Resources:
    WorkspaceBucket:
        Type: AWS::S3::Bucket
        DeletionPolicy: Retain
    WorkspaceStoragePolicy:
        Type: AWS::IAM::Policy
        Properties:
            Roles: [!Ref MigrationFunctionRoleName]
Outputs:
    Arn:
        Value: !GetAtt WorkspaceBucket.Arn
"""
    candidate=release.policy_only_template(original)
    added=[line for line in candidate.splitlines(keepends=True) if line.startswith('    '+release.LAYOUT_POLICY+':')]
    assert len(added)==1 and candidate.replace(added[0],'',1)==original
    assert json.loads(added[0].split(':',1)[1])==release.layout_policy()
    assert release.policy_only_template(candidate)==candidate


def test_layout_policy_name_collision_is_rejected():
    original=deployed_template();original['Resources'][release.LAYOUT_POLICY]={'Type':'AWS::IAM::Role'}
    with pytest.raises(RuntimeError,match='differs'):release.policy_only_template(original)


@pytest.mark.parametrize('logical,kind',[('WorkspaceBucket','AWS::S3::Bucket'),('WorkspaceBucketPolicy','AWS::S3::BucketPolicy'),('WorkspaceKey','AWS::KMS::Key')])
def test_existing_storage_update_cannot_modify_bucket_bucket_policy_or_key(tmp_path,logical,kind):
    cfn=ChangeCFN(existing=existing(),changes=[change('Modify',logical,kind)])
    cfn.get_template=lambda **kw:{'TemplateBody':deployed_template()}
    with pytest.raises(RuntimeError,match='Unexpected resource'):
        release.change_set(cfn,'stack',release.SPECS['artifact-workspace'],'unused-local-template','ProductionMigrationRole',tmp_path)
    assert cfn.executed==[]


def test_existing_storage_update_preserves_deployed_resources_and_rechecks_policy_scope(tmp_path):
    cfn=ChangeCFN(existing=existing('UPDATE_ROLLBACK_COMPLETE'),changes=[change('Add',release.LAYOUT_POLICY,'AWS::IAM::Policy')])
    cfn.get_template=lambda **kw:{'TemplateBody':deployed_template()}
    plan=release.change_set(cfn,'stack',release.SPECS['artifact-workspace'],'unused-local-template','ProductionMigrationRole',tmp_path)
    assert plan['policyOnly'] is True
    candidate=json.loads(cfn.request['TemplateBody']);candidate['Resources'].pop(release.LAYOUT_POLICY)
    assert candidate==deployed_template()
    cfn.changes=[change('Modify','WorkspaceBucket','AWS::S3::Bucket')]
    with pytest.raises(RuntimeError,match='Unexpected resource'):release.execute(cfn,plan)
    assert cfn.executed==[]


def test_waiter_failure_prints_actual_resource_reason_without_repeating_traceback(capsys):
    cfn=ChangeCFN()
    def waiter(name):
        def wait(**kwargs):raise WaiterError(name=name,reason='rollback',last_response={})
        return SimpleNamespace(wait=wait)
    cfn.get_waiter=waiter
    cfn.describe_stack_events=lambda **kw:{'StackEvents':[{'LogicalResourceId':'WorkspaceBucket','ResourceStatus':'UPDATE_FAILED','ResourceStatusReason':'Specific AWS failure reason'}]}
    with pytest.raises(RuntimeError,match='did not complete'):release.execute(cfn,{'id':'change-set','stack':'stack','create':False})
    assert 'WorkspaceBucket: Specific AWS failure reason' in capsys.readouterr().out


def test_unmanaged_layout_policy_name_is_not_overwritten():
    def missing_resource(**kwargs):raise ClientError({'Error':{'Code':'ValidationError'}},'DescribeStackResource')
    clients={'iam':SimpleNamespace(get_role_policy=lambda **kw:{'PolicyDocument':release.layout_policy()['Properties']['PolicyDocument']}),
             'cloudformation':SimpleNamespace(describe_stack_resource=missing_resource)}
    with pytest.raises(RuntimeError,match='outside this storage stack'):
        release.verify_layout_policy_ownership(SimpleNamespace(client=lambda name:clients[name]),'stack','role')
