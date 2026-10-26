#!/usr/bin/env python3
"""Read-only SAM reconciliation capture. Share only reconciliation-summary.json.

Live templates/parameters and optional deployed ZIPs are private local evidence.
This command never builds, deploys, imports, creates a change set or executes SQL.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import tempfile
import urllib.request
import zipfile
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[1]
STABLE={'CREATE_COMPLETE','UPDATE_COMPLETE','UPDATE_ROLLBACK_COMPLETE'}
MODULES={'CustomerManagement':'customer-management','EnvironmentManagement':'environment-management',
 'ClusterManagement':'cluster-management','MigrationManagement':'migration-management','AccessManagement':'access-management'}
COMPANIONS=('artifact-workspace','workspace-repositories','workspace-image-runtime','workspace-images')
ENV_KEYS={'DB_NAME','DB_PROXY_HOST','DB_SECRET_ARN','MIGRATION_SOURCE_FIRST_ENABLED','MIGRATION_WORKSPACE_BUCKET',
 'MIGRATION_WORKSPACE_KMS_KEY','MIGRATION_WORKSPACE_BUCKET_OWNER','SOURCE_CONNECTOR_DELIVERY_ROLE_ARN',
 'SOURCE_REGISTRY_ALLOWED_ROLE_ARNS','SOURCE_REGISTRY_PRINCIPAL_ARN','GITHUB_APP_ID','GITHUB_APP_PRIVATE_KEY_SECRET_ARN',
 'MIGRATION_CONNECTOR_IMAGE_REPOSITORY','MIGRATION_CONNECTOR_IMAGE_DIGEST'}

def require(value,message):
    if not value:raise RuntimeError(message)

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2,default=str))

def error_code(error):return getattr(error,'response',{}).get('Error',{}).get('Code',type(error).__name__)

def error_record(scope,error):
    value={'scope':scope,'code':error_code(error)}
    if isinstance(error,RuntimeError):value['detail']=str(error)
    elif getattr(error,'operation_name',None):value['operation']=error.operation_name
    return value

def contract():
    value=json.loads((ROOT/'infrastructure/sam-reconciliation-contract.json').read_text())
    require(value.get('version')==1,'Unknown source contract version')
    paths={'infrastructure/template.yaml',*('infrastructure/modules/'+v+'/template.yaml' for v in MODULES.values())}
    require(set(value['sources'])==paths,'Source contract has unexpected template coverage')
    for path,expected in value['sources'].items():
        require(hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==expected,
                'Source contract is stale; regenerate and review it before capture')
    return value

def items(client,operation,key,**kwargs):
    return [item for page in client.get_paginator(operation).paginate(**kwargs) for item in page.get(key,[])]

def parameters(current,env,github_kms=''):
    result=dict(current);flag=env.get('MIGRATION_SOURCE_FIRST_ENABLED','false')
    require(flag in ('true','false'),'Invalid source-first flag')
    result.update(MigrationSourceFirstEnabled=flag,
      MigrationWorkspaceBucketName=env.get('MIGRATION_WORKSPACE_BUCKET',''),
      MigrationWorkspaceKmsKeyArn=env.get('MIGRATION_WORKSPACE_KMS_KEY',''),
      MigrationWorkspaceBucketOwner=env.get('MIGRATION_WORKSPACE_BUCKET_OWNER',''))
    if flag=='true':require(all(result[k] for k in ('MigrationWorkspaceBucketName','MigrationWorkspaceKmsKeyArn','MigrationWorkspaceBucketOwner')),'Enabled workspace has incomplete live bindings')
    role=env.get('SOURCE_CONNECTOR_DELIVERY_ROLE_ARN',result.get('SourceConnectorDeliveryRoleArn',''))
    require(not role or re.fullmatch(r'arn:[a-z-]+:iam::(?!000000000000)[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]+',role),'Placeholder or malformed delivery role')
    result['SourceConnectorDeliveryRoleArn']=role
    roles=json.loads(env.get('SOURCE_REGISTRY_ALLOWED_ROLE_ARNS','[]'))
    require(isinstance(roles,list) and all(isinstance(r,str) and re.fullmatch(r'arn:[a-z-]+:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]+',r) for r in roles),'Registry roles must be exact ARNs')
    result['SourceRegistryAllowedRoleArns']=','.join(sorted(set(roles)))
    for target,source in (('GitHubAppId','GITHUB_APP_ID'),('GitHubAppPrivateKeySecretArn','GITHUB_APP_PRIVATE_KEY_SECRET_ARN')):
        if env.get(source):result[target]=env[source]
    result['GitHubAppPrivateKeyKmsKeyArn']=github_kms
    require(not any(v=='****' for v in result.values()),'Redacted parameters require private operator input')
    return result

def route_gaps(authored,owned,live):
    result=[]
    for logical,r in authored.get('Resources',{}).items():
        if r.get('Type')!='AWS::ApiGatewayV2::Route':continue
        route=r.get('Properties',{}).get('RouteKey')
        if not isinstance(route,str):reason='DYNAMIC_ROUTE_REQUIRES_REVIEW'
        elif route not in live:reason='NOT_LIVE_REQUIRES_REVIEW'
        elif not owned.get(route):reason='LIVE_ROUTE_NOT_OWNED_BY_THIS_STACK'
        elif owned[route]!=[logical]:reason='LOGICAL_ID_RECONCILIATION_REQUIRED'
        else:continue
        result.append({'route':route if isinstance(route,str) else None,'sourceLogicalId':logical,
                       'deployedLogicalIds':owned.get(route,[]) if isinstance(route,str) else [],'reason':reason})
    return result

def capture(session,label,parent,directory,artifacts=False,frontend=None):
    cfn=session.client('cloudformation');account=session.client('sts').get_caller_identity()['Account'];region=session.region_name
    summary={'errors':[],'stacks':0,'functions':0,'routes':0,'routeOwnershipGaps':[],
             'branchSourceDifferences':{},'companionStacks':{},'frontend':'not-requested','deploymentReady':False}
    stacks={};functions={};apis={};roles=set();seen=set();archives={};private=directory/label
    def visit(name,logical):
        require(name not in seen,'Repeated stack reference');seen.add(name)
        desc=cfn.describe_stacks(StackName=name)['Stacks'][0]
        require(desc['StackId'].startswith(f'arn:aws:cloudformation:{region}:{account}:stack/'),'Stack account/region mismatch')
        require(desc['StackStatus'] in STABLE,'Stack not stable')
        resources=[r for r in items(cfn,'list_stack_resources','StackResourceSummaries',StackName=name)
                   if r.get('PhysicalResourceId') and r.get('ResourceStatus')!='DELETE_COMPLETE']
        record={'description':desc,'resources':resources,'templates':{stage:cfn.get_template(StackName=name,TemplateStage=stage)['TemplateBody'] for stage in ('Original','Processed')}}
        stacks[logical]=record;summary['stacks']+=1;write(private/'stacks'/(logical.replace('/','--')+'.json'),record)
        for r in resources:
            kind=r['ResourceType'];physical=r['PhysicalResourceId'];path=logical+'/'+r['LogicalResourceId'];file=path.replace('/','--')+'.json'
            if kind=='AWS::CloudFormation::Stack':visit(physical,path)
            elif kind=='AWS::Lambda::Function':
                lam=session.client('lambda');cfg=lam.get_function_configuration(FunctionName=physical)
                require(cfg['FunctionArn'].startswith(f'arn:aws:lambda:{region}:{account}:function:'),'Lambda account/region mismatch')
                require(cfg.get('State')=='Active' and cfg.get('LastUpdateStatus')=='Successful','Lambda not stable')
                env=cfg.get('Environment',{}).get('Variables',{})
                meta={k:v for k,v in cfg.items() if k not in ('Environment','ResponseMetadata')}
                meta['Environment']={'Variables':{k:v for k,v in env.items() if k in ENV_KEYS}};meta['environmentKeys']=sorted(env)
                functions[path]=meta;roles.add(cfg['Role']);summary['functions']+=1;write(private/'functions'/file,meta)
                try:
                    policy=lam.get_policy(FunctionName=physical)
                    write(private/'function-policies'/file,policy)
                except Exception as error:
                    if error_code(error)!='ResourceNotFoundException':summary['errors'].append(error_record('function-policy/'+path,error))
                if artifacts:
                    target=archives.get(cfg['CodeSha256'])
                    if target:raw=target.read_bytes()
                    else:
                        response=lam.get_function(FunctionName=physical)
                        require(response['Configuration']['RevisionId']==cfg['RevisionId'],'Lambda changed during capture')
                        require(response['Code'].get('Location'),'Only ZIP baseline capture is supported')
                        with urllib.request.urlopen(response['Code']['Location'],timeout=60) as stream:raw=stream.read()
                        require(base64.b64encode(hashlib.sha256(raw).digest()).decode()==cfg['CodeSha256'],'ZIP checksum mismatch')
                        target=private/'artifacts'/(hashlib.sha256(raw).hexdigest()+'.zip');target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
                        archives[cfg['CodeSha256']]=target
                    meta['deployedArchive']=str(target.relative_to(private));write(private/'functions'/file,meta)
                    module=cfg.get('Handler','').rsplit('.',2)[0].replace('.','/')+'/'
                    with zipfile.ZipFile(io.BytesIO(raw)) as z:
                        require(len(z.namelist())==len(set(z.namelist())),'Duplicate ZIP members')
                        diff=[n for n in z.namelist() if n.endswith('.py') and n.startswith((module,'navigan/shared/')) and
                              (not (ROOT/'src'/n).is_file() or (ROOT/'src'/n).read_bytes()!=z.read(n))]
                    if diff:summary['branchSourceDifferences'][path]=sorted(diff)
            elif kind=='AWS::ApiGatewayV2::Api':
                api=session.client('apigatewayv2');apis[physical]={key:items(api,op,'Items',ApiId=physical) for key,op in (
                    ('routes','get_routes'),('integrations','get_integrations'),('authorizers','get_authorizers'),('stages','get_stages'))}
                summary['routes']+=len(apis[physical]['routes']);write(private/'apis'/file,apis[physical])
            elif kind=='AWS::ECS::Service':
                parts=physical.split('/');require(len(parts)==3,'Cannot resolve ECS cluster')
                ecs=session.client('ecs');response=ecs.describe_services(cluster=parts[-2],services=[physical])
                require(not response.get('failures') and len(response.get('services',[]))==1,'ECS service missing')
                service=response['services'][0];task=ecs.describe_task_definition(taskDefinition=service['taskDefinition'],include=['TAGS'])
                write(private/'services'/file,{'service':service,'task':task})
                roles.update(task['taskDefinition'][k] for k in ('taskRoleArn','executionRoleArn') if task['taskDefinition'].get(k))
                if logical=='frontend':
                    containers=[c for c in task['taskDefinition']['containerDefinitions'] if c['name']=='frontend']
                    require(len(containers)==1,'Hosted frontend container missing or ambiguous')
                    values={v['name']:v['value'] for v in containers[0].get('environment',[])}
                    flag=values.get('MIGRATION_SOURCE_FIRST_ENABLED','false')
                    require(flag in ('true','false'),'Invalid hosted frontend migration flag')
                    bindings={p['ParameterKey']:p['ParameterValue'] for p in desc.get('Parameters',[])}
                    require(values.get('NAVIGAN_API_ORIGIN') and values.get('NAVIGAN_API_BASE_PATH'),'Hosted frontend API bindings missing')
                    bindings.update(MigrationSourceFirstEnabled=flag,ImageUri=containers[0]['image'],
                        ApiOrigin=values['NAVIGAN_API_ORIGIN'],ApiBasePath=values['NAVIGAN_API_BASE_PATH'])
                    write(private/'frontend-parameters.json',{'Parameters':[{'ParameterKey':k,'ParameterValue':str(v)} for k,v in sorted(bindings.items())]})
                    summary['frontendParametersResolved']=True
                elif logical=='companion/workspace-images':
                    containers=[c for c in task['taskDefinition']['containerDefinitions'] if c['name']=='collector']
                    require(len(containers)==1,'Image collector container missing or ambiguous')
                    values={v['name']:v['value'] for v in containers[0].get('environment',[])}
                    bindings={p['ParameterKey']:p['ParameterValue'] for p in desc.get('Parameters',[])}
                    bindings.update(WorkerImage=containers[0]['image'],DesiredCount=str(service['desiredCount']))
                    for parameter,variable in (('DatabaseProxyHost','DB_PROXY_HOST'),('DatabaseName','DB_NAME'),
                        ('DatabaseSecretArn','DB_SECRET_ARN'),('WorkspaceBucketName','MIGRATION_WORKSPACE_BUCKET'),
                        ('WorkspaceKmsKeyArn','MIGRATION_WORKSPACE_KMS_KEY'),('WorkspaceBucketOwner','MIGRATION_WORKSPACE_BUCKET_OWNER'),
                        ('AllowedRegistryRoleArns','IMAGE_COLLECTION_ROLE_ARNS')):
                        if variable in values:bindings[parameter]=values[variable]
                    write(private/'collector-image-parameters.json',{'Parameters':[{'ParameterKey':k,'ParameterValue':str(v)} for k,v in sorted(bindings.items())]})
                    summary['collectorImageParametersResolved']=True
        return record
    root=visit(parent,'root');current={p['ParameterKey']:p['ParameterValue'] for p in root['description'].get('Parameters',[])}
    require(current.get('DatabaseName'),'Parent database identity missing')
    migration=functions.get('root/MigrationManagement/MigrationFunction');require(migration,'Migration API not captured')
    env=migration['Environment']['Variables'];require(env.get('DB_NAME')==current['DatabaseName'],'API/parent databases differ')
    github_kms=''
    if env.get('GITHUB_APP_PRIVATE_KEY_SECRET_ARN'):
        key=session.client('secretsmanager').describe_secret(SecretId=env['GITHUB_APP_PRIVATE_KEY_SECRET_ARN']).get('KmsKeyId')
        if key:
            meta=session.client('kms').describe_key(KeyId=key)['KeyMetadata']
            if meta.get('KeyManager')=='CUSTOMER':github_kms=meta['Arn']
    definitions=contract();resolved=parameters(current,env,github_kms)
    require(not [k for k in definitions['requiredParameters'] if not resolved.get(k)],'Required source parameters missing from live state')
    write(private/'sam-parameters.json',{'StackName':parent,'Parameters':[{'ParameterKey':k,'ParameterValue':str(v)} for k,v in sorted(resolved.items()) if k in definitions['parameters']]})
    summary['migrationSettingsResolved']=True;summary['sourceFirstEnabled']=resolved['MigrationSourceFirstEnabled']=='true'
    if resolved.get('SourceConnectorDeliveryRoleArn'):roles.add(resolved['SourceConnectorDeliveryRoleArn'])
    roles.update(json.loads(env.get('SOURCE_REGISTRY_ALLOWED_ROLE_ARNS','[]')))
    for suffix in (*COMPANIONS,'source-recovery'):
        try:visit(parent+'-'+suffix,'companion/'+suffix);summary['companionStacks'][suffix]='captured'
        except Exception as error:
            detail=getattr(error,'response',{}).get('Error',{})
            if suffix=='source-recovery' and detail.get('Code')=='ValidationError' and 'does not exist' in detail.get('Message',''):
                summary['companionStacks'][suffix]='absent'
            else:summary['errors'].append(error_record('companion/'+suffix,error))
    workspace=stacks.get('companion/artifact-workspace')
    if workspace:
        outputs={o['OutputKey']:o['OutputValue'] for o in workspace['description'].get('Outputs',[])}
        matches=all(env.get(k)==outputs.get(v) and env.get(k) for k,v in (
            ('MIGRATION_WORKSPACE_BUCKET','WorkspaceBucketName'),('MIGRATION_WORKSPACE_KMS_KEY','WorkspaceKmsKeyArn'),
            ('MIGRATION_WORKSPACE_BUCKET_OWNER','WorkspaceBucketOwner')))
        summary['workspaceBindingsMatchCompanion']=bool(matches)
        if not matches:summary['errors'].append({'scope':'workspace-bindings','code':'LIVE_BINDINGS_DIFFER'})
    if frontend:
        try:visit(frontend,'frontend');summary['frontend']='captured'
        except Exception as error:summary['errors'].append(error_record('frontend',error))
    routes=[r for a in apis.values() for r in a['routes']];live={r['RouteKey']:r for r in routes}
    for module,folder in MODULES.items():
        owned={}
        for r in stacks.get('root/'+module,{}).get('resources',[]):
            if r['ResourceType']=='AWS::ApiGatewayV2::Route':
                matches=[v for v in routes if v['RouteId']==r['PhysicalResourceId'].rsplit('|',1)[-1]]
                require(len(matches)==1,'Managed route mapping is ambiguous')
                owned.setdefault(matches[0]['RouteKey'],[]).append(r['LogicalResourceId'])
        gaps=route_gaps(definitions['routes'][module],owned,live)
        summary['routeOwnershipGaps'].extend({'module':module,**g} for g in gaps)
    iam=session.client('iam')
    for index,arn in enumerate(sorted(roles)):
        try:
            if arn.split(':')[4]!=account:
                summary['externalRoleTrustNotCaptured']=summary.get('externalRoleTrustNotCaptured',0)+1
                write(private/'iam'/f'external-role-{index}.json',{'reference':arn,'scope':'external-account-reference-only'})
                continue
            name=arn.rsplit('/',1)[-1];policy={'role':iam.get_role(RoleName=name)['Role'],'inline':[]}
            require(policy['role']['Arn']==arn,'IAM role identity mismatch')
            for policy_name in items(iam,'list_role_policies','PolicyNames',RoleName=name):policy['inline'].append(iam.get_role_policy(RoleName=name,PolicyName=policy_name))
            policy['attached']=items(iam,'list_attached_role_policies','AttachedPolicies',RoleName=name)
            write(private/'iam'/f'role-{index}.json',policy)
        except Exception as error:summary['errors'].append(error_record('iam',error))
    summary['deployedZipBaselineCaptured']=artifacts
    summary['remainingWork']=['Reconcile live route/IAM ownership before a change set',
      'Preserve or explicitly approve the code baseline','Coordinate companion stacks and database verification as separate stages']
    return summary

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--environment',choices=['dev','prod','both'],default='both');parser.add_argument('--capture',action='store_true')
    parser.add_argument('--profile');parser.add_argument('--region',required=True);parser.add_argument('--expected-account',required=True)
    parser.add_argument('--dev-stack');parser.add_argument('--prod-stack');parser.add_argument('--dev-frontend-stack');parser.add_argument('--prod-frontend-stack')
    parser.add_argument('--capture-artifacts',action='store_true');args=parser.parse_args()
    contract()  # Check source consistency before making any AWS calls.
    labels=['dev','prod'] if args.environment=='both' else [args.environment]
    for label in labels:require(getattr(args,label+'_stack'),'Provide --'+label+'-stack explicitly')
    require(len({getattr(args,label+'_stack') for label in labels})==len(labels),'DEV and PROD must be different stacks')
    import boto3
    session=boto3.Session(profile_name=args.profile,region_name=args.region)
    require(session.client('sts').get_caller_identity()['Account']==args.expected_account,'Unexpected AWS account')
    directory=Path(tempfile.mkdtemp(prefix='navigan-sam-reconciliation-'));directory.chmod(0o700)
    manifest={'format':1,'observedAt':datetime.now(timezone.utc).isoformat(),'deploymentReady':False,'environments':{}}
    for label in labels:
        try:manifest['environments'][label]=capture(session,label,getattr(args,label+'_stack'),directory,args.capture_artifacts,getattr(args,label+'_frontend_stack'))
        except Exception as error:manifest['environments'][label]={'deploymentReady':False,'errors':[error_record('environment',error)]}
    if labels==['dev','prod'] and all((directory/label/'sam-parameters.json').is_file() for label in labels):
        databases=[next(p['ParameterValue'] for p in json.loads((directory/label/'sam-parameters.json').read_text())['Parameters']
                        if p['ParameterKey']=='DatabaseName') for label in labels]
        if databases[0]==databases[1]:
            for label in labels:manifest['environments'][label]['errors'].append({'scope':'environment-isolation','code':'DATABASE_IDENTITIES_NOT_DISTINCT'})
    summary=directory/'reconciliation-summary.json';write(summary,manifest)
    print('Read-only SAM capture finished. No AWS resources changed.')
    print('Private capture directory: '+str(directory));print('Share this compact summary: '+str(summary))
    print('Deployment remains blocked pending ownership and code-baseline reconciliation.')
    return 2 if any(e.get('errors') for e in manifest['environments'].values()) else 0

if __name__=='__main__':raise SystemExit(main())
