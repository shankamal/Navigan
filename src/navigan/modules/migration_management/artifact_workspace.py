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


def s3_client():
    import boto3
    from botocore.config import Config
    return boto3.client('s3', config=Config(signature_version='s3v4',connect_timeout=3,read_timeout=5,retries={'max_attempts':2}))


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
    workspace_id = 'AWS-' + uuid.uuid4().hex
    manifest = dict(schemaVersion=1,workspaceId=workspace_id,migrationId=identifier,customerId=migration['customer_id'],
                    sourceClusterId=source['source_cluster_id'],inventoryDigest=body['inventoryDigest'],
                    inventoryVersion=inventory['inventoryVersion'],migrationVersion=migration['version'],
                    namespaces=body['namespaces'],createdAt=datetime.now(timezone.utc).isoformat(),status='PLANNED',
                    artifacts=plan_artifacts(report,body['namespaces']),
                    mappingEvidence=[{'workload':r['workload'],'mappingStatus':r.get('mappingStatus','UNRESOLVED')}
                                     for r in report.get('workloads',[]) if r['workload'].get('namespace') in body['namespaces']],
                    limitations=['Only the workspace index is stored. Files and images have not been collected.',
                                 'Persistent data and target deployment are separate workstreams.'])
    key = workspace_prefix(migration['customer_id'],identifier,workspace_id) + 'workspace-manifest.json'
    version, sha = persist_manifest(client or s3_client(),bucket,key_id,owner,key,manifest)
    service.repo.create_artifact_workspace(manifest,bucket,key,version,sha)
    return {**manifest,'stale':False,'collectedArtifactCount':0}


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
        results.append({**row['manifest'], 'status':row['status'], 'artifacts':artifacts,
                        'collectedArtifactCount':sum(a['status']=='COLLECTED' for a in artifacts),
                        'jobs':[{'jobId':j['job_id'],'artifactId':j['artifact_id'],'status':j['status'],
                                 'attempts':j['attempts'],'errorCode':j['error_code']} for j in jobs],
                        'stale':row['inventory_digest'] != inventory.get('inventoryDigest') or row['source_cluster_id'] != source['source_cluster_id']})
    return results[0] if workspace_id else {'migrationId':identifier,'workspaces':results}
