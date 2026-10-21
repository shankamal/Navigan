"""Transactional DB queue. Polling is the dispatch mechanism: no dual-write gap."""
import uuid
from .artifact_workspace import read
from .deployment_sources import StrictModel
from pydantic import Field
from navigan.shared.errors import ApiError

class StartCollection(StrictModel):
    version: int = Field(gt=0)

def enqueue(service, identifier, workspace_id, body):
    service.access.require('migration.edit')
    migration, source = service.deployment_context(identifier)
    service.access.require_customer(migration['customer_id'], migration['created_by'])
    migration = service.repo.get(identifier, lock=True)
    if migration['version'] != body['version']:
        raise ApiError(409,'CONCURRENT_UPDATE','Reload before starting collection.')
    snapshot = read(service, identifier, workspace_id)
    if snapshot['stale']:
        raise ApiError(409,'STALE_WORKSPACE','Create a workspace from current discovery before collecting.')
    db = service.repo.db
    artifacts = db.execute("SELECT artifact_id FROM migration_management.workspace_artifacts WHERE workspace_id=%s AND kind='REPOSITORY_DEFINITION' AND status <> 'COLLECTED'",[workspace_id]).fetchall()
    for artifact in artifacts:
        db.execute("INSERT INTO migration_management.workspace_collection_jobs (job_id,workspace_id,artifact_id,status,created_by) VALUES (%s,%s,%s,'QUEUED',%s) "
                   "ON CONFLICT(workspace_id,artifact_id) DO UPDATE SET status='QUEUED',attempts=0,error_code=NULL,lease_token=NULL,lease_until=NULL,updated_at=now() "
                   "WHERE workspace_collection_jobs.status='FAILED'",
                   ['COL-'+uuid.uuid4().hex, workspace_id,artifact['artifact_id'],service.principal.user_id])
    if artifacts:
        settle(db, workspace_id)
    return read(service, identifier, workspace_id)


def claim(db):
    # Exhausted leases are terminal, so crashed workers cannot leave eternal RUNNING jobs.
    exhausted = db.execute("UPDATE migration_management.workspace_collection_jobs SET status='FAILED',error_code='LEASE_EXHAUSTED',lease_token=NULL,lease_until=NULL,updated_at=now() "
                          "WHERE status='RUNNING' AND lease_until<now() AND attempts>=3 RETURNING workspace_id").fetchall()
    for row in exhausted:
        settle(db,row['workspace_id'])
    token = uuid.uuid4().hex
    return db.execute("WITH candidate AS (SELECT job_id FROM migration_management.workspace_collection_jobs "
                      "WHERE status='QUEUED' OR (status='RUNNING' AND lease_until<now() AND attempts<3) "
                      "ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1) "
                      "UPDATE migration_management.workspace_collection_jobs j SET status='RUNNING',attempts=attempts+1,lease_token=%s,"
                      "lease_until=now()+interval '5 minutes',updated_at=now() FROM candidate c WHERE j.job_id=c.job_id RETURNING j.*",[token]).fetchone()


def settle(db, workspace_id):
    db.execute("SELECT workspace_id FROM migration_management.artifact_workspaces WHERE workspace_id=%s FOR UPDATE",[workspace_id]).fetchone()
    db.execute("UPDATE migration_management.artifact_workspaces SET status=CASE WHEN EXISTS "
               "(SELECT 1 FROM migration_management.workspace_collection_jobs WHERE workspace_id=%s AND status IN ('QUEUED','RUNNING')) "
               "THEN 'COLLECTING' ELSE 'PARTIAL' END WHERE workspace_id=%s",[workspace_id,workspace_id])


def finish(db, job, result=None, error=None):
    accepted = db.execute("UPDATE migration_management.workspace_collection_jobs SET status=%s,error_code=%s,lease_token=NULL,lease_until=NULL,updated_at=now() "
                          "WHERE job_id=%s AND status='RUNNING' AND lease_token=%s AND lease_until>now() RETURNING workspace_id",
                          ['FAILED' if error else 'SUCCEEDED',error,job['job_id'],job['lease_token']]).fetchone()
    if not accepted:
        return False
    if result:
        db.execute("UPDATE migration_management.workspace_artifacts SET status='COLLECTED',object_key=%s,object_version=%s,sha256=%s,size_bytes=%s,"
                   "validation=%s::jsonb,updated_at=now() WHERE workspace_id=%s AND artifact_id=%s",
                   [result['key'],result['version'],result['sha256'],result['size'],result['validation'],job['workspace_id'],job['artifact_id']])
    settle(db,job['workspace_id'])
    return True
