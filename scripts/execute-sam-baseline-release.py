#!/usr/bin/env python3
"""Execute an existing DEV baseline only after fresh scope and runtime checks.

Does not build, package, upload, create change sets, or touch PROD/database.
Conditional permission/task-definition updates are permitted only with a fresh
proof of unchanged definitions and stable referenced identities. AWS may still
replace these permissions or register a task revision. Service bindings and all
other existing physical resources must remain unchanged after the update.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import time
import uuid


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


release = module('sam_execution_release', 'prepare-sam-baseline-release.py')
runtime = module('sam_execution_runtime', 'verify-sam-runtime-bindings.py')
read = release.read; write = release.write; require = release.require

DEPENDENCIES = {
    'AWS::S3::BucketPolicy': {'PolicyDocument'},
    'AWS::S3::Bucket': {'BucketEncryption'},
    'AWS::ApiGatewayV2::Integration': {'IntegrationUri'},
    'AWS::Events::Rule': {'Targets'},
    'AWS::CodeBuild::Project': {'ServiceRole'},
    'AWS::Lambda::Permission': {'SourceArn'},
    'AWS::ECS::TaskDefinition': {'TaskRoleArn'},
}
BINDINGS = {'AWS::Lambda::Function', 'AWS::IAM::Role', 'AWS::ECS::Service'}


def allow_change(item, verified):
    """Independent execution gate; never trust a saved reviewPassed flag."""
    require(item.get('action') == 'Modify', 'Execution refuses adds, removals and imports')
    kind = item.get('type'); replacement = item.get('replacement')
    require(replacement in ('False', 'Conditional'), 'Execution refuses resource replacement')
    if kind in BINDINGS:
        require(replacement == 'False', 'Runtime resource must update in place')
        require((item['stackPath'], item['logicalId'], kind) in verified,
                'Changed runtime resource was not verified against live AWS')
        return
    if kind == 'AWS::CloudFormation::Stack':
        require(replacement == 'False' and set(item.get('scope', [])) <= {'Properties'},
                'Unexpected nested stack modification')
        require(set(item.get('properties', [])) <= {'TemplateURL'}, 'Nested stack parameters or configuration changed')
        return
    require(kind in DEPENDENCIES, 'Unsupported resource type in execution scope')
    require(set(item.get('scope', [])) <= {'Properties'}, 'Unexpected dependency resource scope')
    properties = set(item.get('properties', []))
    require(properties and properties <= DEPENDENCIES[kind], 'Unexpected dependency properties')
    proof = item.get('dependencyEvidence') or {}
    require(proof.get('definitionUnchanged') is True and proof.get('referencedIdentitiesStable') is True
            and proof.get('references'), 'Dependency definition or identity is not proven unchanged')
    if replacement == 'Conditional':
        require(kind in ('AWS::Lambda::Permission', 'AWS::ECS::TaskDefinition'),
                'Unexpected conditional replacement type')


def expected_stages(private):
    return {p.stem for p in (private / 'stacks').glob('*.json')
            if p.stem == 'root' or (p.stem.startswith('companion--') and p.stem.count('--') == 1)}


def preflight(session, directory, private, stack, account, region):
    summary = read(directory / 'release-summary.json')
    require(summary.get('environment') == 'dev' and summary.get('executed') is False
            and not summary.get('errors'), 'Release is not an unexecuted DEV plan without errors')
    require(set(summary['stages']) == expected_stages(private), 'Prepared release has missing or unexpected stages')
    review = release.review_existing(session, directory, private, 'dev', stack, account, region)
    require(not review['errors'] and set(review['stages']) == expected_stages(private),
            'Fresh saved-plan review failed; inspect existing-plan-review.json')
    live = runtime.verify(session, directory, private, account)
    require(live.get('matchesLive') is True and not live['errors'],
            'Fresh runtime verification failed; inspect runtime-binding-verification.json')
    # Runtime evidence uses capture filenames; review paths use nested logical IDs.
    verified = {(r['stack'].replace('root--', 'root/'), r['resource'], r['type'])
                for r in live['resources'] if r['matchesLive']}
    allowed = []
    for stage, data in review['stages'].items():
        for item in data.get('changes', []):
            allow_change(item, verified)
            allowed.append({'stage': stage, 'stack': item['stackPath'], 'resource': item['logicalId'],
                            'type': item['type'], 'replacement': item['replacement']})
    require(allowed, 'No executable modifications were reviewed')
    return review, allowed


def inventory(cfn, records):
    result = {}
    for name, record in records.items():
        rows = release.baseline.routes.capture.items(cfn, 'list_stack_resources', 'StackResourceSummaries',
                                                     StackName=record['description']['StackId'])
        result[name] = {r['LogicalResourceId']: {'id': r.get('PhysicalResourceId'), 'type': r['ResourceType']}
                        for r in rows if r.get('ResourceStatus') != 'DELETE_COMPLETE'}
    return result


def check_inventory(before, after, allowed):
    conditional = {(r['stack'].replace('root/', 'root--'), r['resource']) for r in allowed
                   if r['replacement'] == 'Conditional'}
    require(set(before) == set(after), 'Stack inventory changed')
    for name, old in before.items():
        new = after[name]
        require(set(old) == set(new), 'Existing resource set changed during execution')
        for logical, resource in old.items():
            require(resource['type'] == new[logical]['type'], 'Resource type changed during execution')
            require(resource['id'] == new[logical]['id'] or (name, logical) in conditional,
                    'Unexpected resource identity changed during execution')


def wait_for_update(cfn, plan, previous, timeout=3600):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = cfn.describe_stacks(StackName=plan['stackId'])['Stacks'][0]
        status = current['StackStatus']
        print('DEV baseline update: ' + status, flush=True)
        changed = str(current.get('LastUpdatedTime')) != str(previous.get('LastUpdatedTime'))
        if changed and status == 'UPDATE_COMPLETE':
            return
        require(status not in ('UPDATE_FAILED', 'UPDATE_ROLLBACK_IN_PROGRESS', 'UPDATE_ROLLBACK_COMPLETE',
                               'UPDATE_ROLLBACK_FAILED', 'UPDATE_ROLLBACK_COMPLETE_CLEANUP_IN_PROGRESS',
                               'ROLLBACK_COMPLETE', 'ROLLBACK_FAILED', 'DELETE_IN_PROGRESS', 'DELETE_COMPLETE'),
                'Stack failed or entered rollback; later stages were not executed')
        time.sleep(5)
    raise RuntimeError('Update is still running; inspect execution-record.json and AWS stack status before any retry')


def execute(session, directory, private, stack, account, region):
    journal_path = directory / 'execution-record.json'
    require(not journal_path.exists(), 'An execution record already exists; inspect its stage statuses before retrying')
    review, allowed = preflight(session, directory, private, stack, account, region)
    cfn = session.client('cloudformation')
    records = {p.stem: read(p) for p in (private / 'stacks').glob('*.json')}
    before = inventory(cfn, records)
    write(directory / 'pre-execution-inventory.json', before)
    journal = {'environment': 'dev', 'executed': False, 'complete': False,
               'scopeVerified': True, 'runtimeVerified': True, 'stages': {}, 'reviewedChanges': allowed}
    write(journal_path, journal)
    try:
        for stage in review['stages']:
            plan = read(directory / stage / 'plan.json')
            if review['stages'][stage].get('noChanges'):
                journal['stages'][stage] = {'status': 'NO_CHANGES'}; write(journal_path, journal); continue
            # Recheck the exact stage immediately before mutation; no new plan.
            state = cfn.describe_change_set(ChangeSetName=plan['changeSetId'])
            require(state['StackId'] == plan['stackId'] and state['Status'] == 'CREATE_COMPLETE'
                    and state['ExecutionStatus'] == 'AVAILABLE', 'Reviewed change set is no longer available')
            previous = cfn.describe_stacks(StackName=plan['stackId'])['Stacks'][0]
            require(previous['StackStatus'] in release.baseline.routes.capture.STABLE and
                    str(previous.get('LastUpdatedTime')) == str(records[stage]['description'].get('LastUpdatedTime')),
                    'Stage changed after preflight')
            token = 'navigan-dev-baseline-' + uuid.uuid4().hex
            journal['stages'][stage] = {'status': 'REQUESTED', 'clientRequestToken': token,
                                       'stackId': plan['stackId'], 'changeSetId': plan['changeSetId']}
            write(journal_path, journal)
            print('Executing verified DEV stage: ' + stage, flush=True)
            cfn.execute_change_set(ChangeSetName=plan['changeSetId'], StackName=plan['stackId'], ClientRequestToken=token)
            journal['executed'] = True; write(journal_path, journal)
            wait_for_update(cfn, plan, previous)
            journal['stages'][stage]['status'] = 'UPDATE_COMPLETE'; write(journal_path, journal)
        after = inventory(cfn, records)
        write(directory / 'post-execution-inventory.json', after)
        check_inventory(before, after, allowed)
        live = runtime.verify(session, directory, private, account, after_execution=True)
        require(live.get('matchesLive') is True and not live['errors'], 'Post-update runtime verification failed')
        journal['complete'] = True; journal['postRuntimeVerified'] = True
    except Exception as error:
        journal['error'] = release.baseline.routes.capture.error_record('execution', error)
        raise
    finally:
        write(journal_path, journal)
    print('DEV baseline change sets executed and runtime/inventory verified. PROD unchanged.', flush=True)
    print('Maintained source SAM templates and authenticated workflow validation remain separate pending work.', flush=True)
    return journal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release-directory', type=Path, required=True)
    parser.add_argument('--capture-directory', type=Path, required=True)
    parser.add_argument('--environment', choices=['dev'], required=True)
    parser.add_argument('--expected-stack', required=True)
    parser.add_argument('--expected-account', required=True)
    parser.add_argument('--region', required=True); parser.add_argument('--profile')
    args = parser.parse_args()
    private = args.capture_directory.resolve() / 'dev'
    capture = read(args.capture_directory / 'reconciliation-summary.json')
    require(not capture['environments']['dev'].get('errors'), 'DEV capture has errors')
    root = read(private / 'stacks/root.json')['description']['StackId']
    require(root.startswith('arn:aws:cloudformation:' + args.region + ':' + args.expected_account + ':stack/')
            and root.split(':stack/', 1)[1].split('/')[0] == args.expected_stack,
            'Expected account/region/DEV stack differs from capture')
    import boto3
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    require(session.client('sts').get_caller_identity()['Account'] == args.expected_account, 'Unexpected AWS account')
    execute(session, args.release_directory.resolve(), private, args.expected_stack, args.expected_account, args.region)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
