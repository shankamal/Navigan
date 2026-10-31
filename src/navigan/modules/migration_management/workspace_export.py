"""Version-pinned workspace manifests. Image bytes remain in private S3 storage."""
import base64
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone
import hashlib
import json
import re
import uuid

from pydantic import Field
from navigan.shared.errors import ApiError
from .deployment_sources import StrictModel
from .artifact_workspace import canonical, read, storage_configuration, storage_prefix, persist_manifest

MAX_ARTIFACTS = 100
VERIFY_SECONDS = 18


class CreateWorkspaceExport(StrictModel):
    version: int = Field(gt=0)


def export_client():
    import boto3
    from botocore.config import Config
    return boto3.client('s3', config=Config(signature_version='s3v4', connect_timeout=2,
                                          read_timeout=3, retries={'max_attempts': 0}))


def verify_object(client, bucket, key_id, owner, prefix, record, *, image=None, artifact_id='workspace-index'):
    def fail(code, message):
        raise ApiError(409, code, message, {'artifactId': artifact_id})
    key, version = record.get('object_key'), record.get('object_version')
    sha, size = record.get('sha256'), record.get('size_bytes')
    if (not isinstance(key, str) or not key.startswith(prefix) or not isinstance(version, str)
            or not version or version == 'null' or not re.fullmatch(r'[a-f0-9]{64}', sha or '')
            or type(size) is not int or size <= 0):
        fail('EXPORT_STORAGE_EVIDENCE_REQUIRED', 'An artifact lacks a valid workspace object version, size or SHA-256.')
    try:
        head = client.head_object(Bucket=bucket, Key=key, VersionId=version,
                                  ExpectedBucketOwner=owner, ChecksumMode='ENABLED')
    except Exception:
        raise ApiError(503, 'EXPORT_OBJECT_UNAVAILABLE', 'A pinned S3 object could not be checked. Retry or review its storage access.',
                       {'artifactId': artifact_id}) from None
    if (head.get('VersionId') != version or head.get('ContentLength') != size
            or head.get('ServerSideEncryption') != 'aws:kms' or head.get('SSEKMSKeyId') != key_id):
        fail('EXPORT_OBJECT_MISMATCH', 'A pinned object failed version, size or encryption checks.')
    checksum = head.get('ChecksumSHA256', '')
    full = base64.b64encode(bytes.fromhex(sha)).decode()
    composite = re.fullmatch(r'([A-Za-z0-9+/]{43}=)-([1-9][0-9]{0,4})', checksum)
    if checksum == full and head.get('ChecksumType') != 'COMPOSITE':
        scope = 'FULL_OBJECT'
    elif composite and int(composite[2]) <= 10000 and head.get('ChecksumType') in {None, 'COMPOSITE'}:
        # Multipart SHA-256 is not the full-file SHA-256. Collection verified the
        # part checksums and recorded the full hash; do not equate these values.
        if not image or (image.get('validation') or {}).get('integrity') != 'VERIFIED':
            fail('EXPORT_CHECKSUM_MISMATCH', 'An object has an unexpected multipart checksum.')
        scope = 'COMPOSITE'
    else:
        fail('EXPORT_CHECKSUM_MISMATCH', 'An object has a missing or mismatched S3 SHA-256 checksum.')
    return dict(bucket=bucket, key=key, versionId=version, sha256=sha, sizeBytes=size,
                s3Checksum=dict(algorithm='SHA256', type=scope, value=checksum),
                storageVerification='PINNED_VERSION_METADATA_VERIFIED',
                fullSha256Verification='MATCHED_S3_CHECKSUM' if scope == 'FULL_OBJECT' else 'VERIFIED_AT_COLLECTION')


def verify_review(client, bucket, owner, record, artifact, workspace, by_id, by_record):
    try:
        body = client.get_object(Bucket=bucket, Key=record['object_key'], VersionId=record['object_version'],
                                 ExpectedBucketOwner=owner)['Body']
        try:
            raw = body.read(2 * 1024**2 + 1)
        finally:
            body.close()
        if len(raw) > 2 * 1024**2 or len(raw) != record['size_bytes'] or hashlib.sha256(raw).hexdigest() != record['sha256']:
            raise ValueError()
        receipt = json.loads(raw)
        review = artifact['validation']['historicalReview']
        resource = artifact['source']['resource']
        parent = review['parent']
        definition = by_id[review['parentDefinitionArtifactId']]
        image_ids = {a['artifactId'] for a in by_id.values() if a['kind'] == 'IMAGE'
                     and any(all(w.get(k) == v for k, v in parent.items()) for w in a.get('workloads', []))}
        reviewed_objects = {obj['artifact_id']: obj for obj in receipt.get('collectedParentObjects', [])}
        required_ids = {review['parentDefinitionArtifactId'], *image_ids}
        object_fields = ('artifact_id', 'object_key', 'object_version', 'sha256', 'size_bytes')
        versions_match = (set(reviewed_objects) == required_ids and all(
            all(reviewed_objects[aid].get(field) == by_record[aid].get(field) for field in object_fields) for aid in required_ids))
        if (not versions_match or artifact['kind'] != 'LIVE_DEFINITION' or resource['kind'] != 'Job'
                or receipt.get('kind') != 'HISTORICAL_JOB_REVIEW' or receipt.get('workspaceId') != workspace['workspaceId']
                or receipt.get('migrationId') != workspace['migrationId'] or receipt.get('sourceClusterId') != workspace['sourceClusterId']
                or receipt.get('inventoryDigest') != workspace['inventoryDigest'] or receipt.get('artifactId') != artifact['artifactId']
                or receipt.get('resource') != resource or receipt.get('review') != review
                or parent.get('kind') != 'CronJob' or parent.get('namespace') != resource['namespace']
                or review.get('sourceAbsence') != 'OPERATOR_CONFIRMED' or review.get('parentOwnership') != 'OPERATOR_ASSERTED'
                or review.get('replayRequired') is not False or review.get('targetReady') is not False
                or definition['kind'] not in {'REPOSITORY_DEFINITION', 'LIVE_DEFINITION'} or definition['status'] != 'COLLECTED'
                or not any(all(w.get(k) == v for k, v in parent.items()) for w in definition.get('workloads', []))
                or not image_ids or set(review['imageArtifactIds']) != image_ids
                or any(by_id[i]['status'] != 'COLLECTED' for i in image_ids)):
            raise ValueError()
    except Exception:
        raise ApiError(409, 'EXPORT_REVIEW_INVALID', 'A historical exclusion receipt could not be verified against this workspace.',
                       {'artifactId': artifact['artifactId']}) from None


def create(service, identifier, workspace_id, body, client=None):
    service.access.require('migration.edit')
    migration, source = service.deployment_context(identifier)
    service.access.require_customer(migration['customer_id'], migration['created_by'])
    migration = service.repo.get(identifier, lock=True)
    if migration['version'] != body['version']:
        raise ApiError(409, 'CONCURRENT_UPDATE', 'Reload before creating the workspace export.')
    workspace = read(service, identifier, workspace_id)
    if workspace['stale']:
        raise ApiError(409, 'STALE_WORKSPACE', 'Export a workspace from the current source inventory.')
    if (workspace.get('workspaceId') != workspace_id or workspace.get('migrationId') != identifier
            or workspace.get('customerId') != migration['customer_id'] or workspace.get('sourceClusterId') != source['source_cluster_id']):
        raise ApiError(409, 'EXPORT_SCOPE_MISMATCH', 'The saved workspace index does not match the current migration scope.')
    artifacts = workspace['artifacts']
    if not artifacts or len(artifacts) > MAX_ARTIFACTS:
        raise ApiError(409, 'EXPORT_SCOPE_LIMIT', 'This export supports workspaces containing 1 to 100 artifact records.')
    if any(a['kind'] not in {'REPOSITORY_DEFINITION', 'IMAGE', 'LIVE_DEFINITION', 'HELM_RELEASE'} for a in artifacts):
        raise ApiError(409, 'EXPORT_KIND_UNSUPPORTED', 'A workspace artifact uses an unsupported content format.')
    if any(a['status'] not in {'COLLECTED', 'EXCLUDED_FROM_REPLAY'} for a in artifacts):
        raise ApiError(409, 'EXPORT_ARTIFACTS_UNRESOLVED', 'Collect or review every required artifact before exporting.')
    if any(j['status'] in {'QUEUED', 'RUNNING'} for j in workspace.get('jobs', [])):
        raise ApiError(409, 'EXPORT_COLLECTION_ACTIVE', 'Wait for active collection jobs to finish before exporting.')
    bucket, key_id, owner = storage_configuration()
    row = service.repo.db.execute(
        'SELECT bucket_name,manifest_key,manifest_version,manifest_sha256 FROM migration_management.artifact_workspaces '
        'WHERE workspace_id=%s AND migration_id=%s AND customer_id=%s',
        [workspace_id, identifier, migration['customer_id']]).fetchone()
    if not row or row['bucket_name'] != bucket:
        raise ApiError(409, 'WORKSPACE_STORAGE_CHANGED', 'Workspace storage configuration changed.')
    records = service.repo.db.execute(
        'SELECT artifact_id,object_key,object_version,sha256,size_bytes FROM migration_management.workspace_artifacts '
        'WHERE workspace_id=%s ORDER BY artifact_id', [workspace_id]).fetchall()
    by_record = {r['artifact_id']: r for r in records}
    by_id = {a['artifactId']: a for a in artifacts}
    if len(records) != len(artifacts) or set(by_record) != set(by_id):
        raise ApiError(409, 'EXPORT_ARTIFACT_STATE_CHANGED', 'The workspace artifact records do not match its index.')
    for artifact in artifacts:
        validation = artifact.get('validation') or {}
        if artifact['kind'] == 'IMAGE' and (validation.get('format') != 'OCI_ARCHIVE' or validation.get('integrity') != 'VERIFIED'
                or validation.get('content') != 'COMPLETE' or validation.get('digest') != artifact['source'].get('digest')
                or not re.fullmatch(r'sha256:[a-f0-9]{64}', artifact['source'].get('digest') or '')):
            raise ApiError(409, 'EXPORT_IMAGE_VALIDATION_REQUIRED', 'An image lacks complete digest-verified collection evidence.',
                           {'artifactId': artifact['artifactId']})
    client = client or export_client()
    index = dict(object_key=row['manifest_key'], object_version=row['manifest_version'], sha256=row['manifest_sha256'])
    # The original planning index is immutable and its canonical bytes are retained in the DB manifest.
    stored = service.repo.list_artifact_workspaces(identifier, migration['customer_id'], workspace_id)[0]
    prefix = storage_prefix(migration['customer_id'], identifier, workspace_id, stored['manifest'])
    index['size_bytes'] = len(canonical(stored['manifest']))
    def verify_artifact(artifact):
        record = by_record[artifact['artifactId']]
        result = verify_object(client, bucket, key_id, owner, prefix, record,
                               image=artifact if artifact['kind'] == 'IMAGE' else None,
                               artifact_id=artifact['artifactId'])
        if artifact['status'] == 'EXCLUDED_FROM_REPLAY':
            verify_review(client, bucket, owner, record, artifact, workspace, by_id, by_record)
        return result
    pool = ThreadPoolExecutor(max_workers=8)
    try:
        original = pool.submit(verify_object, client, bucket, key_id, owner, prefix, index)
        futures = {a['artifactId']: pool.submit(verify_artifact, a) for a in artifacts}
        _, pending = wait([original, *futures.values()], timeout=VERIFY_SECONDS)
        if pending:
            raise ApiError(503, 'EXPORT_VERIFY_TIMEOUT', 'Storage verification took too long. No export was created; retry.')
        original_object = original.result()
        verified = {aid: future.result() for aid, future in futures.items()}
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    entries = []
    validation_fields = {'format', 'integrity', 'content', 'deploymentRevision', 'dependencies', 'platforms', 'manifestCount', 'attestationCount',
                         'attestationTrustStatus', 'targetPlatformStatus', 'reviewRequired', 'originalSourceVerified', 'historicalReview'}
    for artifact in sorted(artifacts, key=lambda a: a['artifactId']):
        validation = artifact.get('validation') or {}
        excluded = artifact['status'] == 'EXCLUDED_FROM_REPLAY'
        evidence = {**{k:v for k,v in validation.items() if k in validation_fields}, 'targetReady': False}
        recovery = validation.get('recovery') or {}
        if recovery:
            evidence['recoveryEvidence'] = {k:v for k,v in recovery.items() if k in {'jobId','status','format','releaseRevision','completedAt'}}
        content_format = ('HISTORICAL_JOB_REVIEW' if excluded else 'REPOSITORY_FILE_BUNDLE' if artifact['kind']=='REPOSITORY_DEFINITION'
                          else validation.get('format') or recovery.get('format'))
        if not content_format:
            raise ApiError(409, 'EXPORT_CONTENT_FORMAT_REQUIRED', 'An artifact lacks its collected content format.', {'artifactId':artifact['artifactId']})
        entries.append(dict(artifactId=artifact['artifactId'], kind=artifact['kind'], status=artifact['status'],
                            source=artifact['source'], workloads=artifact.get('workloads', []), replayRequired=not excluded,
                            objectRole='HISTORICAL_REVIEW_RECEIPT' if excluded else 'COLLECTED_ARTIFACT', contentFormat=content_format,
                            storage=verified[artifact['artifactId']], validation=evidence))
    export_id = 'EXP-' + uuid.uuid4().hex
    excluded_count = sum(a['status'] == 'EXCLUDED_FROM_REPLAY' for a in artifacts)
    manifest = dict(schemaVersion=1, kind='MIGRATION_WORKSPACE_EXPORT', exportId=export_id, workspaceId=workspace_id,
                    migrationId=identifier, customerId=migration['customer_id'], sourceClusterId=source['source_cluster_id'],
                    inventoryDigest=workspace['inventoryDigest'], inventoryVersion=workspace['inventoryVersion'],
                    migrationVersion=migration['version'], namespaces=workspace['namespaces'],
                    createdAt=datetime.now(timezone.utc).isoformat(), createdBy=service.principal.user_id,
                    originalIndex=original_object, artifacts=entries, originallyListedArtifactCount=len(artifacts),
                    collectedArtifactCount=len(artifacts)-excluded_count, requiredArtifactCount=len(artifacts)-excluded_count, excludedArtifactCount=excluded_count,
                    targetReady=False, dependencyCompleteness='NOT_VERIFIED',
                    limitations=['Collected content and recovered configuration require review before deployment.',
                                 'Repository mapping does not prove the deployed Git revision.',
                                 'Historical Job ownership is operator-asserted; excluded runs are not recovered definitions.',
                                 'Multipart image full hashes were verified at collection and are not recomputed during export.',
                                 'Images and files remain in private S3; this JSON manifest is not a combined archive.',
                                 'Dependency closure, persistent data and target compatibility remain separate validation steps.'])
    key = prefix + 'exports/' + export_id + '.json'
    version, sha = persist_manifest(client, bucket, key_id, owner, key, manifest)
    url = client.generate_presigned_url('get_object', Params=dict(Bucket=bucket, Key=key, VersionId=version,
            ResponseContentDisposition='attachment; filename="'+export_id+'.json"'), ExpiresIn=300)
    return dict(workspaceId=workspace_id, exportId=export_id,
                storage=dict(bucket=bucket, key=key, versionId=version, sha256=sha, sizeBytes=len(canonical(manifest))),
                collectedArtifactCount=len(artifacts)-excluded_count, excludedArtifactCount=excluded_count,
                targetReady=False, dependencyCompleteness='NOT_VERIFIED', downloadUrl=url, expiresInSeconds=300)
