import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sam_execution_test', ROOT / 'scripts/execute-sam-baseline-release.py')
helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)


def item(kind='AWS::Lambda::Permission', replacement='Conditional'):
    return {'stackPath': 'root/Module', 'logicalId': 'Invoke', 'action': 'Modify', 'type': kind,
        'replacement': replacement, 'scope': ['Properties'], 'properties': ['SourceArn'],
        'dependencyEvidence': {'definitionUnchanged': True, 'referencedIdentitiesStable': True,
            'references': [{'resource': 'Poll', 'attribute': 'Arn', 'referenceChange': 'False'}]}}


def test_conditional_permission_requires_unchanged_definition_and_stable_identity():
    helper.allow_change(item(), set())
    for key in ('definitionUnchanged', 'referencedIdentitiesStable'):
        candidate = item(); candidate['dependencyEvidence'][key] = False
        with pytest.raises(RuntimeError, match='not proven'):
            helper.allow_change(candidate, set())


@pytest.mark.parametrize('field,value', [('action', 'Remove'), ('action', 'Add'), ('replacement', 'True'),
    ('properties', ['Principal']), ('scope', ['Metadata']), ('dependencyEvidence', None), ('type', 'AWS::RDS::DBInstance')])
def test_execution_refuses_unreviewed_or_destructive_scope(field, value):
    candidate = item(); candidate[field] = value
    with pytest.raises(RuntimeError): helper.allow_change(candidate, set())


def test_conditional_is_never_allowed_for_a_bucket_or_runtime_function():
    candidate = item('AWS::S3::Bucket'); candidate['properties'] = ['BucketEncryption']
    with pytest.raises(RuntimeError, match='conditional'):
        helper.allow_change(candidate, set())
    with pytest.raises(RuntimeError, match='in place'):
        helper.allow_change(item('AWS::Lambda::Function'), set())


def test_saved_review_flag_is_not_an_execution_authorization():
    candidate = item('AWS::Lambda::Function', 'False'); candidate['reviewPassed'] = True
    with pytest.raises(RuntimeError, match='not verified'):
        helper.allow_change(candidate, set())
    helper.allow_change(candidate, {('root/Module', 'Invoke', 'AWS::Lambda::Function')})


def test_nested_parameter_changes_are_rejected():
    candidate = item('AWS::CloudFormation::Stack', 'False'); candidate['properties'] = ['Parameters']
    with pytest.raises(RuntimeError, match='parameters'):
        helper.allow_change(candidate, set())
    candidate['properties'] = ['TemplateURL']; helper.allow_change(candidate, set())


def test_only_explicit_conditional_resources_can_change_identity():
    before = {'root--Module': {'Invoke': {'type': 'AWS::Lambda::Permission', 'id': 'old'},
                              'Function': {'type': 'AWS::Lambda::Function', 'id': 'same'}}}
    after = copy.deepcopy(before); after['root--Module']['Invoke']['id'] = 'new'
    helper.check_inventory(before, after, [{'stack': 'root/Module', 'resource': 'Invoke', 'replacement': 'Conditional'}])
    after['root--Module']['Function']['id'] = 'different'
    with pytest.raises(RuntimeError, match='identity'):
        helper.check_inventory(before, after, [{'stack': 'root/Module', 'resource': 'Invoke', 'replacement': 'Conditional'}])


def test_resource_addition_or_removal_is_detected_after_execution():
    with pytest.raises(RuntimeError, match='resource set'):
        helper.check_inventory({'root': {}}, {'root': {'New': {'type': 'AWS::S3::Bucket', 'id': 'new'}}}, [])


def test_wait_does_not_mistake_previous_update_complete_for_execution_success(monkeypatch):
    values = iter([{'StackStatus': 'UPDATE_COMPLETE', 'LastUpdatedTime': 'old'},
                   {'StackStatus': 'UPDATE_IN_PROGRESS', 'LastUpdatedTime': 'new'},
                   {'StackStatus': 'UPDATE_COMPLETE', 'LastUpdatedTime': 'new'}])
    cfn = SimpleNamespace(describe_stacks=lambda **kw: {'Stacks': [next(values)]})
    sleeps = []; monkeypatch.setattr(helper.time, 'sleep', lambda seconds: sleeps.append(seconds))
    helper.wait_for_update(cfn, {'stackId': 'root'}, {'LastUpdatedTime': 'old'})
    assert len(sleeps) == 2


def test_rollback_stops_instead_of_waiting_for_the_next_stage():
    cfn = SimpleNamespace(describe_stacks=lambda **kw: {'Stacks': [{'StackStatus': 'UPDATE_ROLLBACK_IN_PROGRESS'}]})
    with pytest.raises(RuntimeError, match='rollback'):
        helper.wait_for_update(cfn, {'stackId': 'root'}, {})


def setup_execution(tmp_path, monkeypatch):
    private = tmp_path / 'dev'; directory = tmp_path / 'release'; directory.mkdir()
    records = {name: {'description': {'StackId': name, 'LastUpdatedTime': 'old'}}
               for name in ('companion--example', 'root')}
    for name, record in records.items():
        helper.write(private / 'stacks' / (name + '.json'), record)
        helper.write(directory / name / 'plan.json', {'stackId': name, 'changeSetId': 'cs-' + name})
    helper.write(directory / 'release-summary.json', {'environment': 'dev', 'executed': False,
        'errors': [], 'stages': {name: {} for name in records}})
    review = {'errors': [], 'stages': {name: {'changes': []} for name in records}}
    allowed = [{'stage': 'root', 'stack': 'root', 'resource': 'Function', 'type': 'AWS::Lambda::Function', 'replacement': 'False'}]
    monkeypatch.setattr(helper, 'preflight', lambda *a: (review, allowed))
    monkeypatch.setattr(helper, 'inventory', lambda *a: {'root': {'Function': {'type': 'AWS::Lambda::Function', 'id': 'same'}}})
    monkeypatch.setattr(helper.runtime, 'verify', lambda *a, **kw: {'matchesLive': True, 'errors': []})
    calls = []
    cfn = SimpleNamespace(describe_change_set=lambda **kw: {'StackId': kw['ChangeSetName'][3:],
        'Status': 'CREATE_COMPLETE', 'ExecutionStatus': 'AVAILABLE'},
        describe_stacks=lambda **kw: {'Stacks': [{'StackStatus': 'UPDATE_COMPLETE', 'LastUpdatedTime': 'old'}]},
        execute_change_set=lambda **kw: calls.append(kw))
    session = SimpleNamespace(client=lambda name: cfn)
    return session, directory, private, calls


def test_executes_only_saved_plans_and_persists_completion(tmp_path, monkeypatch):
    session, directory, private, calls = setup_execution(tmp_path, monkeypatch)
    monkeypatch.setattr(helper, 'wait_for_update', lambda *a: None)
    result = helper.execute(session, directory, private, 'example-dev', '000000000001', 'ap-south-1')
    assert result['complete'] and result['postRuntimeVerified']
    assert [c['ChangeSetName'] for c in calls] == ['cs-companion--example', 'cs-root']
    assert all(c['ClientRequestToken'].startswith('navigan-dev-baseline-') for c in calls)
    with pytest.raises(RuntimeError, match='already exists'):
        helper.execute(session, directory, private, 'example-dev', '000000000001', 'ap-south-1')
    assert len(calls) == 2


def test_first_stage_failure_prevents_root_execution_and_saves_failure(tmp_path, monkeypatch):
    session, directory, private, calls = setup_execution(tmp_path, monkeypatch)
    def fail(*args): raise RuntimeError('Stack entered rollback')
    monkeypatch.setattr(helper, 'wait_for_update', fail)
    with pytest.raises(RuntimeError, match='rollback'):
        helper.execute(session, directory, private, 'example-dev', '000000000001', 'ap-south-1')
    assert len(calls) == 1
    journal = helper.read(directory / 'execution-record.json')
    assert journal['complete'] is False and journal['error']['code'] == 'RuntimeError'


def test_fresh_preflight_failure_prevents_every_aws_execution(tmp_path, monkeypatch):
    session, directory, private, calls = setup_execution(tmp_path, monkeypatch)
    def fail(*args): raise RuntimeError('Runtime no longer matches')
    monkeypatch.setattr(helper, 'preflight', fail)
    with pytest.raises(RuntimeError, match='no longer matches'):
        helper.execute(session, directory, private, 'example-dev', '000000000001', 'ap-south-1')
    assert not calls and not (directory / 'execution-record.json').exists()


def test_preflight_requires_complete_stages_and_matching_runtime(tmp_path, monkeypatch):
    session, directory, private, calls = setup_execution(tmp_path, monkeypatch)
    # Restore actual preflight after fixture patched the execution dependency.
    spec = importlib.util.spec_from_file_location('fresh_execution_test', ROOT / 'scripts/execute-sam-baseline-release.py')
    actual = importlib.util.module_from_spec(spec); spec.loader.exec_module(actual)
    review = {'errors': [], 'stages': {name: {'changes': [item()]} for name in ('companion--example', 'root')}}
    monkeypatch.setattr(actual.release, 'review_existing', lambda *a: review)
    monkeypatch.setattr(actual.runtime, 'verify', lambda *a: {'matchesLive': False, 'errors': []})
    with pytest.raises(RuntimeError, match='runtime verification failed'):
        actual.preflight(session, directory, private, 'example-dev', '000000000001', 'ap-south-1')
    summary = actual.read(directory / 'release-summary.json'); summary['stages'].pop('root')
    actual.write(directory / 'release-summary.json', summary)
    with pytest.raises(RuntimeError, match='missing or unexpected'):
        actual.preflight(session, directory, private, 'example-dev', '000000000001', 'ap-south-1')
