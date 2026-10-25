import ast
import base64
import hashlib
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('parity_details',ROOT/'scripts/audit-parity-runtime-details.py')
audit=importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_binding_check_does_not_treat_two_missing_values_as_match():
    values=audit.bindings({}, {})
    assert set(values.values())=={'missing-or-different'}


def test_binding_check_detects_prod_database_without_exposing_secret_values():
    baseline={'DB_NAME':'navigan_dev','DB_SECRET_ARN':'private-reference'}
    values=audit.bindings({'DB_NAME':'navigan','DB_SECRET_ARN':'private-reference'},baseline)
    assert values['DB_NAME']=='missing-or-different'
    assert values['DB_SECRET_ARN']=='match'
    assert 'private-reference' not in str(values)


def test_source_report_distinguishes_formatting_from_code_change():
    first=audit.source_report({'navigan/x.py':b'x=1\n'})['navigan/x.py']
    spaced=audit.source_report({'navigan/x.py':b'x = 1\n'})['navigan/x.py']
    changed=audit.source_report({'navigan/x.py':b'x=2\n'})['navigan/x.py']
    assert first['sha256']!=spaced['sha256']
    assert first['astSha256']==spaced['astSha256']
    assert first['astSha256']!=changed['astSha256']


def test_schema_sql_is_catalog_only_select():
    sql=audit.SCHEMA_SQL.upper()
    assert sql.startswith('SELECT')
    for forbidden in ('INSERT INTO','UPDATE ','DELETE FROM','ALTER ','CREATE ','DROP ','COPY '):
        assert forbidden not in sql
    assert 'HAS_TABLE_PRIVILEGE' in sql
    assert 'PG_POLICY' in sql
    assert 'PG_ATTRIBUTE' in sql


def test_table_difference_is_explicit_for_missing_and_changed_objects():
    assert audit.compare({'a':1,'b':2},{'b':3,'c':4})=={'a':'only-dev','b':'different','c':'only-prod'}


def test_error_codes_never_emit_exception_message():
    assert audit.code(RuntimeError('private-reference'))=='RuntimeError'


def test_image_rejects_untrusted_or_unpinned_reference_before_aws():
    with pytest.raises(RuntimeError,match='trusted digest-pinned'):
        audit.inspect_image(object(),'untrusted/image:latest')


def test_package_sources_checks_download_checksum_and_omits_noncode(monkeypatch):
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w') as z:
        z.writestr('navigan/x.py',b'x=1')
        z.writestr('.env',b'private')
    raw=buffer.getvalue()
    monkeypatch.setattr(audit.urllib.request,'urlopen',lambda *a,**k:io.BytesIO(raw))
    response={'Code':{'Location':'private-url'},'Configuration':{
        'CodeSha256':base64.b64encode(hashlib.sha256(raw).digest()).decode()}}
    assert audit.package_sources(response)=={'navigan/x.py':b'x=1'}
    response['Configuration']['CodeSha256']='wrong'
    with pytest.raises(RuntimeError,match='checksum mismatch'):
        audit.package_sources(response)


def test_storage_verifies_all_public_access_flags_and_expected_owner():
    calls=[]
    class S3:
        def head_bucket(self,**kw):calls.append(kw)
        def get_public_access_block(self,**kw):
            calls.append(kw)
            return {'PublicAccessBlockConfiguration':{'BlockPublicAcls':True,'IgnorePublicAcls':True,
                                                       'BlockPublicPolicy':True,'RestrictPublicBuckets':False}}
        def get_bucket_encryption(self,**kw):
            calls.append(kw)
            return {'ServerSideEncryptionConfiguration':{'Rules':[{'ApplyServerSideEncryptionByDefault':
                {'SSEAlgorithm':'aws:kms','KMSMasterKeyID':'dev-key'}}]}}
        def get_bucket_versioning(self,**kw):
            calls.append(kw)
            return {'Status':'Enabled'}
    session=SimpleNamespace(client=lambda name:S3() if name=='s3' else SimpleNamespace(
        describe_key=lambda **kw:{'KeyMetadata':{'KeyState':'Enabled'}}))
    result=audit.storage_status(session,{'MIGRATION_WORKSPACE_BUCKET':'dev-bucket',
        'MIGRATION_WORKSPACE_KMS_KEY':'dev-key','MIGRATION_WORKSPACE_BUCKET_OWNER':audit.ACCOUNT})
    assert result['publicAccessBlocked'] is False
    assert result['kmsConfigurationMatches'] is True
    assert all(c['ExpectedBucketOwner']==audit.ACCOUNT for c in calls)


def test_no_aws_mutation_calls_or_docker_execution_commands():
    tree=ast.parse((ROOT/'scripts/audit-parity-runtime-details.py').read_text())
    methods={n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
    assert not methods & {'update_function_code','update_function_configuration','put_role_policy',
                          'create_change_set','execute_change_set','put_object','send_command'}
    commands=[n.args[0].value for n in ast.walk(tree) if isinstance(n,ast.Call) and
              isinstance(n.func,ast.Name) and n.func.id=='run' and n.args and isinstance(n.args[0],ast.Constant)]
    assert 'create' in commands and 'cp' in commands and 'rm' in commands
    assert not {'run','start','exec'} & set(commands)
