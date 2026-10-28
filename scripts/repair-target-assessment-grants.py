#!/usr/bin/env python3
"""Restore the confirmed missing PROD target-assessment table grants.

Default reads only. --apply grants exactly SELECT, INSERT on the existing target
assessment table to navigan_api in PROD, inside a verified transaction. Never
updates DEV, table definitions, application rows, IAM, APIs or collectors.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import tempfile

ACCOUNT,REGION='905418045935','ap-south-1'
PARENTS={'dev':'navigan-ashok-dev','prod':'navigan-custmanagement-cfnstk'}
DATABASES={'dev':'navigan_dev','prod':'navigan'}
TABLE='migration_management.migration_target_assessments'
ROLE='navigan_api'
GRANT='GRANT SELECT, INSERT ON TABLE migration_management.migration_target_assessments TO navigan_api'
EXPECTED={'can_select':True,'can_insert':True,'can_update':False,'can_delete':False}
INSPECT="""SELECT current_database() AS database_name,
 'migration_management.migration_target_assessments' AS table_name,
 to_regclass('migration_management.migration_target_assessments') IS NOT NULL AS table_exists,
 to_regrole('navigan_api')::text AS role_name,
 CASE WHEN to_regrole('navigan_api') IS NOT NULL THEN
 has_schema_privilege('navigan_api','migration_management','USAGE') END AS schema_usage,
 CASE WHEN to_regrole('navigan_api') IS NOT NULL THEN
 has_table_privilege('navigan_api',to_regclass('migration_management.migration_target_assessments'),'SELECT') END AS can_select,
 CASE WHEN to_regrole('navigan_api') IS NOT NULL THEN
 has_table_privilege('navigan_api',to_regclass('migration_management.migration_target_assessments'),'INSERT') END AS can_insert,
 CASE WHEN to_regrole('navigan_api') IS NOT NULL THEN
 has_table_privilege('navigan_api',to_regclass('migration_management.migration_target_assessments'),'UPDATE') END AS can_update,
 CASE WHEN to_regrole('navigan_api') IS NOT NULL THEN
 has_table_privilege('navigan_api',to_regclass('migration_management.migration_target_assessments'),'DELETE') END AS can_delete"""


def require(condition,message):
    if not condition:raise RuntimeError(message)


def connection(session,label,cluster):
    stack=session.client('cloudformation').describe_stacks(StackName=PARENTS[label])['Stacks'][0]
    require(stack['StackStatus'] in ('CREATE_COMPLETE','UPDATE_COMPLETE','UPDATE_ROLLBACK_COMPLETE'),'Parent stack not stable')
    params={p['ParameterKey']:p['ParameterValue'] for p in stack['Parameters']}
    require(params.get('DatabaseName')==DATABASES[label],'Unexpected database identity in '+label)
    secret=params['ApiDatabaseSecretArn']
    require(secret.startswith(f'arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:'),'Unexpected database secret identity')
    return {'resourceArn':cluster['DBClusterArn'],'secretArn':secret,'database':DATABASES[label]}


def inspect(data,connect,transaction=None):
    result=data.execute_statement(**connect,sql=INSPECT,formatRecordsAs='JSON',
        **({'transactionId':transaction} if transaction else {}))
    rows=json.loads(result['formattedRecords'])
    require(len(rows)==1,'Unexpected privilege query result')
    row=rows[0]
    require(row.get('database_name')==connect['database'] and row.get('table_name')==TABLE and row.get('table_exists') is True
            and row.get('role_name')==ROLE and row.get('schema_usage') is True,
            'Database/table/role/schema prerequisite verification failed')
    require(all(type(row.get(k)) is bool for k in EXPECTED),'Incomplete table privilege evidence')
    return row


def privileges(row):return {k:row[k] for k in EXPECTED}


def repair(session,apply=False,record_root=None):
    require(session.client('sts').get_caller_identity()['Account']==ACCOUNT,'Unexpected AWS account')
    cluster=session.client('rds').describe_db_clusters(DBClusterIdentifier='aws-infra-platform-db')['DBClusters'][0]
    require(cluster['DBClusterArn'].startswith(f'arn:aws:rds:{REGION}:{ACCOUNT}:cluster:') and
            cluster.get('Status')=='available' and cluster.get('HttpEndpointEnabled') is True,
            'Expected available Aurora cluster with Data API')
    data=session.client('rds-data')
    connections={label:connection(session,label,cluster) for label in PARENTS}
    before={label:inspect(data,connect) for label,connect in connections.items()}
    require(privileges(before['dev'])==EXPECTED,'DEV does not match the reviewed minimum table grants')
    require(before['prod']['can_update'] is False and before['prod']['can_delete'] is False,
            'Unexpected PROD update/delete grants; inspect before changing access')
    print(json.dumps({'dev':privileges(before['dev']),'prod':privileges(before['prod'])},indent=2))
    if privileges(before['prod'])==EXPECTED:
        print('Target-assessment table grants already match. No change required.')
        return before
    if not apply:
        print('Read-only check complete. --apply restores only the missing PROD SELECT/INSERT table grants.')
        return before
    directory=Path(tempfile.mkdtemp(prefix='navigan-prod-target-grants-',dir=record_root));directory.chmod(0o700)
    record=directory/'grant-record.json'
    record.write_text(json.dumps({'table':TABLE,'role':ROLE,'before':before,'statement':GRANT},indent=2))
    print('Private grant record: '+str(record),flush=True)
    connect=connections['prod']
    transaction=data.begin_transaction(**connect)['transactionId']
    committed=False
    try:
        current=inspect(data,connect,transaction)
        require(privileges(current)==privileges(before['prod']),'PROD privileges changed since inspection')
        data.execute_statement(**connect,transactionId=transaction,sql=GRANT)
        require(privileges(inspect(data,connect,transaction))==EXPECTED,'Target table grant verification failed')
        data.commit_transaction(resourceArn=connect['resourceArn'],secretArn=connect['secretArn'],transactionId=transaction)
        committed=True
    except Exception:
        if not committed:
            data.rollback_transaction(resourceArn=connect['resourceArn'],secretArn=connect['secretArn'],transactionId=transaction)
        raise
    after=inspect(data,connect)
    require(privileges(after)==EXPECTED,'Committed PROD grants could not be verified')
    require(inspect(data,connections['dev'])==before['dev'],'DEV grants changed concurrently; inspect before claiming parity')
    record.write_text(json.dumps({'table':TABLE,'role':ROLE,'before':before,'prodAfter':after,
                                  'statement':GRANT,'committed':True},indent=2))
    print('PROD target-assessment SELECT/INSERT grants committed and verified. DEV grants retained.')
    print('No application rows or table definitions changed. Authenticated target-assessment validation remains required.')
    return {'dev':before['dev'],'prod':after}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',default='navigan');parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    require(subprocess.check_output(['git','branch','--show-current'],cwd=root,text=True).strip()=='new_migration_approach_18oct26',
            'Use the existing migration branch')
    import boto3
    repair(boto3.Session(profile_name=args.profile,region_name=REGION),args.apply)


if __name__=='__main__':main()
