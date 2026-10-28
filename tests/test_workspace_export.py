import base64
import hashlib
import io
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from navigan.shared.errors import ApiError
from navigan.modules.migration_management import workspace_export as export
from navigan.modules.migration_management.artifact_workspace import canonical, workspace_prefix
from navigan.modules.migration_management.handler import route_of

MID='MIG-'+'a'*32
WID='AWS-'+'b'*32
CID='CUS-test'
PREFIX=workspace_prefix(CID,MID,WID)


class Storage:
 def __init__(self):
  self.objects={};self.puts=[];self.heads=[];self.downloads=[];self.gets=[]
 def add(self,key,content,version='saved-version',composite=False):
  sha=hashlib.sha256(content).digest()
  checksum=base64.b64encode(hashlib.sha256(sha).digest() if composite else sha).decode()+('-1' if composite else '')
  self.objects[(key,version)]=dict(body=content,ChecksumSHA256=checksum,ChecksumType='COMPOSITE' if composite else 'FULL_OBJECT',
    ContentLength=len(content),VersionId=version,ServerSideEncryption='aws:kms',SSEKMSKeyId='key')
  return dict(object_key=key,object_version=version,sha256=sha.hex(),size_bytes=len(content))
 def head_object(self,**args):
  assert args['ExpectedBucketOwner']=='0'*12 and args['ChecksumMode']=='ENABLED'
  self.heads.append(args)
  return {k:v for k,v in self.objects[(args['Key'],args['VersionId'])].items() if k!='body'}
 def get_object(self,**args):
  assert args['ExpectedBucketOwner']=='0'*12
  self.gets.append(args)
  return {'Body':io.BytesIO(self.objects[(args['Key'],args['VersionId'])]['body'])}
 def put_object(self,**args):
  assert args['ExpectedBucketOwner']=='0'*12 and args['ServerSideEncryption']=='aws:kms' and args['SSEKMSKeyId']=='key'
  assert args['IfNoneMatch']=='*' and args['ChecksumSHA256']==base64.b64encode(hashlib.sha256(args['Body']).digest()).decode()
  self.puts.append(args)
  self.add(args['Key'],args['Body'],version='export-version')
  return {'VersionId':'export-version'}
 def generate_presigned_url(self,operation,**args):
  assert operation=='get_object' and args['Params']['VersionId']=='export-version' and args['ExpiresIn']==300
  self.downloads.append(args)
  return 'https://private.example/download?versionId=export-version'


def setup(monkeypatch):
 for key,value in [('BUCKET','bucket'),('KMS_KEY','key'),('BUCKET_OWNER','0'*12)]:monkeypatch.setenv('MIGRATION_WORKSPACE_'+key,value)
 parent=dict(apiVersion='batch/v1',kind='CronJob',namespace='shop',name='check')
 job={**parent,'kind':'Job','name':'check-123'}
 aid=lambda n:'ART-'+str(n)*64
 artifacts=[dict(artifactId=aid(1),kind='REPOSITORY_DEFINITION',source={'filePath':'operations.yaml'},workloads=[parent],status='PENDING_COLLECTION'),
            dict(artifactId=aid(2),kind='IMAGE',source={'reference':'example/image@sha256:'+'f'*64,'digest':'sha256:'+'f'*64},workloads=[parent],status='PENDING_COLLECTION'),
            dict(artifactId=aid(3),kind='LIVE_DEFINITION',source={'resource':job},workloads=[job],status='EXPORT_REQUIRED')]
 review=dict(decisionId='DEC-test',parent=parent,parentDefinitionArtifactId=aid(1),imageArtifactIds=[aid(2)],
             sourceAbsence='OPERATOR_CONFIRMED',parentOwnership='OPERATOR_ASSERTED',replayRequired=False,targetReady=False)
 state=[dict(artifact_id=aid(1),status='COLLECTED',validation={'format':'REPOSITORY_BUNDLE'}),
        dict(artifact_id=aid(2),status='COLLECTED',validation=dict(format='OCI_ARCHIVE',integrity='VERIFIED',content='COMPLETE',digest='sha256:'+'f'*64,platforms=['linux/amd64'])),
        dict(artifact_id=aid(3),status='EXCLUDED_FROM_REPLAY',validation={'historicalReview':review,'recovery':{'status':'CUSTOMER_INPUT_REQUIRED'}})]
 manifest=dict(workspaceId=WID,migrationId=MID,customerId=CID,sourceClusterId='SRC-test',inventoryDigest='current',inventoryVersion=1,namespaces=['shop'],artifacts=artifacts)
 storage=Storage()
 records=[dict(artifact_id=aid(1),**storage.add(PREFIX+'definitions/original/file.json',b'{"private-content":"private-test-value"}')),
          dict(artifact_id=aid(2),**storage.add(PREFIX+'images/image.tar',b'image-bytes',composite=True))]
 receipt=dict(kind='HISTORICAL_JOB_REVIEW',workspaceId=WID,migrationId=MID,sourceClusterId='SRC-test',inventoryDigest='current',artifactId=aid(3),resource=job,review=review,collectedParentObjects=[dict(r) for r in records])
 records.append(dict(artifact_id=aid(3),**storage.add(PREFIX+'reviews/review.json',canonical(receipt))))
 index=storage.add(PREFIX+'workspace-manifest.json',canonical(manifest))
 row=dict(workspace_id=WID,manifest=manifest,status='PARTIAL',bucket_name='bucket',inventory_digest='current',source_cluster_id='SRC-test',
          manifest_key=index['object_key'],manifest_version=index['object_version'],manifest_sha256=index['sha256'])
 migration=dict(migration_id=MID,customer_id=CID,version=3,created_by='owner')
 repo=Mock();repo.get.return_value=migration
 repo.get_source_inventory.return_value={'inventory':{'inventoryDigest':'current'}}
 repo.list_artifact_workspaces.return_value=[row];repo.workspace_collection_state.return_value=(state,[])
 def execute(sql,args):
  cursor=Mock()
  if sql.startswith('SELECT bucket_name,manifest_key'):
   assert args==[WID,MID,CID];cursor.fetchone.return_value=row
  elif sql.startswith('SELECT artifact_id,object_key'):
   assert args==[WID];cursor.fetchall.return_value=records
  else:raise AssertionError(sql)
  return cursor
 repo.db.execute.side_effect=execute
 api=SimpleNamespace(repo=repo,access=Mock(),principal=SimpleNamespace(user_id='owner'),
   deployment_context=Mock(return_value=(migration,{'source_cluster_id':'SRC-test'})))
 return api,storage,row,state,records


def test_export_pins_versions_preserves_exclusions_and_distinguishes_multipart_checksums(monkeypatch):
 api,s3,row,state,records=setup(monkeypatch)
 result=export.create(api,MID,WID,{'version':3},s3)
 manifest=json.loads(s3.puts[0]['Body'])
 assert result['collectedArtifactCount']==2 and result['excludedArtifactCount']==1 and result['targetReady'] is False
 assert manifest['originallyListedArtifactCount']==3 and manifest['dependencyCompleteness']=='NOT_VERIFIED'
 image=manifest['artifacts'][1]
 assert image['storage']['s3Checksum']['type']=='COMPOSITE'
 assert image['storage']['fullSha256Verification']=='VERIFIED_AT_COLLECTION'
 assert image['storage']['sha256']==records[1]['sha256']
 excluded=manifest['artifacts'][2]
 assert excluded['replayRequired'] is False and excluded['objectRole']=='HISTORICAL_REVIEW_RECEIPT'
 assert excluded['validation']['historicalReview']['parentOwnership']=='OPERATOR_ASSERTED'
 assert len(s3.gets)==1 and s3.gets[0]['Key'].startswith(PREFIX+'reviews/')
 assert 'private-test-value' not in json.dumps(manifest) and 'image-bytes' not in json.dumps(manifest)
 assert s3.puts[0]['Key'].startswith(PREFIX+'exports/EXP-')
 assert result['storage']['versionId']=='export-version' and s3.downloads[0]['Params']['Key']==s3.puts[0]['Key']
 assert all(h.get('VersionId') for h in s3.heads)
 api.access.require.assert_any_call('migration.edit')
 api.access.require_customer.assert_called_with(CID,'owner')


@pytest.mark.parametrize('change,code',[
 ('version','CONCURRENT_UPDATE'),('stale','STALE_WORKSPACE'),('unresolved','EXPORT_ARTIFACTS_UNRESOLVED'),
 ('active','EXPORT_COLLECTION_ACTIVE'),('bucket','WORKSPACE_STORAGE_CHANGED'),('missing_record','EXPORT_ARTIFACT_STATE_CHANGED'),
 ('no_version','EXPORT_STORAGE_EVIDENCE_REQUIRED'),('outside_prefix','EXPORT_STORAGE_EVIDENCE_REQUIRED'),
 ('image_validation','EXPORT_IMAGE_VALIDATION_REQUIRED'),('review','EXPORT_REVIEW_INVALID')])
def test_invalid_exports_do_not_create_objects_or_links(monkeypatch,change,code):
 api,s3,row,state,records=setup(monkeypatch);body={'version':3}
 if change=='version':body['version']=2
 if change=='stale':row['inventory_digest']='old'
 if change=='unresolved':state[0]['status']='PENDING_COLLECTION'
 if change=='active':api.repo.workspace_collection_state.return_value=(state,[dict(job_id='COL-test',artifact_id=state[0]['artifact_id'],status='RUNNING',attempts=1,error_code=None)])
 if change=='bucket':row['bucket_name']='other'
 if change=='missing_record':records.pop()
 if change=='no_version':records[0]['object_version']=None
 if change=='outside_prefix':records[0]['object_key']='another-customer/file'
 if change=='image_validation':state[1]['validation']['integrity']='NOT_VERIFIED'
 if change=='review':state[2]['validation']['historicalReview']={**state[2]['validation']['historicalReview'],'parentOwnership':'VERIFIED'}
 with pytest.raises(ApiError) as error:export.create(api,MID,WID,body,s3)
 assert error.value.code==code
 assert not s3.puts and not s3.downloads


@pytest.mark.parametrize('bad',[{'ChecksumSHA256':'wrong'},{'VersionId':'different'},{'ContentLength':0},{'SSEKMSKeyId':'other'},{'ServerSideEncryption':'AES256'}])
def test_changed_s3_metadata_blocks_export(monkeypatch,bad):
 api,s3,_,_,records=setup(monkeypatch)
 s3.objects[(records[0]['object_key'],records[0]['object_version'])].update(bad)
 with pytest.raises(ApiError):export.create(api,MID,WID,{'version':3},s3)
 assert not s3.puts and not s3.downloads


def test_missing_s3_version_returns_sanitized_error(monkeypatch):
 api,s3,_,_,records=setup(monkeypatch)
 del s3.objects[(records[0]['object_key'],records[0]['object_version'])]
 with pytest.raises(ApiError) as error:export.create(api,MID,WID,{'version':3},s3)
 assert error.value.code=='EXPORT_OBJECT_UNAVAILABLE'
 assert error.value.details['artifactId']==records[0]['artifact_id']
 assert not s3.puts


def test_tampered_review_bytes_block_export_even_if_head_metadata_matches(monkeypatch):
 api,s3,_,_,records=setup(monkeypatch)
 s3.objects[(records[2]['object_key'],records[2]['object_version'])]['body']=b'{}'
 with pytest.raises(ApiError) as error:export.create(api,MID,WID,{'version':3},s3)
 assert error.value.code=='EXPORT_REVIEW_INVALID' and not s3.puts


def test_unauthorized_or_cross_workspace_export_is_rejected(monkeypatch):
 api,s3,_,_,_=setup(monkeypatch)
 api.access.require_customer.side_effect=ApiError(403,'FORBIDDEN','Forbidden')
 with pytest.raises(ApiError):export.create(api,MID,WID,{'version':3},s3)
 assert not s3.heads and not s3.puts
 api.access.require_customer.side_effect=None
 api.repo.list_artifact_workspaces.return_value=[]
 with pytest.raises(ApiError) as error:export.create(api,MID,WID,{'version':3},s3)
 assert error.value.code=='WORKSPACE_NOT_FOUND'
 assert not s3.puts


def test_export_route_has_strict_workspace_scope():
 base='/api/v1/migrations/'+MID+'/artifact-workspaces/'+WID+'/exports'
 assert route_of('POST',base)==('workspace_export_create',MID,WID)
 for method,path in [('GET',base),('DELETE',base),('POST',base+'/extra'),('POST',base.replace(WID,'AWS-invalid'))]:
  with pytest.raises(ApiError):route_of(method,path)


def test_export_uses_full_object_image_checksum_when_available(monkeypatch):
 api,s3,_,_,records=setup(monkeypatch)
 obj=s3.objects[(records[1]['object_key'],records[1]['object_version'])]
 obj.update(ChecksumType='FULL_OBJECT',ChecksumSHA256=base64.b64encode(bytes.fromhex(records[1]['sha256'])).decode())
 export.create(api,MID,WID,{'version':3},s3)
 manifest=json.loads(s3.puts[0]['Body'])
 assert manifest['artifacts'][1]['storage']['fullSha256Verification']=='MATCHED_S3_CHECKSUM'


def test_export_preserves_recovered_helm_format_without_internal_job_handles(monkeypatch):
 import gzip
 api,s3,row,state,records=setup(monkeypatch)
 artifact=row['manifest']['artifacts'][2]
 artifact.update(kind='HELM_RELEASE',source={'namespace':'shop','release':'app'})
 state[2].update(status='COLLECTED',validation={'reviewRequired':True,'recovery':{
   'format':'HELM_RELEASE_BUNDLE','status':'PARTIAL_RECOVERY','releaseRevision':3,'commandId':'private-command','parameterName':'private-parameter'}})
 records[2].update(s3.add(records[2]['object_key'],gzip.compress(b'{"config":{"password":"private-test-value"}}')))
 index=s3.add(row['manifest_key'],canonical(row['manifest']));row['manifest_sha256']=index['sha256']
 export.create(api,MID,WID,{'version':3},s3)
 manifest=json.loads(s3.puts[0]['Body'])
 helm=manifest['artifacts'][2]
 assert helm['contentFormat']=='HELM_RELEASE_BUNDLE' and helm['validation']['reviewRequired'] is True
 assert helm['validation']['recoveryEvidence']['releaseRevision']==3
 assert not s3.gets and 'private-command' not in json.dumps(manifest) and 'private-test-value' not in json.dumps(manifest)


def test_export_verification_timeout_creates_no_manifest(monkeypatch):
 api,s3,_,_,_=setup(monkeypatch)
 monkeypatch.setattr(export,'wait',lambda *args,**kwargs:(set(),{object()}))
 with pytest.raises(ApiError) as error:export.create(api,MID,WID,{'version':3},s3)
 assert error.value.code=='EXPORT_VERIFY_TIMEOUT' and not s3.puts and not s3.downloads


def test_export_put_failure_does_not_offer_download(monkeypatch):
 api,s3,_,_,_=setup(monkeypatch)
 def fail(**kwargs):raise RuntimeError('private-storage-error')
 s3.put_object=fail
 with pytest.raises(ApiError) as error:export.create(api,MID,WID,{'version':3},s3)
 assert error.value.code=='WORKSPACE_STORAGE_FAILED' and not s3.downloads


@pytest.mark.parametrize('count',[0,101])
def test_export_requires_bounded_nonempty_scope(monkeypatch,count):
 api,s3,row,state,records=setup(monkeypatch)
 row['manifest']['artifacts']=[row['manifest']['artifacts'][0]]*count
 with pytest.raises(ApiError) as error:export.create(api,MID,WID,{'version':3},s3)
 assert error.value.code=='EXPORT_SCOPE_LIMIT' and not s3.heads


def test_export_rejects_parent_versions_changed_since_historical_review(monkeypatch):
 api,s3,_,_,records=setup(monkeypatch)
 content=s3.objects[(records[0]['object_key'],records[0]['object_version'])]['body']
 records[0].update(s3.add(records[0]['object_key'],content,version='new-parent-version'))
 with pytest.raises(ApiError) as error:export.create(api,MID,WID,{'version':3},s3)
 assert error.value.code=='EXPORT_REVIEW_INVALID' and not s3.puts


def test_export_rejects_index_scope_mismatch(monkeypatch):
 api,s3,row,_,_=setup(monkeypatch)
 row['manifest']['customerId']='CUS-other'
 with pytest.raises(ApiError) as error:export.create(api,MID,WID,{'version':3},s3)
 assert error.value.code=='EXPORT_SCOPE_MISMATCH' and not s3.heads
