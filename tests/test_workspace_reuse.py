import base64
import copy
import hashlib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from navigan.shared.errors import ApiError
from navigan.modules.migration_management import artifact_workspace as workspace
from navigan.modules.migration_management.workspace_reuse import carry_forward

CID, MID, SID = 'CUS-test', 'MIG-test', 'SRC-test'
OLD, NEW = 'AWS-old', 'AWS-new'
DIGEST = 'sha256:' + 'a' * 64


class Storage:
    def __init__(self):
        self.objects = {}
        self.copies = []
        self.heads = []

    def add(self, key, version='old-version', body=b'saved-bytes'):
        sha = hashlib.sha256(body).digest()
        self.objects[key, version] = dict(VersionId=version, ContentLength=len(body),
            ChecksumSHA256=base64.b64encode(sha).decode(), ChecksumType='FULL_OBJECT',
            ServerSideEncryption='aws:kms', SSEKMSKeyId='key')
        return dict(object_key=key, object_version=version, sha256=sha.hex(), size_bytes=len(body))

    def head_object(self, **args):
        assert args['ExpectedBucketOwner'] == '0' * 12 and args['ChecksumMode'] == 'ENABLED'
        self.heads.append(args)
        return self.objects[args['Key'], args['VersionId']]

    def copy_object(self, **args):
        assert args['ExpectedBucketOwner'] == args['ExpectedSourceBucketOwner'] == '0' * 12
        assert args['ServerSideEncryption'] == 'aws:kms' and args['SSEKMSKeyId'] == 'key'
        assert args['ChecksumAlgorithm'] == 'SHA256'
        source = args['CopySource']
        assert source['Bucket'] == args['Bucket'] == 'bucket'
        head = self.objects[source['Key'], source['VersionId']]
        self.objects[args['Key'], 'new-version'] = {**head, 'VersionId': 'new-version'}
        self.copies.append(args)
        return {'VersionId': 'new-version'}

    def put_object(self, **args):
        record = self.add(args['Key'], 'index-version', args['Body'])
        assert base64.b64encode(bytes.fromhex(record['sha256'])).decode() == args['ChecksumSHA256']
        return {'VersionId': 'index-version'}


def setup(kind='IMAGE'):
    source = ({'reference': 'registry.example/image:tag', 'digest': DIGEST} if kind == 'IMAGE' else
              {'repository': 'example/app', 'commit': 'b' * 40, 'filePath': 'app.yaml', 'format': 'MANIFESTS'})
    artifact = dict(artifactId='ART-' + 'c' * 64, kind=kind, source=source, status='PENDING_COLLECTION',
                    workloads=[{'kind': 'Deployment', 'namespace': 'shop', 'name': 'app'}])
    manifest = dict(workspaceId=NEW, customerId=CID, migrationId=MID, sourceClusterId=SID,
                    inventoryDigest='new-inventory', artifacts=[artifact])
    previous = {**copy.deepcopy(manifest), 'workspaceId': OLD, 'inventoryDigest': 'old-inventory'}
    storage = Storage()
    key = workspace.workspace_prefix(CID, MID, OLD) + 'images/archive'
    row = dict(artifact_id=artifact['artifactId'], kind=kind, status='COLLECTED', provenance=copy.deepcopy(source),
               workspace_id=OLD, bucket_name='bucket', previous_manifest=previous,
               validation=dict(format='OCI_ARCHIVE', integrity='VERIFIED', content='COMPLETE', digest=DIGEST),
               **storage.add(key))
    service = SimpleNamespace(repo=SimpleNamespace(db=Mock()))
    service.repo.db.execute.return_value.fetchall.return_value = [row]
    return service, manifest, storage, row


@pytest.mark.parametrize('kind', ['IMAGE', 'REPOSITORY_DEFINITION'])
def test_exact_objects_reused_with_pinned_copy_and_new_prefix(kind):
    service, manifest, storage, old = setup(kind)
    saved_before = copy.deepcopy(old)
    result = carry_forward(service, manifest, storage, 'bucket', 'key', '0' * 12)
    assert len(result) == 1
    assert result[0]['object_key'].startswith(workspace.workspace_prefix(CID, MID, NEW))
    assert result[0]['object_version'] == 'new-version'
    assert result[0]['validation']['reuse']['workspaceId'] == OLD
    assert result[0]['validation']['targetReady'] is False
    assert storage.copies[0]['CopySource']['VersionId'] == 'old-version'
    assert old == saved_before
    sql, params = service.repo.db.execute.call_args.args
    assert "a.status='COLLECTED'" in sql
    assert params[:4] == [MID, CID, SID, 'bucket']


@pytest.mark.parametrize('change', ['customer', 'migration', 'source', 'bucket', 'identity', 'kind', 'status',
    'digest', 'image_incomplete', 'archive_format', 'integrity', 'prior_index', 'prefix', 'version', 'size',
    'checksum', 'kms', 's3_version'])
def test_rejects_unsafe_reuse_without_claiming_saved(change):
    service, manifest, storage, row = setup()
    if change in {'customer', 'migration', 'source'}:
        field = {'customer': 'customerId', 'migration': 'migrationId', 'source': 'sourceClusterId'}[change]
        row['previous_manifest'][field] = 'different'
    if change == 'bucket': row['bucket_name'] = 'another-bucket'
    if change == 'identity': row['provenance']['reference'] = 'registry.example/other:tag'
    if change == 'kind': row['kind'] = 'LIVE_DEFINITION'
    if change == 'status': row['status'] = 'EXCLUDED_FROM_REPLAY'
    if change == 'digest': row['validation']['digest'] = 'sha256:' + 'f' * 64
    if change == 'image_incomplete': row['validation']['content'] = 'INCOMPLETE'
    if change == 'archive_format': row['validation']['format'] = 'OTHER'
    if change == 'integrity': row['validation']['integrity'] = 'UNKNOWN'
    if change == 'prior_index': row['previous_manifest']['artifacts'] = []
    if change == 'prefix': row['object_key'] = 'customers/other/file'
    if change == 'version': row['object_version'] = 'null'
    if change == 'size': row['size_bytes'] = 0
    head = next(iter(storage.objects.values()))
    if change == 'checksum': head['ChecksumSHA256'] = 'wrong'
    if change == 'kms': head['SSEKMSKeyId'] = 'other-key'
    if change == 's3_version': head['VersionId'] = 'different'
    assert carry_forward(service, manifest, storage, 'bucket', 'key', '0' * 12) == []
    assert not storage.copies


@pytest.mark.parametrize('change', ['commit', 'path', 'repository'])
def test_changed_repository_content_is_not_reused(change):
    service, manifest, storage, row = setup('REPOSITORY_DEFINITION')
    field = {'commit': 'commit', 'path': 'filePath', 'repository': 'repository'}[change]
    row['provenance'][field] = 'changed'
    assert carry_forward(service, manifest, storage, 'bucket', 'key', '0' * 12) == []


@pytest.mark.parametrize('kind', ['LIVE_DEFINITION', 'HELM_RELEASE'])
def test_live_and_helm_content_needs_fresh_recovery(kind):
    service, manifest, storage, _ = setup()
    manifest['artifacts'][0]['kind'] = kind
    assert carry_forward(service, manifest, storage, 'bucket', 'key', '0' * 12) == []
    service.repo.db.execute.assert_not_called()


def test_missing_object_or_failed_copy_leaves_artifact_collectable():
    service, manifest, storage, _ = setup()
    storage.copy_object = Mock(side_effect=RuntimeError('unavailable'))
    assert carry_forward(service, manifest, storage, 'bucket', 'key', '0' * 12) == []
    assert manifest['artifacts'][0]['status'] == 'PENDING_COLLECTION'


def test_bad_destination_is_not_saved():
    service, manifest, storage, _ = setup()
    original = storage.copy_object
    def corrupt(**args):
        result = original(**args)
        storage.objects[args['Key'], result['VersionId']]['ChecksumSHA256'] = 'wrong'
        return result
    storage.copy_object = corrupt
    assert carry_forward(service, manifest, storage, 'bucket', 'key', '0' * 12) == []


def create_context(monkeypatch, report):
    from test_migration_artifact_workspace import service, MID
    for suffix, value in [('BUCKET', 'bucket'), ('KMS_KEY', 'key'), ('BUCKET_OWNER', '0' * 12)]:
        monkeypatch.setenv('MIGRATION_WORKSPACE_' + suffix, value)
    monkeypatch.setattr(workspace, 'build_report', lambda *args: report)
    api = service()
    api.repo.list_artifact_workspaces.return_value = []
    api.repo.db.execute.return_value.fetchall.return_value = []
    return api, MID


def test_unchecked_inventory_cannot_create_dead_end_workspace(monkeypatch):
    api, mid = create_context(monkeypatch, {'analysisCurrent': False})
    with pytest.raises(ApiError) as error:
        workspace.create(api, mid, {'version': 2, 'inventoryDigest': 'current', 'namespaces': ['shop']}, Storage())
    assert error.value.code == 'SOURCE_CHECK_REQUIRED'
    api.repo.create_artifact_workspace.assert_not_called()


def test_updated_index_uses_current_candidates_and_available_images_and_is_idempotent(monkeypatch):
    from test_migration_artifact_workspace import S3, RESOURCE
    report = {'analysisCurrent': True, 'workloads': [{'workload': RESOURCE,
        'candidates': [{'repository': 'example/app', 'commit': 'b' * 40, 'filePath': 'app.yaml', 'format': 'MANIFESTS'}],
        'containers': [{'name': 'app', 'configuredImage': 'registry.example/image:tag', 'observedDigests': [DIGEST],
                        'registryEvidence': {'status': 'AVAILABLE'}}]}]}
    api, mid = create_context(monkeypatch, report)
    old = dict(workspace_id=OLD, inventory_digest='current', source_cluster_id='SRC-one',
               manifest={'namespaces': ['shop'], 'artifacts': []})
    api.repo.list_artifact_workspaces.return_value = [old]
    body = {'version': 2, 'inventoryDigest': 'current', 'namespaces': ['shop']}
    result = workspace.create(api, mid, body, S3())
    assert {a['kind'] for a in result['artifacts']} == {'IMAGE', 'REPOSITORY_DEFINITION'}
    assert all(a['status'] == 'PENDING_COLLECTION' for a in result['artifacts'])
    api.repo.create_artifact_workspace.assert_called_once()
    assert old['manifest']['artifacts'] == []
    revised = dict(workspace_id=result['workspaceId'], manifest=result, inventory_digest='current',
                   source_cluster_id='SRC-one', status='PLANNED')
    api.repo.list_artifact_workspaces.side_effect = lambda *args: [revised] if len(args) == 3 else [revised, old]
    again = workspace.create(api, mid, body, S3())
    assert again['workspaceId'] == result['workspaceId']
    api.repo.create_artifact_workspace.assert_called_once()


def test_verified_copy_is_persisted_with_current_links_and_old_record_untouched(monkeypatch):
    from test_migration_artifact_workspace import RESOURCE
    report = {'analysisCurrent': True, 'workloads': [{'workload': RESOURCE, 'candidates': [],
        'containers': [{'name': 'app', 'configuredImage': 'registry.example/image:tag', 'observedDigests': [DIGEST],
                        'registryEvidence': {'status': 'AVAILABLE'}}]}]}
    api, mid = create_context(monkeypatch, report)
    m, s = api.deployment_context.return_value
    image = next(a for a in workspace.plan_artifacts(report, ['shop']) if a['kind'] == 'IMAGE')
    old_manifest = dict(workspaceId=OLD, customerId=m['customer_id'], migrationId=mid,
                        sourceClusterId=s['source_cluster_id'], artifacts=[copy.deepcopy(image)])
    storage = Storage()
    record = dict(artifact_id=image['artifactId'], kind='IMAGE', status='COLLECTED', workspace_id=OLD,
                  bucket_name='bucket', previous_manifest=old_manifest, provenance=copy.deepcopy(image['source']),
                  validation=dict(format='OCI_ARCHIVE', integrity='VERIFIED', content='COMPLETE', digest=DIGEST),
                  **storage.add(workspace.workspace_prefix(m['customer_id'], mid, OLD) + 'images/old.tar'))
    original = copy.deepcopy(record)
    api.repo.db.execute.return_value.fetchall.return_value = [record]
    result = workspace.create(api, mid, {'version': 2, 'inventoryDigest': 'current', 'namespaces': ['shop']}, storage)
    assert result['reusedArtifactCount'] == result['collectedArtifactCount'] == 1
    reused = next(a for a in result['artifacts'] if a['kind'] == 'IMAGE')
    assert reused['status'] == 'COLLECTED' and reused['workloads'][0]['name'] == RESOURCE['name']
    assert reused['storage']['key'].startswith(workspace.workspace_prefix(m['customer_id'], mid, result['workspaceId']))
    writes = [c.args for c in api.repo.db.execute.call_args_list if c.args[0].startswith('UPDATE')]
    assert len(writes) == 1 and writes[0][1][-2:] == [result['workspaceId'], image['artifactId']]
    assert record == original
