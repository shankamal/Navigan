#!/usr/bin/env python3
"""Package the deployed-code baseline and prepare unexecuted nested change sets.

Uploads verified artifacts to the existing deployment bucket and creates UPDATE
change sets for one explicitly selected environment. Never executes changes.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from urllib.parse import urlparse
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sam_release_baseline', ROOT / 'scripts/materialize-sam-baseline.py')
baseline = importlib.util.module_from_spec(spec); spec.loader.exec_module(baseline)
read = baseline.read; write = baseline.write; require = baseline.require


def artifact_buckets(record):
    candidates = set()
    for resource in baseline.body(record['templates']['Processed'])['Resources'].values():
        if resource['Type'] != 'AWS::CloudFormation::Stack':
            continue
        value = resource['Properties'].get('TemplateURL')
        require(isinstance(value, str), 'Deployment artifact URL is not a literal S3 URL')
        url = urlparse(value); host = url.hostname or ''
        # Only discover the bucket. Captured version/signature query parameters
        # are neither fetched nor printed, and need not remain valid. Ownership
        # and region are independently verified with the authenticated S3 API.
        require(url.scheme in ('https', 's3') and not url.fragment and not url.username and not url.password,
                'Unexpected deployment artifact URL structure (query values omitted)')
        if url.scheme == 's3':
            require(not url.query and url.port is None, 'Unexpected S3 URI structure')
            bucket = host
        elif host == 's3.amazonaws.com' or re.fullmatch(r's3(?:\.dualstack)?[.-][a-z0-9-]+\.amazonaws\.com', host):
            require(url.port in (None, 443), 'Unexpected deployment artifact URL port')
            bucket = url.path.lstrip('/').split('/')[0]
        else:
            require(url.port in (None, 443), 'Unexpected deployment artifact URL port')
            match = re.fullmatch(r'(.+)\.s3(?:\.dualstack)?(?:[.-][a-z0-9-]+)?\.amazonaws\.com', host)
            require(match, 'Deployment artifact URL is not hosted in S3')
            bucket = match.group(1)
        require(re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', bucket), 'Invalid deployment bucket')
        candidates.add(bucket)
    require(candidates, 'No existing deployment buckets found in captured templates')
    # Scoped releases can leave nested templates in several deployment buckets.
    # Prefer the normal SAM bucket, then use stable lexical ordering.
    return sorted(candidates, key=lambda name: (not name.startswith('aws-sam-cli-managed-'), name))


def artifact_bucket(record):
    return artifact_buckets(record)[0]


def select_artifact_bucket(s3, record, account, region, requested=None):
    candidates = artifact_buckets(record)
    if requested:
        require(requested in candidates, 'Requested bucket is not referenced by this environment capture')
        candidates = [requested]
    rejected = {}
    for bucket in candidates:
        try:
            location = s3.get_bucket_location(Bucket=bucket, ExpectedBucketOwner=account).get('LocationConstraint') or 'us-east-1'
        except Exception as error:
            code = baseline.routes.capture.error_code(error)
            if code not in ('AccessDenied', '403', 'NoSuchBucket', '404'):
                raise
            rejected[code] = rejected.get(code, 0) + 1
            continue
        if ('eu-west-1' if location == 'EU' else location) != region:
            rejected['REGION_MISMATCH'] = rejected.get('REGION_MISMATCH', 0) + 1
            continue
        return bucket
    raise RuntimeError('No captured deployment bucket passed owner/region verification: ' + json.dumps(rejected, sort_keys=True))


def review_change(change):
    resource = change.get('ResourceChange', {})
    allowed = {'AWS::Lambda::Function', 'AWS::IAM::Role', 'AWS::IAM::Policy',
               'AWS::CloudFormation::Stack', 'AWS::ECS::Service'}
    passed = (resource.get('Action') == 'Modify' and resource.get('Replacement') == 'False'
              and resource.get('ResourceType') in allowed)
    return {'logicalId': resource.get('LogicalResourceId'), 'type': resource.get('ResourceType'),
            'action': resource.get('Action'), 'replacement': resource.get('Replacement'), 'reviewPassed': passed}


def resource_references(value):
    """Extract only explicit local resource references; do not evaluate code."""
    found = set()
    if isinstance(value, list):
        for item in value:
            found.update(resource_references(item))
    elif isinstance(value, dict):
        if set(value) == {'Fn::GetAtt'}:
            target = value['Fn::GetAtt']
            if isinstance(target, str):
                target = target.split('.', 1)
            if isinstance(target, list) and len(target) == 2 and all(isinstance(v, str) for v in target):
                found.add(tuple(target))
        elif set(value) == {'Ref'} and isinstance(value['Ref'], str):
            found.add((value['Ref'], 'Ref'))
        for key, item in value.items():
            if key == 'Fn::Sub':
                text = item[0] if isinstance(item, list) and item else item
                if isinstance(text, str):
                    overrides = set(item[1]) if isinstance(item, list) and len(item) == 2 and isinstance(item[1], dict) else set()
                    for name in re.findall(r'\$\{([^}]+)\}', text):
                        if name.startswith('!') or name in overrides:
                            continue
                        parts = name.split('.', 1)
                        found.add((parts[0], parts[1] if len(parts) == 2 else 'Ref'))
            found.update(resource_references(item))
    return found


def dependency_proof(resource, before, after, changes, physical):
    """Explain an unchanged definition's dynamic dependency without hiding risk.

    This evidence does not override a Conditional replacement or deployment gate.
    The original AWS replacement value is retained for review.
    """
    logical = resource.get('LogicalResourceId')
    old = before.get('Resources', {}).get(logical); new = after.get('Resources', {}).get(logical)
    if not old or not new or old != new or resource.get('Action') != 'Modify':
        return None
    if before.get('Conditions', {}) != after.get('Conditions', {}) or before.get('Mappings', {}) != after.get('Mappings', {}):
        return None
    def external_or_unknown(value):
        if isinstance(value, list):
            return any(external_or_unknown(v) for v in value)
        if isinstance(value, dict):
            supported = {'Fn::GetAtt', 'Fn::Sub', 'Fn::Join', 'Fn::If', 'Fn::Select',
                         'Fn::Split', 'Fn::FindInMap', 'Fn::Base64'}
            return any((key.startswith('Fn::') and key not in supported) or external_or_unknown(v)
                       for key, v in value.items())
        return False
    if external_or_unknown(new.get('Properties', {})):
        return None
    identity_fields = {
        'AWS::IAM::Role': ('RoleName', 'Path'),
        'AWS::Events::Rule': ('Name', 'EventBusName'),
        'AWS::Lambda::Function': ('FunctionName',),
        'AWS::S3::Bucket': ('BucketName',),
        'AWS::KMS::Key': (),
    }
    evidence = []
    for target, attribute in sorted(resource_references(new.get('Properties', {}))):
        if target.startswith('AWS::') or target in before.get('Parameters', {}):
            continue
        source_old = before['Resources'].get(target); source_new = after['Resources'].get(target)
        if not source_old or not source_new or not physical.get(target) or source_old['Type'] != source_new['Type']:
            return None
        proposed = changes.get(target)
        if proposed:
            if proposed.get('Action') != 'Modify' or proposed.get('Replacement') != 'False':
                return None
            fields = identity_fields.get(source_old['Type'])
            if fields is None or attribute not in ('Arn', 'Ref'):
                return None
            if any(source_old.get('Properties', {}).get(k) != source_new.get('Properties', {}).get(k) for k in fields):
                return None
            if source_old.get('Condition') != source_new.get('Condition'):
                return None
        elif source_old != source_new:
            return None
        evidence.append({'resource': target, 'attribute': attribute,
                         'referenceChange': proposed.get('Replacement') if proposed else 'not-changed'})
    if not evidence:
        return None
    return {'definitionUnchanged': True, 'referencedIdentitiesStable': True, 'references': evidence,
            'conditionalReplacementStillRequiresReview': resource.get('Replacement') == 'Conditional'}


def inspect_changes(cfn, change_set, output, seen=None, explain=False, stack_path='root'):
    seen = set() if seen is None else seen
    require(change_set not in seen, 'Repeated nested change set')
    seen.add(change_set)
    details = cfn.describe_change_set(ChangeSetName=change_set)
    require(details['Status'] == 'CREATE_COMPLETE', 'Change set is not complete')
    changes = baseline.routes.capture.items(cfn, 'describe_change_set', 'Changes', ChangeSetName=change_set)
    details['Changes'] = changes
    write(output / (hashlib.sha256(change_set.encode()).hexdigest() + '.json'), details)
    context = None
    if explain:
        before = baseline.body(cfn.get_template(StackName=details['StackId'], TemplateStage='Processed')['TemplateBody'])
        after = baseline.body(cfn.get_template(StackName=details['StackId'], ChangeSetName=change_set,
                                               TemplateStage='Processed')['TemplateBody'])
        current = cfn.describe_stacks(StackName=details['StackId'])['Stacks'][0]
        require(current['StackStatus'] in baseline.routes.capture.STABLE, 'Nested stack is not stable')
        bindings = {p['ParameterKey']: p.get('ParameterValue') for p in current.get('Parameters', [])}
        for parameter in details.get('Parameters', []):
            require(parameter.get('UsePreviousValue') is True or
                    parameter.get('ParameterValue') == bindings.get(parameter['ParameterKey']),
                    'Nested change-set parameters differ from the running stack')
            old_parameter = next((p for p in current.get('Parameters', []) if p['ParameterKey'] == parameter['ParameterKey']), {})
            require(parameter.get('ResolvedValue') == old_parameter.get('ResolvedValue'), 'Resolved parameter values differ')
        live = baseline.routes.capture.items(cfn, 'list_stack_resources', 'StackResourceSummaries', StackName=details['StackId'])
        physical = {r['LogicalResourceId']: r['PhysicalResourceId'] for r in live
                    if r.get('PhysicalResourceId') and r.get('ResourceStatus') != 'DELETE_COMPLETE'}
        context = (before, after, {c['ResourceChange']['LogicalResourceId']: c['ResourceChange'] for c in changes}, physical)
    reviewed = []
    for change in changes:
        item = review_change(change); reviewed.append(item)
        resource = change.get('ResourceChange', {})
        if explain:
            item['stackPath'] = stack_path
            item['scope'] = resource.get('Scope', [])
            item['properties'] = sorted({d.get('Target', {}).get('Name') for d in resource.get('Details', [])
                                         if d.get('Target', {}).get('Attribute') == 'Properties' and d.get('Target', {}).get('Name')})
            proof = dependency_proof(resource, *context)
            if proof:
                item['dependencyEvidence'] = proof
        nested = resource.get('ChangeSetId')
        if resource.get('ResourceType') == 'AWS::CloudFormation::Stack':
            require(nested, 'Nested stack change set is missing; cannot review child operations')
        if nested:
            reviewed.extend(inspect_changes(cfn, nested, output, seen, explain,
                stack_path + '/' + resource['LogicalResourceId']))
    return reviewed


def review_existing(session, directory, private, environment, expected_stack, account, region):
    """Read existing AWS plans; never package, upload, execute, or approve them."""
    summary = read(directory / 'release-summary.json')
    require(summary.get('environment') == environment and summary.get('executed') is False, 'Release environment/status differs')
    records = {p.stem: read(p) for p in (private / 'stacks').glob('*.json')}
    root_arn = records['root']['description']['StackId']
    require(root_arn.split(':stack/', 1)[1].split('/')[0] == expected_stack, 'Unexpected root stack')
    prefix = 'arn:aws:cloudformation:' + region + ':' + account + ':'
    cfn = session.client('cloudformation')
    result = {'environment': environment, 'executed': False, 'deploymentReady': False, 'stages': {}, 'errors': []}
    for stage in summary.get('stages', {}):
        try:
            require(stage in records, 'Stage is not in the environment capture')
            plan = read(directory / stage / 'plan.json')
            expected = records[stage]['description']['StackId']
            require(expected.startswith(prefix + 'stack/') and plan['stackId'] == expected and not plan.get('executed'), 'Unexpected stage target or executed plan')
            require(plan['changeSetId'].startswith(prefix + 'changeSet/'), 'Change-set account/region differs')
            details = cfn.describe_change_set(ChangeSetName=plan['changeSetId'])
            require(details['StackId'] == expected, 'AWS change-set stack differs from saved plan')
            if plan.get('noChanges'):
                result['stages'][stage] = {'noChanges': True, 'changes': []}; continue
            require(details.get('ExecutionStatus') == 'AVAILABLE', 'Change set is no longer available')
            current = cfn.describe_stacks(StackName=expected)['Stacks'][0]
            require(current['StackStatus'] in baseline.routes.capture.STABLE and
                    str(current.get('LastUpdatedTime')) == str(records[stage]['description'].get('LastUpdatedTime')), 'Stack changed since capture')
            # Unchanged definitions are meaningful only while parameter bindings
            # and conditions retain their previous values.
            current_parameters = {p['ParameterKey']: p.get('ParameterValue') for p in current.get('Parameters', [])}
            for parameter in details.get('Parameters', []):
                require(parameter.get('UsePreviousValue') is True or
                        parameter.get('ParameterValue') == current_parameters.get(parameter['ParameterKey']), 'Change-set parameters differ from the running stack')
            changes = inspect_changes(cfn, plan['changeSetId'], directory / stage / 'review-evidence',
                                      explain=True, stack_path=stage)
            result['stages'][stage] = {'changes': changes,
                'scopeReviewPassed': all(c['reviewPassed'] for c in changes)}
        except Exception as error:
            result['errors'].append(baseline.routes.capture.error_record(stage, error))
    write(directory / 'existing-plan-review.json', result)
    return result


def sam_package(template, destination, bucket, prefix, profile, region, log):
    command = ['sam', 'package', '--template-file', str(template), '--output-template-file', str(destination),
               '--s3-bucket', bucket, '--s3-prefix', prefix, '--region', region, '--use-json']
    if profile:
        command.extend(['--profile', profile])
    environment = dict(os.environ, SAM_CLI_TELEMETRY='0', AWS_PAGER='')
    with log.open('w') as stream:
        process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, env=environment)
        while process.poll() is None:
            print('Packaging verified baseline artifacts...', flush=True)
            time.sleep(5)
    require(process.returncode == 0 and destination.is_file(), 'SAM packaging failed; inspect private packaging log')


def restore_package_metadata(before, after):
    """Remove packaging-only changes without permitting property rewrites."""
    result = copy.deepcopy(after)
    require(set(before['Resources']) == set(result['Resources']), 'Packaging changed the resource set')
    for logical, original in before['Resources'].items():
        packaged = result['Resources'][logical]
        require(packaged['Type'] == original['Type'], 'Packaging changed a resource type')
        if 'Metadata' in original:
            packaged['Metadata'] = copy.deepcopy(original['Metadata'])
        else:
            packaged.pop('Metadata', None)
        comparable = copy.deepcopy(packaged)
        if original['Type'] == 'AWS::Lambda::Function':
            code = comparable.get('Properties', {}).get('Code')
            require(isinstance(code, dict) and code.get('S3Bucket') and code.get('S3Key'),
                    'Packaged Lambda code is not an S3 ZIP reference')
            comparable['Properties']['Code'] = copy.deepcopy(original['Properties']['Code'])
        require(comparable == original, 'Packaging changed resource fields beyond code and packaging metadata')
    before_top = {k: v for k, v in before.items() if k != 'Resources'}
    after_top = {k: v for k, v in result.items() if k != 'Resources'}
    require(before_top == after_top, 'Packaging changed template-level fields')
    return result


def package(template, destination, bucket, prefix, profile, region, log, s3=None, expected_owner=None, active=None):
    """Package children first so metadata is restored before any child upload.

    SAM adds SamResourceId metadata even to native resources. Restoring only the
    root after recursive packaging would leave that churn in uploaded children.
    """
    template = template.resolve(); active = set() if active is None else active
    require(template not in active, 'Repeated nested template reference')
    active.add(template)
    try:
        original = read(template)
        for resource in original['Resources'].values():
            if resource['Type'] != 'AWS::CloudFormation::Stack':
                continue
            value = resource.get('Properties', {}).get('TemplateURL')
            if isinstance(value, str) and urlparse(value).scheme in ('https', 's3'):
                continue
            require(isinstance(value, str), 'Nested template must be a literal local path')
            child = Path(value).resolve()
            require(child.is_file() and child.is_relative_to(template.parent), 'Nested template escapes the generated baseline')
            require(s3 is not None and expected_owner, 'Nested packaging requires the verified artifact bucket client and owner')
            child_output = destination.parent / (child.stem + '-packaged.json')
            package(child, child_output, bucket, prefix, profile, region,
                    destination.parent / (child.stem + '-package.log'), s3, expected_owner, active)
            raw = child_output.read_bytes(); key = prefix + '/templates/' + hashlib.sha256(raw).hexdigest() + '.json'
            s3.put_object(Bucket=bucket, Key=key, Body=raw, ExpectedBucketOwner=expected_owner)
            resource['Properties']['TemplateURL'] = 'https://' + bucket + '.s3.' + region + '.amazonaws.com/' + key
        prepared_input = destination.parent / (template.stem + '-package-input.json')
        write(prepared_input, original)
        sam_package(prepared_input, destination, bucket, prefix, profile, region, log)
        write(destination, restore_package_metadata(original, read(destination)))
    finally:
        active.remove(template)


def prepare_stack(cfn, s3, record, packaged, bucket, prefix, output):
    previous = record['description']; current = cfn.describe_stacks(StackName=previous['StackId'])['Stacks'][0]
    require(current['StackStatus'] in baseline.routes.capture.STABLE and
            str(current.get('LastUpdatedTime')) == str(previous.get('LastUpdatedTime')), 'Stack changed before preparation')
    raw = packaged.read_bytes(); key = prefix + '/' + packaged.name
    s3.put_object(Bucket=bucket, Key=key, Body=raw,
                  ExpectedBucketOwner=current['StackId'].split(':')[4])
    template_url = 'https://' + bucket + '.s3.' + current['StackId'].split(':')[3] + '.amazonaws.com/' + key
    request = {'StackName': current['StackId'], 'ChangeSetName': 'sam-baseline-' + uuid.uuid4().hex[:12],
        'ChangeSetType': 'UPDATE', 'TemplateURL': template_url, 'IncludeNestedStacks': True,
        'Capabilities': ['CAPABILITY_NAMED_IAM', 'CAPABILITY_AUTO_EXPAND'],
        'Parameters': [{'ParameterKey': p['ParameterKey'], 'UsePreviousValue': True} for p in current.get('Parameters', [])],
        'Description': 'Reconcile deployed code/settings; unexecuted baseline review'}
    if current.get('RoleARN'):
        request['RoleARN'] = current['RoleARN']
    if current.get('Tags'):
        request['Tags'] = current['Tags']
    created = cfn.create_change_set(**request)
    plan = {'stackId': created['StackId'], 'changeSetId': created['Id'], 'executed': False, 'reviewPassed': False}
    write(output / 'plan.json', plan)
    for _ in range(120):
        state = cfn.describe_change_set(ChangeSetName=created['Id'])
        if state['Status'] == 'CREATE_COMPLETE':
            break
        if state['Status'] == 'FAILED':
            reason = state.get('StatusReason', '').lower()
            if "didn't contain changes" in reason or 'no updates are to be performed' in reason:
                plan.update(noChanges=True, reviewPassed=True); write(output / 'plan.json', plan)
                return {'noChanges': True, 'reviewPassed': True, 'changes': []}
            write(output / 'failed-change-set.json', state)
            raise RuntimeError('Change-set preparation failed; inspect private failed-change-set.json')
        require(state['Status'] in ('CREATE_PENDING', 'CREATE_IN_PROGRESS'), 'Unexpected change-set status')
        print('Waiting for baseline change set and nested review...', flush=True); time.sleep(5)
    else:
        raise RuntimeError('Change-set preparation still running; inspect saved plan before retrying')
    require(state.get('ExecutionStatus') == 'AVAILABLE', 'Change set is not available')
    changes = inspect_changes(cfn, created['Id'], output / 'changes')
    passed = all(c['reviewPassed'] for c in changes)
    plan['reviewPassed'] = passed; write(output / 'plan.json', plan)
    return {'noChanges': False, 'reviewPassed': passed, 'changes': changes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture-directory', type=Path, required=True)
    parser.add_argument('--environment', choices=['dev', 'prod'], required=True)
    parser.add_argument('--expected-stack', required=True); parser.add_argument('--expected-account', required=True)
    parser.add_argument('--profile'); parser.add_argument('--region', required=True)
    parser.add_argument('--artifact-bucket', help='Optional explicit bucket already referenced by the captured environment')
    parser.add_argument('--review-directory', type=Path, help='Read-only review of existing saved change sets; no packaging or AWS writes')
    args = parser.parse_args()
    if not args.review_directory:
        require(shutil.which('sam'), 'AWS SAM CLI is not available in PATH')
    source = args.capture_directory.resolve(); private = source / args.environment
    summary = read(source / 'reconciliation-summary.json')
    require(not summary['environments'][args.environment].get('errors'), 'Capture has errors')
    root = read(private / 'stacks/root.json'); arn = root['description']['StackId']
    require(arn.startswith('arn:aws:cloudformation:' + args.region + ':' + args.expected_account + ':stack/')
            and arn.split(':stack/')[1].split('/')[0] == args.expected_stack, 'Unexpected target environment')
    import boto3
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    require(session.client('sts').get_caller_identity()['Account'] == args.expected_account, 'Unexpected AWS account')
    if args.review_directory:
        result = review_existing(session, args.review_directory.resolve(), private, args.environment,
                                 args.expected_stack, args.expected_account, args.region)
        compact = {'environment': args.environment, 'executed': False, 'deploymentReady': False,
                   'stages': {}, 'errors': result['errors']}
        for stage, data in result['stages'].items():
            changes = data.get('changes', [])
            compact['stages'][stage] = {'noChanges': data.get('noChanges', False), 'changes': len(changes),
                'unchangedDependenciesExplained': sum('dependencyEvidence' in c for c in changes),
                'blocked': [{'stackPath': c['stackPath'], 'logicalId': c['logicalId'], 'type': c['type'],
                             'replacement': c['replacement'], 'properties': c['properties'],
                             'dependencyEvidence': c.get('dependencyEvidence')}
                            for c in changes if not c['reviewPassed']]}
        write(args.review_directory / 'existing-plan-review-summary.json', compact)
        print(json.dumps(compact, indent=2))
        print('Read-only review complete. No change sets created, approved or executed; no artifacts uploaded.')
        return 2 if result['errors'] else 0
    s3 = session.client('s3'); cfn = session.client('cloudformation')
    bucket = select_artifact_bucket(s3, root, args.expected_account, args.region, args.artifact_bucket)
    print('Existing deployment bucket verified for the expected account and region.', flush=True)
    output = Path(tempfile.mkdtemp(prefix='navigan-sam-release-')); output.chmod(0o700)
    print('Private release directory: ' + str(output), flush=True)
    templates = output / 'templates'
    counts = baseline.materialize(session, private, templates)
    require(counts['unverifiedRoles'] == 0, 'Managed IAM roles are not fully verified')
    records = {p.stem: read(p) for p in (private / 'stacks').glob('*.json')}
    stages = [name for name in sorted(records) if name == 'root' or name == 'frontend'
              or (name.startswith('companion--') and name.count('--') == 1)]
    result = {'environment': args.environment, 'executed': False, 'deploymentReady': False,
              'baselineCounts': counts, 'stages': {}, 'errors': []}
    prefix = 'navigan-sam-baseline/' + uuid.uuid4().hex
    for name in stages:
        try:
            directory = output / name; directory.mkdir()
            packaged = directory / (name + '-packaged.json')
            print('Preparing stage: ' + name, flush=True)
            package(templates / (name + '.json'), packaged, bucket, prefix, args.profile, args.region,
                    directory / 'package.log', s3, args.expected_account)
            result['stages'][name] = prepare_stack(cfn, s3, records[name], packaged, bucket, prefix, directory)
            write(output / 'release-summary.json', result)
        except Exception as error:
            result['errors'].append(baseline.routes.capture.error_record(name, error)); break
    write(output / 'release-summary.json', result)
    print(json.dumps(result, indent=2))
    print('No change sets executed. Share release-summary.json; keep templates, policies and plans private.')
    return 2 if result['errors'] or any(not s['reviewPassed'] for s in result['stages'].values()) else 0


if __name__ == '__main__':
    raise SystemExit(main())
