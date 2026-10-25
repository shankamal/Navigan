#!/usr/bin/env python3
"""Promote live PROD collector artifacts into DEV, retaining DEV configuration.

Default/--prepare reads AWS and saves a private local plan/rollback record.
--apply prepares and executes. --execute PLAN executes an exact saved plan.
Writes only DEV Lambda code, DEV ECR artifacts and the DEV image service/task.
Does not rebuild branch source, change IAM, schedules, databases or PROD resources.
"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('collector_parity_support',ROOT/'scripts/align-dev-workspace-with-prod.py')
support=importlib.util.module_from_spec(spec);spec.loader.exec_module(support)
ACCOUNT,REGION=support.ACCOUNT,support.REGION
require=support.require
PARENTS=support.PARENTS
REGISTRY=f'{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com'
DEV_REPOSITORY='navigan/dev-workspace-image-collector'
PROD_REPOSITORY='navigan/prod-workspace-image-collector'
FORMAT='navigan-dev-collector-parity-v1'


def stable(service):
    return (service['desiredCount']==1 and service['runningCount']==1 and service['pendingCount']==0
            and len(service.get('deployments',[]))==1 and service['deployments'][0].get('rolloutState')=='COMPLETED')


def snapshot(session,label):
    parent=PARENTS[label];cfn=session.client('cloudformation')
    stack=cfn.describe_stacks(StackName=parent)['Stacks'][0]
    params={p['ParameterKey']:p['ParameterValue'] for p in stack['Parameters']}
    require(params.get('DatabaseName')==support.DATABASES[label],'Wrong parent database')
    require(stack['StackStatus'] in ('CREATE_COMPLETE','UPDATE_COMPLETE','UPDATE_ROLLBACK_COMPLETE'),'Parent stack is not stable')
    physical=lambda suffix,logical:cfn.describe_stack_resource(StackName=parent+suffix,LogicalResourceId=logical)['StackResourceDetail']['PhysicalResourceId']
    name=physical('-workspace-repositories','Worker')
    require(name==parent+'-workspace-repositories','Unexpected repository collector function')
    worker=session.client('lambda').get_function(FunctionName=name)
    cfg=worker['Configuration'];env=cfg.get('Environment',{}).get('Variables',{})
    require(env.get('DB_NAME')==support.DATABASES[label] and cfg.get('State')=='Active' and
            cfg.get('LastUpdateStatus')=='Successful' and cfg.get('Runtime')=='python3.12'
            and cfg.get('Handler')=='navigan.modules.migration_management.workspace_worker.lambda_handler'
            and cfg.get('Architectures',['x86_64'])==['x86_64'] and cfg.get('PackageType','Zip')=='Zip',
            'Repository collector runtime/identity mismatch')
    service_id=physical('-workspace-images','WorkerService');parts=service_id.split('/')
    require(len(parts)==3 and ':service/' in service_id,'Cannot resolve image collector service')
    cluster=parts[-2];ecs=session.client('ecs')
    response=ecs.describe_services(cluster=cluster,services=[service_id])
    require(not response.get('failures') and len(response.get('services',[]))==1,'Image service missing')
    service=response['services'][0];require(stable(service),'Image service must have one healthy completed task')
    require(service.get('deploymentController',{}).get('type','ECS')=='ECS','Unsupported deployment controller')
    described=ecs.describe_task_definition(taskDefinition=service['taskDefinition'],include=['TAGS'])
    task=described['taskDefinition']
    require(task['family'].startswith(parent+'-workspace-images-WorkerTask-'),'Unexpected image task family')
    collectors=[c for c in task['containerDefinitions'] if c['name']=='collector']
    require(len(collectors)==1,'Expected exactly one collector container')
    variables={v['name']:v['value'] for v in collectors[0].get('environment',[])}
    for key in ('DB_NAME','DB_PROXY_HOST','DB_SECRET_ARN','MIGRATION_WORKSPACE_BUCKET',
                'MIGRATION_WORKSPACE_KMS_KEY','MIGRATION_WORKSPACE_BUCKET_OWNER'):
        require(variables.get(key) and variables[key]==env.get(key),'Collector bindings differ: '+key)
    repository=DEV_REPOSITORY if label=='dev' else PROD_REPOSITORY
    require(collectors[0]['image'].startswith(REGISTRY+'/'+repository+'@sha256:'),'Unexpected collector image repository/reference')
    return {'worker':worker,'service':service,'task':task,'tags':described.get('tags',[]),'cluster':cluster,'image':collectors[0]['image']}


def signature(value):
    return {'worker':support.identity(value['worker']),
            'workerConfiguration':support.config_fingerprint(value['worker']['Configuration']),
            'task':value['task']['taskDefinitionArn'],'service':value['service']['serviceArn'],
            'serviceSettings':support.sha(json.dumps({k:v for k,v in value['service'].items() if k in (
                'desiredCount','networkConfiguration','deploymentConfiguration','capacityProviderStrategy',
                'launchType','platformVersion','loadBalancers','serviceRegistries','enableExecuteCommand',
                'schedulingStrategy','placementConstraints','placementStrategy','deploymentController')},sort_keys=True,default=str).encode())}


def manifest(ecr,repository,digest):
    response=ecr.batch_get_image(repositoryName=repository,imageIds=[{'imageDigest':digest}])
    images=response.get('images',[])
    require(not response.get('failures') and bool(images),'Unable to read collector manifest')
    rows={(i['imageId']['imageDigest'],i['imageManifest'],i.get('imageManifestMediaType')) for i in images}
    require(len(rows)==1,'Conflicting ECR manifest rows')
    row=next(iter(rows));require(row[0]==digest,'ECR returned another digest')
    value=json.loads(row[1])
    require((value.get('config',{}).get('digest') and value.get('layers')) or
            isinstance(value.get('manifests'),list),'Expected a collector image manifest or index')
    return value


def runtime_manifest(ecr,repository,digest):
    """Resolve only an unambiguous baseline linux/amd64 image, ignoring attestations."""
    seen=set()
    for _ in range(4):
        require(digest not in seen,'Cyclic collector image index')
        seen.add(digest)
        value=manifest(ecr,repository,digest)
        if value.get('config',{}).get('digest') and value.get('layers'):
            return digest,value
        candidates=[m for m in value['manifests'] if
                    m.get('platform',{}).get('os')=='linux' and
                    m.get('platform',{}).get('architecture')=='amd64' and
                    m.get('platform',{}).get('variant') in (None,'','v1')]
        require(len(candidates)==1,'Collector index must contain exactly one baseline linux/amd64 image')
        child=candidates[0]
        require(child.get('mediaType') in (
                    'application/vnd.oci.image.manifest.v1+json',
                    'application/vnd.docker.distribution.manifest.v2+json',
                    'application/vnd.oci.image.index.v1+json',
                    'application/vnd.docker.distribution.manifest.list.v2+json') and
                isinstance(child.get('digest'),str) and child['digest'].startswith('sha256:'),
                'Unsupported collector index descriptor')
        digest=child['digest']
    raise RuntimeError('Collector image index exceeds the supported nesting depth')


def content_identity(value):
    return {'config':value['config']['digest'],'layers':[v['digest'] for v in value['layers']]}


def verify_local_image(local,source,manifest_digest,expected):
    require(local.get('Architecture')=='amd64' and local.get('Os')=='linux','Unsupported collector platform')
    if local.get('Id')==expected['config']['digest']:
        # Classic Docker storage reports the config digest as the image ID.
        return
    # Containerd-backed storage may report the manifest digest as its ID.
    # Require the exact descriptor and repository reference as corroboration.
    descriptor=local.get('Descriptor') or {}
    require(local.get('Id')==manifest_digest and descriptor.get('digest')==manifest_digest and
            descriptor.get('mediaType') in ('application/vnd.oci.image.manifest.v1+json',
                                           'application/vnd.docker.distribution.manifest.v2+json') and
            source in local.get('RepoDigests',[]),
            'Local image identity differs from the verified ECR manifest/config')


def copy_image(session,source,directory):
    ecr=session.client('ecr');source_digest=source.rsplit('@',1)[1]
    source_digest,expected=runtime_manifest(ecr,PROD_REPOSITORY,source_digest)
    # Pull/tag the verified platform manifest, rather than an index or attestation.
    source=REGISTRY+'/'+PROD_REPOSITORY+'@'+source_digest
    with tempfile.TemporaryDirectory(prefix='docker-auth-',dir=directory) as authdir:
        docker=['docker','--config',authdir]
        def run(*args,**kw):
            return subprocess.run([*docker,*args],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=900,**kw)
        auth=ecr.get_authorization_token(registryIds=[ACCOUNT])['authorizationData'][0]
        username,password=base64.b64decode(auth['authorizationToken']).decode().split(':',1)
        run('login','--username',username,'--password-stdin',REGISTRY,input=password.encode())
        print('Copying the verified PROD image into the existing DEV repository; no source build.',flush=True)
        run('pull','--platform','linux/amd64',source)
        local=json.loads(run('image','inspect',source).stdout)[0]
        verify_local_image(local,source,source_digest,expected)
        tag='parity-'+source_digest.split(':',1)[1]
        target=REGISTRY+'/'+DEV_REPOSITORY+':'+tag
        existing=ecr.describe_repositories(repositoryNames=[DEV_REPOSITORY])['repositories']
        require(len(existing)==1 and existing[0]['registryId']==ACCOUNT,'DEV repository identity mismatch')
        # Reuse an already-copied immutable artifact without another push.
        check=ecr.batch_get_image(repositoryName=DEV_REPOSITORY,imageIds=[{'imageTag':tag}])
        if check.get('images'):
            dest=check['images'][0]['imageId']['imageDigest']
        else:
            require(all(x.get('failureCode')=='ImageNotFound' for x in check.get('failures',[])), 'Unexpected DEV ECR read failure')
            run('tag',source,target);run('push',target)
            found=ecr.describe_images(repositoryName=DEV_REPOSITORY,imageIds=[{'imageTag':tag}])['imageDetails']
            require(len(found)==1,'DEV image digest cannot be resolved');dest=found[0]['imageDigest']
        dest,copied=runtime_manifest(ecr,DEV_REPOSITORY,dest)
        require(content_identity(copied)==content_identity(expected),
                'Copied DEV image content differs from PROD')
        return REGISTRY+'/'+DEV_REPOSITORY+'@'+dest


def registration(task,tags,image,allowed):
    # Copy current DEV settings, including roles, volumes, logging and sidecars.
    request={k:copy.deepcopy(v) for k,v in task.items() if k in allowed}
    request['tags']=copy.deepcopy(tags)
    old=copy.deepcopy(request)
    matches=[c for c in request['containerDefinitions'] if c['name']=='collector']
    require(len(matches)==1,'Unexpected collector task definition')
    matches[0]['image']=image
    expected=copy.deepcopy(old)
    next(c for c in expected['containerDefinitions'] if c['name']=='collector')['image']=image
    require(request==expected,'Task settings changed outside collector image')
    return request


def wait_service(ecs,cluster,service,task):
    for attempt in range(120):
        response=ecs.describe_services(cluster=cluster,services=[service])
        require(not response.get('failures') and len(response.get('services',[]))==1,'Service disappeared during rollout')
        current=response['services'][0]
        if stable(current):
            require(current['taskDefinition']==task,'DEV collector rolled back; inspect service events before retry')
            return
        if attempt % 6 == 0:
            print('Waiting for DEV collector rollout to complete.',flush=True)
        time.sleep(10)
    raise RuntimeError('DEV rollout still unresolved; inspect events before retrying. Rollback task is saved in release record.')


def execute(session,path):
    plan=json.loads(path.read_text());require(plan.get('format')==FORMAT and plan.get('account')==ACCOUNT and plan.get('region')==REGION,'Invalid DEV collector plan')
    dev,prod=snapshot(session,'dev'),snapshot(session,'prod')
    require(signature(dev)==plan['dev'] and signature(prod)==plan['prod'],'Collector runtime changed since preparation')
    raw=(path.parent/'prod-repository.zip').read_bytes()
    require(support.zip_sha(raw)==prod['worker']['Configuration']['CodeSha256'],'PROD collector package checksum mismatch')
    require(len(raw)<=50*1024*1024,'Repository package exceeds direct Lambda upload limit; no promotion performed')
    original=(path.parent/'dev-repository-original.zip').read_bytes()
    require(support.zip_sha(original)==dev['worker']['Configuration']['CodeSha256'],'DEV rollback package checksum mismatch')
    target=copy_image(session,prod['image'],path.parent)
    ecs=session.client('ecs');allowed=set(ecs.meta.service_model.operation_model('RegisterTaskDefinition').input_shape.members)
    request=registration(dev['task'],dev['tags'],target,allowed)
    candidate=ecs.register_task_definition(**request)['taskDefinition']['taskDefinitionArn']
    # Save the exact candidate and rollback IDs before either runtime is changed.
    plan['candidateTask']=candidate;plan['candidateImage']=target
    path.write_text(json.dumps(plan,indent=2))
    require(signature(snapshot(session,'dev'))==plan['dev'] and signature(snapshot(session,'prod'))==plan['prod'],
            'Runtime changed while copying artifacts; no runtime promotion performed')
    lam=session.client('lambda');cfg=dev['worker']['Configuration']
    if cfg['CodeSha256']!=support.zip_sha(raw):
        lam.update_function_code(FunctionName=cfg['FunctionName'],RevisionId=cfg['RevisionId'],ZipFile=raw)
        lam.get_waiter('function_updated').wait(FunctionName=cfg['FunctionName'])
    current=lam.get_function_configuration(FunctionName=cfg['FunctionName'])
    require(current['CodeSha256']==support.zip_sha(raw) and support.config_fingerprint(current)==plan['dev']['workerConfiguration'],
            'DEV repository worker code/configuration verification failed')
    print('DEV repository collector code verified; promoting the DEV image task.',flush=True)
    service=dev['service']['serviceArn']
    ecs.update_service(cluster=dev['cluster'],service=service,taskDefinition=candidate)
    wait_service(ecs,dev['cluster'],service,candidate)
    tasks=ecs.list_tasks(cluster=dev['cluster'],serviceName=dev['service']['serviceName'],desiredStatus='RUNNING')['taskArns']
    require(bool(tasks),'No running DEV collector task')
    described=ecs.describe_tasks(cluster=dev['cluster'],tasks=tasks)
    require(not described.get('failures') and bool(described.get('tasks')),'Running tasks cannot be verified')
    for task in described['tasks']:
        require(task['taskDefinitionArn']==candidate,'Unexpected running collector task revision')
        images=[c for c in task['containers'] if c['name']=='collector']
        require(len(images)==1 and images[0].get('imageDigest')==target.rsplit('@',1)[1],'Running image digest mismatch')
    print('DEV repository and image collector artifacts match PROD. DEV settings/roles/schedule retained.')
    print('No PROD changes or database commands performed. Real collection/export workflow checks remain required.')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--profile',default='navigan')
    mode=parser.add_mutually_exclusive_group();mode.add_argument('--prepare',action='store_true');mode.add_argument('--apply',action='store_true');mode.add_argument('--execute',type=Path,metavar='PLAN')
    args=parser.parse_args()
    require(subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()==support.BRANCH,'Use the existing migration branch')
    import boto3
    session=boto3.Session(profile_name=args.profile,region_name=REGION)
    require(session.client('sts').get_caller_identity()['Account']==ACCOUNT,'Unexpected AWS account')
    if args.execute:execute(session,args.execute);return
    dev,prod=snapshot(session,'dev'),snapshot(session,'prod')
    directory=Path(tempfile.mkdtemp(prefix='navigan-dev-collector-parity-'));directory.chmod(0o700)
    (directory/'dev-repository-original.zip').write_bytes(support.download(dev['worker']))
    (directory/'prod-repository.zip').write_bytes(support.download(prod['worker']))
    (directory/'dev-task-original.json').write_text(json.dumps(dev['task'],indent=2,default=str))
    plan={'format':FORMAT,'account':ACCOUNT,'region':REGION,'dev':signature(dev),'prod':signature(prod)}
    path=directory/'release-plan.json';path.write_text(json.dumps(plan,indent=2))
    print('DEV collector parity plan prepared; no AWS resources changed. Release plan: '+str(path),flush=True)
    if args.apply:execute(session,path)


if __name__=='__main__':main()
