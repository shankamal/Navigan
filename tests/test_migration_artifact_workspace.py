from types import SimpleNamespace
from unittest.mock import Mock
import hashlib
import pytest
from pydantic import ValidationError
from navigan.shared.errors import ApiError
from navigan.modules.migration_management import artifact_workspace as w
from navigan.modules.migration_management.handler import route_of

MID='MIG-'+'a'*32
WID='AWS-'+'b'*32
RESOURCE=dict(apiVersion='apps/v1',kind='Deployment',namespace='shop',name='api')
def row(**values): return dict(workload=RESOURCE,candidates=[],containers=[],**values)
def service():
 m=dict(migration_id=MID,customer_id='CUS-one',version=2,created_by='owner',source_configuration={'sourceClusterId':'SRC-one'})
 s=dict(source_cluster_id='SRC-one',customer_id='CUS-one',delivery_configuration={})
 repo=Mock();repo.get.return_value=m;repo.workspace_collection_state.return_value=([],[])
 repo.get_source_inventory.return_value={'inventory':dict(inventoryDigest='current',inventoryVersion=3,resources=[RESOURCE])}
 return SimpleNamespace(repo=repo,access=Mock(),deployment_context=Mock(return_value=(m,s)))
class S3:
 def put_object(self,**args): self.put=args;return {'VersionId':'one'}
 def head_object(self,**args):
  assert args['VersionId']=='one' and args['ExpectedBucketOwner']=='0'*12
  return dict(ChecksumSHA256=self.put['ChecksumSHA256'],ContentLength=len(self.put['Body']),ServerSideEncryption='aws:kms')
def test_scope_and_reconstruction():
 result=w.plan_artifacts({'workloads':[row(),{**row(),'workload':{**RESOURCE,'namespace':'other'}}]},['shop'])
 assert len(result)==1 and result[0]['status']=='EXPORT_REQUIRED'
 assert result[0]['validationStatus']=='NOT_VALIDATED'
def test_candidate_allowlist():
 result=w.plan_artifacts({'workloads':[{**row(),'candidates':[dict(repository='example/app',commit='a'*40,filePath='app.yaml',token='secret',content='secret')]}]},['shop'])
 assert result[0]['status']=='PENDING_COLLECTION' and 'secret' not in str(result)
@pytest.mark.parametrize('availability,status',[('AVAILABLE','PENDING_COLLECTION'),('NOT_FOUND','RECOVERY_REQUIRED'),('ACCESS_REQUIRED','ACCESS_REQUIRED'),('UNAVAILABLE','CHECK_REQUIRED')])
def test_image_status(availability,status):
 r={**row(),'containers':[dict(name='api',configuredImage='example/app:tag',observedDigests=['sha256:'+'a'*64],registryEvidence={'status':availability})]}
 image=next(a for a in w.plan_artifacts({'workloads':[r]},['shop']) if a['kind']=='IMAGE')
 assert image['status']==status and image['platformStatus']=='NOT_CHECKED'
def test_digest_required_and_deduplication():
 c=dict(configuredImage='example/app:tag',registryEvidence={'status':'AVAILABLE'})
 r={**row(),'containers':[{**c,'name':'one'},{**c,'name':'two'}]}
 images=[a for a in w.plan_artifacts({'workloads':[r]},['shop']) if a['kind']=='IMAGE']
 assert len(images)==1 and len(images[0]['workloads'])==2 and images[0]['status']=='DIGEST_REQUIRED'
@pytest.mark.parametrize('ns',[[],['../other'],['shop','shop'],['UPPER']])
def test_scope_validation(ns):
 with pytest.raises(ValidationError):w.CreateArtifactWorkspace(version=1,inventoryDigest='current',namespaces=ns)
def test_routes_and_path_traversal():
 base='/api/v1/migrations/'+MID+'/artifact-workspaces'
 assert route_of('POST',base)[0]=='artifact_workspace_create'
 assert route_of('GET',base)[0]=='artifact_workspace_list'
 assert route_of('GET',base+'/'+WID)[2]==WID
 with pytest.raises(ApiError):route_of('DELETE',base+'/'+WID)
 with pytest.raises(ApiError):w.workspace_prefix('../other',MID,WID)
def test_storage_integrity():
 s=S3();version,sha=w.persist_manifest(s,'bucket','key','0'*12,'index',{'test':1})
 assert version=='one' and sha==hashlib.sha256(s.put['Body']).hexdigest()
 assert s.put['IfNoneMatch']=='*' and s.put['SSEKMSKeyId']=='key'
@pytest.mark.parametrize('bad',[{'ChecksumSHA256':'wrong'},{'ContentLength':0},{'ServerSideEncryption':'AES256'}])
def test_integrity_rejection(bad):
 s=S3();original=s.head_object;s.head_object=lambda **args:{**original(**args),**bad}
 with pytest.raises(ApiError):w.persist_manifest(s,'bucket','key','0'*12,'index',{})
def test_unversioned_storage_rejected():
 s=S3();s.put_object=lambda **args:{}
 with pytest.raises(ApiError):w.persist_manifest(s,'bucket','key','0'*12,'index',{})
@pytest.mark.parametrize('body,code',[(dict(version=1,inventoryDigest='current',namespaces=['shop']),'CONCURRENT_UPDATE'),(dict(version=2,inventoryDigest='old',namespaces=['shop']),'STALE_INVENTORY'),(dict(version=2,inventoryDigest='current',namespaces=['other']),'UNKNOWN_NAMESPACE')])
def test_reject_before_storage(body,code):
 api=service()
 with pytest.raises(ApiError) as error:w.create(api,MID,body,S3())
 assert error.value.code==code
 api.repo.create_artifact_workspace.assert_not_called()
def test_create_index_only(monkeypatch):
 monkeypatch.setattr(w, 'build_report', lambda *args: {'analysisCurrent': True, 'workloads': []})
 for name,value in [('BUCKET','bucket'),('KMS_KEY','key'),('BUCKET_OWNER','0'*12)]:monkeypatch.setenv('MIGRATION_WORKSPACE_'+name,value)
 api=service();api.repo.list_artifact_workspaces.return_value=[]
 result=w.create(api,MID,dict(version=2,inventoryDigest='current',namespaces=['shop']),S3())
 assert result['status']=='PLANNED' and result['collectedArtifactCount']==0
 api.access.require.assert_called_with('migration.edit')
 api.access.require_customer.assert_called_with('CUS-one','owner')
 api.repo.create_artifact_workspace.assert_called_once()
def test_cross_migration_lookup():
 api=service();api.repo.list_artifact_workspaces.return_value=[]
 with pytest.raises(ApiError) as error:w.read(api,MID,WID)
 assert error.value.status==404
 api.repo.list_artifact_workspaces.assert_called_with(MID,'CUS-one',WID)
def test_stale_workspace():
 api=service();api.repo.list_artifact_workspaces.return_value=[dict(workspace_id=WID,manifest={'artifacts':[]},status='PLANNED',inventory_digest='old',source_cluster_id='SRC-one')]
 assert w.read(api,MID,WID)['stale'] is True


def test_layout_v2_create_is_fresh_and_persists_readable_snapshot_path(monkeypatch):
 from unittest.mock import Mock
 monkeypatch.setenv('MIGRATION_WORKSPACE_LAYOUT_VERSION','2')
 for name,value in [('BUCKET','bucket'),('KMS_KEY','key'),('BUCKET_OWNER','0'*12)]:monkeypatch.setenv('MIGRATION_WORKSPACE_'+name,value)
 monkeypatch.setattr(w,'build_report',lambda *args:{'analysisCurrent':True,'workloads':[row()]})
 reuse=Mock();monkeypatch.setattr('navigan.modules.migration_management.workspace_reuse.carry_forward',reuse)
 api=service();api.repo.get.return_value.update(customer_name='Example Customer',name='Migration Demo')
 api.repo.get_source_inventory.return_value['inventory']['createdAt']='2026-10-31T06:00:00+00:00'
 api.repo.list_artifact_workspaces.return_value=[]
 client=S3();result=w.create(api,MID,dict(version=2,inventoryDigest='current',namespaces=['shop']),client)
 assert result['storageLayoutVersion']==2 and result['collectionMode']=='FRESH'
 assert result['reusedArtifactCount']==0 and result['collectedArtifactCount']==0
 assert result['storage']['prefix'].startswith('navigan/customers/example-customer--')
 assert '/migrations/migration-demo--'+MID[4:16]+'/' in result['storage']['prefix']
 assert '/inventories/inventory-0003--20261031t060000z/workspaces/workspace--' in result['storage']['prefix']
 assert client.put['Key']==result['storage']['prefix']+'workspace-manifest.json'
 reuse.assert_not_called()
 assert w.storage_prefix('CUS-one',MID,result['workspaceId'],result)==result['storage']['prefix']
 with pytest.raises(ApiError):w.storage_prefix('CUS-other',MID,result['workspaceId'],result)
 changed={**result,'storage':{'prefix':'navigan/customers/other/private/'}}
 with pytest.raises(ApiError):w.storage_prefix('CUS-one',MID,result['workspaceId'],changed)
 # A newly captured inventory must get a fresh workspace even when its content
 # digest and analyzed artifacts are identical to the previous snapshot.
 api.repo.list_artifact_workspaces.return_value=[dict(workspace_id=result['workspaceId'],manifest=result,
  inventory_digest='current',source_cluster_id='SRC-one',bucket_name='bucket',status='PLANNED')]
 api.repo.get_source_inventory.return_value['inventory']['inventoryVersion']=4
 result2=w.create(api,MID,dict(version=2,inventoryDigest='current',namespaces=['shop']),client)
 assert result2['workspaceId']!=result['workspaceId'] and result2['inventoryVersion']==4
 assert w.read(api,MID,result['workspaceId'])['stale'] is True


@pytest.mark.parametrize('kind,folder',[('REPOSITORY_DEFINITION','repository-files/'),('IMAGE','container-images/'),('RECOVERY','source-recovery/'),('REVIEW','reports/reviews/')])
def test_layout_v2_artifact_categories_are_consistent(kind,folder):
 assert w.artifact_folder({'storageLayoutVersion':2},kind)==folder
 assert w.storage_prefix('CUS-one',MID,WID)==w.workspace_prefix('CUS-one',MID,WID)


@pytest.mark.parametrize('status', ['COLLECTED', 'EXCLUDED_FROM_REPLAY'])
def test_saved_locations_use_exact_database_object_even_for_old_inventory(status):
 api=service()
 artifact=dict(artifactId='ART-one',kind='LIVE_DEFINITION',status='EXPORT_REQUIRED')
 api.repo.list_artifact_workspaces.return_value=[dict(workspace_id=WID,bucket_name='private-bucket',
  manifest={'artifacts':[artifact]},status='PARTIAL',inventory_digest='old',source_cluster_id='SRC-one')]
 api.repo.workspace_collection_state.return_value=([dict(artifact_id='ART-one',status=status,validation={},
  object_key='customers/CUS-one/migrations/'+MID+'/workspaces/older/retained-object',
  object_version='immutable-version',sha256='a'*64,size_bytes=123)],[])
 result=w.read(api,MID,WID)
 stored=result['artifacts'][0]['storage']
 assert stored==dict(bucket='private-bucket',key='customers/CUS-one/migrations/'+MID+'/workspaces/older/retained-object',
  versionId='immutable-version',sha256='a'*64,sizeBytes=123)
 assert result['stale'] is True and result['inventoryDigest']=='old'


def test_uncollected_artifact_does_not_retain_old_manifest_storage():
 api=service()
 api.repo.list_artifact_workspaces.return_value=[dict(workspace_id=WID,bucket_name='private-bucket',
  manifest={'artifacts':[dict(artifactId='ART-one',status='COLLECTED',storage={'key':'old'})]},
  status='PARTIAL',inventory_digest='current',source_cluster_id='SRC-one')]
 api.repo.workspace_collection_state.return_value=([dict(artifact_id='ART-one',status='RECOVERY_REQUIRED',validation={})],[])
 assert 'storage' not in w.read(api,MID,WID)['artifacts'][0]


def historical_context(monkeypatch):
 import json
 from unittest.mock import Mock
 for name,value in [('BUCKET','bucket'),('KMS_KEY','key'),('BUCKET_OWNER','0'*12)]:
  monkeypatch.setenv('MIGRATION_WORKSPACE_'+name,value)
 api=service(); api.principal=SimpleNamespace(user_id='reviewer')
 resource=dict(apiVersion='batch/v1',kind='Job',namespace='shop',name='check-123')
 parent={**resource,'kind':'CronJob','name':'check'}
 failed={'recovery':{'jobId':'REC-'+'e'*32,'status':'CUSTOMER_INPUT_REQUIRED','message':'Source export unavailable'}}
 artifacts=[dict(artifactId='ART-'+'1'*64,kind='LIVE_DEFINITION',status='RECOVERY_REQUIRED',source={'resource':resource},workloads=[resource]),
            dict(artifactId='ART-'+'2'*64,kind='REPOSITORY_DEFINITION',status='COLLECTED',source={'filePath':'operations.yaml'},workloads=[parent]),
            dict(artifactId='ART-'+'3'*64,kind='IMAGE',status='COLLECTED',source={'digest':'sha256:'+'a'*64},workloads=[parent])]
 state=[dict(artifact_id=a['artifactId'],status=a['status'],validation=failed if i==0 else {}) for i,a in enumerate(artifacts)]
 manifest=dict(workspaceId=WID,migrationId=MID,customerId='CUS-one',inventoryDigest='current',artifacts=artifacts)
 api.repo.list_artifact_workspaces.return_value=[dict(workspace_id=WID,bucket_name='bucket',manifest=manifest,status='PARTIAL',inventory_digest='current',source_cluster_id='SRC-one')]
 api.repo.workspace_collection_state.return_value=(state,[])
 prefix=w.workspace_prefix('CUS-one',MID,WID)
 objects=[dict(artifact_id=a['artifactId'],object_key=prefix+a['artifactId'],object_version='saved-version',sha256='a'*64,size_bytes=5) for a in artifacts[1:]]
 def execute(sql,params):
  cursor=Mock()
  if sql.startswith('SELECT artifact_id,object_key'):
   cursor.fetchall.return_value=objects
  if "SET status='EXCLUDED_FROM_REPLAY'" in sql:
   state[0].update(status='EXCLUDED_FROM_REPLAY',validation=json.loads(params[0]))
  return cursor
 api.repo.db.execute.side_effect=execute
 body=dict(version=2,recovery=dict(operation='EXCLUDE_HISTORICAL_JOB',workspaceId=WID,artifactId=artifacts[0]['artifactId'],
          parentArtifactId=artifacts[1]['artifactId'],parentCronJobName='check',confirmHistoricalRun=True))
 client=S3();client.put_object=Mock(wraps=client.put_object)
 return api,body,client,state,artifacts,objects


def test_historical_job_receipt_preserves_failed_export_and_pinned_parent_versions(monkeypatch):
 import json
 api,body,client,state,artifacts,objects=historical_context(monkeypatch)
 result=w.exclude_historical_job(api,MID,body,client)
 assert result['artifacts'][0]['status']=='EXCLUDED_FROM_REPLAY'
 assert result['collectedArtifactCount']==2
 assert result['excludedArtifactCount']==1 and result['requiredArtifactCount']==2 and result['unresolvedArtifactCount']==0
 receipt=json.loads(client.put['Body'])
 assert receipt['kind']=='HISTORICAL_JOB_REVIEW'
 assert receipt['previousValidation']['recovery']['status']=='CUSTOMER_INPUT_REQUIRED'
 assert receipt['collectedParentObjects']==objects
 review=receipt['review']
 assert review['parentOwnership']=='OPERATOR_ASSERTED' and review['sourceAbsence']=='OPERATOR_CONFIRMED'
 assert review['replayRequired'] is False and review['targetReady'] is False
 assert review['reviewedBy']=='reviewer' and review['parent']['name']=='check'
 assert state[0]['validation']['recovery']['status']=='CUSTOMER_INPUT_REQUIRED'
 assert client.put['Key'].startswith(w.workspace_prefix('CUS-one',MID,WID)+'reviews/')
 api.access.require.assert_any_call('migration.edit')
 api.access.require_customer.assert_called_with('CUS-one','owner')
 w.exclude_historical_job(api,MID,body,client)
 assert client.put_object.call_count==1


@pytest.mark.parametrize('change,code',[
 ('confirmation','HISTORICAL_REVIEW_REQUIRED'),('version','CONCURRENT_UPDATE'),('stale','STALE_WORKSPACE'),
 ('wrong_kind','HISTORICAL_JOB_REQUIRED'),('active','FAILED_JOB_EXPORT_REQUIRED'),('no_failed_export','FAILED_JOB_EXPORT_REQUIRED'),
 ('parent_namespace','SAVED_CRONJOB_REQUIRED'),('parent_other_workspace','SAVED_CRONJOB_REQUIRED'),
 ('parent_not_saved','SAVED_CRONJOB_REQUIRED'),('image_not_saved','CRONJOB_IMAGES_REQUIRED'),
 ('image_not_pinned','CRONJOB_IMAGES_REQUIRED'),('no_image','CRONJOB_IMAGES_REQUIRED'),
 ('parent_version','PARENT_STORAGE_EVIDENCE_REQUIRED'),('parent_prefix','PARENT_STORAGE_EVIDENCE_REQUIRED')])
def test_historical_review_rejects_unsafe_or_incomplete_exclusions(monkeypatch,change,code):
 api,body,client,state,artifacts,objects=historical_context(monkeypatch)
 if change=='confirmation':body['recovery']['confirmHistoricalRun']=False
 if change=='version':body['version']=1
 if change=='stale':api.repo.list_artifact_workspaces.return_value[0]['inventory_digest']='old'
 if change=='wrong_kind':artifacts[0]['source']['resource']['kind']='Deployment'
 if change=='active':state[0]['status']='RECOVERING'
 if change=='no_failed_export':state[0]['validation']={}
 if change=='parent_namespace':artifacts[1]['workloads'][0]['namespace']='other'
 if change=='parent_other_workspace':body['recovery']['parentArtifactId']='ART-'+'f'*64
 if change=='parent_not_saved':state[1]['status']='PENDING_COLLECTION'
 if change=='image_not_saved':state[2]['status']='PENDING_COLLECTION'
 if change=='image_not_pinned':artifacts[2]['source']['digest']=None
 if change=='no_image':artifacts.pop()
 if change=='parent_version':objects[0]['object_version']='null'
 if change=='parent_prefix':objects[0]['object_key']='customers/another-customer/file'
 with pytest.raises(ApiError) as error:w.exclude_historical_job(api,MID,body,client)
 assert error.value.code==code
 client.put_object.assert_not_called()
 assert state[0]['status']!='EXCLUDED_FROM_REPLAY'


def test_historical_receipt_storage_failure_does_not_exclude_job(monkeypatch):
 api,body,client,state,_,_=historical_context(monkeypatch)
 client.head_object=lambda **kwargs:dict(ChecksumSHA256='wrong')
 with pytest.raises(ApiError) as error:w.exclude_historical_job(api,MID,body,client)
 assert error.value.code=='WORKSPACE_STORAGE_FAILED'
 assert state[0]['status']=='RECOVERY_REQUIRED'


def test_historical_review_requires_customer_authorization(monkeypatch):
 api,body,client,_,_,_=historical_context(monkeypatch)
 api.access.require_customer.side_effect=ApiError(403,'FORBIDDEN','Forbidden')
 with pytest.raises(ApiError):w.exclude_historical_job(api,MID,body,client)
 client.put_object.assert_not_called()


def test_reviewed_job_cannot_be_overwritten_by_recovery_poll(monkeypatch):
 from navigan.modules.migration_management.artifact_recovery import workspace_context
 api,body,client,_,_,_=historical_context(monkeypatch)
 w.exclude_historical_job(api,MID,body,client)
 with pytest.raises(ApiError) as error:workspace_context(api,MID,{**body['recovery'],'operation':'POLL'})
 assert error.value.code=='HISTORICAL_REVIEW_EXISTS'


def test_historical_confirmation_schema_requires_boolean_not_text():
 from navigan.modules.migration_management.deployment_sources import AnalyzeDeploymentSources
 value=dict(version=2,recovery=dict(operation='EXCLUDE_HISTORICAL_JOB',confirmHistoricalRun='true'))
 with pytest.raises(ValidationError):AnalyzeDeploymentSources.model_validate(value)
 value['recovery']['confirmHistoricalRun']=True
 assert AnalyzeDeploymentSources.model_validate(value).recovery.confirmHistoricalRun is True


def test_historical_review_uses_existing_recovery_api_without_ssm(monkeypatch):
 from navigan.modules.migration_management.artifact_recovery import recover
 api,body,client,_,_,_=historical_context(monkeypatch)
 calls=[]
 def factory(name):
  calls.append(name)
  assert name=='s3'
  return client
 result=recover(api,MID,body,factory=factory)
 assert result['workspace']['artifacts'][0]['status']=='EXCLUDED_FROM_REPLAY'
 assert calls==['s3']

