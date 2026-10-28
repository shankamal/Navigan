#!/usr/bin/env python3
"""Restore DEV summary APIs only. Read-only by default; prepare then execute PLAN.

Preserves deployed modules except summary handler/repository additions. No schema,
IAM, authentication configuration, business write paths or frontend changes.
"""
from __future__ import annotations
import argparse
import ast
import base64
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import textwrap
import urllib.request
import uuid
import zipfile

import boto3

ROOT = Path(__file__).resolve().parents[1]
def load_helper(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

support = load_helper('summary_api_support', 'deploy-migration-api-prod.py')
ACCOUNT, REGION = support.ACCOUNT, support.REGION
PARENT = 'navigan-ashok-dev'
# The storage reader resolves only this exact DEV stack; no PROD preflight is called.
support.storage.PARENT = PARENT
require = support.require
SPECS = {
    'customers': ('CustomerManagement', 'CustomerFunction', 'CustomerIntegration', 'customer_management'),
    'environments': ('EnvironmentManagement', 'EnvironmentFunction', 'EnvironmentIntegration', 'environment_management'),
    'clusters': ('ClusterManagement', 'ClusterFunction', 'ClusterIntegration', 'cluster_management'),
}
ROUTE = 'NaviganDevSummaryRoute'
PERMISSION = 'NaviganDevSummaryInvoke'



def upload(session, workspace, directory, name, content):
    """Store versioned preparation artifacts only in the verified DEV workspace."""
    from urllib.parse import quote
    key = f"deployment-packages/dev-summary-api/{digest(content)}/{name}"
    result = session.client('s3').put_object(
        Bucket=workspace['WorkspaceBucketName'], Key=key, Body=content,
        ExpectedBucketOwner=ACCOUNT, ServerSideEncryption='aws:kms',
        SSEKMSKeyId=workspace['WorkspaceKmsKeyArn'])
    version = result.get('VersionId')
    require(version and version != 'null', 'Versioned deployment upload required')
    code = {'S3Bucket': workspace['WorkspaceBucketName'], 'S3Key': key, 'S3ObjectVersion': version}
    url = f"https://{workspace['WorkspaceBucketName']}.s3.{REGION}.amazonaws.com/{key}?versionId={quote(version, safe='')}"
    return code, url


def digest(value):
    return hashlib.sha256(value).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, default=str))


def node_text(source, node):
    return '\n'.join(source.splitlines()[node.lineno - 1:node.end_lineno])


def patch_handler(original, resource):
    tree = ast.parse(original)
    execute = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'execute')
    require(any(isinstance(n, ast.FunctionDef) and n.name == 'lambda_handler' for n in tree.body), 'Lambda entry point missing')
    positions = [n for n in execute.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'path' for t in n.targets)]
    require(len(positions) == 1, 'Unexpected deployed execute path parser; inspect before promotion')
    has_tx = any(a.arg == 'tx' for a in execute.args.args)
    tx = 'tx' if has_tx else 'transaction'
    code = textwrap.dedent(f'''\
        if path == BASE + "/summary":
            if method != "GET":
                raise ApiError(405, "METHOD_NOT_ALLOWED", "Method not supported for this endpoint.")
            with {tx}() as db:
                db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                return response(200, Repository(db, principal).summary(), correlation)
    ''')
    # Existing summary implementations must be the known read-only contract.
    for n in execute.body:
        if isinstance(n, ast.If) and any(isinstance(x, ast.Constant) and x.value == 'summary' for x in ast.walk(n.test)) or (
            isinstance(n, ast.If) and any(isinstance(x, ast.Constant) and x.value == '/summary' for x in ast.walk(n.test))):
            desired = (ROOT / f'src/navigan/modules/{SPECS[resource][3]}/handler.py').read_text()
            known = next(x for x in ast.walk(ast.parse(desired)) if isinstance(x, ast.If) and
                         any(isinstance(y, ast.Constant) and y.value in ('summary', '/summary') for y in ast.walk(x.test)))
            require(ast.dump(n, include_attributes=False) == ast.dump(known, include_attributes=False),
                    'Unknown existing summary handler; review rather than replace it')
            return original
    lines = original.splitlines(keepends=True)
    lines.insert(positions[0].end_lineno, textwrap.indent(code, '    '))
    result = ''.join(lines)
    parsed = ast.parse(result)
    updated = next(n for n in parsed.body if isinstance(n, ast.FunctionDef) and n.name == 'execute')
    updated.body.pop(execute.body.index(positions[0]) + 1)
    require(ast.dump(tree) == ast.dump(parsed), 'Non-summary handler changes rejected')
    return result


def patch_repository(original, resource):
    module = SPECS[resource][3]
    desired = (ROOT / f'src/navigan/modules/{module}/repository.py').read_text()
    known_tree = ast.parse(desired)
    known_class = next(n for n in known_tree.body if isinstance(n, ast.ClassDef) and n.name == 'Repository')
    known = next(n for n in known_class.body if isinstance(n, ast.FunctionDef) and n.name == 'summary')
    tree = ast.parse(original)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Repository')
    existing = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'summary']
    if existing:
        require(len(existing) == 1 and ast.dump(existing[0]) == ast.dump(known), 'Unknown existing summary repository method')
        return original
    require('scope_clause' in original, 'Existing tenant scope helper required')
    if resource == 'clusters':
        # Reuse the installed visibility boundary; never change which clusters are visible.
        require('VISIBLE_CLUSTER_CONDITION' in original, 'Deployed cluster visibility contract requires review')
    lines = original.splitlines(keepends=True)
    lines.insert(cls.end_lineno, '\n' + node_text(desired, known) + '\n')
    result = ''.join(lines)
    parsed = ast.parse(result)
    updated = next(n for n in parsed.body if isinstance(n, ast.ClassDef) and n.name == 'Repository')
    updated.body.pop()
    require(ast.dump(tree) == ast.dump(parsed), 'Non-summary repository changes rejected')
    return result


def package(original, destination, resource):
    prefix = f'navigan/modules/{SPECS[resource][3]}/'
    with zipfile.ZipFile(original) as old, zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as new:
        require(len(old.namelist()) == len(set(old.namelist())), 'Duplicate ZIP members rejected')
        changes = {}
        for filename, patch in [('handler.py', patch_handler), ('repository.py', patch_repository)]:
            path = prefix + filename
            require(path in old.namelist(), 'Unexpected deployed package structure: ' + path)
            changes[path] = patch(old.read(path).decode(), resource).encode()
        for entry in old.infolist():
            if entry.filename.startswith(prefix) and entry.filename.endswith('.pyc') and (
                Path(entry.filename).name.startswith(('handler.', 'repository.')) or
                Path(entry.filename).name in ('handler.pyc', 'repository.pyc')):
                continue
            content = changes.get(entry.filename)
            new.writestr(entry, old.read(entry.filename) if content is None else content)
    with zipfile.ZipFile(destination) as new:
        require(sum(x.file_size for x in new.infolist()) <= 250 * 1024 * 1024, 'Lambda ZIP too large')
    return destination


def proposed_child(before, function, api, reference, resource, code):
    after = copy.deepcopy(before)
    resources = after['Resources']
    require(resources[function]['Type'] == 'AWS::Lambda::Function', 'Expected deployed Lambda')
    resources[function]['Properties']['Code'] = code
    desired = {'ApiId': api, 'RouteKey': f'GET /api/v1/{resource}/summary',
               **{k: reference[k] for k in ('AuthorizationType', 'AuthorizerId', 'Target')},
               'AuthorizationScopes': reference.get('AuthorizationScopes', [])}
    routes = [r for r in resources.values() if r['Type'] == 'AWS::ApiGatewayV2::Route' and
              r['Properties'].get('RouteKey') == desired['RouteKey']]
    if routes:
        require(len(routes) == 1, 'Duplicate managed summary routes')
        # Resolved live route protection is checked separately in preflight.
    else:
        require(ROUTE not in resources, 'Summary route logical ID collision')
        resources[ROUTE] = {'Type': 'AWS::ApiGatewayV2::Route', 'Properties': desired}
    permission = {'Type': 'AWS::Lambda::Permission', 'Properties': {
        'Action': 'lambda:InvokeFunction', 'FunctionName': {'Ref': function},
        'Principal': 'apigateway.amazonaws.com', 'SourceAccount': ACCOUNT,
        'SourceArn': f'arn:aws:execute-api:{REGION}:{ACCOUNT}:{api}/v1/GET/api/v1/{resource}/summary'}}
    require(PERMISSION not in resources or resources[PERMISSION] == permission, 'Summary permission logical ID collision')
    resources[PERMISSION] = permission
    validate_delta(before, after, function)
    return after


def validate_delta(before, after, function):
    b, a = before['Resources'], after['Resources']
    require(before.keys() == after.keys() and all(before[k] == after[k] for k in before if k != 'Resources'), 'Nested settings changed')
    require(set(b) <= set(a), 'Resource deletion rejected')
    for key in set(a) | set(b):
        if key == function:
            expected = copy.deepcopy(b[key])
            expected['Properties']['Code'] = a[key]['Properties']['Code']
            require(expected == a[key], 'Only Lambda code may change')
        elif key in (ROUTE, PERMISSION) and key not in b:
            require(a[key]['Type'] == ('AWS::ApiGatewayV2::Route' if key == ROUTE else 'AWS::Lambda::Permission'), 'Unexpected addition')
        else:
            require(a.get(key) == b.get(key), 'Unrelated resource change rejected: ' + key)


def inspect_plan(cfn, identifier, records):
    root = cfn.describe_change_set(ChangeSetName=identifier)
    require(root['StackName'] == PARENT and root['Status'] == 'CREATE_COMPLETE' and root['ExecutionStatus'] == 'AVAILABLE', 'Unavailable change set')
    changes = support.all_items(cfn, 'describe_change_set', 'Changes', ChangeSetName=identifier)
    allowed = {r['nestedLogical']: r for r in records}
    require(bool(changes) and len(changes) <= len(allowed), 'Unexpected root change count')
    for item in changes:
        r = item['ResourceChange']
        require(r['LogicalResourceId'] in allowed and r['ResourceType'] == 'AWS::CloudFormation::Stack' and
                r['Action'] == 'Modify' and r.get('Replacement', 'False') == 'False' and r.get('ChangeSetId'), 'Unrelated root change')
        record = allowed[r['LogicalResourceId']]
        child = cfn.describe_change_set(ChangeSetName=r['ChangeSetId'])
        require(child['StackId'] == record['stack'], 'Wrong nested stack')
        before = support.body(cfn.get_template(StackName=record['stack'], TemplateStage='Processed')['TemplateBody'])
        after = support.body(cfn.get_template(StackName=record['stack'], ChangeSetName=r['ChangeSetId'], TemplateStage='Processed')['TemplateBody'])
        require(digest(json.dumps(after, sort_keys=True).encode()) == record['templateHash'], 'Prepared template changed')
        validate_delta(before, after, record['functionLogical'])
        child_changes = support.all_items(cfn, 'describe_change_set', 'Changes', ChangeSetName=r['ChangeSetId'])
        require(bool(child_changes), 'Nested change details are required')
        for entry in child_changes:
            change = entry['ResourceChange']
            key = change['LogicalResourceId']
            require(change.get('Replacement', 'False') == 'False' and not change.get('ChangeSetId'), 'Replacement rejected')
            if key in (ROUTE, PERMISSION):
                require(change['Action'] == 'Add' and key not in before['Resources'], 'Only new summary route/permission allowed')
            elif key == record['functionLogical']:
                require(change['Action'] == 'Modify' and change['ResourceType'] == 'AWS::Lambda::Function', 'Lambda recreation rejected')
            else:
                require(change['Action'] == 'Modify' and before['Resources'].get(key) == after['Resources'].get(key)
                        and change['ResourceType'] in ('AWS::ApiGatewayV2::Integration', 'AWS::ApiGatewayV2::Route', 'AWS::Lambda::Permission')
                        and (support.references(before['Resources'][key], record['functionLogical']) or
                             support.references(before['Resources'][key], record['integrationLogical'])), 'Unrelated dependency change: ' + key)
            print(f"  {record['resource']}: {change['Action']} {key} ({change['ResourceType']})")


def preflight(session):
    require(session.client('sts').get_caller_identity()['Account'] == ACCOUNT, 'Wrong AWS account')
    cfn, lambdas, gateway = (session.client(x) for x in ('cloudformation', 'lambda', 'apigatewayv2'))
    parent = cfn.describe_stacks(StackName=PARENT)['Stacks'][0]
    require(parent['StackStatus'] in support.storage.STABLE, 'Parent stack not stable')
    require({x['ParameterKey']: x['ParameterValue'] for x in parent['Parameters']}.get('DatabaseName') == 'navigan_dev', 'Not DEV database')
    root = support.body(cfn.get_template(StackName=PARENT, TemplateStage='Processed')['TemplateBody'])
    records = []
    for resource, (nested, function, integration, module) in SPECS.items():
        stack_id = cfn.describe_stack_resource(StackName=PARENT, LogicalResourceId=nested)['StackResourceDetail']['PhysicalResourceId']
        require(stack_id.startswith(f'arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/{PARENT}-'), 'Unexpected nested stack')
        stack = cfn.describe_stacks(StackName=stack_id)['Stacks'][0]
        require(stack['StackStatus'] in support.storage.STABLE, 'Nested stack not stable')
        params = {x['ParameterKey']: x['ParameterValue'] for x in stack['Parameters']}
        require(params.get('DatabaseName') == 'navigan_dev', 'Wrong nested database')
        api = params['ApiId']
        require(gateway.get_stage(ApiId=api, StageName='v1').get('AutoDeploy') is True, 'Expected auto-deployed v1 stage')
        physical = lambda logical: cfn.describe_stack_resource(StackName=stack_id, LogicalResourceId=logical)['StackResourceDetail']['PhysicalResourceId']
        config = lambdas.get_function_configuration(FunctionName=physical(function))
        require(config['FunctionArn'].startswith(f'arn:aws:lambda:{REGION}:{ACCOUNT}:function:{PARENT}-') and
                config.get('Runtime') == 'python3.12' and config.get('PackageType', 'Zip') == 'Zip' and
                config.get('State') == 'Active' and config.get('LastUpdateStatus') == 'Successful' and
                config.get('Environment', {}).get('Variables', {}).get('DB_NAME') == 'navigan_dev', 'Unexpected or unstable Lambda')
        integration_id = physical(integration)
        require(gateway.get_integration(ApiId=api, IntegrationId=integration_id).get('IntegrationUri') == config['FunctionArn'], 'Wrong integration target')
        routes = support.all_items(gateway, 'get_routes', 'Items', ApiId=api)
        reference = next(x for x in routes if x['RouteKey'] == f'GET /api/v1/{resource}')
        require(reference.get('AuthorizationType') == 'JWT' and reference.get('AuthorizerId') and
                reference.get('Target') == 'integrations/' + integration_id, 'Expected protected list route')
        require(gateway.get_authorizer(ApiId=api, AuthorizerId=reference['AuthorizerId'])['AuthorizerType'] == 'JWT', 'Expected JWT authorizer')
        current = [x for x in routes if x['RouteKey'] == f'GET /api/v1/{resource}/summary']
        for route in current:
            require(all(route.get(k, [] if k == 'AuthorizationScopes' else None) == reference.get(k, [] if k == 'AuthorizationScopes' else None)
                        for k in ('AuthorizationType', 'AuthorizerId', 'AuthorizationScopes', 'Target')), 'Existing summary route protection differs')
        before = support.body(cfn.get_template(StackName=stack_id, TemplateStage='Processed')['TemplateBody'])
        managed = any(x['Type'] == 'AWS::ApiGatewayV2::Route' and x.get('Properties', {}).get('RouteKey') == f'GET /api/v1/{resource}/summary' for x in before['Resources'].values())
        require(not current or managed, 'Existing unmanaged summary route requires review before promotion')
        print(f"{resource}: summary route {'present' if current else 'MISSING'}; Lambda {config['FunctionName']}")
        records.append({'resource': resource, 'nestedLogical': nested, 'functionLogical': function,
            'integrationLogical': integration, 'stack': stack_id, 'stackStamp': support.stamp(stack),
            'function': config['FunctionName'], 'revision': config['RevisionId'], 'oldSha': config['CodeSha256'],
            'api': api, 'reference': reference, 'config': config, 'summaryPresent': bool(current),
            'before': before})
    return parent, root, records


def execute(session, path):
    plan = json.loads(path.read_text())
    require(plan.get('format') == 'navigan-summary-dev-v1' and plan.get('account') == ACCOUNT and plan.get('region') == REGION, 'Wrong release plan')
    parent, root, records = preflight(session)
    require(support.stamp(parent) == plan['parentStamp'], 'Parent changed; prepare again')
    require({r['resource'] for r in plan['records']} == set(SPECS), 'Plan must cover exactly three modules')
    for saved in plan['records']:
        live = next(r for r in records if r['resource'] == saved['resource'])
        require(all(live[k] == saved[k] for k in ('function', 'stack', 'revision', 'oldSha', 'stackStamp', 'functionLogical', 'integrationLogical', 'nestedLogical')), 'Deployment changed since preparation')
    cfn = session.client('cloudformation')
    inspect_plan(cfn, plan['changeSet'], plan['records'])
    cfn.execute_change_set(ChangeSetName=plan['changeSet'])
    print('Waiting for the scoped summary API deployment', flush=True)
    cfn.get_waiter('stack_update_complete').wait(StackName=PARENT, WaiterConfig={'Delay': 10, 'MaxAttempts': 180})
    _, _, deployed = preflight(session)
    for saved in plan['records']:
        current = next(x for x in deployed if x['resource'] == saved['resource'])
        require(current['oldSha'] == saved['newSha'] and current['summaryPresent'], 'Deployed package/summary route verification failed')
    print('Three DEV summary routes and packages verified. Frontend unchanged. Verify authenticated summary 200 responses and disappearance of fallback count requests; remaining list latency is a separate investigation.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', default='navigan')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--prepare', action='store_true')
    mode.add_argument('--execute', type=Path, metavar='PLAN')
    args = parser.parse_args()
    session = boto3.Session(profile_name=args.profile, region_name=REGION)
    if args.execute:
        execute(session, args.execute)
        return
    support.storage.check_checkout()
    dirty = subprocess.check_output(['git', 'status', '--porcelain', '--', 'scripts/deploy-summary-apis-dev.py', 'scripts/deploy-summary-apis-prod.py',
        'scripts/deploy-migration-api-prod.py', 'src/navigan/modules/customer_management',
        'src/navigan/modules/environment_management', 'src/navigan/modules/cluster_management'], cwd=ROOT, text=True)
    require(not dirty.strip(), 'Review/commit local summary release sources first; unrelated files are preserved')
    parent, root, records = preflight(session)
    if not args.prepare:
        print('Read-only check complete. Use --prepare to inspect deployed ZIPs and create an unexecuted scoped release.')
        return
    workspace = support.storage.verify_storage(session, 'artifact-workspace')
    directory = Path(tempfile.mkdtemp(prefix='navigan-dev-summary-'))
    directory.chmod(0o700)
    print('Private rollback/release record: ' + str(directory), flush=True)
    dump(directory / 'parent-original.json', root)
    # Validate every deployed package before uploading or creating changes.
    for r in records:
        dump(directory / f"{r['resource']}-original-template.json", r['before'])
        dump(directory / f"{r['resource']}-original-configuration.json", r['config'])
        deployed = session.client('lambda').get_function(FunctionName=r['function'])
        require(deployed['Configuration']['RevisionId'] == r['revision'], 'Lambda changed during preparation')
        original = directory / f"{r['resource']}-original.zip"
        with urllib.request.urlopen(deployed['Code']['Location'], timeout=60) as stream:
            original.write_bytes(stream.read())
        require(base64.b64encode(hashlib.sha256(original.read_bytes()).digest()).decode() == r['oldSha'], 'Original ZIP checksum mismatch')
        package(original, directory / f"{r['resource']}-updated.zip", r['resource'])
    updated_root = copy.deepcopy(root)
    for r in records:
        data = (directory / f"{r['resource']}-updated.zip").read_bytes()
        code, _ = upload(session, workspace, directory, f"summary-{r['resource']}.zip", data)
        after = proposed_child(r['before'], r['functionLogical'], r['api'], r['reference'], r['resource'], code)
        dump(directory / f"{r['resource']}-updated-template.json", after)
        _, url = upload(session, workspace, directory, f"summary-{r['resource']}-template.json", json.dumps(after).encode())
        updated_root['Resources'][r['nestedLogical']]['Properties']['TemplateURL'] = url
        r['templateHash'] = digest(json.dumps(after, sort_keys=True).encode())
        r['newSha'] = base64.b64encode(hashlib.sha256(data).digest()).decode()
    _, url = upload(session, workspace, directory, 'summary-parent.json', json.dumps(updated_root).encode())
    cfn = session.client('cloudformation')
    request = dict(StackName=PARENT, ChangeSetName='navigan-dev-summary-' + uuid.uuid4().hex[:16], ChangeSetType='UPDATE',
        TemplateURL=url, IncludeNestedStacks=True, Capabilities=['CAPABILITY_NAMED_IAM', 'CAPABILITY_AUTO_EXPAND'],
        Parameters=[{'ParameterKey': p['ParameterKey'], 'UsePreviousValue': True} for p in parent.get('Parameters', [])])
    if parent.get('RoleARN'):
        request['RoleARN'] = parent['RoleARN']
    identifier = cfn.create_change_set(**request)['Id']
    print('Prepared change set: ' + identifier, flush=True)
    cfn.get_waiter('change_set_create_complete').wait(ChangeSetName=identifier, WaiterConfig={'Delay': 5, 'MaxAttempts': 180})
    inspect_plan(cfn, identifier, records)
    public_records = [{k: v for k, v in r.items() if k not in ('config', 'before', 'reference')} for r in records]
    plan = directory / 'release-plan.json'
    dump(plan, {'format': 'navigan-summary-dev-v1', 'account': ACCOUNT, 'region': REGION,
        'parentStamp': support.stamp(parent), 'changeSet': identifier, 'records': public_records})
    print('Summary API release prepared; NOT executed. Release plan: ' + str(plan))


if __name__ == '__main__':
    main()
