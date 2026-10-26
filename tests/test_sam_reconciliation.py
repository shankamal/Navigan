import ast
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tomllib

import pytest

ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
capture=load('sam_reconcile_test','scripts/reconcile-sam.py')
generator=load('sam_contract_test','scripts/generate-sam-contract.py')


def test_successful_resource_import_is_a_stable_stack_state():
    assert 'IMPORT_COMPLETE' in capture.STABLE


def test_contract_exactly_matches_source_and_hashes():
    assert capture.contract()==generator.build()


def test_parent_forwards_every_new_migration_binding():
    root=generator.load_template(ROOT/'infrastructure/template.yaml')
    forwarded=root['Resources']['MigrationManagement']['Properties']['Parameters']
    assert forwarded['WorkspaceBucketName']=={'Ref':'MigrationWorkspaceBucketName'}
    assert forwarded['WorkspaceKmsKeyArn']=={'Ref':'MigrationWorkspaceKmsKeyArn'}
    assert forwarded['WorkspaceBucketOwner']=={'Ref':'MigrationWorkspaceBucketOwner'}
    assert forwarded['MigrationSourceFirstEnabled']=={'Ref':'MigrationSourceFirstEnabled'}
    assert forwarded['GitHubAppPrivateKeySecretArn']=={'Ref':'GitHubAppPrivateKeySecretArn'}
    assert forwarded['GitHubAppPrivateKeyKmsKeyArn']=={'Ref':'GitHubAppPrivateKeyKmsKeyArn'}
    assert forwarded['SourceRegistryAllowedRoleArns']=={'Fn::Join':[',',{'Ref':'SourceRegistryAllowedRoleArns'}]}
    assert 'EnableWorkspaceCollector' not in forwarded
    assert 'MigrationWorkspaceRequired' in root['Rules']


def test_child_flag_registry_json_and_least_privilege_policies():
    child=generator.load_template(ROOT/'infrastructure/modules/migration-management/template.yaml')
    env=child['Resources']['MigrationFunction']['Properties']['Environment']['Variables']
    assert env['MIGRATION_SOURCE_FIRST_ENABLED']=={'Ref':'MigrationSourceFirstEnabled'}
    assert env['SOURCE_REGISTRY_ALLOWED_ROLE_ARNS']['Fn::If'][2]=='[]'
    read=child['Resources']['MigrationGithubReadPolicy']
    statement=read['Properties']['PolicyDocument']['Statement'][0]
    assert statement['Action']=='secretsmanager:GetSecretValue'
    assert statement['Resource']=={'Ref':'GitHubAppPrivateKeySecretArn'}
    registry=child['Resources']['MigrationRegistryRolesPolicy']
    assert registry['Condition']=='AdditionalRegistryRolesConfigured'
    assert registry['Properties']['PolicyDocument']['Statement'][0]['Resource']=={'Ref':'SourceRegistryAllowedRoleArns'}
    assert child['Parameters']['SourceConnectorDeliveryRoleArn']['Default']==''
    assert child['Parameters']['EnableWorkspaceCollector']['Default']=='false'


def test_frontend_requires_api_origin_and_persists_migration_flag():
    frontend=generator.load_template(ROOT/'infrastructure/frontend/service.yaml')
    assert 'Default' not in frontend['Parameters']['ApiOrigin']
    env=frontend['Resources']['TaskDefinition']['Properties']['ContainerDefinitions'][0]['Environment']
    flag=next(e for e in env if e['Name']=='MIGRATION_SOURCE_FIRST_ENABLED')
    assert flag['Value']=={'Ref':'MigrationSourceFirstEnabled'}
    script=(ROOT/'scripts/frontend/deploy.sh').read_text()
    assert '"MigrationSourceFirstEnabled=$MIGRATION_SOURCE_FIRST_ENABLED"' in script
    assert 'ApiOrigin=$NAVIGAN_API_ORIGIN' in script


@pytest.mark.parametrize('env',['default','dev','prod'])
def test_all_sam_profiles_stage_without_embedded_live_targets(env):
    config=tomllib.loads((ROOT/'samconfig.toml').read_text())
    deploy=config[env]['deploy']['parameters']
    assert deploy['no_execute_changeset'] is True
    assert deploy['confirm_changeset'] is True
    assert 'stack_name' not in deploy
    if env == 'default':
        assert 'parameter_overrides' not in deploy
    else:
        assert deploy['parameter_overrides'] == 'DeploymentEnvironment=' + env


def test_environment_specific_route_ownership_is_maintained_in_source():
    root=generator.load_template(ROOT/'infrastructure/template.yaml')
    assert 'Default' not in root['Parameters']['DeploymentEnvironment']
    for module in ('CustomerManagement','EnvironmentManagement','ClusterManagement','MigrationManagement'):
        assert root['Resources'][module]['Properties']['Parameters']['DeploymentEnvironment']=={'Ref':'DeploymentEnvironment'}
    for folder,resource,generic in [('customer-management','customers','CustomerSummaryRoute'),
                                    ('environment-management','environments','EnvironmentSummaryRoute'),
                                    ('cluster-management','clusters','ClusterSummaryRoute')]:
        template=generator.load_template(ROOT/'infrastructure/modules'/folder/'template.yaml')
        for environment,prefix in [('dev','NaviganDev'),('prod','NaviganProduction')]:
            route=template['Resources'][prefix+'SummaryRoute']
            permission=template['Resources'][prefix+'SummaryInvoke']
            assert route['Condition']=='Is'+environment.title()
            assert route['Properties']['RouteKey']==f'GET /api/v1/{resource}/summary'
            assert permission['Condition']=='Is'+environment.title()
        assert generic not in template['Resources']


def test_prod_artifact_routes_and_dev_companion_match_established_owners():
    migration=generator.load_template(ROOT/'infrastructure/modules/migration-management/template.yaml')
    expected=[
        'GET /api/v1/source-clusters/{sourceClusterId}/deployment-sources',
        'PUT /api/v1/source-clusters/{sourceClusterId}/deployment-sources',
        'GET /api/v1/migrations/{migrationId}/deployment-evidence',
        'POST /api/v1/migrations/{migrationId}/deployment-evidence',
        'GET /api/v1/migrations/{migrationId}/artifact-workspaces',
        'POST /api/v1/migrations/{migrationId}/artifact-workspaces',
        'GET /api/v1/migrations/{migrationId}/artifact-workspaces/{workspaceId}',
        'POST /api/v1/migrations/{migrationId}/artifact-workspaces/{workspaceId}/collection-jobs',
        'POST /api/v1/migrations/{migrationId}/artifact-workspaces/{workspaceId}/exports',
    ]
    assert [migration['Resources'][f'NaviganProdArtifactRoute{i}']['Properties']['RouteKey']
            for i in range(9)]==expected
    assert all(migration['Resources'][f'NaviganProdArtifactRoute{i}']['Condition']=='IsProd' for i in range(9))
    for logical in ('InstallSourceClusterConnectorRoute','GetMigrationSourceInventoryRoute','AssessMigrationRoute'):
        assert migration['Resources'][logical]['Condition']=='IsProd'
    cluster=generator.load_template(ROOT/'infrastructure/modules/cluster-management/template.yaml')
    assert 'UpgradeConnectorRoute' not in cluster['Resources']
    companion=generator.load_template(ROOT/'infrastructure/companion/dev-route-ownership.yaml')
    assert len(companion['Resources'])==13
    assert all(r['Type']=='AWS::ApiGatewayV2::Route' and r['DeletionPolicy']=='Retain'
               and r['UpdateReplacePolicy']=='Retain' for r in companion['Resources'].values())
    dev_routes={r['routeKey']:r for r in generator.build()['routes']['dev']}
    assert dev_routes[expected[0]]['owner']=={'captureStack':'companion--sam-route-ownership',
        'logicalId':'MigrationManagementGetSourceDeploymentSourcesRoute'}
    assert len(dev_routes)==len(generator.build()['routes']['dev'])


def bindings():
    return {'DB_NAME':'example_dev','MIGRATION_SOURCE_FIRST_ENABLED':'true',
        'MIGRATION_WORKSPACE_BUCKET':'example-bucket','MIGRATION_WORKSPACE_KMS_KEY':'example-key',
        'MIGRATION_WORKSPACE_BUCKET_OWNER':'000000000001'}


def test_live_values_override_stale_parameters_and_empty_roles_are_empty():
    result=capture.parameters({'MigrationWorkspaceBucketName':'stale'},bindings())
    assert result['MigrationWorkspaceBucketName']=='example-bucket'
    assert result['SourceRegistryAllowedRoleArns']==''
    assert result['SourceConnectorDeliveryRoleArn']==''


def test_exact_registry_roles_are_canonicalized_without_widening():
    env=bindings();env['SOURCE_REGISTRY_ALLOWED_ROLE_ARNS']=json.dumps([
        'arn:aws:iam::000000000001:role/example-b','arn:aws:iam::000000000001:role/example-a'])
    result=capture.parameters({},env)
    assert result['SourceRegistryAllowedRoleArns'].endswith(':role/example-a,arn:aws:iam::000000000001:role/example-b')


@pytest.mark.parametrize('values',[
    {'MIGRATION_SOURCE_FIRST_ENABLED':'unexpected'},
    {'MIGRATION_WORKSPACE_BUCKET':''},
    {'SOURCE_CONNECTOR_DELIVERY_ROLE_ARN':'arn:aws:iam::000000000000:role/placeholder'},
    {'SOURCE_REGISTRY_ALLOWED_ROLE_ARNS':'["*"]'},
    {'SOURCE_REGISTRY_ALLOWED_ROLE_ARNS':'{}'},
])
def test_invalid_runtime_bindings_stop_capture(values):
    env=bindings();env.update(values)
    with pytest.raises(RuntimeError):capture.parameters({},env)


def authored():return [{'module':'MigrationManagement','sourceLogicalId':'ExpectedRoute','routeKey':'GET /example',
    'owner':{'captureStack':'root--MigrationManagement','logicalId':'ExpectedRoute'}}]


def test_route_ownership_differences_are_not_silently_adopted():
    expected={'captureStack':'root--MigrationManagement','logicalId':'ExpectedRoute'}
    assert capture.route_gaps(authored(),{'GET /example':[expected]},{'GET /example':{}})==[]
    assert capture.route_gaps(authored(),{'GET /example':[{'captureStack':'root--MigrationManagement','logicalId':'LegacyRoute'}]},
                              {'GET /example':{}})[0]['reason']=='ROUTE_OWNER_RECONCILIATION_REQUIRED'
    assert capture.route_gaps(authored(),{}, {'GET /example':{}})[0]['reason']=='LIVE_ROUTE_NOT_OWNED_BY_CLOUDFORMATION'
    assert capture.route_gaps(authored(),{}, {})[0]['reason']=='NOT_LIVE_REQUIRES_REVIEW'


def test_capture_entrypoints_cannot_deploy_or_read_secret_values():
    tree=ast.parse((ROOT/'scripts/reconcile-sam.py').read_text())
    methods={n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
    assert not methods & {'create_change_set','execute_change_set','update_stack','deploy','update_function_code',
                          'put_role_policy','get_secret_value','execute_statement','send_command','put_object'}
    wrapper=(ROOT/'scripts/deploy-platform-safe.sh').read_text()
    assert 'sam deploy' not in wrapper and 'reconcile-sam.py' in wrapper
    assert '--capture' in wrapper


def test_capture_collects_ownership_and_filters_runtime_secret_values(tmp_path,monkeypatch):
    account='000000000001';region='us-east-1';role=f'arn:aws:iam::{account}:role/example'
    env={**bindings(),'PRIVATE_TOKEN':'do-not-report-this-value'}
    lambda_cfg={'FunctionName':'example-function','FunctionArn':f'arn:aws:lambda:{region}:{account}:function:example',
        'State':'Active','LastUpdateStatus':'Successful','Role':role,'Handler':'navigan.modules.migration_management.handler.lambda_handler',
        'CodeSha256':'checksum','RevisionId':'revision','Environment':{'Variables':env}}
    root_resources=[{'LogicalResourceId':n,'ResourceType':'AWS::CloudFormation::Stack','PhysicalResourceId':'example-'+n}
                    for n in ('MigrationManagement','SharedPlatform')]
    by_stack={'example':root_resources,'example-MigrationManagement':[
        {'LogicalResourceId':'MigrationFunction','ResourceType':'AWS::Lambda::Function','PhysicalResourceId':'example-function'},
        {'LogicalResourceId':'LegacyRoute','ResourceType':'AWS::ApiGatewayV2::Route','PhysicalResourceId':'route-id'}],
        'example-SharedPlatform':[{'LogicalResourceId':'Api','ResourceType':'AWS::ApiGatewayV2::Api','PhysicalResourceId':'api-id'}]}
    class Missing(Exception):
        response={'Error':{'Code':'ValidationError','Message':'Stack does not exist'}}
    class CFN:
        def describe_stacks(self,StackName):
            if StackName.endswith(('-source-recovery','-sam-route-ownership')):raise Missing()
            outputs=[{'OutputKey':k,'OutputValue':v} for k,v in {
                'WorkspaceBucketName':'example-bucket','WorkspaceKmsKeyArn':'example-key','WorkspaceBucketOwner':account}.items()]
            return {'Stacks':[{'StackId':f'arn:aws:cloudformation:{region}:{account}:stack/{StackName}/id',
                'StackStatus':'UPDATE_COMPLETE','Parameters':[{'ParameterKey':'DatabaseName','ParameterValue':'example_dev'}],
                'Outputs':outputs}]}
        def get_template(self,**kwargs):return {'TemplateBody':{'Resources':{}}}
        def get_paginator(self,operation):
            return SimpleNamespace(paginate=lambda **kw:[{'StackResourceSummaries':by_stack.get(kw['StackName'],[])}])
    class API:
        def get_paginator(self,operation):
            return SimpleNamespace(paginate=lambda **kw:[{'Items':[{'RouteId':'route-id','RouteKey':'GET /example'}] if operation=='get_routes' else []}])
    class IAM:
        def get_role(self,**kwargs):return {'Role':{'Arn':role}}
        def get_paginator(self,operation):
            return SimpleNamespace(paginate=lambda **kw:[{'PolicyNames':[],'AttachedPolicies':[]}])
    clients={'sts':SimpleNamespace(get_caller_identity=lambda:{'Account':account}),'cloudformation':CFN(),
             'lambda':SimpleNamespace(get_function_configuration=lambda **kw:lambda_cfg,
                 get_policy=lambda **kw:{'Policy':json.dumps({'Statement':[]})}),'apigatewayv2':API(),'iam':IAM()}
    session=SimpleNamespace(region_name=region,client=lambda name:clients[name])
    contract={'requiredParameters':['DatabaseName','DeploymentEnvironment'],'parameters':['DatabaseName','DeploymentEnvironment',
        'MigrationSourceFirstEnabled','MigrationWorkspaceBucketName','MigrationWorkspaceKmsKeyArn','MigrationWorkspaceBucketOwner'],
        'routes':{'dev':authored(),'prod':authored()}}
    monkeypatch.setattr(capture,'contract',lambda:contract)
    summary=capture.capture(session,'dev','example',tmp_path)
    assert summary['errors']==[] and summary['deploymentReady'] is False
    assert summary['workspaceBindingsMatchCompanion'] is True
    assert summary['routeOwnershipGaps'][0]['reason']=='ROUTE_OWNER_RECONCILIATION_REQUIRED'
    assert 'do-not-report-this-value' not in json.dumps(summary)
    metadata=json.loads(next((tmp_path/'dev/functions').glob('*.json')).read_text())
    assert 'PRIVATE_TOKEN' not in metadata['Environment']['Variables']
    assert 'do-not-report-this-value' not in json.dumps(metadata)
