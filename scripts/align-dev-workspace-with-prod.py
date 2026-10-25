#!/usr/bin/env python3
"""Correct the observed DEV workspace packaging gap using verified live PROD source.

Default/--prepare: AWS reads only, save a private local rollback/release record.
--execute PLAN: update only DEV MigrationFunction code, preserving configuration.
--apply: prepare and execute this same verified correction in one invocation.
No production, schema, IAM, storage, source-agent or collector writes.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import urllib.request
import zipfile

ACCOUNT = '905418045935'
REGION = 'ap-south-1'
BRANCH = 'new_migration_approach_18oct26'
ROOT = Path(__file__).resolve().parents[1]
PARENTS = {'dev': 'navigan-ashok-dev', 'prod': 'navigan-custmanagement-cfnstk'}
DATABASES = {'dev': 'navigan_dev', 'prod': 'navigan'}
PREFIX = 'navigan/modules/migration_management/'
WORKSPACE = PREFIX + 'artifact_workspace.py'
PROD_HASH = '1cd70fe6275537bcbd5c7719ee496c3ade6c9a3f90bcab6d45476d2c75d14e81'
DEV_HASH = '8eae340425badf85f7cc537b57b30c28d59d4b94954a0f1659c8abb823f89bdb'
FORMAT = 'navigan-dev-workspace-parity-v1'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def zip_sha(data):
    return base64.b64encode(hashlib.sha256(data).digest()).decode()


def members(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as package:
        require(len(package.namelist()) == len(set(package.namelist())), 'Duplicate ZIP members rejected')
        return {entry.filename: package.read(entry) for entry in package.infolist()}


def build(dev_raw, prod_raw):
    dev, prod = members(dev_raw), members(prod_raw)
    require(WORKSPACE in dev and WORKSPACE in prod, 'Workspace source missing')
    require(sha(prod[WORKSPACE]) == PROD_HASH, 'PROD workspace differs from the reviewed inventory; re-inspect before copying')
    require(sha(dev[WORKSPACE]) in (DEV_HASH, PROD_HASH), 'Unexpected DEV workspace version; review first')
    migration = lambda files: {k: v for k, v in files.items() if k.startswith(PREFIX) and k.endswith('.py')}
    dm, pm = migration(dev), migration(prod)
    differences = {k for k in set(dm) | set(pm) if dm.get(k) != pm.get(k)}
    require(differences <= {WORKSPACE}, 'Unexpected migration source differences outside the reviewed workspace file')
    if not differences:
        return None
    compile(prod[WORKSPACE], WORKSPACE, 'exec')
    target = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(dev_raw)) as old, zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as new:
        for entry in old.infolist():
            name = entry.filename
            stale = (name.startswith(PREFIX) and name.endswith('.pyc') and
                     Path(name).name.split('.')[0] == 'artifact_workspace')
            if not stale:
                new.writestr(entry, prod[WORKSPACE] if name == WORKSPACE else dev[name])
    result = target.getvalue()
    updated = members(result)
    require(migration(updated) == pm, 'Migration source parity not achieved')
    require(all(value == updated.get(name) for name, value in dev.items()
                if name != WORKSPACE and not (name.startswith(PREFIX) and name.endswith('.pyc') and
                                              Path(name).name.split('.')[0] == 'artifact_workspace')),
            'An unrelated package member changed')
    require(sum(len(v) for v in updated.values()) <= 250 * 1024 * 1024 and len(result) <= 50 * 1024 * 1024,
            'Lambda package limits exceeded')
    return result


def runtime(session, label):
    cfn = session.client('cloudformation')
    parent = PARENTS[label]
    stack = cfn.describe_stacks(StackName=parent)['Stacks'][0]
    require(stack['StackStatus'] in ('CREATE_COMPLETE', 'UPDATE_COMPLETE', 'UPDATE_ROLLBACK_COMPLETE'), 'Parent stack is not stable')
    params = {p['ParameterKey']: p['ParameterValue'] for p in stack['Parameters']}
    require(params.get('DatabaseName') == DATABASES[label], 'Unexpected database identity')
    nested = cfn.describe_stack_resource(StackName=parent, LogicalResourceId='MigrationManagement')['StackResourceDetail']['PhysicalResourceId']
    require(nested.startswith(f'arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/{parent}-MigrationManagement-'), 'Unexpected migration stack')
    name = cfn.describe_stack_resource(StackName=nested, LogicalResourceId='MigrationFunction')['StackResourceDetail']['PhysicalResourceId']
    response = session.client('lambda').get_function(FunctionName=name)
    config = response['Configuration']
    require(config['FunctionArn'].startswith(f'arn:aws:lambda:{REGION}:{ACCOUNT}:function:{parent}-'), 'Unexpected Lambda target')
    require(config.get('PackageType', 'Zip') == 'Zip' and config.get('Runtime') == 'python3.12' and
            config.get('State') == 'Active' and config.get('LastUpdateStatus') == 'Successful', 'Lambda runtime is not stable')
    require(config.get('Environment', {}).get('Variables', {}).get('DB_NAME') == DATABASES[label], 'Lambda database identity mismatch')
    return response


def download(response):
    with urllib.request.urlopen(response['Code']['Location'], timeout=60) as stream:
        raw = stream.read()
    require(zip_sha(raw) == response['Configuration']['CodeSha256'], 'Downloaded package checksum mismatch')
    return raw


def identity(response):
    config = response['Configuration']
    return {k: config[k] for k in ('FunctionName', 'RevisionId', 'CodeSha256')}


def config_fingerprint(config):
    # Never write environment/secret references to the public release plan.
    fields = ('Environment', 'Role', 'VpcConfig', 'Runtime', 'Handler', 'Layers', 'Architectures',
              'Timeout', 'MemorySize', 'EphemeralStorage', 'TracingConfig', 'FileSystemConfigs',
              'DeadLetterConfig', 'KMSKeyArn', 'LoggingConfig')
    return sha(json.dumps({k: config.get(k) for k in fields}, sort_keys=True, default=str).encode())


def execute(session, path):
    plan = json.loads(path.read_text())
    require(plan.get('format') == FORMAT and plan.get('account') == ACCOUNT and plan.get('region') == REGION, 'Invalid DEV parity release plan')
    dev, prod = runtime(session, 'dev'), runtime(session, 'prod')
    require(identity(dev) == plan['dev'] and identity(prod) == plan['prod'], 'Runtime changed since preparation; prepare again')
    require(config_fingerprint(dev['Configuration']) == plan['configuration'], 'DEV configuration changed')
    original = (path.parent / 'dev-original.zip').read_bytes()
    raw = (path.parent / 'dev-updated.zip').read_bytes()
    prod_raw = download(prod)
    require(zip_sha(original) == plan['dev']['CodeSha256'], 'Rollback package checksum mismatch')
    require(build(original, prod_raw) == raw and zip_sha(raw) == plan['newSha'], 'Prepared package does not match reviewed PROD-only correction')
    lam = session.client('lambda')
    lam.update_function_code(FunctionName=dev['Configuration']['FunctionName'],
                             RevisionId=dev['Configuration']['RevisionId'], ZipFile=raw)
    lam.get_waiter('function_updated').wait(FunctionName=dev['Configuration']['FunctionName'])
    current = runtime(session, 'dev')['Configuration']
    require(current['CodeSha256'] == plan['newSha'], 'Deployed code checksum mismatch')
    require(config_fingerprint(current) == plan['configuration'], 'DEV configuration changed during deployment')
    print('DEV workspace correction deployed and verified. Migration module source matches the reviewed PROD baseline.')
    print('DEV configuration preserved. PROD, collectors, source agents and database unchanged. Workflow validation remains required.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', default='navigan')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--prepare', action='store_true')
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--execute', type=Path, metavar='PLAN')
    args = parser.parse_args()
    branch = subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip()
    require(branch == BRANCH, 'Use the existing ' + BRANCH + ' checkout')
    import boto3
    session = boto3.Session(profile_name=args.profile, region_name=REGION)
    require(session.client('sts').get_caller_identity()['Account'] == ACCOUNT, 'Unexpected AWS account')
    if args.execute:
        execute(session, args.execute)
        return
    dev, prod = runtime(session, 'dev'), runtime(session, 'prod')
    original, production = download(dev), download(prod)
    updated = build(original, production)
    if updated is None:
        print('Migration module source already matches reviewed PROD. No correction required.')
        return
    directory = Path(tempfile.mkdtemp(prefix='navigan-dev-workspace-parity-'))
    directory.chmod(0o700)
    (directory / 'dev-original.zip').write_bytes(original)
    (directory / 'dev-updated.zip').write_bytes(updated)
    plan = {'format': FORMAT, 'account': ACCOUNT, 'region': REGION, 'dev': identity(dev), 'prod': identity(prod),
            'newSha': zip_sha(updated), 'configuration': config_fingerprint(dev['Configuration'])}
    path = directory / 'release-plan.json'
    path.write_text(json.dumps(plan, indent=2))
    print('Verified live PROD baseline; prepared one-file DEV workspace correction. No AWS resources changed.')
    print('Release plan: ' + str(path))
    if args.apply:
        execute(session, path)


if __name__ == '__main__':
    main()
