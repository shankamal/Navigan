#!/usr/bin/env python3
"""Preserve deployed route IDs and optionally prepare unexecuted route imports.

Uses a private reconcile-sam capture. Execution requires an explicit DEV-only
flag and verifies an import-only plan. Never updates routes, builds code,
changes IAM, or deploys an application stack.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import time
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


def build(private, definitions, environment):
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
    require(environment in definitions['routes'], 'Environment route contract missing')
    for authored in definitions['routes'][environment]:
        module = authored['module']; logical = authored['sourceLogicalId']; key = authored['routeKey']
        require(isinstance(key, str), 'Dynamic route key requires review')
        expected = authored['owner']
        value = {'module': module, 'sourceLogicalId': logical, 'routeKey': key, 'expectedOwner': expected}
        route = routes.get(key)
        if route is None:
            value['action'] = 'missing-live-route'
        else:
            matched = owners.get(route['RouteId'], [])
            require(len(matched) <= 1, 'Route has multiple captured owners')
            value.update(apiId=api_id, routeId=route['RouteId'])
            if matched:
                actual = {'captureStack': matched[0]['captureStack'], 'logicalId': matched[0]['logicalId']}
                value.update(owner=matched[0], action='retain-managed' if actual == expected else 'ownership-mismatch')
            else:
                require(expected['captureStack'] == 'companion--sam-route-ownership',
                        'A module-owned route is live but unmanaged; restore it through its module stack')
                adopted_id = expected['logicalId']
                require(adopted_id not in template['Resources'], 'Import logical ID collision')
                template['Resources'][adopted_id] = {
                    'Type': ROUTE, 'DeletionPolicy': 'Retain', 'UpdateReplacePolicy': 'Retain',
                    'Properties': route_properties(api_id, route)}
                value.update(action='import-candidate', importLogicalId=adopted_id)
                candidates.append(value)
        mappings.append(value)
    require(not [r for r in mappings if r['action'] in ('missing-live-route', 'ownership-mismatch')],
            'Live route set or CloudFormation ownership differs from the maintained environment contract')
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
    # CloudFormation encodes a composite identifier as one comma-separated
    # entry (for example ["ApiId,RouteId"]). AWS CDK's resource importer also
    # splits these entries before constructing ResourceIdentifier properties.
    require(all(isinstance(name, str) for name in entries[0]), 'Malformed route import identifier names')
    names = [part.strip() for entry in entries[0] for part in entry.split(',')]
    require(all(names) and len(names) == len(set(names)), 'Empty or duplicate route import identifier names')
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


def execute_import(session, data, directory, plan):
    """Execute only the just-prepared, revalidated, route-only import."""
    cfn = session.client('cloudformation'); api = session.client('apigatewayv2')
    changes = capture.items(cfn, 'describe_change_set', 'Changes', ChangeSetName=plan['changeSetId'])
    details = cfn.describe_change_set(ChangeSetName=plan['changeSetId'])
    details['Changes'] = changes
    validate_changes(details, data['template']['Resources'])
    live_template = cfn.get_template(ChangeSetName=plan['changeSetId'], TemplateStage='Original')['TemplateBody']
    if isinstance(live_template, str):
        live_template = json.loads(live_template)
    require(live_template == data['template'], 'Import template changed after preparation')
    for route in data['candidates']:
        require(route_properties(route['apiId'], api.get_route(ApiId=route['apiId'], RouteId=route['routeId'])) ==
                data['template']['Resources'][route['importLogicalId']]['Properties'],
                'Route changed after preparation')
    plan['executionRequested'] = True
    write(directory / 'import-plan.json', plan)
    cfn.execute_change_set(ChangeSetName=plan['changeSetId'])
    plan['executed'] = True
    write(directory / 'import-plan.json', plan)
    for _ in range(120):
        state = cfn.describe_stacks(StackName=plan['stackId'])['Stacks'][0]['StackStatus']
        print('Route ownership import: ' + state, flush=True)
        if state == 'IMPORT_COMPLETE':
            break
        require(state in ('REVIEW_IN_PROGRESS', 'IMPORT_IN_PROGRESS'), 'Import did not complete successfully; inspect private plan')
        time.sleep(5)
    else:
        raise RuntimeError('Import still running; inspect the saved stack ID before retrying')
    actual = capture.items(cfn, 'list_stack_resources', 'StackResourceSummaries', StackName=plan['stackId'])
    require({r['LogicalResourceId'] for r in actual} == set(data['template']['Resources']), 'Imported resource set differs')
    by_id = {r['LogicalResourceId']: r for r in actual}
    for route in data['candidates']:
        resource = by_id[route['importLogicalId']]
        require(resource['ResourceType'] == ROUTE and resource['PhysicalResourceId'].rsplit('|', 1)[-1] == route['routeId'],
                'Imported route physical ID differs')
        require(route_properties(route['apiId'], api.get_route(ApiId=route['apiId'], RouteId=route['routeId'])) ==
                data['template']['Resources'][route['importLogicalId']]['Properties'], 'Route settings differ after import')
    plan['verifiedComplete'] = True
    write(directory / 'import-plan.json', plan)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture-directory', type=Path)
    parser.add_argument('--prepare-import', action='store_true')
    parser.add_argument('--execute-dev-import', type=Path, help='Execute an existing DEV import-plan.json after revalidation')
    parser.add_argument('--expected-dev-stack', help='Explicit DEV root stack name for saved-plan execution')
    parser.add_argument('--profile'); parser.add_argument('--region'); parser.add_argument('--expected-account')
    args = parser.parse_args()
    if args.execute_dev_import:
        require(not (args.prepare_import or args.capture_directory), 'Use the saved execution plan separately from preparation')
        require(args.region and args.expected_account and args.expected_dev_stack, 'Execution requires explicit region, account and DEV stack')
        import boto3
        session = boto3.Session(profile_name=args.profile, region_name=args.region)
        require(session.client('sts').get_caller_identity()['Account'] == args.expected_account, 'Unexpected AWS account')
        execute_saved_import(session, args.execute_dev_import, args.expected_account, args.region, args.expected_dev_stack)
        print('DEV route import completed and verified. Existing route IDs and settings retained. PROD unchanged.')
        return 0
    require(args.capture_directory, 'Provide --capture-directory for preparation')
    definitions = capture.contract()
    source = args.capture_directory.resolve(); summary = read(source / 'reconciliation-summary.json')
    require(summary.get('format') == 1, 'Unknown capture format')
    environments = summary['environments']
    require(environments and not any(v.get('errors') for v in environments.values()), 'Capture contains errors')
    # Resolve and verify both environments before preparing any AWS change set.
    datasets = {label: build(source / label, definitions, label) for label in environments}
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
                  for action in ('retain-managed', 'import-candidate', 'missing-live-route', 'ownership-mismatch')}
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
    print(json.dumps(result, indent=2))
    if result['environments'].get('dev', {}).get('importPrepared'):
        print('Verified DEV import plan: ' + str(output / 'dev/import-plan.json'))
    if any(e['errors'] for e in result['environments'].values()):
        print('PREPARATION FAILED: do not run import execution from this output directory.')
    print('Application stacks, code, IAM and database unchanged. Route import executed: ' + str(result['executed']))
    return 2 if any(e['errors'] for e in result['environments'].values()) else 0


def execute_saved_import(session, path, account, region, expected_dev_stack):
    path = path.resolve(); directory = path.parent
    require(path.name == 'import-plan.json' and directory.name == 'dev', 'Only a saved DEV import plan can execute')
    require(path.is_file(), 'No prepared import plan exists; inspect route-ownership-summary.json first')
    plan = read(path); data = read(directory / 'ownership-map.json')
    data['template'] = read(directory / 'route-import-template.json')
    data['candidates'] = [r for r in data['routes'] if r['action'] == 'import-candidate']
    prefix = 'arn:aws:cloudformation:' + region + ':' + account + ':'
    require(data['rootStack'].startswith(prefix + 'stack/'), 'DEV capture account or region differs')
    require(data['rootStack'].split(':stack/', 1)[1].split('/')[0] == expected_dev_stack, 'Saved plan is not for the explicitly requested DEV stack')
    require(plan['changeSetId'].startswith(prefix + 'changeSet/') and plan['stackId'].startswith(prefix + 'stack/'),
            'Import plan account or region differs')
    expected_name = data['rootStack'].split(':stack/', 1)[1].split('/')[0] + '-sam-route-ownership'
    require(plan['stackId'].split(':stack/', 1)[1].split('/')[0] == expected_name, 'Import stack differs from DEV plan')
    require(plan.get('verifiedImportOnly') and not plan.get('executionRequested') and not plan.get('executed'),
            'Plan is unverified or execution was already requested; inspect stack status before retrying')
    require({r['importLogicalId'] for r in data['candidates']} == set(data['template']['Resources']), 'Candidate resource set differs')
    require(set(data['template']) <= {'AWSTemplateFormatVersion', 'Resources'}, 'Import template contains unexpected top-level sections')
    require(all(r['Type'] == ROUTE and r.get('DeletionPolicy') == 'Retain' and r.get('UpdateReplacePolicy') == 'Retain'
                for r in data['template']['Resources'].values()), 'Import template must contain retained routes only')
    execute_import(session, data, directory, plan)


if __name__ == '__main__':
    raise SystemExit(main())
