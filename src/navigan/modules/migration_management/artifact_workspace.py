"""Private snapshot-bound workspace indices; artifact collection is a later stage."""
import base64
import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pydantic import Field, field_validator
from navigan.shared.errors import ApiError
from .deployment_sources import StrictModel, build_report


class CreateArtifactWorkspace(StrictModel):
    version: int = Field(gt=0)
    inventoryDigest: str = Field(min_length=1, max_length=128)
    namespaces: list[str] = Field(min_length=1, max_length=500)

    @field_validator('namespaces')
    @classmethod
    def validate_namespaces(cls, values):
        if len(set(values)) != len(values) or any(not re.fullmatch(r'[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?', x) for x in values):
            raise ValueError('Select unique Kubernetes namespaces.')
        return sorted(values)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def workspace_prefix(customer, migration, workspace):
    if any(not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', v) for v in (customer, migration, workspace)):
        raise ApiError(400, 'INVALID_WORKSPACE_IDENTITY', 'Invalid workspace identity.')
    return f'customers/{customer}/migrations/{migration}/workspaces/{workspace}/'


def plan_artifacts(report, namespaces):
    artifacts = {}
    def add(kind, source, status, workload, **extra):
        key = 'ART-' + hashlib.sha256(canonical({'kind':kind, 'source':source})).hexdigest()
        entry = artifacts.setdefault(key, dict(artifactId=key, kind=kind, source=source, status=status,
                                               validationStatus='NOT_VALIDATED', workloads=[], **extra))
        if workload not in entry['workloads']:
            entry['workloads'].append(workload)
    for row in report.get('workloads', []):
        workload = {k:row['workload'].get(k) for k in ('apiVersion','kind','namespace','name')}
        if workload['namespace'] not in namespaces:
            continue
        for candidate in row.get('candidates', []):
            add('REPOSITORY_DEFINITION', {k:candidate.get(k) for k in ('repository','commit','filePath','format')},
                'PENDING_COLLECTION', workload)
        if not row.get('candidates'):
            add('LIVE_DEFINITION', {'resource':workload}, 'EXPORT_REQUIRED', workload,
                limitation='A live export is required; inventory evidence is not a deployable manifest.')
        if row.get('helmRelease'):
            add('HELM_RELEASE', {'namespace':workload['namespace'], 'release':row['helmRelease']},
                'RECOVERY_REVIEW_REQUIRED', workload,
                limitation='Retained release data is not a verified original chart package.')
        for container in row.get('containers', []):
            reference = container.get('configuredImage', '')
            declared = reference.split('@', 1)[1] if '@' in reference else None
            digests = sorted(set(container.get('observedDigests') or ([declared] if declared else [])))
            availability = (container.get('registryEvidence') or {}).get('status', 'NOT_CHECKED')
            status = {'AVAILABLE':'PENDING_COLLECTION','NOT_FOUND':'RECOVERY_REQUIRED',
                      'ACCESS_REQUIRED':'ACCESS_REQUIRED','NOT_CONNECTED':'ACCESS_REQUIRED'}.get(availability, 'CHECK_REQUIRED')
            for digest in digests or [None]:
                add('IMAGE', {'reference':reference, 'digest':digest}, status if digest else 'DIGEST_REQUIRED',
                    {**workload,'containerName':container.get('name'),'containerType':container.get('containerType')},
                    sourceAvailability=availability, platformStatus='NOT_CHECKED')
    return list(artifacts.values())


def storage_configuration():
    bucket, key, owner = [os.getenv(name, '') for name in
                         ('MIGRATION_WORKSPACE_BUCKET','MIGRATION_WORKSPACE_KMS_KEY','MIGRATION_WORKSPACE_BUCKET_OWNER')]
    if not bucket or not key or not re.fullmatch(r'\d{12}', owner):
        raise ApiError(503, 'WORKSPACE_STORAGE_REQUIRED', 'Configure private workspace storage, its KMS key and bucket owner first.')
    return bucket, key, owner


def s3_client(*, fast=False):
    import boto3
    from botocore.config import Config
    return boto3.client('s3', config=Config(signature_version='s3v4',connect_timeout=1 if fast else 3,
                       read_timeout=2 if fast else 5,retries={'max_attempts':0 if fast else 2}))


def persist_manifest(client, bucket, key_id, owner, key, manifest):
    content = canonical(manifest)
    digest = hashlib.sha256(content).digest()
    checksum = base64.b64encode(digest).decode()
    try:
        result = client.put_object(Bucket=bucket,Key=key,Body=content,ContentType='application/json',
                                   ExpectedBucketOwner=owner,ServerSideEncryption='aws:kms',SSEKMSKeyId=key_id,
                                   ChecksumSHA256=checksum,IfNoneMatch='*')
        version = result.get('VersionId')
        if not version or version == 'null':
            raise ValueError('Versioning required')
        stored = client.head_object(Bucket=bucket,Key=key,VersionId=version,ExpectedBucketOwner=owner,ChecksumMode='ENABLED')
        if (stored.get('ChecksumSHA256') != checksum or stored.get('ContentLength') != len(content)
                or stored.get('ServerSideEncryption') != 'aws:kms'):
            raise ValueError('Verification failed')
    except Exception:
        raise ApiError(503, 'WORKSPACE_STORAGE_FAILED', 'Workspace index could not be stored and verified. Check storage configuration and retry.') from None
    return version, digest.hex()


def create(service, identifier, body, client=None):
    service.access.require('migration.edit')
    migration, source = service.deployment_context(identifier)
    service.access.require_customer(migration['customer_id'],migration['created_by'])
    migration = service.repo.get(identifier, lock=True)
    if migration['version'] != body['version']:
        raise ApiError(409,'CONCURRENT_UPDATE','Reload the migration before creating a workspace.')
    if migration['source_configuration'].get('sourceClusterId') != source['source_cluster_id']:
        raise ApiError(409,'SOURCE_CHANGED','The source changed. Reload before creating a workspace.')
    inventory = service.repo.get_source_inventory(identifier).get('inventory')
    if not inventory or inventory.get('inventoryDigest') != body['inventoryDigest']:
        raise ApiError(409,'STALE_INVENTORY','Refresh discovery and use the current inventory snapshot.')
    known = {r.get('namespace') for r in inventory.get('resources',[]) if r.get('namespace')}
    known.update(r.get('name') for r in inventory.get('resources',[]) if r.get('kind') == 'Namespace')
    if not set(body['namespaces']) <= known:
        raise ApiError(400,'UNKNOWN_NAMESPACE','Select namespaces present in captured inventory.')
    bucket, key_id, owner = storage_configuration()
    report = build_report(migration,inventory,source)
    if not report.get('analysisCurrent'):
        raise ApiError(409, 'SOURCE_CHECK_REQUIRED', 'Run Recheck sources against the current inventory before updating the workspace index.')
    planned = plan_artifacts(report, body['namespaces'])
    fingerprint = hashlib.sha256(canonical(planned)).hexdigest()
    previous = service.repo.list_artifact_workspaces(identifier, migration['customer_id'])
    for existing in previous:
        saved = existing['manifest']
        if (existing['inventory_digest'] == body['inventoryDigest']
                and existing['source_cluster_id'] == source['source_cluster_id']
                and sorted(saved['namespaces']) == sorted(body['namespaces'])
                and saved.get('analysisFingerprint') == fingerprint):
            return read(service, identifier, existing['workspace_id'])
    workspace_id = 'AWS-' + uuid.uuid4().hex
    manifest = dict(schemaVersion=1,workspaceId=workspace_id,migrationId=identifier,customerId=migration['customer_id'],
                    sourceClusterId=source['source_cluster_id'],inventoryDigest=body['inventoryDigest'],
                    inventoryVersion=inventory['inventoryVersion'],migrationVersion=migration['version'],
                    namespaces=body['namespaces'],createdAt=datetime.now(timezone.utc).isoformat(),status='PLANNED',
                    artifacts=planned, analysisFingerprint=fingerprint,
                    mappingEvidence=[{'workload':r['workload'],'mappingStatus':r.get('mappingStatus','UNRESOLVED')}
                                     for r in report.get('workloads',[]) if r['workload'].get('namespace') in body['namespaces']],
                    limitations=['Uncollected files and images require collection. Reused objects are verified copies of exact source identities.',
                                 'Persistent data and target deployment are separate workstreams.'])
    from .workspace_reuse import carry_forward, save_reused
    client = client or s3_client(fast=True)
    reused = carry_forward(service, manifest, client, bucket, key_id, owner)
    by_id = {r['artifact_id']: r for r in reused}
    for artifact in manifest['artifacts']:
        if artifact['artifactId'] in by_id:
            artifact['status'] = 'COLLECTED'
            artifact['validation'] = by_id[artifact['artifactId']]['validation']
    manifest['reusedArtifactCount'] = len(reused)
    manifest['storage'] = {'bucket': bucket, 'prefix': workspace_prefix(migration['customer_id'], identifier, workspace_id)}
    for artifact in manifest['artifacts']:
        if artifact['artifactId'] in by_id:
            record = by_id[artifact['artifactId']]
            artifact['storage'] = {'bucket': bucket, 'key': record['object_key'], 'versionId': record['object_version']}
    key = workspace_prefix(migration['customer_id'],identifier,workspace_id) + 'workspace-manifest.json'
    version, sha = persist_manifest(client,bucket,key_id,owner,key,manifest)
    service.repo.create_artifact_workspace(manifest,bucket,key,version,sha)
    save_reused(service, workspace_id, reused)
    return {**manifest,'stale':False,'collectedArtifactCount':len(reused)}


def read(service,identifier,workspace_id=None):
    service.access.require('migration.view')
    migration,source = service.deployment_context(identifier)
    service.access.require_customer(migration['customer_id'],migration['created_by'])
    inventory = service.repo.get_source_inventory(identifier).get('inventory') or {}
    rows = service.repo.list_artifact_workspaces(identifier,migration['customer_id'],workspace_id)
    if workspace_id and not rows:
        raise ApiError(404,'WORKSPACE_NOT_FOUND','Workspace was not found within this migration.')
    results = []
    for row in rows:
        records, jobs = service.repo.workspace_collection_state(row['workspace_id'])
        by_id = {a['artifact_id']:a for a in records}
        artifacts = [{**a, 'status':by_id.get(a['artifactId'],{}).get('status',a['status']),
                      'validation':by_id.get(a['artifactId'],{}).get('validation',{})}
                     for a in row['manifest']['artifacts']]
        for artifact in artifacts:
            record = by_id.get(artifact['artifactId'], {})
            if artifact['status'] not in {'COLLECTED', 'EXCLUDED_FROM_REPLAY'}:
                artifact.pop('storage', None)
            elif record.get('object_key') and record.get('object_version'):
                # The saved object may belong to an older workspace reused by this
                # snapshot. Never reconstruct or relocate its immutable location.
                artifact['storage'] = {'bucket': row['bucket_name'], 'key': record['object_key'],
                                       'versionId': record['object_version'], 'sha256': record.get('sha256'),
                                       'sizeBytes': record.get('size_bytes')}
        results.append({**row['manifest'], 'status':row['status'], 'artifacts':artifacts,
                        'inventoryDigest':row['inventory_digest'], 'sourceClusterId':row['source_cluster_id'],
                        'collectedArtifactCount':sum(a['status']=='COLLECTED' for a in artifacts),
                        'excludedArtifactCount':sum(a['status']=='EXCLUDED_FROM_REPLAY' for a in artifacts),
                        'requiredArtifactCount':sum(a['status']!='EXCLUDED_FROM_REPLAY' for a in artifacts),
                        'unresolvedArtifactCount':sum(a['status'] not in {'COLLECTED','EXCLUDED_FROM_REPLAY'} for a in artifacts),
                        'jobs':[{'jobId':j['job_id'],'artifactId':j['artifact_id'],'status':j['status'],
                                 'attempts':j['attempts'],'errorCode':j['error_code']} for j in jobs],
                        'stale':row['inventory_digest'] != inventory.get('inventoryDigest') or row['source_cluster_id'] != source['source_cluster_id']})
    return results[0] if workspace_id else {'migrationId':identifier,'workspaces':results}


def exclude_historical_job(service, identifier, body, client=None):
    """An explicit operator disposition, not proof of ownership or a recovered Job."""
    service.access.require('migration.edit')
    migration, source = service.deployment_context(identifier)
    service.access.require_customer(migration['customer_id'], migration['created_by'])
    migration = service.repo.get(identifier, lock=True)
    if migration['version'] != body['version']:
        raise ApiError(409, 'CONCURRENT_UPDATE', 'Reload before reviewing historical runs.')
    request = body['recovery']
    if request.get('confirmHistoricalRun') is not True:
        raise ApiError(400, 'HISTORICAL_REVIEW_REQUIRED', 'Confirm the source Job was deleted and belongs to the selected CronJob.')
    workspace_id, artifact_id = request.get('workspaceId'), request.get('artifactId')
    if not workspace_id or not artifact_id or not request.get('parentArtifactId') or not request.get('parentCronJobName'):
        raise ApiError(400, 'HISTORICAL_REVIEW_REQUIRED', 'Select the Job and a saved parent CronJob definition.')
    workspace = read(service, identifier, workspace_id)
    if workspace['stale']:
        raise ApiError(409, 'STALE_WORKSPACE', 'Review a workspace from the current inventory.')
    by_id = {a['artifactId']: a for a in workspace['artifacts']}
    artifact, parent = by_id.get(artifact_id), by_id.get(request['parentArtifactId'])
    resource = (artifact or {}).get('source', {}).get('resource', {})
    if not artifact or artifact['kind'] != 'LIVE_DEFINITION' or resource.get('kind') != 'Job':
        raise ApiError(400, 'HISTORICAL_JOB_REQUIRED', 'Only a Job run can receive this historical exclusion.')
    if artifact['status'] == 'EXCLUDED_FROM_REPLAY':
        review = artifact.get('validation', {}).get('historicalReview', {})
        if review.get('parentDefinitionArtifactId') != request['parentArtifactId'] or review.get('parent', {}).get('name') != request['parentCronJobName']:
            raise ApiError(409, 'HISTORICAL_REVIEW_EXISTS', 'This run already has a recorded historical review.')
        return workspace
    if artifact['status'] != 'RECOVERY_REQUIRED' or artifact.get('validation', {}).get('recovery', {}).get('status') != 'CUSTOMER_INPUT_REQUIRED':
        raise ApiError(409, 'FAILED_JOB_EXPORT_REQUIRED', 'Review the failed source export before excluding a historical Job.')
    parent_identity = dict(apiVersion='batch/v1', kind='CronJob', namespace=resource['namespace'], name=request['parentCronJobName'])
    def linked(a):
        return any(all(w.get(k) == v for k, v in parent_identity.items()) for w in a.get('workloads', []))
    if not parent or parent['kind'] not in {'REPOSITORY_DEFINITION', 'LIVE_DEFINITION'} or parent['status'] != 'COLLECTED' or not linked(parent):
        raise ApiError(409, 'SAVED_CRONJOB_REQUIRED', 'Select a collected CronJob definition in the same namespace and workspace.')
    images = [a for a in workspace['artifacts'] if a['kind'] == 'IMAGE' and linked(a)]
    if not images or any(a['status'] != 'COLLECTED' or not re.fullmatch(r'sha256:[a-f0-9]{64}', a.get('source', {}).get('digest') or '') for a in images):
        raise ApiError(409, 'CRONJOB_IMAGES_REQUIRED', 'Collect all pinned images linked to this CronJob first.')
    bucket, key_id, owner = storage_configuration()
    rows = service.repo.list_artifact_workspaces(identifier, migration['customer_id'], workspace_id)
    if not rows or rows[0]['bucket_name'] != bucket:
        raise ApiError(409, 'WORKSPACE_STORAGE_CHANGED', 'Workspace storage configuration changed.')
    required_ids = [parent['artifactId'], *[a['artifactId'] for a in images]]
    records = service.repo.db.execute(
        'SELECT artifact_id,object_key,object_version,sha256,size_bytes FROM migration_management.workspace_artifacts '
        'WHERE workspace_id=%s AND artifact_id=ANY(%s)', [workspace_id, required_ids]).fetchall()
    objects = {r['artifact_id']: r for r in records}
    prefix = workspace_prefix(migration['customer_id'], identifier, workspace_id)
    for required_id in required_ids:
        obj = objects.get(required_id, {})
        if (not obj.get('object_key', '').startswith(prefix) or not obj.get('object_version') or obj.get('object_version') == 'null'
                or not re.fullmatch(r'[a-f0-9]{64}', obj.get('sha256') or '') or not (obj.get('size_bytes') or 0) > 0):
            raise ApiError(409, 'PARENT_STORAGE_EVIDENCE_REQUIRED', 'The parent definition and images need verified collection records.')
    review = dict(decisionId='DEC-' + uuid.uuid4().hex, parent=parent_identity,
                  parentDefinitionArtifactId=parent['artifactId'], imageArtifactIds=[a['artifactId'] for a in images],
                  reviewedBy=service.principal.user_id, reviewedAt=datetime.now(timezone.utc).isoformat(),
                  sourceAbsence='OPERATOR_CONFIRMED', parentOwnership='OPERATOR_ASSERTED',
                  replayRequired=False, targetReady=False,
                  limitation='Operator-reviewed historical exclusion. The deleted Job was not recovered; former ownership was not independently verified.')
    receipt = dict(schemaVersion=1, kind='HISTORICAL_JOB_REVIEW', workspaceId=workspace_id, migrationId=identifier,
                   sourceClusterId=source['source_cluster_id'], inventoryDigest=workspace['inventoryDigest'],
                   artifactId=artifact_id, resource=resource, review=review, collectedParentObjects=records,
                   previousValidation=artifact.get('validation', {}))
    key = prefix + 'reviews/' + review['decisionId'] + '.json'
    version, sha = persist_manifest(client or s3_client(), bucket, key_id, owner, key, receipt)
    validation = {**artifact.get('validation', {}), 'historicalReview': review, 'targetReady': False, 'reviewRequired': True}
    service.repo.db.execute(
        "UPDATE migration_management.workspace_artifacts SET status='EXCLUDED_FROM_REPLAY',validation=%s::jsonb,"
        'object_key=%s,object_version=%s,sha256=%s,size_bytes=%s,updated_at=now() WHERE workspace_id=%s AND artifact_id=%s',
        [canonical(validation).decode(), key, version, sha, len(canonical(receipt)), workspace_id, artifact_id])
    return read(service, identifier, workspace_id)

