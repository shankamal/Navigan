import ast
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
])
def test_discovers_existing_bucket_from_root_nested_template_urls(url):
    record = {'templates': {'Processed': {'Resources': {'Nested': {'Type': 'AWS::CloudFormation::Stack',
        'Properties': {'TemplateURL': url}}}}}}
    assert helper.artifact_bucket(record) == 'existing-bucket'


@pytest.mark.parametrize('url', ['https://example.com/template', 'http://s3.amazonaws.com/bucket/template',
                              'https://existing-bucket.s3.amazonaws.com/template?private=query'])
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
