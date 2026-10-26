"""Read-only comparisons for already prepared SAM baseline plans.

Loaded by prepare-sam-baseline-release.py --review-directory --verify-runtime.
No policies, environment values, credentials or package URLs are printed.
"""
import base64
import hashlib
import json
import re


def verify(session, directory, private, account, after_execution=False):
    read = lambda path: json.loads(path.read_text())
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location('runtime_binding_baseline', Path(__file__).with_name('materialize-sam-baseline.py'))
    baseline = importlib.util.module_from_spec(spec); spec.loader.exec_module(baseline)
    records = {p.stem: read(p) for p in (private / 'stacks').glob('*.json')}
    by_id = {record['description']['StackId']: (name, record) for name, record in records.items()}
    external_policies = {r['PhysicalResourceId'] for record in records.values() for r in record['resources']
                         if r['ResourceType'] == 'AWS::IAM::Policy'}
    locks = read(directory / 'templates/code-locks.json')
    cfn = session.client('cloudformation'); iam = session.client('iam'); lam = session.client('lambda')
    roles = {}; uploaded = {}; seen = set(); results = []; errors = []
    def role(name):
        if name not in roles:
            roles[name] = iam.get_role(RoleName=name)['Role']
        return roles[name]
    def mismatch(fields, key, expected, actual):
        if expected != actual:
            fields.append(key)
    for path in sorted(directory.glob('*/review-evidence/*.json')):
        try:
            detail = read(path); stack_id = detail['StackId']
            if stack_id in seen:
                continue
            seen.add(stack_id)
            if stack_id not in by_id:
                raise RuntimeError('Reviewed stack is not in the environment capture')
            name, record = by_id[stack_id]
            current = cfn.describe_stacks(StackName=stack_id)['Stacks'][0]
            if current['StackStatus'] not in baseline.routes.capture.STABLE:
                raise RuntimeError('Stack is not stable during runtime verification')
            template_request = {'StackName': stack_id, 'TemplateStage': 'Processed'}
            if not after_execution:
                template_request['ChangeSetName'] = detail['ChangeSetId']
            source = baseline.body(cfn.get_template(**template_request)['TemplateBody'])
            before = baseline.body(record['templates']['Processed'])
            physical = {r['LogicalResourceId']: r['PhysicalResourceId'] for r in record['resources']}
            parameters = {p['ParameterKey']: p.get('ParameterValue') for p in current.get('Parameters', [])}
            parameters.update({'AWS::AccountId': account, 'AWS::Region': session.region_name,
                'AWS::StackName': stack_id.split(':stack/', 1)[1].split('/')[0], 'AWS::Partition': stack_id.split(':')[1]})
            def value(node):
                if isinstance(node, list):
                    return [value(v) for v in node]
                if not isinstance(node, dict):
                    return node
                if set(node) == {'Ref'}:
                    key = node['Ref']
                    if key in parameters:
                        return parameters[key]
                    if key in physical:
                        return physical[key]
                    raise RuntimeError('Unresolved proposed parameter/reference')
                if set(node) == {'Fn::GetAtt'}:
                    target = node['Fn::GetAtt']; target = target.split('.', 1) if isinstance(target, str) else target
                    if len(target) == 2 and target[1] == 'Arn' and source['Resources'][target[0]]['Type'] == 'AWS::IAM::Role':
                        return role(physical[target[0]])['Arn']
                    raise RuntimeError('Unresolved proposed resource attribute')
                if set(node) == {'Fn::Sub'}:
                    item = node['Fn::Sub']; text, extra = (item, {}) if isinstance(item, str) else item
                    bindings = {**parameters, **{k: value(v) for k, v in extra.items()}}
                    def substitute(match):
                        key = match.group(1)
                        if key not in bindings:
                            raise RuntimeError('Unresolved proposed substitution')
                        return str(bindings[key])
                    return re.sub(r'\$\{([^}]+)\}', substitute, text)
                if any(k.startswith('Fn::') for k in node):
                    raise RuntimeError('Unsupported proposed intrinsic during runtime comparison')
                return {k: value(v) for k, v in node.items()}
            for logical, resource in source['Resources'].items():
                kind = resource['Type']
                if kind not in ('AWS::IAM::Role', 'AWS::Lambda::Function', 'AWS::ECS::Service') or logical not in physical:
                    continue
                fields = []; properties = resource.get('Properties', {})
                if kind == 'AWS::IAM::Role':
                    actual = role(physical[logical])
                    mismatch(fields, 'TrustPolicy', value(properties.get('AssumeRolePolicyDocument')), actual['AssumeRolePolicyDocument'])
                    mismatch(fields, 'ManagedPolicyArns', sorted(value(properties.get('ManagedPolicyArns', []))),
                        sorted(p['PolicyArn'] for p in baseline.routes.capture.items(iam, 'list_attached_role_policies', 'AttachedPolicies', RoleName=actual['RoleName'])))
                    mismatch(fields, 'PermissionsBoundary', value(properties.get('PermissionsBoundary')),
                        actual.get('PermissionsBoundary', {}).get('PermissionsBoundaryArn'))
                    mismatch(fields, 'Path', value(properties.get('Path', '/')), actual.get('Path', '/'))
                    mismatch(fields, 'MaxSessionDuration', value(properties.get('MaxSessionDuration', 3600)), actual.get('MaxSessionDuration', 3600))
                    live = {policy: iam.get_role_policy(RoleName=actual['RoleName'], PolicyName=policy)['PolicyDocument']
                        for policy in baseline.routes.capture.items(iam, 'list_role_policies', 'PolicyNames', RoleName=actual['RoleName'])}
                    proposed = {value(p['PolicyName']): value(p['PolicyDocument']) for p in properties.get('Policies', [])}
                    for policy, document in proposed.items():
                        mismatch(fields, 'InlinePolicy/' + policy, document, live.get(policy))
                    old_names = {value(p['PolicyName']) for p in before['Resources'][logical].get('Properties', {}).get('Policies', [])}
                    if (old_names - proposed.keys()) & live.keys():
                        fields.append('ExistingManagedInlinePolicyWouldBeRemoved')
                    if live.keys() - proposed.keys() - external_policies:
                        fields.append('LiveInlinePoliciesNotDeclared')
                elif kind == 'AWS::Lambda::Function':
                    actual = lam.get_function_configuration(FunctionName=physical[logical])
                    if actual.get('State') != 'Active' or actual.get('LastUpdateStatus') != 'Successful':
                        raise RuntimeError('Lambda is not stable during runtime verification')
                    if actual.get('Environment', {}).get('Error'):
                        raise RuntimeError('Lambda environment is unreadable')
                    expected_lock = locks[name + '--' + logical]
                    mismatch(fields, 'CodeSha256', expected_lock['CodeSha256'], actual['CodeSha256'])
                    # CloudFormation legitimately advances RevisionId while
                    # reapplying identical code/settings. Code hashes and all
                    # configuration comparisons remain mandatory afterward.
                    if not after_execution:
                        mismatch(fields, 'RevisionId', expected_lock['RevisionId'], actual['RevisionId'])
                    defaults = {'Environment': {'Variables': {}}, 'Description': '', 'TracingConfig': {'Mode': 'PassThrough'},
                        'EphemeralStorage': {'Size': 512}, 'Architectures': ['x86_64'], 'Layers': [], 'FileSystemConfigs': [],
                        'DeadLetterConfig': {}, 'KMSKeyArn': None, 'PackageType': 'Zip'}
                    for field in ('Handler', 'Runtime', 'Role', 'Timeout', 'MemorySize', *defaults):
                        declared = value(properties.get(field, defaults.get(field)))
                        live = actual.get(field, defaults.get(field))
                        if field == 'Layers':
                            live = [layer['Arn'] for layer in actual.get('Layers', [])]
                        mismatch(fields, field, declared, live)
                    expected_logging = value(properties.get('LoggingConfig', {'LogFormat': 'Text', 'LogGroup': '/aws/lambda/' + actual['FunctionName']}))
                    mismatch(fields, 'LoggingConfig', expected_logging, actual.get('LoggingConfig', expected_logging))
                    declared_vpc = value(properties.get('VpcConfig', {})); live_vpc = actual.get('VpcConfig', {})
                    for field in ('SubnetIds', 'SecurityGroupIds'):
                        mismatch(fields, 'VpcConfig/' + field, sorted(declared_vpc.get(field, [])), sorted(live_vpc.get(field, [])))
                    mismatch(fields, 'VpcConfig/Ipv6AllowedForDualStack', declared_vpc.get('Ipv6AllowedForDualStack', False), live_vpc.get('Ipv6AllowedForDualStack', False))
                    concurrency = lam.get_function_concurrency(FunctionName=physical[logical]).get('ReservedConcurrentExecutions')
                    mismatch(fields, 'ReservedConcurrentExecutions', value(properties.get('ReservedConcurrentExecutions')), concurrency)
                    code = value(properties['Code'])
                    if not isinstance(code, dict) or not isinstance(code.get('S3Bucket'), str) or not isinstance(code.get('S3Key'), str):
                        raise RuntimeError('Proposed code is not a literal packaged S3 ZIP')
                    code_key = (code['S3Bucket'], code['S3Key'], code.get('S3ObjectVersion'))
                    if code_key not in uploaded:
                        request = {'Bucket': code_key[0], 'Key': code_key[1], 'ExpectedBucketOwner': account}
                        if code_key[2]: request['VersionId'] = code_key[2]
                        response = session.client('s3').get_object(**request)
                        stream = response['Body']
                        try:
                            digest = hashlib.sha256()
                            for chunk in iter(lambda: stream.read(1024 * 1024), b''): digest.update(chunk)
                            uploaded[code_key] = base64.b64encode(digest.digest()).decode()
                        finally:
                            stream.close()
                    mismatch(fields, 'UploadedZipSha256', actual['CodeSha256'], uploaded[code_key])
                else:
                    parts = physical[logical].split('/')
                    response = session.client('ecs').describe_services(cluster=parts[-2], services=[physical[logical]])
                    if response.get('failures') or len(response.get('services', [])) != 1:
                        raise RuntimeError('ECS service is unavailable')
                    service = response['services'][0]
                    mismatch(fields, 'TaskDefinition', value(properties.get('TaskDefinition')), service['taskDefinition'])
                    mismatch(fields, 'DesiredCount', value(properties.get('DesiredCount')), service['desiredCount'])
                results.append({'stack': name, 'resource': logical, 'type': kind, 'matchesLive': not fields, 'differentFields': fields})
        except Exception as error:
            errors.append(baseline.routes.capture.error_record(path.parent.parent.name, error))
    if not results:
        errors.append({'scope': 'runtime', 'code': 'NO_RESOURCES_VERIFIED'})
    result = {'matchesLive': bool(results) and not errors and all(r['matchesLive'] for r in results),
              'resources': results, 'errors': errors, 'deploymentReady': False}
    baseline.write(directory / ('post-execution-runtime-verification.json' if after_execution else 'runtime-binding-verification.json'), result)
    return result
