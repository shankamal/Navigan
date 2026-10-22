import base64
from contextlib import contextmanager
import hashlib
import io
import json
import tarfile
from unittest.mock import Mock
import pytest
from navigan.modules.migration_management.image_collector import source_reference, validate_archive, upload_archive, copy_archive
from navigan.modules.migration_management.repository_collector import CollectionError
from navigan.modules.migration_management.source_authentication import ecr_session_policy
from navigan.modules.migration_management.workspace_collection import StartCollection, claim, renew


def archive(tmp_path, *, multi=False, missing=False, corrupt=False, unsafe=False, mismatch=False):
    files={}
    def blob(data):
        raw=json.dumps(data,separators=(',',':')).encode() if isinstance(data,dict) else data
        digest=hashlib.sha256(raw).hexdigest();files['blobs/sha256/'+digest]=raw
        return dict(digest='sha256:'+digest,size=len(raw))
    layer=blob(b'layer-content');manifests=[]
    for arch in (['amd64','arm64'] if multi else ['amd64']):
        config=blob(dict(os='linux',architecture=arch))
        manifest=blob(dict(schemaVersion=2,config=config,layers=[layer]))
        manifest['platform']=dict(os='linux',architecture='wrong' if mismatch else arch)
        manifests.append(manifest)
    root=blob(dict(schemaVersion=2,manifests=manifests)) if multi else manifests[0]
    files['index.json']=json.dumps(dict(schemaVersion=2,manifests=[root])).encode()
    files['oci-layout']=b'{"imageLayoutVersion":"1.0.0"}'
    if missing:del files['blobs/sha256/'+layer['digest'].split(':')[1]]
    if corrupt:files['blobs/sha256/'+layer['digest'].split(':')[1]]=b'wrong'
    if unsafe:files['../secret']=b'bad'
    path=tmp_path/'image.tar'
    with tarfile.open(path,'w') as stream:
        for name,raw in files.items():
            member=tarfile.TarInfo('./'+name);member.size=len(raw);stream.addfile(member,io.BytesIO(raw))
    return path,root['digest']


def test_complete_platform_archive(tmp_path):
    path,digest=archive(tmp_path);result=validate_archive(path,digest)
    assert result['platforms']==['linux/amd64'] and result['content']=='COMPLETE'
    assert result['targetReady'] is False


def test_multi_platform_index(tmp_path):
    path,digest=archive(tmp_path,multi=True);result=validate_archive(path,digest)
    assert result['platforms']==['linux/amd64','linux/arm64'] and result['manifestCount']==2


@pytest.mark.parametrize('option',['missing','corrupt','unsafe','mismatch'])
def test_invalid_content_never_ready(tmp_path,option):
    path,digest=archive(tmp_path,**{option:True})
    with pytest.raises(CollectionError):validate_archive(path,digest)


def test_wrong_source_digest_rejected(tmp_path):
    path,_=archive(tmp_path)
    with pytest.raises(CollectionError):validate_archive(path,'sha256:'+'0'*64)


def test_archive_links_not_followed(tmp_path):
    path=tmp_path/'bad.tar'
    with tarfile.open(path,'w') as stream:
        link=tarfile.TarInfo('blobs/link');link.type=tarfile.SYMTYPE;link.linkname='/etc/passwd';stream.addfile(link)
    with pytest.raises(CollectionError):validate_archive(path,'sha256:'+'a'*64)


@pytest.mark.parametrize('ref',['http://evil/app','localhost/app','host:5000/app','evil/app;command','../app'])
def test_invalid_reference(ref):
    with pytest.raises(CollectionError):source_reference({'reference':ref,'digest':'sha256:'+'a'*64})


def test_no_tag_substitution():
    _,ref=source_reference({'reference':'alpine:latest','digest':'sha256:'+'a'*64})
    assert ref=='docker.io/library/alpine@sha256:'+'a'*64
    with pytest.raises(CollectionError):source_reference({'reference':'alpine@sha256:'+'b'*64,'digest':'sha256:'+'a'*64})


class S3:
    def __init__(self):self.parts=[];self.aborted=False
    def create_multipart_upload(self,**args):
        assert args['ServerSideEncryption']=='aws:kms' and args['ExpectedBucketOwner']=='0'*12
        return {'UploadId':'upload'}
    def upload_part(self,**args):
        self.parts.append(args['Body'])
        return {'ChecksumSHA256':args['ChecksumSHA256'],'ETag':'etag'}
    def complete_multipart_upload(self,**args):
        assert args['IfNoneMatch']=='*'
        return {'VersionId':'version'}
    def head_object(self,**args):
        assert args['VersionId']=='version'
        digest=hashlib.sha256(b''.join(hashlib.sha256(p).digest() for p in self.parts)).digest()
        return dict(ContentLength=sum(map(len,self.parts)),ServerSideEncryption='aws:kms',ChecksumSHA256=base64.b64encode(digest).decode()+'-'+str(len(self.parts)))
    def abort_multipart_upload(self,**args):self.aborted=True


def test_multipart_and_whole_file_checksums(tmp_path,monkeypatch):
    from navigan.modules.migration_management import image_collector as module
    monkeypatch.setattr(module,'PART_SIZE',5)
    path=tmp_path/'archive';path.write_bytes(b'archive-payload')
    client=S3();result=upload_archive(client,path,'bucket','key','0'*12,'object')
    assert len(client.parts)>1 and not client.aborted
    assert result['sha256']==hashlib.sha256(path.read_bytes()).hexdigest()


def test_failed_upload_aborts(tmp_path):
    path=tmp_path/'archive';path.write_bytes(b'archive')
    client=S3();client.upload_part=lambda **args:{'ChecksumSHA256':'wrong'}
    with pytest.raises(CollectionError):upload_archive(client,path,'bucket','key','0'*12,'object')
    assert client.aborted


def test_stored_checksum_mismatch_rejected(tmp_path):
    path=tmp_path/'archive';path.write_bytes(b'archive')
    client=S3();client.head_object=lambda **args:dict(ContentLength=7,ServerSideEncryption='aws:kms',ChecksumSHA256='wrong')
    with pytest.raises(CollectionError):upload_archive(client,path,'bucket','key','0'*12,'object')


def test_lease_renewal_requires_live_token():
    db=Mock();db.execute.return_value.fetchone.return_value=None
    assert renew(db,{'job_id':'j','lease_token':'expired'}) is False
    assert 'lease_until>now()' in db.execute.call_args.args[0]


def test_jobs_filtered_by_worker_kind():
    db=Mock();db.execute.return_value.fetchall.return_value=[];claim(db,'IMAGE')
    sql,params=db.execute.call_args.args
    assert 'a.kind=%s' in sql and params[0]=='IMAGE'
    assert StartCollection(version=2,artifactKind='IMAGE').artifactKind=='IMAGE'


def test_ecr_pull_scope_preserves_discovery_permissions():
    statement=ecr_session_policy('0'*12,'test-region','team/app')['Statement'][1]
    assert statement['Resource'].endswith('/team/app')
    assert 'ecr:BatchGetImage' in statement['Action'] and 'ecr:GetDownloadUrlForLayer' in statement['Action']
    assert ecr_session_policy('0'*12,'test-region')['Statement'][1]['Action']==['ecr:DescribeImages']


def test_credentials_not_in_command(tmp_path,monkeypatch):
    from navigan.modules.migration_management import image_collector as module
    monkeypatch.setattr(module.shutil,'disk_usage',lambda _:Mock(free=100*1024**3))
    process=Mock(returncode=0);process.poll.return_value=0
    def popen(command,**kwargs):
        assert 'SECRET' not in str(command) and 'AWS_SECRET_ACCESS_KEY' not in kwargs['env']
        assert '--all' in command and '--preserve-digests' in command
        assert (tmp_path/'auth.json').stat().st_mode & 0o777 == 0o600
        (tmp_path/'image.tar').write_bytes(b'archive');return process
    monkeypatch.setattr(module.subprocess,'Popen',popen)
    copy_archive({'reference':'alpine:tag','digest':'sha256:'+'a'*64},tmp_path,auth='SECRET')
    assert not (tmp_path/'auth.json').exists()


def test_invalid_archive_never_uploads(monkeypatch):
    from navigan.modules.migration_management import image_worker as worker
    @contextmanager
    def tx():yield Mock()
    @contextmanager
    def beat(*args):yield lambda:None
    monkeypatch.setattr(worker,'transaction',tx);monkeypatch.setattr(worker,'heartbeat',beat)
    monkeypatch.setattr(worker,'claim',lambda db,kind:dict(job_id='j',workspace_id='w',artifact_id='a',lease_token='lease'))
    monkeypatch.setattr(worker,'load_context',lambda *args:dict(bucket_name='bucket',provenance={'digest':'sha256:'+'a'*64}))
    monkeypatch.setattr(worker,'registry_auth',lambda _:None)
    monkeypatch.setattr(worker,'storage_configuration',lambda:('bucket','key','0'*12))
    monkeypatch.setattr(worker,'copy_archive',lambda *args,**kwargs:'archive')
    def invalid(*args,**kwargs):raise CollectionError('IMAGE_CONTENT_INCOMPLETE')
    monkeypatch.setattr(worker,'validate_archive',invalid)
    upload=Mock();finished=Mock()
    monkeypatch.setattr(worker,'upload_archive',upload);monkeypatch.setattr(worker,'finish',finished)
    assert worker.run_once()['code']=='IMAGE_CONTENT_INCOMPLETE'
    upload.assert_not_called();assert finished.call_args.kwargs=={'error':'IMAGE_CONTENT_INCOMPLETE'}


def test_bearer_mode_not_placed_in_argv():
    from navigan.modules.migration_management.image_worker import registry_auth
    with pytest.raises(CollectionError) as error:
        registry_auth(dict(provenance={'reference':'ghcr.io/example/app','digest':'sha256:'+'a'*64},credential_entry={'mode':'BEARER'}))
    assert error.value.code=='REGISTRY_AUTH_MODE_UNSUPPORTED'


def test_saved_registry_token(monkeypatch):
    from navigan.modules.migration_management import image_worker as worker
    monkeypatch.setattr(worker,'read_credential',lambda *args:dict(username='reader',token='secret'))
    result=worker.registry_auth(dict(provenance={'reference':'ghcr.io/example/app','digest':'sha256:'+'a'*64},credential_entry={'mode':'TOKEN'}))
    assert base64.b64decode(result)==b'reader:secret'
