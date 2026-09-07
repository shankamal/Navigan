"""Check API authorization and cross-stack wiring against the public contract."""

import json
from pathlib import Path
import tomllib
import yaml

ROOT = Path(__file__).resolve().parents[1]


def templates():
    return tuple(yaml.safe_load((ROOT / path).read_text()) for path in (
        'infrastructure/template.yaml',
        'infrastructure/shared/template.yaml',
        'infrastructure/modules/customer-management/template.yaml',
    ))


def test_gateway_exposes_every_documented_operation_with_authentication():
    _, shared, module = templates()
    contract = json.loads((ROOT / 'docs/openapi.json').read_text())
    expected = {f'{method.upper()} {path}' for path, methods in contract['paths'].items() for method in methods}
    routes = [r['Properties'] for r in module['Resources'].values() if r['Type'] == 'AWS::ApiGatewayV2::Route']
    assert {p['RouteKey'] for p in routes} == expected
    assert len(routes) == len(expected) == 18
    for props in routes:
        assert props['ApiId'] == {'Ref': 'ApiId'}
        assert props['AuthorizationType'] == 'JWT'
        assert props['AuthorizerId'] == {'Ref': 'AuthorizerId'}
        assert props['AuthorizationScopes'] == [{'Ref': 'JwtScope'}]
        assert props['Target'] == {'Fn::Join': ['/', ['integrations', {'Ref': 'CustomerIntegration'}]]}
    integration = module['Resources']['CustomerIntegration']['Properties']
    assert integration['IntegrationUri'] == {'Fn::GetAtt': ['CustomerFunction', 'Arn']}
    assert integration['PayloadFormatVersion'] == '2.0'
    assert integration['TimeoutInMillis'] == 29000
    assert integration['IntegrationType'] == 'AWS_PROXY'
    authorizer = shared['Resources']['EnterpriseJwt']['Properties']
    assert authorizer['AuthorizerType'] == 'JWT'
    assert authorizer['JwtConfiguration'] == {'Issuer': {'Ref': 'JwtIssuer'}, 'Audience': [{'Ref': 'JwtAudience'}]}
    assert shared['Resources']['ApiStage']['Properties']['AutoDeploy'] is True
    permission = module['Resources']['CustomerInvokePermission']['Properties']
    assert permission['Principal'] == 'apigateway.amazonaws.com'
    assert permission['SourceAccount'] == {'Ref': 'AWS::AccountId'}
    assert permission['SourceArn']['Fn::Sub'].endswith('${ApiId}/v1/*/api/v1/customers*')


def test_parent_passes_all_required_child_parameters_and_outputs():
    parent, shared, module = templates()
    assert set(parent['Resources']) == {'SharedPlatform', 'CustomerManagement', 'EnvironmentManagement'}
    for name, child in [('SharedPlatform', shared), ('CustomerManagement', module)]:
        app = parent['Resources'][name]
        assert app['Type'] == 'AWS::Serverless::Application'
        assert (ROOT / 'infrastructure' / app['Properties']['Location']).is_file()
        supplied = app['Properties']['Parameters']
        assert set(supplied) == set(child['Parameters'])
        for value in supplied.values():
            if 'Ref' in value:
                assert value['Ref'] in parent['Parameters']
            elif 'Fn::GetAtt' in value:
                stack, output = value['Fn::GetAtt']
                assert stack == 'SharedPlatform'
                assert output.removeprefix('Outputs.') in shared['Outputs']
    supplied = parent['Resources']['CustomerManagement']['Properties']['Parameters']
    for name in ['PrivateSubnetIds', 'LambdaSecurityGroupIds']:
        assert supplied[name] == {'Fn::Join': [',', {'Ref': name}]}
    code = ROOT / 'infrastructure/modules/customer-management' / module['Globals']['Function']['CodeUri']
    assert (code / 'requirements.txt').is_file()
    assert (code / 'navigan/modules/customer_management/handler.py').is_file()
    assert module['Globals']['Function']['Runtime'] == 'python3.12'
    assert module['Globals']['Function']['Architectures'] == ['x86_64']
    assert sum(r['Type'] == 'AWS::ApiGatewayV2::Api' for r in shared['Resources'].values()) == 1
    assert not any(r['Type'] in ['AWS::ApiGatewayV2::Api', 'AWS::Serverless::HttpApi'] for r in module['Resources'].values())
    publisher = module['Resources']['OutboxPublisher']['Properties']
    assert publisher['Environment']['Variables']['EVENT_BUS_NAME'] == {'Ref': 'EventBusName'}
    assert publisher['Events']['Poll']['Properties']['Enabled'] == {'Fn::If': ['PublishOutbox', True, False]}
    assert module['Resources']['NotificationRule']['Properties']['EventBusName'] == {'Ref': 'EventBusName'}


def test_sam_config_builds_parent_and_deploys_built_nested_templates():
    config = tomllib.loads((ROOT / 'samconfig.toml').read_text())
    assert config['version'] == 0.1
    env = config['default']
    assert (ROOT / env['build']['parameters']['template_file']).is_file()
    assert env['build']['parameters']['use_container'] is True
    deploy = env['deploy']['parameters']
    assert deploy['template_file'] == '.aws-sam/build/template.yaml'
    assert {'CAPABILITY_IAM', 'CAPABILITY_AUTO_EXPAND'} <= set(deploy['capabilities'].split())
    assert deploy['confirm_changeset'] is True
