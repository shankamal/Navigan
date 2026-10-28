#!/usr/bin/env python3
"""Read-only collector, schema/grant and storage checks. JSON goes to stdout.

--inspect-images uses local Docker to pull/copy trusted, digest-pinned collector
images, without starting containers. It removes only its own temporary container
and credential directory. No AWS resources or application data are changed.
"""
from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from datetime import datetime, timezone

ACCOUNT, REGION = '905418045935', 'ap-south-1'
PARENTS = {'dev': 'navigan-ashok-dev', 'prod': 'navigan-custmanagement-cfnstk'}
DATABASES = {'dev': 'navigan_dev', 'prod': 'navigan'}
SCHEMA_SQL = """SELECT current_database() AS database_name,
 COALESCE((SELECT jsonb_agg(jsonb_build_object(
 'schema',n.nspname,'table',c.relname,'rls',c.relrowsecurity,'forceRls',c.relforcerowsecurity,
 'columns',(SELECT jsonb_agg(jsonb_build_object('name',a.attname,'type',format_type(a.atttypid,a.atttypmod),
 'notNull',a.attnotnull,'default',pg_get_expr(d.adbin,d.adrelid)) ORDER BY a.attnum)
 FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
 WHERE a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped),
 'constraints',(SELECT jsonb_agg(pg_get_constraintdef(x.oid) ORDER BY pg_get_constraintdef(x.oid))
 FROM pg_constraint x WHERE x.conrelid=c.oid),
 'indexes',(SELECT jsonb_agg(pg_get_indexdef(i.indexrelid) ORDER BY pg_get_indexdef(i.indexrelid))
 FROM pg_index i WHERE i.indrelid=c.oid),
 'policies',(SELECT jsonb_agg(jsonb_build_object('name',p.polname,'cmd',p.polcmd,
 'qual',pg_get_expr(p.polqual,p.polrelid),'check',pg_get_expr(p.polwithcheck,p.polrelid),
 'roles',(SELECT jsonb_agg(r.rolname ORDER BY r.rolname) FROM pg_roles r WHERE r.oid=ANY(p.polroles)),
 'publicRole',0=ANY(p.polroles)) ORDER BY p.polname) FROM pg_policy p WHERE p.polrelid=c.oid),
 'apiPrivileges',CASE WHEN to_regrole('navigan_api') IS NULL THEN NULL ELSE jsonb_build_object(
 'select',has_table_privilege('navigan_api',c.oid,'SELECT'),
 'insert',has_table_privilege('navigan_api',c.oid,'INSERT'),
 'update',has_table_privilege('navigan_api',c.oid,'UPDATE'),
 'delete',has_table_privilege('navigan_api',c.oid,'DELETE')) END)
 ORDER BY n.nspname,c.relname)
 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE c.relkind IN ('r','p') AND n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'),
 '[]'::jsonb) AS tables"""


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def code(error):
    return getattr(error, 'response', {}).get('Error', {}).get('Code', type(error).__name__)


def resources(cfn, stack):
    return [r for page in cfn.get_paginator('list_stack_resources').paginate(StackName=stack)
            for r in page['StackResourceSummaries'] if r.get('PhysicalResourceId')]


def package_sources(response):
    with urllib.request.urlopen(response['Code']['Location'], timeout=60) as stream:
        raw = stream.read()
    require(base64.b64encode(hashlib.sha256(raw).digest()).decode() == response['Configuration']['CodeSha256'], 'ZIP checksum mismatch')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        require(len(z.namelist()) == len(set(z.namelist())), 'Duplicate ZIP members')
        return {n: z.read(n) for n in z.namelist() if n.startswith('navigan/') and n.endswith('.py')}


def source_report(files):
    return {name: {'sha256': digest(raw), 'astSha256': digest(ast.dump(ast.parse(raw), include_attributes=False).encode())}
            for name, raw in sorted(files.items())}


def storage_status(session, env):
    bucket, key = env['MIGRATION_WORKSPACE_BUCKET'], env['MIGRATION_WORKSPACE_KMS_KEY']
    require(env.get('MIGRATION_WORKSPACE_BUCKET_OWNER') == ACCOUNT, 'Wrong workspace owner')
    s3 = session.client('s3')
    s3.head_bucket(Bucket=bucket, ExpectedBucketOwner=ACCOUNT)
    block = s3.get_public_access_block(Bucket=bucket, ExpectedBucketOwner=ACCOUNT)['PublicAccessBlockConfiguration']
    encrypted = s3.get_bucket_encryption(Bucket=bucket, ExpectedBucketOwner=ACCOUNT)['ServerSideEncryptionConfiguration']['Rules']
    return {'ownerVerified': True, 'publicAccessBlocked': all(block.get(k) is True for k in (
        'BlockPublicAcls','IgnorePublicAcls','BlockPublicPolicy','RestrictPublicBuckets')),
        'versioning': s3.get_bucket_versioning(Bucket=bucket, ExpectedBucketOwner=ACCOUNT).get('Status'),
        'kmsConfigurationMatches': any(r.get('ApplyServerSideEncryptionByDefault', {}).get('SSEAlgorithm') == 'aws:kms'
           and r['ApplyServerSideEncryptionByDefault'].get('KMSMasterKeyID') == key for r in encrypted),
        'kmsState': session.client('kms').describe_key(KeyId=key)['KeyMetadata']['KeyState']}


def bindings(env, baseline):
    keys = ('DB_NAME','DB_PROXY_HOST','DB_SECRET_ARN','MIGRATION_WORKSPACE_BUCKET',
            'MIGRATION_WORKSPACE_KMS_KEY','MIGRATION_WORKSPACE_BUCKET_OWNER')
    return {k: 'match' if env.get(k) and env.get(k) == baseline.get(k) else 'missing-or-different' for k in keys}


def role_summary(session, arn):
    iam = session.client('iam'); name = arn.rsplit('/', 1)[-1]
    policies = []
    for page in iam.get_paginator('list_role_policies').paginate(RoleName=name):
        for policy in page['PolicyNames']:
            policies.append({'name': policy, 'document': iam.get_role_policy(RoleName=name,PolicyName=policy)['PolicyDocument']})
    for page in iam.get_paginator('list_attached_role_policies').paginate(RoleName=name):
        for policy in page['AttachedPolicies']:
            version = iam.get_policy(PolicyArn=policy['PolicyArn'])['Policy']['DefaultVersionId']
            policies.append({'name': policy['PolicyName'], 'document': iam.get_policy_version(
                PolicyArn=policy['PolicyArn'],VersionId=version)['PolicyVersion']['Document']})
    # IAM policy documents contain ARNs/conditions, not secret values.
    role = iam.get_role(RoleName=name)['Role']
    return {'policies': policies, 'trust': role['AssumeRolePolicyDocument'],
            'permissionsBoundary': role.get('PermissionsBoundary')}


def inspect_image(session, image):
    registry = ACCOUNT + '.dkr.ecr.' + REGION + '.amazonaws.com'
    require(image.startswith(registry + '/navigan/') and '@sha256:' in image, 'Expected trusted digest-pinned Navigan image')
    auth = session.client('ecr').get_authorization_token(registryIds=[ACCOUNT])['authorizationData'][0]
    username, password = base64.b64decode(auth['authorizationToken']).decode().split(':', 1)
    with tempfile.TemporaryDirectory(prefix='navigan-image-parity-') as temporary:
        root = Path(temporary); root.chmod(0o700)
        docker = ['docker', '--config', str(root / 'auth')]
        def run(*args, **kwargs):
            return subprocess.run([*docker, *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600, **kwargs)
        run('login', '--username', username, '--password-stdin', registry, input=password.encode())
        run('pull', '--platform', 'linux/amd64', image)
        container = run('create','--platform','linux/amd64','--network','none',image).stdout.decode().strip()
        try:
            run('cp',container + ':/app/navigan',str(root / 'navigan'))
            run('cp',container + ':/app/entrypoint.py',str(root / 'entrypoint.py'))
            run('cp',container + ':/app/requirements.txt',str(root / 'requirements.txt'))
            installed = {}
            with tempfile.TemporaryFile() as tar:
                subprocess.run([*docker,'cp',container + ':/usr/local/lib/python3.12/site-packages','-'],
                               check=True,stdout=tar,stderr=subprocess.PIPE,timeout=600)
                tar.seek(0)
                with tarfile.open(fileobj=tar,mode='r|*') as archive:
                    for member in archive:
                        if member.isfile() and member.name.endswith('.dist-info/METADATA'):
                            raw = archive.extractfile(member).read()
                            installed[member.name.rsplit('/',2)[-2]] = digest(raw)
            files = {'navigan/' + str(p.relative_to(root / 'navigan')): p.read_bytes()
                     for p in (root / 'navigan').rglob('*.py')}
            return {'source': source_report(files),'entrypointSha256':digest((root/'entrypoint.py').read_bytes()),
                    'requirementsSha256':digest((root/'requirements.txt').read_bytes()),'installedPackageMetadata':installed}
        finally:
            # This container was created solely for copying files and was never started.
            run('rm', container)


def collect(session, label, cluster_arn, inspect_images):
    cfn = session.client('cloudformation'); parent = PARENTS[label]
    stack = cfn.describe_stacks(StackName=parent)['Stacks'][0]
    params = {p['ParameterKey']:p['ParameterValue'] for p in stack['Parameters']}
    require(params['DatabaseName'] == DATABASES[label], 'Unexpected database')
    nested = cfn.describe_stack_resource(StackName=parent,LogicalResourceId='MigrationManagement')['StackResourceDetail']['PhysicalResourceId']
    fn = cfn.describe_stack_resource(StackName=nested,LogicalResourceId='MigrationFunction')['StackResourceDetail']['PhysicalResourceId']
    api = session.client('lambda').get_function(FunctionName=fn); env = api['Configuration']['Environment']['Variables']
    require(env.get('DB_NAME') == DATABASES[label], 'Migration API database mismatch')
    result = {'errors':[], 'sourceFirst':env.get('MIGRATION_SOURCE_FIRST_ENABLED') == 'true',
              'migrationSources':source_report(package_sources(api))}
    def check(key, callback):
        try: result[key] = callback()
        except Exception as error: result['errors'].append({'check':key,'code':code(error)})
    def database():
        response = session.client('rds-data').execute_statement(resourceArn=cluster_arn,
            secretArn=params['ApiDatabaseSecretArn'],database=DATABASES[label],sql=SCHEMA_SQL,formatRecordsAs='JSON')
        rows = json.loads(response['formattedRecords']); require(len(rows)==1 and rows[0]['database_name']==DATABASES[label], 'Database identity mismatch')
        tables = rows[0]['tables']; tables = json.loads(tables) if isinstance(tables,str) else tables
        require(bool(tables), 'No application schema metadata visible')
        return {t['schema']+'.'+t['table']:t for t in tables}
    check('tables',database)
    check('storage',lambda:storage_status(session,env))
    check('migrationRole',lambda:role_summary(session,api['Configuration']['Role']))
    def repository():
        worker = session.client('lambda').get_function(FunctionName=parent+'-workspace-repositories')
        cfg=worker['Configuration']; worker_env=cfg.get('Environment',{}).get('Variables',{})
        rules=resources(cfn,parent+'-workspace-repositories')
        schedules=[]
        for rule in rules:
            if rule['ResourceType']=='AWS::Events::Rule':
                events=session.client('events'); value=events.describe_rule(Name=rule['PhysicalResourceId'])
                targets=events.list_targets_by_rule(Rule=rule['PhysicalResourceId'])['Targets']
                schedules.append({'state':value['State'],'expression':value.get('ScheduleExpression'),
                                  'targetsWorker':any(t['Arn']==cfg['FunctionArn'] for t in targets)})
        return {'state':cfg.get('State'),'lastUpdate':cfg.get('LastUpdateStatus'),
                'bindings':bindings(worker_env,env),'source':source_report(package_sources(worker)),
                'schedules':schedules,'role':role_summary(session,cfg['Role'])}
    check('repository',repository)
    def images():
        service=next(r for r in resources(cfn,parent+'-workspace-images') if r['ResourceType']=='AWS::ECS::Service')
        identifier=service['PhysicalResourceId']; parts=identifier.split('/'); require(len(parts)>=3,'Cannot resolve ECS cluster')
        ecs=session.client('ecs'); response=ecs.describe_services(cluster=parts[-2],services=[identifier])
        require(not response.get('failures') and len(response.get('services',[]))==1,'ECS service missing')
        svc=response['services'][0]; task=ecs.describe_task_definition(taskDefinition=svc['taskDefinition'])['taskDefinition']
        container=next(c for c in task['containerDefinitions'] if c['name']=='collector')
        variables={x['name']:x['value'] for x in container.get('environment',[])}
        value={'desired':svc['desiredCount'],'running':svc['runningCount'],'pending':svc['pendingCount'],
               'rollouts':[d.get('rolloutState') for d in svc.get('deployments',[])],
               'image':container['image'],'bindings':bindings(variables,env),
               'temporaryStorage':{k:variables.get(k) for k in ('HOME','TMPDIR','XDG_RUNTIME_DIR')},
               'readOnlyRoot':container.get('readonlyRootFilesystem',False),
               'role':role_summary(session,task['taskRoleArn'])}
        if inspect_images:
            value['content']=inspect_image(session,container['image'])
        return value
    check('images',images)
    return result


def compare(dev, prod):
    keys=set(dev)|set(prod)
    return {k:'only-dev' if k not in prod else 'only-prod' if k not in dev else 'different'
            for k in sorted(keys) if dev.get(k)!=prod.get(k)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',default='navigan')
    parser.add_argument('--inspect-images',action='store_true')
    args=parser.parse_args()
    import boto3
    session=boto3.Session(profile_name=args.profile,region_name=REGION)
    require(session.client('sts').get_caller_identity()['Account']==ACCOUNT,'Unexpected account')
    cluster=session.client('rds').describe_db_clusters(DBClusterIdentifier='aws-infra-platform-db')['DBClusters'][0]
    output={'format':1,'observedAt':datetime.now(timezone.utc).isoformat(),'parity':'UNVERIFIED','environments':{}}
    for label in PARENTS:
        try: output['environments'][label]=collect(session,label,cluster['DBClusterArn'],args.inspect_images)
        except Exception as error: output['environments'][label]={'errors':[{'check':'environment','code':code(error)}]}
    dev,prod=(output['environments'][k] for k in ('dev','prod'))
    output['tableDifferences']=compare(dev.get('tables',{}),prod.get('tables',{}))
    output['limits']=['Catalog check covers table columns, constraints, indexes, RLS policies and navigan_api table privileges; not all database objects/grants.',
                     'IAM policy differences require semantic review; inventories do not prove effective cross-account or source access.',
                     'Image inspection copies files from an unstarted local container; it does not prove a successful collection job or compare all OS/native dependencies.',
                     'Authenticated UI/workflow validation and local DEV frontend version remain required.']
    print(json.dumps(output,indent=2,default=str))
    return 2 if any(e.get('errors') for e in output['environments'].values()) else 0


if __name__=='__main__':
    raise SystemExit(main())
