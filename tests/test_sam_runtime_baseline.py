import base64
import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('runtime_baseline_test', ROOT / 'scripts/materialize-sam-baseline.py')
helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)


def test_native_template_preserves_logical_ids_without_repeated_sam_transform():
    template = {'Transform': 'AWS::Serverless-2016-10-31', 'Resources': {'Legacy': {'Type': 'AWS::Lambda::Function'}}}
    actual = helper.body(template)
    assert set(actual['Resources']) == {'Legacy'} and 'Transform' not in actual
    assert 'Transform' in template


def test_unprocessed_templates_stop():
    with pytest.raises(RuntimeError):
        helper.body({'Resources': {'Function': {'Type': 'AWS::Serverless::Function'}}})


def test_function_preserves_full_live_environment_and_removes_old_layers_and_vpc(tmp_path):
    cfg = {'FunctionArn': 'arn', 'Handler': 'main.handler', 'Runtime': 'python3.12', 'Role': 'role',
           'Environment': {'Variables': {'KNOWN': 'value', 'UNLISTED_SETTING': 'private-value'}},
           'VpcConfig': {}, 'Layers': []}
    props = helper.function_properties({'Code': {'S3Key': 'old'}, 'VpcConfig': {'SubnetIds': ['old']},
        'Layers': ['old'], 'Role': 'old'}, cfg, tmp_path / 'code.zip')
    assert props['Environment'] == cfg['Environment']
    assert props['Code'] == str(tmp_path / 'code.zip') and props['Role'] == 'role'
    assert 'Layers' not in props and 'VpcConfig' not in props


def test_unreadable_environment_stops():
    with pytest.raises(RuntimeError):
        helper.function_properties({}, {'Environment': {'Error': {'ErrorCode': 'AccessDenied'}}}, Path('zip'))


def fixture(tmp_path):
    private = tmp_path / 'capture'; output = tmp_path / 'output'
    archive = private / 'artifacts/code.zip'; archive.parent.mkdir(parents=True); archive.write_bytes(b'code')
    checksum = base64.b64encode(hashlib.sha256(b'code').digest()).decode()
    cfg = {'FunctionArn': 'function', 'RevisionId': 'revision', 'CodeSha256': checksum,
           'Role': 'role', 'State': 'Active', 'LastUpdateStatus': 'Successful',
           'Environment': {'Variables': {'FULL_SETTING': 'private'}}}
    helper.write(private / 'functions/root--Function.json', {**cfg, 'deployedArchive': 'artifacts/code.zip'})
    role = {'RoleName': 'role', 'Arn': 'arn:aws:iam::000000000001:role/role', 'AssumeRolePolicyDocument': {'Statement': []}}
    helper.write(private / 'iam/role-0.json', {'role': role})
    resources = {'Function': {'Type': 'AWS::Lambda::Function', 'Properties': {}},
                 'ExistingRole': {'Type': 'AWS::IAM::Role', 'Properties': {}}}
    helper.write(private / 'stacks/root.json', {'description': {'StackId': 'stack', 'Parameters': [
        {'ParameterKey': 'SecretInput', 'ParameterValue': '****'}]},
        'templates': {'Processed': {'Resources': resources}}, 'resources': [
        {'LogicalResourceId': key, 'ResourceType': value['Type'], 'PhysicalResourceId': 'role' if key == 'ExistingRole' else 'function'}
        for key, value in resources.items()]})
    cfn = SimpleNamespace(describe_stacks=lambda **kw: {'Stacks': [{'StackId': 'stack', 'StackStatus': 'UPDATE_COMPLETE'}]})
    lam = SimpleNamespace(get_function_configuration=lambda **kw: cfg, get_function_concurrency=lambda **kw: {})
    iam = SimpleNamespace(get_role=lambda **kw: {'Role': role},
        get_role_policy=lambda **kw: {'PolicyName': 'direct-policy', 'PolicyDocument': {'Statement': [{'Effect': 'Allow'}]}},
        get_paginator=lambda name: SimpleNamespace(paginate=lambda **kw: [
            {'PolicyNames': ['direct-policy']} if name == 'list_role_policies' else {'AttachedPolicies': []}]))
    session = SimpleNamespace(client=lambda name: {'cloudformation': cfn, 'lambda': lam, 'iam': iam}[name])
    return private, output, cfg, session


def test_materializes_live_code_environment_and_additional_inline_permissions(tmp_path):
    private, output, cfg, session = fixture(tmp_path)
    counts = helper.materialize(session, private, output)
    template = helper.read(output / 'root.json')
    assert set(template['Resources']) == {'Function', 'ExistingRole'}
    assert template['Resources']['Function']['Properties']['Environment'] == cfg['Environment']
    assert template['Resources']['ExistingRole']['Properties']['Policies'][0]['PolicyName'] == 'direct-policy'
    assert counts['functions'] == counts['roles'] == 1
    assert helper.read(output / 'root-parameters.json') == [{'ParameterKey': 'SecretInput', 'UsePreviousValue': True}]


def test_runtime_change_stops_before_baseline_can_be_used(tmp_path):
    private, output, cfg, session = fixture(tmp_path)
    cfg['RevisionId'] = 'new-revision'
    with pytest.raises(RuntimeError, match='changed since capture'):
        helper.materialize(session, private, output)


def test_yaml_processed_template_preserves_intrinsics():
    template = helper.body('''AWSTemplateFormatVersion: '2010-09-09'
Conditions:
  Enabled: !Equals [!Ref Mode, enabled]
Resources:
  LegacyRoute:
    Type: AWS::ApiGatewayV2::Route
    Condition: Enabled
    Properties:
      ApiId: !Ref Api
      RouteKey: GET /example
      Target: !Join ['/', [integrations, !GetAtt Integration.Id]]
Outputs:
  Example:
    Value: !Sub ['${Name}-${Suffix}', {Name: !Ref Api, Suffix: !If [Enabled, yes-value, no-value]}]
''')
    props = template['Resources']['LegacyRoute']['Properties']
    assert props['ApiId'] == {'Ref': 'Api'}
    assert props['Target'] == {'Fn::Join': ['/', ['integrations', {'Fn::GetAtt': ['Integration', 'Id']}]]}
    assert template['Outputs']['Example']['Value']['Fn::Sub'][1]['Name'] == {'Ref': 'Api'}
    assert template['Conditions']['Enabled'] == {'Fn::Equals': [{'Ref': 'Mode'}, 'enabled']}


def test_materializes_yaml_capture_without_changing_resource_identity(tmp_path):
    import yaml
    private, output, cfg, session = fixture(tmp_path)
    path = private / 'stacks/root.json'; record = helper.read(path)
    record['templates']['Processed'] = yaml.safe_dump(record['templates']['Processed'])
    helper.write(path, record)
    counts = helper.materialize(session, private, output)
    assert counts['functions'] == 1
    assert set(helper.read(output / 'root.json')['Resources']) == {'Function', 'ExistingRole'}


@pytest.mark.parametrize('value', ['Resources: !!python/object/apply:os.system [echo unsafe]',
    'Resources: !Unknown {Function: value}', 'Resources: [invalid', 'Resources: []'])
def test_invalid_yaml_cannot_execute_tags_or_leak_private_content(value):
    with pytest.raises(RuntimeError) as error:
        helper.body(value)
    assert 'echo unsafe' not in str(error.value)


def test_managed_roles_missing_from_original_capture_are_fetched(tmp_path):
    private, output, cfg, session = fixture(tmp_path)
    (private / 'iam/role-0.json').unlink()
    counts = helper.materialize(session, private, output)
    assert counts['roles'] == 1 and counts['unverifiedRoles'] == 0
    assert helper.read(output / 'iam-locks.json')['role']['role']['RoleName'] == 'role'
