import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('target_grants',ROOT/'scripts/repair-target-assessment-grants.py')
release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)


class Data:
    def __init__(self):
        self.rows={label:{'database_name':db,'table_name':release.TABLE,'role_name':release.ROLE,
                   'schema_usage':True,'table_exists':True,**release.EXPECTED} for label,db in release.DATABASES.items()}
        self.rows['prod'].update(can_select=False,can_insert=False)
        self.calls=[];self.pending=None;self.fail_verify=False
    def execute_statement(self,**kwargs):
        self.calls.append(('statement',kwargs))
        label='prod' if kwargs['database']=='navigan' else 'dev'
        if kwargs['sql']==release.GRANT:
            assert label=='prod' and kwargs['transactionId']=='transaction'
            self.pending.update(can_select=True,can_insert=True)
            return {}
        assert kwargs['sql']==release.INSPECT
        row=self.pending if kwargs.get('transactionId') else self.rows[label]
        if self.fail_verify and row.get('can_select'):
            row=copy.deepcopy(row);row['can_insert']=False
        return {'formattedRecords':json.dumps([row])}
    def begin_transaction(self,**kwargs):
        assert kwargs['database']=='navigan'
        self.calls.append(('begin',kwargs));self.pending=copy.deepcopy(self.rows['prod'])
        return {'transactionId':'transaction'}
    def commit_transaction(self,**kwargs):
        self.calls.append(('commit',kwargs));self.rows['prod']=self.pending;self.pending=None
        return {}
    def rollback_transaction(self,**kwargs):
        self.calls.append(('rollback',kwargs));self.pending=None;return {}


class Session:
    def __init__(self,account=release.ACCOUNT):self.data=Data();self.account=account
    def client(self,name):
        if name=='sts':return SimpleNamespace(get_caller_identity=lambda:{'Account':self.account})
        if name=='rds':return SimpleNamespace(describe_db_clusters=lambda **kw:{'DBClusters':[{
            'DBClusterArn':f'arn:aws:rds:{release.REGION}:{release.ACCOUNT}:cluster:aws-infra-platform-db',
            'Status':'available','HttpEndpointEnabled':True}]})
        if name=='cloudformation':
            def describe(StackName):
                label=next(k for k,v in release.PARENTS.items() if v==StackName)
                return {'Stacks':[{'StackStatus':'UPDATE_COMPLETE','Parameters':[
                    {'ParameterKey':'DatabaseName','ParameterValue':release.DATABASES[label]},
                    {'ParameterKey':'ApiDatabaseSecretArn','ParameterValue':f'arn:aws:secretsmanager:{release.REGION}:{release.ACCOUNT}:secret:database'}]}]}
            return SimpleNamespace(describe_stacks=describe)
        assert name=='rds-data';return self.data


def test_default_only_reads_privileges(tmp_path):
    session=Session();release.repair(session,record_root=tmp_path)
    assert all(kind=='statement' and kw['sql']==release.INSPECT for kind,kw in session.data.calls)
    assert not list(tmp_path.iterdir())


def test_apply_grants_only_prod_table_and_preserves_dev(tmp_path):
    session=Session();dev=copy.deepcopy(session.data.rows['dev'])
    after=release.repair(session,apply=True,record_root=tmp_path)
    assert release.privileges(after['prod'])==release.EXPECTED
    assert session.data.rows['dev']==dev
    grants=[kw for kind,kw in session.data.calls if kind=='statement' and kw['sql']!=release.INSPECT]
    assert len(grants)==1 and grants[0]['sql']==release.GRANT and grants[0]['database']=='navigan'
    assert any(kind=='commit' for kind,_ in session.data.calls)
    record=json.loads(next(tmp_path.glob('*/grant-record.json')).read_text())
    assert record['committed'] is True


def test_matching_grants_are_idempotent_noop(tmp_path):
    session=Session();session.data.rows['prod'].update(release.EXPECTED)
    release.repair(session,apply=True,record_root=tmp_path)
    assert not any(kind in ('begin','commit','rollback') for kind,_ in session.data.calls)
    assert not list(tmp_path.iterdir())


def test_failed_grant_verification_rolls_back(tmp_path):
    session=Session()
    execute=session.data.execute_statement
    def fail(**kwargs):
        result=execute(**kwargs)
        if kwargs['sql']==release.GRANT:session.data.pending['can_insert']=False
        return result
    session.data.execute_statement=fail
    with pytest.raises(RuntimeError,match='grant verification failed'):
        release.repair(session,apply=True,record_root=tmp_path)
    assert any(kind=='rollback' for kind,_ in session.data.calls)
    assert not any(kind=='commit' for kind,_ in session.data.calls)
    assert session.data.rows['prod']['can_select'] is False


@pytest.mark.parametrize('label,field,value',[
    ('dev','can_select',False),('prod','can_update',True),('prod','can_delete',True),
    ('prod','schema_usage',False),('prod','table_name',None),('prod','table_exists',False),('prod','database_name','navigan_dev'),
])
def test_unexpected_prerequisites_stop_before_transaction(tmp_path,label,field,value):
    session=Session();session.data.rows[label][field]=value
    with pytest.raises(RuntimeError):release.repair(session,apply=True,record_root=tmp_path)
    assert not any(kind=='begin' for kind,_ in session.data.calls)


def test_wrong_account_stops_before_database():
    session=Session(account='another-account')
    with pytest.raises(RuntimeError,match='Unexpected AWS account'):release.repair(session,True)
    assert session.data.calls==[]


def test_baseline_contains_only_append_read_privileges_for_target_assessments():
    roles=(ROOT/'database/bootstrap/roles.sql').read_text()
    grants=[block for block in roles.split(';') if 'migration_management.migration_target_assessments' in block]
    assert len(grants)==1
    assert 'GRANT SELECT,INSERT ON' in grants[0]
    assert 'UPDATE' not in grants[0] and 'DELETE' not in grants[0]
