import ast
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('baseline_release_test', ROOT / 'scripts/prepare-sam-baseline-release.py')
helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)


@pytest.mark.parametrize('url', [
    'https://existing-bucket.s3.ap-south-1.amazonaws.com/path/template',
    'https://s3.ap-south-1.amazonaws.com/existing-bucket/path/template',
    'https://existing-bucket.s3.amazonaws.com/path/template',
    'https://s3.amazonaws.com/existing-bucket/path/template',
    'https://existing-bucket.s3.ap-south-1.amazonaws.com/path/template?versionId=example-version',
    'https://s3.ap-south-1.amazonaws.com/existing-bucket/template?X-Amz-Credential=private&X-Amz-Signature=private',
    'https://existing-bucket.s3.dualstack.ap-south-1.amazonaws.com/path/template',
    'https://s3.dualstack.ap-south-1.amazonaws.com/existing-bucket/template',
    's3://existing-bucket/path/template',
])
def test_discovers_existing_bucket_from_root_nested_template_urls(url):
    record = {'templates': {'Processed': {'Resources': {'Nested': {'Type': 'AWS::CloudFormation::Stack',
        'Properties': {'TemplateURL': url}}}}}}
    assert helper.artifact_bucket(record) == 'existing-bucket'


@pytest.mark.parametrize('url', ['https://example.com/template', 'http://s3.amazonaws.com/bucket/template',
    'https://existing-bucket.s3.amazonaws.com/template#fragment',
    'https://existing-bucket.s3.amazonaws.com.evil.example/template?private=query',
    'https://user:private@existing-bucket.s3.amazonaws.com/template',
    'https://existing-bucket.s3.amazonaws.com:8443/template', 's3://existing-bucket/template?private=query'])
def test_rejects_unexpected_bucket_locations(url):
    with pytest.raises(RuntimeError):
        helper.artifact_bucket({'templates': {'Processed': {'Resources': {'Nested': {
            'Type': 'AWS::CloudFormation::Stack', 'Properties': {'TemplateURL': url}}}}}})


def change(kind='AWS::Lambda::Function', action='Modify', replacement='False', logical='Function', nested=None):
    item = {'ResourceChange': {'ResourceType': kind, 'Action': action, 'Replacement': replacement, 'LogicalResourceId': logical}}
    if nested:
        item['ResourceChange']['ChangeSetId'] = nested
    return item


@pytest.mark.parametrize('item', [change(action='Add'), change(action='Remove'), change(action='Import'),
    change(replacement='True'), change(replacement='Conditional'), change(kind='AWS::RDS::DBInstance'),
    change(kind='AWS::Lambda::Permission')])
def test_review_blocks_unexpected_or_replacing_operations(item):
    assert helper.review_change(item)['reviewPassed'] is False


class CFN:
    def __init__(self, changes, failed=None):
        self.changes = changes; self.created = []; self.failed = failed
    def describe_stacks(self, **kwargs):
        return {'Stacks': [{'StackId': 'arn:aws:cloudformation:ap-south-1:000000000001:stack/example/id',
            'StackStatus': 'UPDATE_COMPLETE', 'Parameters': [{'ParameterKey': 'Secret', 'ParameterValue': '****'}],
            'Tags': [{'Key': 'environment', 'Value': 'example'}]}]}
    def create_change_set(self, **kwargs):
        self.created.append(kwargs)
        return {'Id': 'root-change-set', 'StackId': 'stack-id'}
    def describe_change_set(self, ChangeSetName):
        if self.failed:
            return {'Status': 'FAILED', 'StatusReason': self.failed}
        return {'Status': 'CREATE_COMPLETE', 'ExecutionStatus': 'AVAILABLE', 'Changes': self.changes[ChangeSetName]}
    def get_paginator(self, operation):
        return SimpleNamespace(paginate=lambda **kw: [self.describe_change_set(**kw)])


def test_recursively_checks_nested_changes(tmp_path):
    cfn = CFN({'root': [change('AWS::CloudFormation::Stack', logical='Nested', nested='child')],
               'child': [change()]})
    reviewed = helper.inspect_changes(cfn, 'root', tmp_path)
    assert len(reviewed) == 2 and all(c['reviewPassed'] for c in reviewed)


def test_nested_removal_is_blocked_even_when_root_modification_is_allowed(tmp_path):
    cfn = CFN({'root': [change('AWS::CloudFormation::Stack', nested='child')], 'child': [change(action='Remove')]})
    assert not all(c['reviewPassed'] for c in helper.inspect_changes(cfn, 'root', tmp_path))


def test_missing_nested_plan_stops_review(tmp_path):
    with pytest.raises(RuntimeError, match='missing'):
        helper.inspect_changes(CFN({'root': [change('AWS::CloudFormation::Stack')]}), 'root', tmp_path)


def prepare(tmp_path, cfn):
    template = tmp_path / 'packaged.json'; template.write_text(json.dumps({'Resources': {}}))
    s3 = SimpleNamespace(put_object=lambda **kw: None)
    record = {'description': cfn.describe_stacks()['Stacks'][0]}
    return helper.prepare_stack(cfn, s3, record, template, 'existing-bucket', 'private-prefix', tmp_path / 'plan')


def test_prepares_update_without_secret_values_or_execution(tmp_path):
    cfn = CFN({'root-change-set': [change()]})
    result = prepare(tmp_path, cfn)
    assert result['reviewPassed'] is True
    assert cfn.created[0]['IncludeNestedStacks'] is True
    assert cfn.created[0]['ChangeSetType'] == 'UPDATE'
    assert cfn.created[0]['Parameters'] == [{'ParameterKey': 'Secret', 'UsePreviousValue': True}]
    assert helper.read(tmp_path / 'plan/plan.json')['executed'] is False


def test_no_change_stack_is_successful_noop(tmp_path):
    result = prepare(tmp_path, CFN({}, failed="The submitted information didn't contain changes."))
    assert result == {'noChanges': True, 'reviewPassed': True, 'changes': []}


def test_cloudformation_validation_failure_is_not_treated_as_noop(tmp_path):
    with pytest.raises(RuntimeError, match='preparation failed'):
        prepare(tmp_path, CFN({}, failed='Template validation error'))


def test_preparer_cannot_execute_changes_or_mutate_application_runtime():
    tree = ast.parse((ROOT / 'scripts/prepare-sam-baseline-release.py').read_text())
    calls = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert not calls & {'execute_change_set', 'update_stack', 'update_function_code', 'put_role_policy', 'execute_statement'}


def test_bucket_discovery_never_prints_or_fetches_signed_query_values(capsys):
    value = 'https://existing-bucket.s3.amazonaws.com/template?X-Amz-Signature=do-not-print'
    result = helper.artifact_bucket({'templates': {'Processed': {'Resources': {'Nested': {
        'Type': 'AWS::CloudFormation::Stack', 'Properties': {'TemplateURL': value}}}}}})
    assert result == 'existing-bucket'
    assert 'do-not-print' not in str(capsys.readouterr())


def multiple_bucket_record():
    return {'templates': {'Processed': {'Resources': {name: {'Type': 'AWS::CloudFormation::Stack',
        'Properties': {'TemplateURL': 'https://' + bucket + '.s3.ap-south-1.amazonaws.com/template?versionId=example'}}
        for name, bucket in [('First', 'scoped-release-bucket'), ('Second', 'aws-sam-cli-managed-example'),
                             ('Third', 'another-release-bucket')]}}}}


def test_multiple_deployment_buckets_are_supported_with_stable_sam_preference():
    assert helper.artifact_buckets(multiple_bucket_record()) == [
        'aws-sam-cli-managed-example', 'another-release-bucket', 'scoped-release-bucket']


def test_selection_verifies_owner_and_region_before_accepting_bucket():
    calls = []
    def location(**kw):
        calls.append(kw)
        return {'LocationConstraint': 'us-east-1' if kw['Bucket'].startswith('aws-sam-') else 'ap-south-1'}
    bucket = helper.select_artifact_bucket(SimpleNamespace(get_bucket_location=location),
        multiple_bucket_record(), '000000000001', 'ap-south-1')
    assert bucket == 'another-release-bucket'
    assert all(call['ExpectedBucketOwner'] == '000000000001' for call in calls)


def test_inaccessible_bucket_does_not_prevent_verifying_another_captured_bucket():
    class Denied(Exception):
        response = {'Error': {'Code': 'AccessDenied'}}
    def location(**kw):
        if kw['Bucket'].startswith('aws-sam-'):
            raise Denied()
        return {'LocationConstraint': 'ap-south-1'}
    assert helper.select_artifact_bucket(SimpleNamespace(get_bucket_location=location),
        multiple_bucket_record(), '000000000001', 'ap-south-1') == 'another-release-bucket'


def test_explicit_bucket_selection_is_checked_against_capture_and_owner():
    calls = []
    s3 = SimpleNamespace(get_bucket_location=lambda **kw: calls.append(kw) or {'LocationConstraint': 'ap-south-1'})
    assert helper.select_artifact_bucket(s3, multiple_bucket_record(), '000000000001', 'ap-south-1',
        'scoped-release-bucket') == 'scoped-release-bucket'
    with pytest.raises(RuntimeError, match='not referenced'):
        helper.select_artifact_bucket(s3, multiple_bucket_record(), '000000000001', 'ap-south-1', 'other-bucket')
    assert len(calls) == 1


def test_all_wrong_region_buckets_stop_before_upload():
    s3 = SimpleNamespace(get_bucket_location=lambda **kw: {'LocationConstraint': 'us-east-1'})
    with pytest.raises(RuntimeError, match='owner/region'):
        helper.select_artifact_bucket(s3, multiple_bucket_record(), '000000000001', 'ap-south-1')


def test_restores_existing_metadata_and_removes_only_packaging_added_metadata():
    before = {'Resources': {'Route': {'Type': 'AWS::ApiGatewayV2::Route', 'Properties': {'RouteKey': 'GET /example'}},
        'Function': {'Type': 'AWS::Lambda::Function', 'Metadata': {'Owner': 'keep'}, 'Properties': {'Code': '/private/code.zip'}}}}
    after = copy.deepcopy(before)
    after['Resources']['Route']['Metadata'] = {'SamResourceId': 'Route'}
    after['Resources']['Function']['Metadata']['SamResourceId'] = 'Function'
    after['Resources']['Function']['Properties']['Code'] = {'S3Bucket': 'bucket', 'S3Key': 'zip'}
    cleaned = helper.restore_package_metadata(before, after)
    assert 'Metadata' not in cleaned['Resources']['Route']
    assert cleaned['Resources']['Function']['Metadata'] == {'Owner': 'keep'}
    assert cleaned['Resources']['Function']['Properties']['Code'] == {'S3Bucket': 'bucket', 'S3Key': 'zip'}


def test_metadata_cleanup_does_not_hide_packaging_property_changes():
    before = {'Resources': {'Route': {'Type': 'AWS::ApiGatewayV2::Route', 'Properties': {'AuthorizationType': 'JWT'}}}}
    after = copy.deepcopy(before); after['Resources']['Route']['Properties']['AuthorizationType'] = 'NONE'
    with pytest.raises(RuntimeError, match='fields beyond'):
        helper.restore_package_metadata(before, after)


def test_nested_templates_are_cleaned_before_upload_not_only_the_root(tmp_path, monkeypatch):
    templates = tmp_path / 'templates'; templates.mkdir(); output = tmp_path / 'output'; output.mkdir()
    child = templates / 'child.json'; root = templates / 'root.json'
    helper.write(child, {'Resources': {'Route': {'Type': 'AWS::ApiGatewayV2::Route', 'Properties': {'RouteKey': 'GET /example'}}}})
    helper.write(root, {'Resources': {'Child': {'Type': 'AWS::CloudFormation::Stack', 'Properties': {'TemplateURL': str(child)}}}})
    inputs = []
    def fake_sam(source, destination, *args):
        data = helper.read(source); inputs.append(copy.deepcopy(data))
        for logical, resource in data['Resources'].items():
            resource.setdefault('Metadata', {})['SamResourceId'] = logical
        helper.write(destination, data)
    monkeypatch.setattr(helper, 'sam_package', fake_sam)
    uploads = []
    s3 = SimpleNamespace(put_object=lambda **kw: uploads.append(kw))
    helper.package(root, output / 'packaged.json', 'existing-bucket', 'prefix', None, 'ap-south-1',
        output / 'package.log', s3, '000000000001')
    assert len(uploads) == 1 and uploads[0]['ExpectedBucketOwner'] == '000000000001'
    assert 'Metadata' not in json.loads(uploads[0]['Body'])['Resources']['Route']
    packaged = helper.read(output / 'packaged.json')
    assert 'Metadata' not in packaged['Resources']['Child']
    assert packaged['Resources']['Child']['Properties']['TemplateURL'].startswith('https://existing-bucket.s3.ap-south-1.amazonaws.com/prefix/templates/')


def test_nested_packaging_rejects_paths_outside_the_baseline(tmp_path):
    templates = tmp_path / 'templates'; templates.mkdir(); output = tmp_path / 'output'; output.mkdir()
    child = tmp_path / 'outside.json'; helper.write(child, {'Resources': {}})
    root = templates / 'root.json'; helper.write(root, {'Resources': {'Child': {'Type': 'AWS::CloudFormation::Stack',
        'Properties': {'TemplateURL': str(child)}}}})
    with pytest.raises(RuntimeError, match='escapes'):
        helper.package(root, output / 'packaged.json', 'bucket', 'prefix', None, 'ap-south-1', output / 'package.log')


def dependency_fixture():
    template = {'Resources': {
        'Poll': {'Type': 'AWS::Events::Rule', 'Properties': {'Name': 'poll', 'Targets': [{'Arn': {'Fn::GetAtt': ['Function', 'Arn']}}]}},
        'Function': {'Type': 'AWS::Lambda::Function', 'Properties': {'FunctionName': 'function', 'Code': 'old'}},
        'Invoke': {'Type': 'AWS::Lambda::Permission', 'Properties': {
            'SourceArn': {'Fn::GetAtt': ['Poll', 'Arn']}, 'FunctionName': {'Ref': 'Function'},
            'Action': 'lambda:InvokeFunction', 'Principal': 'events.amazonaws.com'}}}}
    proposed = copy.deepcopy(template); proposed['Resources']['Function']['Properties']['Code'] = 'new'
    changes = {'Poll': change('AWS::Events::Rule', logical='Poll')['ResourceChange'],
               'Function': change(logical='Function')['ResourceChange']}
    resource = change('AWS::Lambda::Permission', replacement='Conditional', logical='Invoke')['ResourceChange']
    physical = {'Poll': 'existing-rule', 'Function': 'existing-function', 'Invoke': 'existing-permission'}
    return template, proposed, changes, resource, physical


def test_unchanged_permission_dependencies_are_explained_without_approval():
    before, after, changes, resource, physical = dependency_fixture()
    proof = helper.dependency_proof(resource, before, after, changes, physical)
    assert proof['definitionUnchanged'] and proof['referencedIdentitiesStable']
    assert proof['conditionalReplacementStillRequiresReview'] is True
    assert helper.review_change({'ResourceChange': resource})['reviewPassed'] is False


@pytest.mark.parametrize('failure', ['rule-name', 'rule-bus', 'function-name', 'reference-replaced', 'changed-grant', 'missing-resource'])
def test_dependency_evidence_does_not_hide_identity_or_permission_changes(failure):
    before, after, changes, resource, physical = dependency_fixture()
    if failure == 'rule-name': after['Resources']['Poll']['Properties']['Name'] = 'another-rule'
    if failure == 'rule-bus': after['Resources']['Poll']['Properties']['EventBusName'] = 'another-bus'
    if failure == 'function-name': after['Resources']['Function']['Properties']['FunctionName'] = 'another-function'
    if failure == 'reference-replaced': changes['Poll']['Replacement'] = 'True'
    if failure == 'changed-grant': after['Resources']['Invoke']['Properties']['Principal'] = '*'
    if failure == 'missing-resource': physical.pop('Poll')
    assert helper.dependency_proof(resource, before, after, changes, physical) is None


def test_unchanged_task_role_reference_with_in_place_role_update():
    before = {'Parameters': {'Image': {'Type': 'String'}}, 'Resources': {
        'Role': {'Type': 'AWS::IAM::Role', 'Properties': {'Policies': []}},
        'Task': {'Type': 'AWS::ECS::TaskDefinition', 'Properties': {
            'TaskRoleArn': {'Fn::GetAtt': ['Role', 'Arn']}, 'ContainerDefinitions': [{'Image': {'Ref': 'Image'}}]}}}}
    after = copy.deepcopy(before); after['Resources']['Role']['Properties']['Policies'] = [{'PolicyName': 'new'}]
    resource = change('AWS::ECS::TaskDefinition', replacement='Conditional', logical='Task')['ResourceChange']
    proof = helper.dependency_proof(resource, before, after,
        {'Role': change('AWS::IAM::Role', logical='Role')['ResourceChange']}, {'Role': 'existing-role', 'Task': 'existing-task'})
    assert proof['referencedIdentitiesStable'] is True
    after['Resources']['Role']['Properties']['Path'] = '/different/'
    assert helper.dependency_proof(resource, before, after,
        {'Role': change('AWS::IAM::Role', logical='Role')['ResourceChange']}, {'Role': 'existing-role', 'Task': 'existing-task'}) is None


def test_review_existing_function_cannot_write_to_aws():
    tree = ast.parse((ROOT / 'scripts/prepare-sam-baseline-release.py').read_text())
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    for name in ('review_existing', 'inspect_changes', 'dependency_proof', 'resource_references'):
        calls = {n.func.attr for n in ast.walk(functions[name]) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        assert not calls & {'create_change_set', 'execute_change_set', 'update_stack', 'put_object', 'update_function_code', 'put_role_policy'}
