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
 for name,value in [('BUCKET','bucket'),('KMS_KEY','key'),('BUCKET_OWNER','0'*12)]:monkeypatch.setenv('MIGRATION_WORKSPACE_'+name,value)
 api=service();result=w.create(api,MID,dict(version=2,inventoryDigest='current',namespaces=['shop']),S3())
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
