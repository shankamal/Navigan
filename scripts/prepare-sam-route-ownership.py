#!/usr/bin/env python3
"""Preserve deployed route IDs and optionally prepare unexecuted route imports.

Uses a private reconcile-sam capture. Never executes a change set, updates a
route, builds code, changes IAM, or deploys an application stack.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sam_capture', ROOT / 'scripts/reconcile-sam.py')
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)
require = capture.require
write = capture.write
ROUTE = 'AWS::ApiGatewayV2::Route'
PROPERTIES = {'ApiKeyRequired', 'AuthorizationScopes', 'AuthorizationType',
              'AuthorizerId', 'ModelSelectionExpression', 'OperationName',
              'RequestModels', 'RequestParameters', 'RouteKey',
              'RouteResponseSelectionExpression', 'Target'}


def read(path):
    return json.loads(path.read_text())


def route_properties(api_id, route):
    require(not route.get('ApiGatewayManaged'), 'API-managed routes cannot be adopted')
    unknown = set(route) - PROPERTIES - {'RouteId', 'ApiGatewayManaged', 'ResponseMetadata'}
    require(not unknown, 'Unknown live route properties; inspect before import')
    require(route.get('RouteKey') and route.get('RouteId'), 'Incomplete live route')
    return {'ApiId': api_id, **{k: v for k, v in route.items() if k in PROPERTIES}}


def baseline(private):
    """Check every captured archive; retain per-function version/revision locks."""
    result = {}
    for path in sorted((private / 'functions').glob('*.json')):
        meta = read(path)
        require(meta.get('deployedArchive'), 'Capture deployed ZIPs before reconciliation')
        archive = (private / meta['deployedArchive']).resolve()
        require(archive.is_relative_to(private.resolve()), 'Archive escapes capture directory')
        digest = base64.b64encode(hashlib.sha256(archive.read_bytes()).digest()).decode()
        require(digest == meta['CodeSha256'], 'Captured ZIP checksum differs')
        result[path.stem] = {k: meta[k] for k in ('FunctionArn', 'RevisionId', 'CodeSha256', 'deployedArchive')}
    require(result, 'No captured Lambda baseline')
    return result


def build(private, definitions):
    """Resolve authored routes across all captured stacks, not just their module."""
    stacks = {p.stem: read(p) for p in (private / 'stacks').glob('*.json')}
    require('root' in stacks, 'Root stack capture missing')
    apis = []
    for name, stack in stacks.items():
        for r in stack['resources']:
            if r['ResourceType'] == 'AWS::ApiGatewayV2::Api':
                data = read(private / 'apis' / (name + '--' + r['LogicalResourceId'] + '.json'))
                apis.append((r['PhysicalResourceId'], data))
    require(len(apis) == 1, 'Expected one platform API; ambiguous capture requires review')
    api_id, api = apis[0]
    routes = {r['RouteKey']: r for r in api['routes']}
    require(len(routes) == len(api['routes']), 'Duplicate captured route keys')
    owners = {}
    for name, stack in stacks.items():
        for r in stack['resources']:
            if r['ResourceType'] == ROUTE:
                physical = r['PhysicalResourceId']
                if '|' in physical:
                    require(physical.split('|')[0] == api_id, 'Captured route belongs to another API')
                owners.setdefault(physical.rsplit('|', 1)[-1], []).append({
                    'stack': stack['description']['StackId'], 'captureStack': name,
                    'logicalId': r['LogicalResourceId']})
    mappings = []; candidates = []; template = {'AWSTemplateFormatVersion': '2010-09-09', 'Resources': {}}
    for module, definition in definitions['routes'].items():
        for logical, authored in definition.get('Resources', {}).items():
            if authored['Type'] != ROUTE:
                continue
            key = authored['Properties']['RouteKey']
            require(isinstance(key, str), 'Dynamic route key requires review')
            value = {'module': module, 'sourceLogicalId': logical, 'routeKey': key}
            route = routes.get(key)
            if route is None:
                value['action'] = 'omit-not-live'
            else:
                matched = owners.get(route['RouteId'], [])
                require(len(matched) <= 1, 'Route has multiple captured owners')
                value.update(apiId=api_id, routeId=route['RouteId'])
                if matched:
                    value.update(owner=matched[0], action='retain-managed')
                else:
                    # Canonical IDs are namespaced by module in the companion stack.
                    adopted_id = module + logical
                    require(adopted_id not in template['Resources'], 'Import logical ID collision')
                    template['Resources'][adopted_id] = {
                        'Type': ROUTE, 'DeletionPolicy': 'Retain', 'UpdateReplacePolicy': 'Retain',
                        'Properties': route_properties(api_id, route)}
                    value.update(action='import-candidate', importLogicalId=adopted_id)
                    candidates.append(value)
            mappings.append(value)
    return {'rootStack': stacks['root']['description']['StackId'], 'routes': mappings,
            'template': template, 'candidates': candidates, 'codeBaseline': baseline(private)}


def missing(error):
    data = getattr(error, 'response', {}).get('Error', {})
    message = data.get('Message', '').lower()
    return data.get('Code') == 'ValidationError' and ('does not exist' in message or 'not found' in message)


def validate_changes(response, expected):
    require(response['Status'] == 'CREATE_COMPLETE', 'Import change set did not complete')
    require(response.get('ExecutionStatus') == 'AVAILABLE', 'Import change set is not available')
    changes = [c.get('ResourceChange', {}) for c in response.get('Changes', [])]
    require(len(changes) == len(expected), 'Import change set resource count differs')
    require({c.get('LogicalResourceId') for c in changes} == set(expected), 'Unexpected import resource IDs')
    require(all(c.get('Action') == 'Import' and c.get('ResourceType') == ROUTE
                and c.get('Replacement') in (None, 'False') for c in changes),
            'Change set contains an operation other than route import')


def import_identifiers(info, route):
    """Use CloudFormation's identifier names rather than a fixed pair.

    Legacy and registry-backed types can expose different identifier names.
    Values always come from the captured route revalidated through GetRoute.
    """
    entries = [r.get('ResourceIdentifiers', [])
               for r in info.get('ResourceIdentifierSummaries', [])
               if r.get('ResourceType') == ROUTE]
    require(len(entries) == 1 and entries[0], 'CloudFormation returned no unique route import identifier set')
    names = entries[0]
    values = {'ApiId': route['apiId'], 'RouteId': route['routeId'],
              'Id': route['routeId'], 'RouteKey': route['routeKey']}
    require(all(name in values for name in names),
            'Unsupported CloudFormation route import identifier names: ' + json.dumps(names))
    require(set(names) & {'RouteId', 'Id', 'RouteKey'}, 'Import identifiers do not identify an individual route')
    return {name: values[name] for name in names}


def prepare(session, data, directory):
    cfn = session.client('cloudformation'); api = session.client('apigatewayv2')
    if not data['candidates']:
        return None
    for route in data['candidates']:
        # Check both common physical-ID forms. Any lookup failure except a clear
        # not-found aborts. CloudFormation also rejects resources owned elsewhere.
        for physical in (route['apiId'] + '|' + route['routeId'], route['routeId']):
            try:
                owned = cfn.describe_stack_resources(PhysicalResourceId=physical)['StackResources']
            except Exception as error:
                if missing(error):
                    continue
                raise
            require(not [r for r in owned if r.get('ResourceStatus') != 'DELETE_COMPLETE'],
                    'Import candidate is owned by another stack; keep its existing ownership')
        live = api.get_route(ApiId=route['apiId'], RouteId=route['routeId'])
        require(route_properties(route['apiId'], live) ==
                data['template']['Resources'][route['importLogicalId']]['Properties'],
                'Route changed since capture; recapture before preparation')
    body = json.dumps(data['template'])
    require(len(body.encode()) <= 51200, 'Import template exceeds inline limit')
    info = cfn.get_template_summary(TemplateBody=body)
    write(directory / 'import-template-summary.json', info)
    resources = [{'ResourceType': ROUTE, 'LogicalResourceId': r['importLogicalId'],
                  'ResourceIdentifier': import_identifiers(info, r)}
                 for r in data['candidates']]
    stack_name = data['rootStack'].split(':stack/', 1)[1].split('/')[0] + '-sam-route-ownership'
    require(len(stack_name) <= 128, 'Route ownership stack name is too long')
    try:
        cfn.describe_stacks(StackName=stack_name)
    except Exception as error:
        if not missing(error):
            raise
    else:
        raise RuntimeError('Route ownership stack already exists; inspect its state before continuing')
    write(directory / 'resources-to-import.json', resources)
    response = cfn.create_change_set(StackName=stack_name, ChangeSetName='route-import-' + uuid.uuid4().hex[:12],
        ChangeSetType='IMPORT', TemplateBody=body, ResourcesToImport=resources,
        Description='Adopt existing routes without runtime changes; retain deployed route IDs')
    # Persist immediately so a timeout/interruption never loses the change-set ID.
    plan = {'stackId': response['StackId'], 'changeSetId': response['Id'], 'executed': False}
    write(directory / 'import-plan.json', plan)
    cfn.get_waiter('change_set_create_complete').wait(ChangeSetName=response['Id'],
        WaiterConfig={'Delay': 3, 'MaxAttempts': 18})
    pages = capture.items(cfn, 'describe_change_set', 'Changes', ChangeSetName=response['Id'])
    details = cfn.describe_change_set(ChangeSetName=response['Id'])
    details['Changes'] = pages
    write(directory / 'change-set.json', details)
    validate_changes(details, data['template']['Resources'])
    plan['verifiedImportOnly'] = True
    write(directory / 'import-plan.json', plan)
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture-directory', type=Path, required=True)
    parser.add_argument('--prepare-import', action='store_true')
    parser.add_argument('--profile'); parser.add_argument('--region'); parser.add_argument('--expected-account')
    args = parser.parse_args()
    definitions = capture.contract()
    source = args.capture_directory.resolve(); summary = read(source / 'reconciliation-summary.json')
    require(summary.get('format') == 1, 'Unknown capture format')
    environments = summary['environments']
    require(environments and not any(v.get('errors') for v in environments.values()), 'Capture contains errors')
    # Resolve and verify both environments before preparing any AWS change set.
    datasets = {label: build(source / label, definitions) for label in environments}
    session = None
    if args.prepare_import:
        require(args.region and args.expected_account, 'Import preparation requires explicit region and account')
        import boto3
        session = boto3.Session(profile_name=args.profile, region_name=args.region)
        require(session.client('sts').get_caller_identity()['Account'] == args.expected_account, 'Unexpected AWS account')
        for data in datasets.values():
            require(data['rootStack'].startswith('arn:aws:cloudformation:' + args.region + ':' + args.expected_account + ':stack/'),
                    'Capture account/region does not match requested target')
    output = Path(tempfile.mkdtemp(prefix='navigan-sam-route-ownership-')); output.chmod(0o700)
    result = {'format': 1, 'deploymentReady': False, 'executed': False, 'environments': {}}
    for label, data in datasets.items():
        directory = output / label
        write(directory / 'ownership-map.json', {k: v for k, v in data.items() if k not in ('template', 'candidates')})
        write(directory / 'route-import-template.json', data['template'])
        counts = {action: sum(r['action'] == action for r in data['routes'])
                  for action in ('retain-managed', 'import-candidate', 'omit-not-live')}
        result['environments'][label] = {'routes': counts, 'codeBaselinesVerified': len(data['codeBaseline']),
            'importPrepared': False, 'errors': []}
        try:
            if session:
                plan = prepare(session, data, directory)
                result['environments'][label]['importPrepared'] = bool(plan)
        except Exception as error:
            result['environments'][label]['errors'].append(capture.error_record('route-import', error))
        write(output / 'route-ownership-summary.json', result)
    print('Route identity maps and deployed ZIP locks written: ' + str(output))
    print('Share: ' + str(output / 'route-ownership-summary.json'))
    print('No change set executed. Application stacks, code, IAM and database unchanged.')
    return 2 if any(e['errors'] for e in result['environments'].values()) else 0


if __name__ == '__main__':
    raise SystemExit(main())
