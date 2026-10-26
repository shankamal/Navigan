import ast
import base64
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('runtime_binding_test', ROOT / 'scripts/verify-sam-runtime-bindings.py')
helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)


def fixture(tmp_path):
    private = tmp_path / 'capture'; directory = tmp_path / 'release'
    def write(path, data):
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(data))
    code = b'approved-zip-bytes'; digest = base64.b64encode(hashlib.sha256(code).digest()).decode()
    role = {'RoleName': 'example-role', 'Arn': 'arn:aws:iam::000000000001:role/example-role',
        'AssumeRolePolicyDocument': {'Version': '2012-10-17', 'Statement': []}}
    policy = {'Version': '2012-10-17', 'Statement': [{'Effect': 'Allow', 'Action': 's3:GetObject', 'Resource': 'arn:aws:s3:::example/*'}]}
    template = {'Resources': {
        'Role': {'Type': 'AWS::IAM::Role', 'Properties': {'AssumeRolePolicyDocument': role['AssumeRolePolicyDocument'],
            'Policies': [{'PolicyName': 'Read', 'PolicyDocument': copy.deepcopy(policy)}]}},
        'Function': {'Type': 'AWS::Lambda::Function', 'Properties': {'Role': {'Fn::GetAtt': ['Role', 'Arn']},
            'Handler': 'main.handler', 'Runtime': 'python3.12', 'Timeout': 3, 'MemorySize': 128,
            'Environment': {'Variables': {'PRIVATE_SETTING': 'do-not-print'}}, 'Code': {'S3Bucket': 'example', 'S3Key': 'zip'}}}}}
    record = {'description': {'StackId': 'arn:aws:cloudformation:us-east-1:000000000001:stack/example/id'},
        'templates': {'Processed': copy.deepcopy(template)}, 'resources': [
            {'LogicalResourceId': 'Role', 'ResourceType': 'AWS::IAM::Role', 'PhysicalResourceId': 'example-role'},
            {'LogicalResourceId': 'Function', 'ResourceType': 'AWS::Lambda::Function', 'PhysicalResourceId': 'example-function'}]}
    write(private / 'stacks/root.json', record)
    write(directory / 'root/review-evidence/changes.json', {'StackId': record['description']['StackId'], 'ChangeSetId': 'change-set'})
    write(directory / 'templates/code-locks.json', {'root--Function': {'CodeSha256': digest, 'RevisionId': 'revision'}})
    cfg = {'FunctionName': 'example-function', 'CodeSha256': digest, 'RevisionId': 'revision',
        'State': 'Active', 'LastUpdateStatus': 'Successful',
        'Role': role['Arn'], 'Handler': 'main.handler', 'Runtime': 'python3.12', 'Timeout': 3, 'MemorySize': 128,
        'Environment': {'Variables': {'PRIVATE_SETTING': 'do-not-print'}}}
    uploads = {'body': code}
    clients = {
        'cloudformation': SimpleNamespace(get_template=lambda **kw: {'TemplateBody': template},
            describe_stacks=lambda **kw: {'Stacks': [{'StackStatus': 'UPDATE_COMPLETE', 'Parameters': []}]}),
        'iam': SimpleNamespace(get_role=lambda **kw: {'Role': role},
            get_role_policy=lambda **kw: {'PolicyDocument': policy},
            get_paginator=lambda name: SimpleNamespace(paginate=lambda **kw: [
                {'PolicyNames': ['Read']} if name == 'list_role_policies' else {'AttachedPolicies': []}])),
        'lambda': SimpleNamespace(get_function_configuration=lambda **kw: cfg, get_function_concurrency=lambda **kw: {}),
        's3': SimpleNamespace(get_object=lambda **kw: {'Body': io.BytesIO(uploads['body'])}),
    }
    session = SimpleNamespace(region_name='us-east-1', client=lambda name: clients[name])
    return session, directory, private, template, cfg, policy, uploads


def test_proposed_bindings_and_uploaded_zip_match_live_without_exposing_values(tmp_path):
    session, directory, private, *_ = fixture(tmp_path)
    result = helper.verify(session, directory, private, '000000000001')
    assert result['matchesLive'] is True and len(result['resources']) == 2
    assert result['deploymentReady'] is False
    assert 'do-not-print' not in json.dumps(result)


def test_uploaded_zip_is_hashed_not_assumed_equal_from_its_filename(tmp_path):
    session, directory, private, template, cfg, policy, uploads = fixture(tmp_path)
    uploads['body'] = b'a-different-zip'
    result = helper.verify(session, directory, private, '000000000001')
    assert result['matchesLive'] is False
    assert 'UploadedZipSha256' in next(r for r in result['resources'] if r['resource'] == 'Function')['differentFields']


def test_policy_changes_are_checked_against_live_grants(tmp_path):
    session, directory, private, template, *_ = fixture(tmp_path)
    template['Resources']['Role']['Properties']['Policies'][0]['PolicyDocument']['Statement'][0]['Action'] = '*'
    result = helper.verify(session, directory, private, '000000000001')
    assert result['matchesLive'] is False
    assert 'InlinePolicy/Read' in next(r for r in result['resources'] if r['resource'] == 'Role')['differentFields']


def test_environment_mismatch_is_reported_without_values(tmp_path):
    session, directory, private, template, cfg, *_ = fixture(tmp_path)
    cfg['Environment']['Variables']['PRIVATE_SETTING'] = 'new-private-value'
    result = helper.verify(session, directory, private, '000000000001')
    assert result['matchesLive'] is False
    assert 'Environment' in next(r for r in result['resources'] if r['resource'] == 'Function')['differentFields']
    assert 'new-private-value' not in json.dumps(result)


def test_current_function_revision_changes_block_stale_plan(tmp_path):
    session, directory, private, template, cfg, *_ = fixture(tmp_path)
    cfg['RevisionId'] = 'changed'
    result = helper.verify(session, directory, private, '000000000001')
    assert result['matchesLive'] is False
    assert 'RevisionId' in next(r for r in result['resources'] if r['resource'] == 'Function')['differentFields']


def test_runtime_verifier_has_no_aws_mutation_or_secret_value_calls():
    tree = ast.parse((ROOT / 'scripts/verify-sam-runtime-bindings.py').read_text())
    calls = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert not calls & {'create_change_set', 'execute_change_set', 'put_object', 'put_role_policy',
        'update_function_code', 'update_function_configuration', 'update_service', 'get_secret_value', 'execute_statement'}


def test_removing_a_still_live_previously_managed_inline_policy_is_flagged(tmp_path):
    session, directory, private, template, *_ = fixture(tmp_path)
    template['Resources']['Role']['Properties']['Policies'] = []
    result = helper.verify(session, directory, private, '000000000001')
    assert result['matchesLive'] is False
    fields = next(r for r in result['resources'] if r['resource'] == 'Role')['differentFields']
    assert 'ExistingManagedInlinePolicyWouldBeRemoved' in fields


def test_unstable_lambda_does_not_pass_runtime_verification(tmp_path):
    session, directory, private, template, cfg, *_ = fixture(tmp_path)
    cfg['LastUpdateStatus'] = 'InProgress'
    result = helper.verify(session, directory, private, '000000000001')
    assert result['matchesLive'] is False and result['errors']


def test_post_execution_allows_new_revision_but_still_requires_same_code_and_settings(tmp_path):
    session, directory, private, template, cfg, *_ = fixture(tmp_path)
    cfg['RevisionId'] = 'updated-by-cloudformation'
    assert helper.verify(session, directory, private, '000000000001', after_execution=True)['matchesLive'] is True
    cfg['CodeSha256'] = 'different-code'
    assert helper.verify(session, directory, private, '000000000001', after_execution=True)['matchesLive'] is False


def test_post_execution_reads_current_template_instead_of_unexecuted_changeset(tmp_path):
    session, directory, private, template, *_ = fixture(tmp_path)
    calls = []
    session.client('cloudformation').get_template = lambda **kw: calls.append(kw) or {'TemplateBody': template}
    helper.verify(session, directory, private, '000000000001', after_execution=True)
    assert calls and all('ChangeSetName' not in call for call in calls)
