import base64
import hashlib
from unittest.mock import Mock
import pytest
from navigan.modules.migration_management.repository_collector import collect, CollectionError
from navigan.modules.migration_management.workspace_collection import claim, finish, enqueue
from navigan.modules.migration_management.handler import route_of
from navigan.shared.errors import ApiError

SOURCE=dict(repository='example/app',commit='a'*40,filePath='app.yaml',format='YAML')
def fixture(files=None):
 files=files or {'app.yaml':b'kind: Deployment\n'}
 blobs={};entries=[]
 for path,raw in files.items():
  sha=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
  entries.append(dict(path=path,sha=sha,type='blob',mode='100644',size=len(raw)))
  blobs[sha]=dict(encoding='base64',content=base64.b64encode(raw).decode())
 calls=[]
 def fetch(url,token):
  calls.append(url)
  return {'tree':entries} if '/git/trees/' in url else blobs[url.rsplit('/',1)[1]]
 return fetch,entries,blobs,calls

def test_pinned_commit_verified_blob_and_unverified_mapping():
 fetch,_,_,calls=fixture();result=collect(SOURCE,fetch=fetch)
 assert '/git/trees/'+SOURCE['commit']+'?recursive=1' in calls[0]
 assert result['files'][0]['contentBase64']
 assert result['validation']['integrity']=='VERIFIED'
 assert result['validation']['deploymentRevision']=='NOT_VERIFIED'
 assert result['validation']['targetReady'] is False

def test_helm_local_bundle_includes_siblings_but_not_outside():
 fetch,*_=fixture({'chart/Chart.yaml':b'name: example','chart/templates/app.yaml':b'kind: Deployment','other.yaml':b'other'})
 result=collect({**SOURCE,'format':'HELM','filePath':'chart/Chart.yaml'},fetch=fetch)
 assert [f['path'] for f in result['files']]==['chart/Chart.yaml','chart/templates/app.yaml']
 assert result['validation']['dependencies']=='REVIEW_REQUIRED'

@pytest.mark.parametrize('path',['../x','/x','a//b','a\\b'])
def test_unsafe_paths_never_fetch(path):
 fetch=Mock()
 with pytest.raises(CollectionError):collect({**SOURCE,'filePath':path},fetch=fetch)
 fetch.assert_not_called()

def test_no_floating_ref():
 with pytest.raises(CollectionError):collect({**SOURCE,'commit':'main'},fetch=Mock())

@pytest.mark.parametrize('mode',['120000','160000'])
def test_symlinks_and_submodules_are_not_followed(mode):
 fetch,entries,_,_=fixture();entries[0]['mode']=mode
 with pytest.raises(CollectionError):collect(SOURCE,fetch=fetch)

def test_blob_mismatch_is_not_collected():
 fetch,_,blobs,_=fixture();next(iter(blobs.values()))['content']=base64.b64encode(b'wrong').decode()
 with pytest.raises(CollectionError) as error:collect(SOURCE,fetch=fetch)
 assert error.value.code=='REPOSITORY_INTEGRITY_FAILED'

def test_truncated_tree_is_not_complete():
 with pytest.raises(CollectionError):collect(SOURCE,fetch=lambda *args:{'truncated':True})

def test_missing_definition_distinct():
 with pytest.raises(CollectionError) as error:collect(SOURCE,fetch=lambda *args:{'tree':[]})
 assert error.value.code=='DEFINITION_NOT_FOUND'

def test_claim_reclaims_expired_lease_and_caps_crashes():
 db=Mock();db.execute.return_value.fetchall.return_value=[]
 claim(db)
 sql=' '.join(c.args[0] for c in db.execute.call_args_list)
 assert 'FOR UPDATE OF j SKIP LOCKED' in sql and 'attempts<3' in sql and 'LEASE_EXHAUSTED' in sql

def test_lost_lease_cannot_publish_result():
 db=Mock();db.execute.return_value.fetchone.return_value=None
 assert finish(db,{'job_id':'job','lease_token':'old'},result={'unused':True}) is False
 assert db.execute.call_count==1
 assert 'lease_until>now()' in db.execute.call_args.args[0]

def test_success_keeps_artifact_collected_not_validated():
 db=Mock();db.execute.return_value.fetchone.return_value={'workspace_id':'w'}
 job=dict(job_id='j',lease_token='t',workspace_id='w',artifact_id='a')
 assert finish(db,job,result=dict(key='k',version='v',sha256='a'*64,size=3,validation='{}'))
 statements=' '.join(c.args[0] for c in db.execute.call_args_list)
 assert "status='COLLECTED'" in statements and "ELSE 'PARTIAL'" in statements
 assert "status='VALIDATED'" not in statements

def test_collection_route_rejects_arbitrary_workspace():
 base='/api/v1/migrations/MIG-'+'a'*32+'/artifact-workspaces/'
 assert route_of('POST',base+'AWS-'+'b'*32+'/collection-jobs')[0]=='workspace_collection_start'
 with pytest.raises(ApiError):route_of('POST',base+'other/collection-jobs')

def test_enqueue_rejects_stale_snapshot_before_insert(monkeypatch):
 from types import SimpleNamespace
 from navigan.modules.migration_management import workspace_collection as module
 migration=dict(customer_id='c',created_by='u',version=2)
 repo=Mock();repo.get.return_value=migration
 service=SimpleNamespace(access=Mock(),repo=repo,deployment_context=lambda _: (migration,{}))
 monkeypatch.setattr(module,'read',lambda *args:{'stale':True})
 with pytest.raises(ApiError) as error:enqueue(service,'m','w',{'version':2})
 assert error.value.code=='STALE_WORKSPACE'
 repo.db.execute.assert_not_called()

def test_worker_does_not_store_upstream_error_body(monkeypatch):
 from contextlib import contextmanager
 from navigan.modules.migration_management import workspace_worker as worker
 @contextmanager
 def tx():yield Mock()
 monkeypatch.setattr(worker,'transaction',tx)
 monkeypatch.setattr(worker,'claim',lambda _:dict(job_id='j',lease_token='t'))
 def fail(*args):raise RuntimeError('credential-and-file-content')
 monkeypatch.setattr(worker,'load_context',fail)
 completion=Mock();monkeypatch.setattr(worker,'finish',completion)
 result=worker.run_once()
 assert result['code']=='COLLECTION_FAILED'
 assert 'credential' not in str(completion.call_args)

def test_worker_idle_has_no_storage_or_fetch(monkeypatch):
 from contextlib import contextmanager
 from navigan.modules.migration_management import workspace_worker as worker
 @contextmanager
 def tx():yield Mock()
 monkeypatch.setattr(worker,'transaction',tx)
 monkeypatch.setattr(worker,'claim',lambda _:None)
 fetch=Mock();monkeypatch.setattr(worker,'collect',fetch)
 assert worker.run_once()=={'processed':False}
 fetch.assert_not_called()
