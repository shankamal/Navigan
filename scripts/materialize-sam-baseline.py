#!/usr/bin/env python3
"""Create a private, packageable review baseline from deployed CFN templates.

Preserves native logical IDs and verified deployed ZIPs. Reads fresh Lambda/IAM
settings but never packages, uploads, imports, deploys, or executes SQL. This is
a reconciliation bridge, not approval to deploy the current branch's source.
"""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('baseline_routes', ROOT / 'scripts/prepare-sam-route-ownership.py')
routes = importlib.util.module_from_spec(spec); spec.loader.exec_module(routes)
require = routes.require; read = routes.read; write = routes.write


def body(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = yaml_body(value)
    require(isinstance(value, dict) and isinstance(value.get('Resources'), dict), 'Invalid processed template')
    require(not any(r.get('Type', '').startswith('AWS::Serverless::') for r in value['Resources'].values()),
            'Capture must contain processed native CloudFormation resources')
    value = copy.deepcopy(value)
    transform = value.pop('Transform', None)
    require(transform in (None, 'AWS::Serverless-2016-10-31', ['AWS::Serverless-2016-10-31']),
            'Unexpected transform requires manual review')
    return value


def yaml_body(value):
    """Read CFN YAML without evaluating arbitrary Python tags or intrinsics."""
    try:
        import yaml
    except ImportError:
        raise RuntimeError('YAML templates require PyYAML; install scripts/requirements-sam-reconciliation.txt with the deployment Python') from None
    class Loader(yaml.SafeLoader):
        pass
    allowed = {'Ref', 'Condition', 'And', 'Base64', 'Cidr', 'Equals', 'FindInMap',
               'GetAtt', 'GetAZs', 'If', 'ImportValue', 'Join', 'Length', 'Not',
               'Or', 'Select', 'Split', 'Sub', 'ToJsonString', 'Transform'}
    def intrinsic(loader, tag, node):
        require(tag in allowed, 'Unsupported CloudFormation YAML intrinsic')
        if isinstance(node, yaml.ScalarNode):
            result = loader.construct_scalar(node)
        elif isinstance(node, yaml.SequenceNode):
            result = loader.construct_sequence(node, deep=True)
        else:
            result = loader.construct_mapping(node, deep=True)
        if tag == 'GetAtt' and isinstance(result, str):
            result = result.split('.', 1)
        return {tag if tag in ('Ref', 'Condition') else 'Fn::' + tag: result}
    Loader.add_multi_constructor('!', intrinsic)
    try:
        return yaml.load(value, Loader=Loader)
    except yaml.YAMLError:
        # Parser diagnostics can embed lines containing private template values.
        raise RuntimeError('Invalid CloudFormation YAML; inspect the private captured template locally') from None


def function_properties(properties, cfg, archive, role_bindings=None):
    result = copy.deepcopy(properties)
    # Keep logical IDs and existing resource attributes. Pin current configuration
    # rather than replacing it with the branch's newer shared source or defaults.
    for key in ('Handler', 'Runtime', 'Role', 'Timeout', 'MemorySize', 'Description',
                'Environment', 'KMSKeyArn', 'TracingConfig', 'DeadLetterConfig',
                'Architectures', 'EphemeralStorage', 'FileSystemConfigs', 'LoggingConfig'):
        if key in cfg:
            result[key] = copy.deepcopy(cfg[key])
        else:
            result.pop(key, None)
    require(not cfg.get('Environment', {}).get('Error'), 'Lambda environment could not be read')
    if 'Environment' in cfg:
        result['Environment'] = {'Variables': copy.deepcopy(cfg['Environment'].get('Variables', {}))}
    if cfg.get('VpcConfig', {}).get('VpcId'):
        result['VpcConfig'] = {k: copy.deepcopy(cfg['VpcConfig'][k]) for k in
            ('SubnetIds', 'SecurityGroupIds', 'Ipv6AllowedForDualStack') if k in cfg['VpcConfig']}
    else:
        result.pop('VpcConfig', None)
    if cfg.get('Layers'):
        result['Layers'] = [layer['Arn'] for layer in cfg['Layers']]
    else:
        result.pop('Layers', None)
    # Preserve a verified same-stack role expression instead of turning it into
    # a literal ARN. Do not assume that any similarly named role is equivalent.
    original_role = properties.get('Role', {})
    target = original_role.get('Fn::GetAtt') if isinstance(original_role, dict) else None
    if isinstance(target, list) and len(target) == 2 and target[1] == 'Arn':
        if (role_bindings or {}).get(target[0]) == cfg.get('Role') and cfg.get('Role'):
            result['Role'] = copy.deepcopy(original_role)
    defaults = {'Description': '', 'TracingConfig': {'Mode': 'PassThrough'},
                'EphemeralStorage': {'Size': 512}, 'Architectures': ['x86_64'], 'FileSystemConfigs': []}
    for key, default in defaults.items():
        if key not in properties and result.get(key) == default:
            result.pop(key, None)
    logging = result.get('LoggingConfig', {})
    if 'LoggingConfig' not in properties and cfg.get('FunctionName') and logging == {
            'LogFormat': 'Text', 'LogGroup': '/aws/lambda/' + cfg['FunctionName']}:
        result.pop('LoggingConfig', None)
    require(cfg.get('PackageType', 'Zip') == 'Zip', 'Only captured ZIP functions are supported')
    result['Code'] = str(archive)
    return result


def materialize(session, private, output):
    locks = routes.baseline(private)
    records = {p.stem: read(p) for p in (private / 'stacks').glob('*.json')}
    require('root' in records, 'Missing root stack')
    templates = {}
    for name, record in records.items():
        try:
            templates[name] = body(record['templates']['Processed'])
        except RuntimeError as error:
            raise RuntimeError('Processed template ' + name + ': ' + str(error)) from None
    cfn = session.client('cloudformation'); lam = session.client('lambda'); iam = session.client('iam')
    for record in records.values():
        previous = record['description']; current = cfn.describe_stacks(StackName=previous['StackId'])['Stacks'][0]
        require(current['StackStatus'] in routes.capture.STABLE and current['StackId'] == previous['StackId'], 'Stack is not stable')
        require(str(current.get('LastUpdatedTime')) == str(previous.get('LastUpdatedTime')), 'Stack changed since capture')
    live_roles = {}
    def fetch_role(name, expected_arn=None):
        fresh = iam.get_role(RoleName=name)['Role']
        require(fresh.get('RoleName') == name, 'IAM role name differs')
        require(not expected_arn or fresh['Arn'] == expected_arn, 'IAM role identity differs')
        policies = [iam.get_role_policy(RoleName=name, PolicyName=n) for n in
                    routes.capture.items(iam, 'list_role_policies', 'PolicyNames', RoleName=name)]
        attached = routes.capture.items(iam, 'list_attached_role_policies', 'AttachedPolicies', RoleName=name)
        live_roles[name] = {'role': fresh, 'inline': policies, 'attached': attached}
    for path in sorted((private / 'iam').glob('role-*.json')):
        captured = read(path); role = captured['role']; name = role['RoleName']
        fetch_role(name, role['Arn'])
    # The original capture found roles through Lambda and active ECS tasks.
    # Also verify template-owned roles used by other resources or inactive tasks.
    for record in records.values():
        for resource in record['resources']:
            if resource['ResourceType'] == 'AWS::IAM::Role' and resource['PhysicalResourceId'] not in live_roles:
                fetch_role(resource['PhysicalResourceId'])
    # Separate AWS::IAM::Policy resources already own these inline policies.
    policy_names = {r['PhysicalResourceId'] for record in records.values() for r in record['resources']
                    if r['ResourceType'] == 'AWS::IAM::Policy'}
    counts = {'stacks': len(records), 'functions': 0, 'roles': 0, 'separatePolicies': 0,
              'services': 0, 'unverifiedRoles': 0}
    for name, record in records.items():
        resources = templates[name]['Resources']
        role_bindings = {r['LogicalResourceId']: live_roles[r['PhysicalResourceId']]['role']['Arn']
                         for r in record['resources'] if r['ResourceType'] == 'AWS::IAM::Role'
                         and r['PhysicalResourceId'] in live_roles}
        for resource in record['resources']:
            logical = resource['LogicalResourceId']; kind = resource['ResourceType']
            require(logical in resources, 'Captured resource missing from processed template')
            props = resources[logical].setdefault('Properties', {})
            if kind == 'AWS::CloudFormation::Stack':
                child = name + '--' + logical
                require(child in templates, 'Nested stack template missing')
                props['TemplateURL'] = str((output / (child + '.json')).resolve())
            elif kind == 'AWS::Lambda::Function':
                key = name + '--' + logical; meta = read(private / 'functions' / (key + '.json'))
                cfg = lam.get_function_configuration(FunctionName=meta['FunctionArn'])
                require(cfg['CodeSha256'] == locks[key]['CodeSha256'] and cfg['RevisionId'] == locks[key]['RevisionId'],
                        'Lambda changed since capture; refresh before preparing a baseline')
                require(cfg.get('State') == 'Active' and cfg.get('LastUpdateStatus') == 'Successful', 'Lambda is not stable')
                resources[logical]['Properties'] = function_properties(props, cfg,
                    (private / meta['deployedArchive']).resolve(), role_bindings)
                concurrency = lam.get_function_concurrency(FunctionName=meta['FunctionArn'])
                if 'ReservedConcurrentExecutions' in concurrency:
                    resources[logical]['Properties']['ReservedConcurrentExecutions'] = concurrency['ReservedConcurrentExecutions']
                else:
                    resources[logical]['Properties'].pop('ReservedConcurrentExecutions', None)
                counts['functions'] += 1
            elif kind == 'AWS::IAM::Role':
                role = live_roles.get(resource['PhysicalResourceId'])
                if role is None:
                    counts['unverifiedRoles'] += 1
                    continue
                props['AssumeRolePolicyDocument'] = role['role']['AssumeRolePolicyDocument']
                if role['role'].get('PermissionsBoundary'):
                    props['PermissionsBoundary'] = role['role']['PermissionsBoundary']['PermissionsBoundaryArn']
                else:
                    props.pop('PermissionsBoundary', None)
                managed = [p['PolicyArn'] for p in role['attached']]
                inline = [{'PolicyName': p['PolicyName'], 'PolicyDocument': p['PolicyDocument']}
                          for p in role['inline'] if p['PolicyName'] not in policy_names]
                if managed or 'ManagedPolicyArns' in props:
                    props['ManagedPolicyArns'] = managed
                if inline or 'Policies' in props:
                    props['Policies'] = inline
                counts['roles'] += 1
            elif kind == 'AWS::IAM::Policy':
                matches = [p['PolicyDocument'] for role in live_roles.values() for p in role['inline']
                           if p['PolicyName'] == resource['PhysicalResourceId']]
                if matches:
                    require(len({json.dumps(p, sort_keys=True) for p in matches}) == 1, 'Shared inline policy documents differ')
                    props['PolicyDocument'] = matches[0]; counts['separatePolicies'] += 1
            elif kind == 'AWS::ECS::Service':
                saved = read(private / 'services' / (name + '--' + logical + '.json'))
                physical = resource['PhysicalResourceId']; cluster = physical.split('/')[-2]
                response = session.client('ecs').describe_services(cluster=cluster, services=[physical])
                require(not response.get('failures') and len(response.get('services', [])) == 1, 'ECS service missing')
                service = response['services'][0]
                require(service['taskDefinition'] == saved['service']['taskDefinition'] and
                        service['desiredCount'] == saved['service']['desiredCount'], 'ECS runtime changed since capture')
                props['TaskDefinition'] = service['taskDefinition']; props['DesiredCount'] = service['desiredCount']
                counts['services'] += 1
        write(output / (name + '.json'), templates[name])
        # UsePreviousValue preserves NoEcho inputs without reading secret values.
        write(output / (name + '-parameters.json'), [{'ParameterKey': p['ParameterKey'], 'UsePreviousValue': True}
              for p in record['description'].get('Parameters', [])])
    write(output / 'code-locks.json', locks)
    write(output / 'iam-locks.json', live_roles)
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture-directory', type=Path, required=True)
    parser.add_argument('--profile'); parser.add_argument('--region', required=True)
    parser.add_argument('--expected-account', required=True); args = parser.parse_args()
    capture = args.capture_directory.resolve(); manifest = read(capture / 'reconciliation-summary.json')
    require(manifest.get('format') == 1 and not any(e.get('errors') for e in manifest['environments'].values()), 'Capture has errors')
    import boto3
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    require(session.client('sts').get_caller_identity()['Account'] == args.expected_account, 'Unexpected AWS account')
    for label in manifest['environments']:
        root = read(capture / label / 'stacks/root.json')['description']['StackId']
        require(root.startswith('arn:aws:cloudformation:' + args.region + ':' + args.expected_account + ':stack/'), 'Capture account or region differs')
    output = Path(tempfile.mkdtemp(prefix='navigan-sam-baseline-')); output.chmod(0o700)
    summary = {'deploymentReady': False, 'executed': False, 'environments': {}}
    for label in manifest['environments']:
        try:
            counts = materialize(session, capture / label, output / label)
            summary['environments'][label] = {'counts': counts, 'errors': []}
        except Exception as error:
            summary['environments'][label] = {'errors': [routes.capture.error_record('baseline', error)]}
        write(output / 'baseline-summary.json', summary)
    print('Private packageable review baseline: ' + str(output))
    print(json.dumps(summary, indent=2))
    print('No AWS writes. Full deployment remains pending review of packaged change sets and unresolved ownership.')
    return 2 if any(e['errors'] for e in summary['environments'].values()) else 0


if __name__ == '__main__':
    raise SystemExit(main())
