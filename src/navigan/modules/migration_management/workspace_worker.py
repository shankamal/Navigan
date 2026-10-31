"""One leased repository collection per invocation; callable by schedule or CLI."""
import json
import urllib.error
from navigan.shared.database import transaction
from .workspace_collection import claim, finish
from .repository_collector import collect, CollectionError
from .artifact_workspace import storage_configuration, storage_prefix, artifact_folder, persist_manifest, s3_client, canonical
from .source_authentication import repository_token
from .deployment_sources import repository_read_token


def load_context(db, job, kind="REPOSITORY_DEFINITION"):
    row=db.execute("SELECT w.*,a.provenance,a.kind AS artifact_kind,s.delivery_configuration,m.status AS migration_status,"
                   "m.source_configuration,(SELECT inventory_digest FROM migration_management.migration_source_inventories "
                   "WHERE migration_id=w.migration_id ORDER BY inventory_version DESC LIMIT 1) AS current_digest, "
                   "(SELECT inventory_version FROM migration_management.migration_source_inventories "
                   "WHERE migration_id=w.migration_id ORDER BY inventory_version DESC LIMIT 1) AS current_inventory_version "
                   "FROM migration_management.artifact_workspaces w JOIN migration_management.workspace_artifacts a USING(workspace_id) "
                   "JOIN migration_management.migrations m USING(migration_id) "
                   "JOIN migration_management.source_clusters s ON s.source_cluster_id=w.source_cluster_id AND s.customer_id=w.customer_id "
                   "WHERE w.workspace_id=%s AND a.artifact_id=%s AND m.customer_id=w.customer_id AND NOT EXISTS "
                   "(SELECT 1 FROM migration_management.migration_audit_log l WHERE l.migration_id=w.migration_id AND l.action='MIGRATION_DELETED')",
                   [job['workspace_id'],job['artifact_id']]).fetchone()
    if not row or row['artifact_kind']!=kind or row['migration_status']=='CANCELLED' or row['current_digest']!=row['inventory_digest'] or row['source_configuration'].get('sourceClusterId')!=row['source_cluster_id']:
        raise CollectionError('STALE_WORKSPACE')
    if row.get('manifest',{}).get('storageLayoutVersion',1)==2 and row['inventory_version']!=row.get('current_inventory_version'):
        raise CollectionError('STALE_WORKSPACE')
    delivery=row.get('delivery_configuration') or {}
    if kind=='IMAGE':
        from .image_collector import source_reference
        parts,_=source_reference(row['provenance'])
        if parts['registry'] not in delivery.get('deploymentDiscovery',{}).get('registries',[]):
            raise CollectionError('REGISTRY_ACCESS_CHANGED')
        row['credential_entry']=delivery.get('deploymentAuthentication',{}).get('registry:'+parts['registry'],{})
        return row
    repository=row['provenance']['repository']
    if repository not in [r['repository'] for r in delivery.get('deploymentDiscovery',{}).get('repositories',[])]:
        raise CollectionError('REPOSITORY_ACCESS_CHANGED')
    # Credential values are resolved after the DB transaction closes.
    row['credential_entry']=delivery.get('deploymentAuthentication',{}).get('github:'+repository,{})
    organization=repository.split('/')[0]
    connection=db.execute("SELECT installation_id FROM cluster_management.github_app_connections WHERE customer_id=%s AND lower(organization_login)=lower(%s) AND status='ACTIVE' AND installation_id IS NOT NULL",[row['customer_id'],organization]).fetchone()
    row['installation_id']=connection['installation_id'] if connection else None
    return row


def run_once():
    with transaction() as db:
        job=claim(db)
    if not job:
        return {'processed':False}
    try:
        with transaction() as db:
            row=load_context(db,job)
        def app_token(repository):
            return repository_read_token(row['installation_id'],repository.split('/')[1]) if row['installation_id'] else None
        token=repository_token(row,row['provenance']['repository'],row['credential_entry'],app_token)
        bundle=collect(row['provenance'],token)
        bucket,key_id,owner=storage_configuration()
        if bucket!=row['bucket_name']:
            raise CollectionError('WORKSPACE_STORAGE_CHANGED')
        key=storage_prefix(row['customer_id'],row['migration_id'],job['workspace_id'],row['manifest'])+artifact_folder(row['manifest'],'REPOSITORY_DEFINITION')+job['artifact_id']+'/'+job['lease_token']+'.json'
        version,sha=persist_manifest(s3_client(),bucket,key_id,owner,key,bundle)
        result=dict(key=key,version=version,sha256=sha,size=len(canonical(bundle)),validation=json.dumps(bundle['validation']))
        with transaction() as db:
            # Recheck current source before publishing the stored object into workspace metadata.
            load_context(db,job)
            accepted=finish(db,job,result=result)
        return {'processed':True,'accepted':accepted}
    except Exception as error:
        # Do not persist exception bodies: they can contain credentials or file content.
        code=error.code if isinstance(error,CollectionError) else (
            'ACCESS_REQUIRED' if isinstance(error,urllib.error.HTTPError) and error.code in {401,403} else
            'SOURCE_UNAVAILABLE' if isinstance(error,urllib.error.HTTPError) and error.code==404 else 'COLLECTION_FAILED')
        with transaction() as db:
            finish(db,job,error=code)
        return {'processed':True,'status':'FAILED','code':code}


def lambda_handler(event,context):
    return run_once()

if __name__=='__main__':
    print(json.dumps(run_once()))
