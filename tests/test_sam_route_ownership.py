import base64
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('route_ownership_test', ROOT / 'scripts/prepare-sam-route-ownership.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


def captured(tmp_path):
    root = 'arn:aws:cloudformation:us-east-1:000000000001:stack/example/root'
    route = {'RouteId': 'existing', 'RouteKey': 'GET /owned', 'AuthorizationType': 'JWT', 'AuthorizerId': 'auth', 'Target': 'integrations/existing'}
    unmanaged = {**route, 'RouteId': 'unmanaged', 'RouteKey': 'GET /unmanaged'}
    helper.write(tmp_path / 'stacks/root.json', {'description': {'StackId': root}, 'resources': [
        {'ResourceType': 'AWS::ApiGatewayV2::Api', 'LogicalResourceId': 'Api', 'PhysicalResourceId': 'api'}]})
    helper.write(tmp_path / 'stacks/root--MigrationManagement.json', {'description': {'StackId': root + '-module'}, 'resources': [
        {'ResourceType': helper.ROUTE, 'LogicalResourceId': 'LegacyRoute', 'PhysicalResourceId': 'existing'}]})
    helper.write(tmp_path / 'apis/root--Api.json', {'routes': [route, unmanaged]})
    (tmp_path / 'artifacts').mkdir(); (tmp_path / 'artifacts/code.zip').write_bytes(b'captured-code')
    helper.write(tmp_path / 'functions/root--Function.json', {'FunctionArn': 'function', 'RevisionId': 'revision',
        'CodeSha256': base64.b64encode(hashlib.sha256(b'captured-code').digest()).decode(), 'deployedArchive': 'artifacts/code.zip'})
    definitions = {'routes': {'MigrationManagement': {'Resources': {
        logical: {'Type': helper.ROUTE, 'Properties': {'RouteKey': key}}
        for logical, key in [('OwnedRoute', 'GET /owned'), ('UnmanagedRoute', 'GET /unmanaged'), ('AbsentRoute', 'GET /absent')]}}}}
    return helper.build(tmp_path, definitions)


def test_preserves_live_ids_auth_and_absent_features(tmp_path):
    data = captured(tmp_path)
    owned, unmanaged, absent = data['routes']
    assert owned['action'] == 'retain-managed' and owned['owner']['logicalId'] == 'LegacyRoute'
    assert unmanaged['action'] == 'import-candidate'
    assert absent['action'] == 'omit-not-live'
    resource = data['template']['Resources'][unmanaged['importLogicalId']]
    assert resource['DeletionPolicy'] == resource['UpdateReplacePolicy'] == 'Retain'
    assert resource['Properties'] == {'ApiId': 'api', 'RouteKey': 'GET /unmanaged',
        'AuthorizationType': 'JWT', 'AuthorizerId': 'auth', 'Target': 'integrations/existing'}
    assert len(data['codeBaseline']) == 1


def test_checks_ownership_in_companions_too(tmp_path):
    captured(tmp_path)
    helper.write(tmp_path / 'stacks/companion--other.json', {'description': {'StackId': 'other-owner'}, 'resources': [
        {'ResourceType': helper.ROUTE, 'LogicalResourceId': 'ExistingCompanionRoute', 'PhysicalResourceId': 'unmanaged'}]})
    definition = {'routes': {'MigrationManagement': {'Resources': {'Route': {'Type': helper.ROUTE, 'Properties': {'RouteKey': 'GET /unmanaged'}}}}}}
    data = helper.build(tmp_path, definition)
    assert not data['candidates']
    assert data['routes'][0]['owner']['stack'] == 'other-owner'


def test_tampered_zip_stops_baseline(tmp_path):
    captured(tmp_path)
    (tmp_path / 'artifacts/code.zip').write_bytes(b'changed')
    with pytest.raises(RuntimeError, match='checksum'):
        helper.baseline(tmp_path)


@pytest.mark.parametrize('extra', [{'ApiGatewayManaged': True}, {'NewUnknownProperty': 'value'}])
def test_unknown_or_api_managed_route_requires_review(extra):
    with pytest.raises(RuntimeError):
        helper.route_properties('api', {'RouteId': 'route', 'RouteKey': 'GET /example', **extra})


@pytest.mark.parametrize('change', [
    {'Action': 'Modify', 'ResourceType': helper.ROUTE},
    {'Action': 'Remove', 'ResourceType': helper.ROUTE},
    {'Action': 'Import', 'ResourceType': 'AWS::Lambda::Function'},
    {'Action': 'Import', 'ResourceType': helper.ROUTE, 'Replacement': 'True'},
])
def test_change_set_rejects_any_non_import_operation(change):
    with pytest.raises(RuntimeError):
        helper.validate_changes({'Status': 'CREATE_COMPLETE', 'ExecutionStatus': 'AVAILABLE',
            'Changes': [{'ResourceChange': {'LogicalResourceId': 'Route', **change}}]}, ['Route'])


class NotFound(Exception):
    response = {'Error': {'Code': 'ValidationError', 'Message': 'Stack does not exist'}}


class CFN:
    def __init__(self, resources, owner=False):
        self.resources = resources; self.created = []; self.owner = owner
    def describe_stack_resources(self, **kwargs):
        if self.owner:
            return {'StackResources': [{'ResourceStatus': 'CREATE_COMPLETE'}]}
        raise NotFound()
    def describe_stacks(self, **kwargs):
        raise NotFound()
    def get_template_summary(self, **kwargs):
        return {'ResourceIdentifierSummaries': [{'ResourceType': helper.ROUTE, 'ResourceIdentifiers': ['ApiId', 'RouteId']}]}
    def create_change_set(self, **kwargs):
        self.created.append(kwargs)
        return {'Id': 'change-set', 'StackId': 'new-stack'}
    def get_waiter(self, name):
        return SimpleNamespace(wait=lambda **kw: None)
    def describe_change_set(self, **kwargs):
        return {'Status': 'CREATE_COMPLETE', 'ExecutionStatus': 'AVAILABLE', 'Changes': [
            {'ResourceChange': {'Action': 'Import', 'ResourceType': helper.ROUTE, 'LogicalResourceId': k}}
            for k in self.resources]}
    def get_paginator(self, name):
        return SimpleNamespace(paginate=lambda **kw: [self.describe_change_set(**kw)])


def session(cfn, live):
    return SimpleNamespace(client=lambda name: cfn if name == 'cloudformation' else
        SimpleNamespace(get_route=lambda **kw: live))


def live_route(data):
    props = next(iter(data['template']['Resources'].values()))['Properties']
    return {**{k: v for k, v in props.items() if k != 'ApiId'}, 'RouteId': 'unmanaged'}


def test_prepares_import_only_without_executing(tmp_path):
    data = captured(tmp_path); cfn = CFN(data['template']['Resources'])
    plan = helper.prepare(session(cfn, live_route(data)), data, tmp_path / 'output')
    assert plan['verifiedImportOnly'] and plan['executed'] is False
    assert cfn.created[0]['ChangeSetType'] == 'IMPORT'
    assert cfn.created[0]['ResourcesToImport'][0]['ResourceIdentifier'] == {'ApiId': 'api', 'RouteId': 'unmanaged'}
    assert json.loads((tmp_path / 'output/import-plan.json').read_text()) == plan


def test_live_drift_stops_before_change_set(tmp_path):
    data = captured(tmp_path); cfn = CFN(data['template']['Resources'])
    with pytest.raises(RuntimeError, match='changed since capture'):
        helper.prepare(session(cfn, {**live_route(data), 'Target': 'integrations/changed'}), data, tmp_path / 'output')
    assert not cfn.created


def test_other_stack_owner_stops_before_change_set(tmp_path):
    data = captured(tmp_path); cfn = CFN(data['template']['Resources'], owner=True)
    with pytest.raises(RuntimeError, match='owned by another stack'):
        helper.prepare(session(cfn, live_route(data)), data, tmp_path / 'output')
    assert not cfn.created


def test_access_denied_is_not_treated_as_unowned():
    error = NotFound(); error.response = {'Error': {'Code': 'AccessDenied', 'Message': 'not found'}}
    assert not helper.missing(error)
