"""Reuse exact, verified repository/image objects within one assessment only."""
import copy
import json
import re
from concurrent.futures import ThreadPoolExecutor

from .artifact_workspace import canonical, workspace_prefix


def carry_forward(service, manifest, client, bucket, key_id, owner):
    # Live exports, Helm recovery and historical receipts describe a particular
    # inventory. They must never inherit a previous snapshot's disposition.
    eligible = {a['artifactId']: a for a in manifest['artifacts']
                if a['kind'] in {'IMAGE', 'REPOSITORY_DEFINITION'} and a['status'] == 'PENDING_COLLECTION'}
    if not eligible:
        return []
    rows = service.repo.db.execute(
        "SELECT a.*, w.bucket_name, w.manifest AS previous_manifest "
        "FROM migration_management.workspace_artifacts a "
        "JOIN migration_management.artifact_workspaces w USING (workspace_id) "
        "WHERE w.migration_id=%s AND w.customer_id=%s AND w.source_cluster_id=%s "
        "AND w.bucket_name=%s AND a.status='COLLECTED' AND a.artifact_id=ANY(%s) "
        "ORDER BY w.created_at DESC LIMIT 200",
        [manifest['migrationId'], manifest['customerId'], manifest['sourceClusterId'], bucket, list(eligible)],
    ).fetchall()
    candidates = {}
    for row in rows:
        artifact = eligible.get(row['artifact_id'])
        previous = row.get('previous_manifest') or {}
        if (not artifact or artifact['artifactId'] in candidates or row.get('kind') != artifact['kind']
                or row.get('status') != 'COLLECTED' or row.get('bucket_name') != bucket
                or canonical(row.get('provenance')) != canonical(artifact['source'])
                or previous.get('workspaceId') != row.get('workspace_id')
                or any(previous.get(k) != manifest[k] for k in ('customerId', 'migrationId', 'sourceClusterId'))):
            continue
        # Require the previous index to agree with the collection record too.
        if not any(a.get('artifactId') == artifact['artifactId'] and a.get('kind') == artifact['kind']
                   and canonical(a.get('source')) == canonical(artifact['source']) for a in previous.get('artifacts', [])):
            continue
        source = artifact['source']
        validation = row.get('validation') or {}
        if artifact['kind'] == 'IMAGE':
            if (not re.fullmatch(r'sha256:[a-f0-9]{64}', source.get('digest') or '')
                    or validation.get('format') != 'OCI_ARCHIVE' or validation.get('integrity') != 'VERIFIED'
                    or validation.get('content') != 'COMPLETE' or validation.get('digest') != source['digest']):
                continue
        elif (not re.fullmatch(r'[a-f0-9]{40}', source.get('commit') or '')
              or not source.get('repository') or not source.get('filePath')):
            continue
        # CopyObject is deliberately bounded. Larger objects remain collectable.
        if type(row.get('size_bytes')) is not int or not 0 < row['size_bytes'] <= 5_000_000_000:
            continue
        candidates[artifact['artifactId']] = row
        # Keep this synchronous API operation below the gateway/Lambda budget.
        # Additional or slow objects remain eligible for normal collection.
        if len(candidates) == 12:
            break

    def reuse(item):
        artifact_id, row = item
        artifact = eligible[artifact_id]
        try:
            # Local import avoids the export -> workspace -> reuse import cycle.
            from .workspace_export import verify_object
            previous_prefix = workspace_prefix(manifest['customerId'], manifest['migrationId'], row['workspace_id'])
            verify_object(client, bucket, key_id, owner, previous_prefix, row,
                          image={'validation': row['validation']} if artifact['kind'] == 'IMAGE' else None,
                          artifact_id=artifact_id)
            key = workspace_prefix(manifest['customerId'], manifest['migrationId'], manifest['workspaceId']) + 'reused/' + artifact_id
            result = client.copy_object(
                Bucket=bucket, Key=key, ExpectedBucketOwner=owner, ExpectedSourceBucketOwner=owner,
                CopySource={'Bucket': bucket, 'Key': row['object_key'], 'VersionId': row['object_version']},
                ServerSideEncryption='aws:kms', SSEKMSKeyId=key_id, ChecksumAlgorithm='SHA256')
            record = {**row, 'object_key': key, 'object_version': result.get('VersionId')}
            verify_object(client, bucket, key_id, owner, key, record, artifact_id=artifact_id)
            validation = copy.deepcopy(row['validation'])
            validation['targetReady'] = False
            validation['reuse'] = {'workspaceId': row['workspace_id'], 'objectVersion': row['object_version'],
                                   'identity': 'EXACT_SOURCE', 'storage': 'PINNED_VERSION_VERIFIED'}
            return {**record, 'artifact_id': artifact_id, 'validation': validation}
        except Exception:
            # No COLLECTED claim on missing objects, permission or integrity
            # failures. The new snapshot keeps this artifact ready to collect.
            return None

    # Threads perform only S3 operations; all database work stays on this thread.
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(reuse, candidates.items()))
    return [r for r in results if r is not None]


def save_reused(service, workspace_id, records):
    for row in records:
        service.repo.db.execute(
            "UPDATE migration_management.workspace_artifacts SET status='COLLECTED',object_key=%s,object_version=%s,"
            "sha256=%s,size_bytes=%s,validation=%s::jsonb,updated_at=now() WHERE workspace_id=%s AND artifact_id=%s",
            [row['object_key'], row['object_version'], row['sha256'], row['size_bytes'],
             json.dumps(row['validation']), workspace_id, row['artifact_id']],
        )
