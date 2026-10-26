#!/usr/bin/env python3
"""Package the deployed-code baseline and prepare unexecuted nested change sets.

Uploads verified artifacts to the existing deployment bucket and creates UPDATE
change sets for one explicitly selected environment. Never executes changes.
"""
import argparse
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


def artifact_bucket(record):
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
    require(len(candidates) == 1, 'Existing deployment bucket is ambiguous; inspect captured templates')
    return candidates.pop()


def review_change(change):
    resource = change.get('ResourceChange', {})
    allowed = {'AWS::Lambda::Function', 'AWS::IAM::Role', 'AWS::IAM::Policy',
               'AWS::CloudFormation::Stack', 'AWS::ECS::Service'}
    passed = (resource.get('Action') == 'Modify' and resource.get('Replacement') == 'False'
              and resource.get('ResourceType') in allowed)
    return {'logicalId': resource.get('LogicalResourceId'), 'type': resource.get('ResourceType'),
            'action': resource.get('Action'), 'replacement': resource.get('Replacement'), 'reviewPassed': passed}


def inspect_changes(cfn, change_set, output, seen=None):
    seen = set() if seen is None else seen
    require(change_set not in seen, 'Repeated nested change set')
    seen.add(change_set)
    details = cfn.describe_change_set(ChangeSetName=change_set)
    require(details['Status'] == 'CREATE_COMPLETE', 'Change set is not complete')
    changes = baseline.routes.capture.items(cfn, 'describe_change_set', 'Changes', ChangeSetName=change_set)
    details['Changes'] = changes
    write(output / (hashlib.sha256(change_set.encode()).hexdigest() + '.json'), details)
    reviewed = []
    for change in changes:
        item = review_change(change); reviewed.append(item)
        resource = change.get('ResourceChange', {})
        nested = resource.get('ChangeSetId')
        if resource.get('ResourceType') == 'AWS::CloudFormation::Stack':
            require(nested, 'Nested stack change set is missing; cannot review child operations')
        if nested:
            reviewed.extend(inspect_changes(cfn, nested, output, seen))
    return reviewed


def package(template, destination, bucket, prefix, profile, region, log):
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
    args = parser.parse_args(); require(shutil.which('sam'), 'AWS SAM CLI is not available in PATH')
    source = args.capture_directory.resolve(); private = source / args.environment
    summary = read(source / 'reconciliation-summary.json')
    require(not summary['environments'][args.environment].get('errors'), 'Capture has errors')
    root = read(private / 'stacks/root.json'); arn = root['description']['StackId']
    require(arn.startswith('arn:aws:cloudformation:' + args.region + ':' + args.expected_account + ':stack/')
            and arn.split(':stack/')[1].split('/')[0] == args.expected_stack, 'Unexpected target environment')
    import boto3
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    require(session.client('sts').get_caller_identity()['Account'] == args.expected_account, 'Unexpected AWS account')
    s3 = session.client('s3'); cfn = session.client('cloudformation'); bucket = artifact_bucket(root)
    location = s3.get_bucket_location(Bucket=bucket, ExpectedBucketOwner=args.expected_account).get('LocationConstraint') or 'us-east-1'
    require(('eu-west-1' if location == 'EU' else location) == args.region, 'Deployment bucket is in another region')
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
            package(templates / (name + '.json'), packaged, bucket, prefix, args.profile, args.region, directory / 'package.log')
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
