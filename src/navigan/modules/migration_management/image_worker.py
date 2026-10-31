"""Long-running image queue worker; transfers are not executed in Lambda."""
import base64
from contextlib import contextmanager
import json
import os
import signal
import tempfile
import threading
from .artifact_workspace import storage_configuration, storage_prefix, artifact_folder, s3_client
from .workspace_collection import claim, finish, renew
from .workspace_worker import load_context
from .image_collector import source_reference, copy_archive, validate_archive, upload_archive
from .repository_collector import CollectionError
from .source_authentication import read_credential, ecr_client, ecr_identity
from navigan.shared.database import transaction


def registry_auth(row):
    parts, _ = source_reference(row['provenance'])
    entry = row['credential_entry']; mode = entry.get('mode', 'PUBLIC')
    if '.dkr.ecr.' in parts['registry']:
        if mode not in {'AWS_ROLE', 'AWS_EXISTING_ROLE'}:
            raise CollectionError('REGISTRY_ACCESS_REQUIRED')
        client = ecr_client(parts['registry'], entry, pull_repository=parts['repository'])
        account, _ = ecr_identity(parts['registry'])
        return client.get_authorization_token(registryIds=[account])['authorizationData'][0]['authorizationToken']
    if mode == 'PUBLIC': return None
    if mode != 'TOKEN': raise CollectionError('REGISTRY_AUTH_MODE_UNSUPPORTED')
    credential = read_credential(row, 'registry:'+parts['registry'], entry)
    username = credential.get('username', ''); token = credential.get('token', '')
    if not username or ':' in username or not token: raise CollectionError('REGISTRY_ACCESS_REQUIRED')
    return base64.b64encode((username+':'+token).encode()).decode()


@contextmanager
def heartbeat(job, cancel=None):
    stopped = threading.Event(); lost = threading.Event()
    def pulse():
        while not stopped.wait(20):
            try:
                with transaction() as db:
                    if not renew(db, job): lost.set(); return
            except Exception: lost.set(); return
    thread = threading.Thread(target=pulse, daemon=True); thread.start()
    def check():
        if cancel is not None and cancel.is_set(): raise CollectionError('IMAGE_WORKER_STOPPING')
        if lost.is_set(): raise CollectionError('COLLECTION_LEASE_LOST')
    try: yield check
    finally: stopped.set(); thread.join(timeout=10)


def run_once(cancel=None):
    with transaction() as db: job = claim(db, 'IMAGE')
    if not job: return {'processed': False}
    try:
        with heartbeat(job, cancel) as check:
            with transaction() as db: row = load_context(db, job, 'IMAGE')
            auth = registry_auth(row)
            bucket, key_id, owner = storage_configuration()
            if bucket != row['bucket_name']: raise CollectionError('WORKSPACE_STORAGE_CHANGED')
            with tempfile.TemporaryDirectory(prefix='navigan-image-') as directory:
                os.chmod(directory, 0o700)
                path = copy_archive(row['provenance'], directory, auth=auth, check=check)
                validation = validate_archive(path, row['provenance']['digest'], check=check)
                key = storage_prefix(row['customer_id'], row['migration_id'], job['workspace_id'], row['manifest'])+artifact_folder(row['manifest'],'IMAGE')+job['artifact_id']+'/'+job['lease_token']+'.tar'
                result = upload_archive(s3_client(), path, bucket, key_id, owner, key, check=check)
                result['validation'] = json.dumps(validation)
            check()
            with transaction() as db:
                current = load_context(db, job, 'IMAGE')
                if current['credential_entry'] != row['credential_entry']:
                    raise CollectionError('REGISTRY_ACCESS_CHANGED')
                accepted = finish(db, job, result=result)
        return {'processed': True, 'accepted': accepted}
    except Exception as error:
        code = error.code if isinstance(error, CollectionError) else 'IMAGE_COLLECTION_FAILED'
        with transaction() as db: finish(db, job, error=code)
        return {'processed': True, 'status': 'FAILED', 'code': code}


def main():
    roles = [r.strip() for r in os.getenv('IMAGE_COLLECTION_ROLE_ARNS', '').split(',') if r.strip()]
    if roles: os.environ['SOURCE_REGISTRY_ALLOWED_ROLE_ARNS'] = json.dumps(roles)
    stopped = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT): signal.signal(signum, lambda *_: stopped.set())
    while not stopped.is_set():
        try: result = run_once(stopped)
        except Exception: result = {'status': 'FAILED', 'code': 'IMAGE_WORKER_UNAVAILABLE', 'processed': False}
        print(json.dumps(result), flush=True)
        stopped.wait(1 if result.get('processed') else 20)

if __name__ == '__main__': main()
