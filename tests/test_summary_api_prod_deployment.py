"""Summary release scope, package preservation and tenant-bound query guards."""
import ast
import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('summary_release', ROOT / 'scripts/deploy-summary-apis-prod.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def source(resource, filename):
    return (ROOT / f'src/navigan/modules/{release.SPECS[resource][3]}/{filename}').read_text()


def without_summary(text, kind):
    tree = ast.parse(text)
    if kind == 'handler':
        execute = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'execute')
        node = next(n for n in execute.body if isinstance(n, ast.If) and any(
            isinstance(x, ast.Constant) and x.value in ('summary', '/summary') for x in ast.walk(n.test)))
    else:
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Repository')
        node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'summary')
    lines = text.splitlines(keepends=True)
    del lines[node.lineno - 1:node.end_lineno]
    return ''.join(lines)


@pytest.mark.parametrize('resource', release.SPECS)
def test_patch_is_additive_idempotent_and_preserves_native_package(tmp_path, resource):
    prefix = f'navigan/modules/{release.SPECS[resource][3]}/'
    handler = without_summary(source(resource, 'handler.py'), 'handler')
    repository = without_summary(source(resource, 'repository.py'), 'repository')
    original, updated = tmp_path / 'old.zip', tmp_path / 'new.zip'
    with zipfile.ZipFile(original, 'w') as z:
        z.writestr(prefix + 'handler.py', handler)
        z.writestr(prefix + 'repository.py', repository)
        z.writestr('psycopg_binary/native.so', b'preserved native dependency')
        z.writestr('navigan/shared/auth.py', b'preserved authentication')
        z.writestr(prefix + '__pycache__/handler.cpython-312.pyc', b'old bytecode')
    release.package(original, updated, resource)
    with zipfile.ZipFile(updated) as z:
        assert z.read('psycopg_binary/native.so') == b'preserved native dependency'
        assert z.read('navigan/shared/auth.py') == b'preserved authentication'
        assert prefix + '__pycache__/handler.cpython-312.pyc' not in z.namelist()
        for filename in ('handler.py', 'repository.py'):
            compile(z.read(prefix + filename), filename, 'exec')
    # An already-current deployed package is preserved exactly at source level.
    assert release.patch_handler(source(resource, 'handler.py'), resource) == source(resource, 'handler.py')
    assert release.patch_repository(source(resource, 'repository.py'), resource) == source(resource, 'repository.py')


@pytest.mark.parametrize('resource', release.SPECS)
def test_added_handler_get_only_read_only_transaction_and_other_routes_unchanged(resource):
    original = without_summary(source(resource, 'handler.py'), 'handler')
    patched = release.patch_handler(original, resource)
    func = next(n for n in ast.parse(patched).body if isinstance(n, ast.FunctionDef) and n.name == 'execute')
    guard = next(n for n in func.body if isinstance(n, ast.If) and 'summary' in ast.unparse(n.test))
    events = []
    class Failure(Exception):
        pass
    class DB:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql): events.append(sql)
    principal = object()
    env = {'BASE': '/api/v1/' + resource, 'ApiError': Failure, 'tx': DB, 'transaction': DB,
           'Repository': lambda db, p: SimpleNamespace(summary=lambda: {'principal': p}),
           'response': lambda status, data, corr: (status, data, corr), 'principal': principal,
           'correlation': 'request', 'method': 'GET', 'path': '/api/v1/' + resource + '/summary'}
    fn = ast.FunctionDef(name='run', args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]), body=[guard], decorator_list=[])
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<guard>', 'exec'), env)
    assert env['run']() == (200, {'principal': principal}, 'request')
    assert events == ['SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY']
    env['method'] = 'POST'
    with pytest.raises(Failure): env['run']()
    assert len(events) == 1
    env['path'] = '/api/v1/' + resource
    assert env['run']() is None


@pytest.mark.parametrize('resource', release.SPECS)
def test_summary_uses_existing_tenant_scope_and_aggregate_sql(resource):
    patched = release.patch_repository(without_summary(source(resource, 'repository.py'), 'repository'), resource)
    cls = next(n for n in ast.parse(patched).body if isinstance(n, ast.ClassDef) and n.name == 'Repository')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'summary')
    seen = []
    class DB:
        def execute(self, sql, params):
            seen.append((sql, params))
            assert "customer_id = %s" in sql
            assert params == ['customer-scope']
            assert 'GROUP BY' in sql and 'count(' in sql
            assert '*' not in sql.replace('count(*)', '')
            return SimpleNamespace(fetchall=lambda: [])
    cls = ast.ClassDef(name='Repository', bases=[], keywords=[], body=[method], decorator_list=[])
    env = {'scope_clause': lambda p: ('c.customer_id = %s', ['customer-scope']),
           'VISIBLE_CLUSTER_CONDITION': "coalesce(k.workflow->>'ownershipStatus','') <> 'ARCHIVED'"}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), '<summary>', 'exec'), env)
    repo = env['Repository']()
    repo.db, repo.principal = DB(), object()
    assert repo.summary() == {'total': 0, 'byStatus': {}, 'byProvider': {}}
    assert len(seen) == (2 if resource == 'customers' else 1)
    if resource == 'clusters': assert 'ARCHIVED' in seen[0][0]


def template():
    return {'Resources': {'Fn': {'Type': 'AWS::Lambda::Function', 'Properties': {
        'Code': {'S3Bucket': 'old'}, 'Environment': {'Variables': {'DB_NAME': 'navigan'}}, 'Role': 'existing'}},
        'Unrelated': {'Type': 'AWS::IAM::Role', 'Properties': {'RoleName': 'unchanged'}}}}


def test_template_only_code_and_exact_protected_route_permission():
    before = template()
    reference = {'AuthorizationType': 'JWT', 'AuthorizerId': 'authorizer', 'AuthorizationScopes': ['navigan/api'], 'Target': 'integrations/existing'}
    after = release.proposed_child(before, 'Fn', 'api123', reference, 'customers', {'S3Bucket': 'new'})
    assert before == template()
    props = after['Resources'][release.ROUTE]['Properties']
    assert all(props[k] == v for k, v in reference.items())
    assert props['RouteKey'] == 'GET /api/v1/customers/summary'
    permission = after['Resources'][release.PERMISSION]['Properties']
    assert permission['SourceAccount'] == release.ACCOUNT
    assert permission['SourceArn'].endswith('/v1/GET/api/v1/customers/summary')
    for change in ('Role', 'Environment'):
        tampered = copy.deepcopy(after)
        tampered['Resources']['Fn']['Properties'][change] = 'changed'
        with pytest.raises(RuntimeError): release.validate_delta(before, tampered, 'Fn')
    tampered = copy.deepcopy(after)
    del tampered['Resources']['Unrelated']
    with pytest.raises(RuntimeError): release.validate_delta(before, tampered, 'Fn')


def test_unknown_existing_summary_code_and_cluster_visibility_fail_closed():
    s = source('customers', 'repository.py').replace('def summary(self):', 'def summary(self):\n        return {}')
    with pytest.raises(RuntimeError): release.patch_repository(s, 'customers')
    s = without_summary(source('clusters', 'repository.py'), 'repository').replace('VISIBLE_CLUSTER_CONDITION', 'OLD_VISIBILITY')
    with pytest.raises(RuntimeError): release.patch_repository(s, 'clusters')


def test_change_set_rejects_unrelated_changes_and_replacement():
    before = template()
    reference = {'AuthorizationType': 'JWT', 'AuthorizerId': 'auth', 'Target': 'integrations/id'}
    after = release.proposed_child(before, 'Fn', 'api', reference, 'customers', {'S3Bucket': 'new'})
    record = {'nestedLogical': 'CustomerManagement', 'functionLogical': 'Fn', 'integrationLogical': 'Integration',
              'resource': 'customers', 'stack': 'child-stack',
              'templateHash': release.digest(__import__('json').dumps(after, sort_keys=True).encode())}
    root_change = {'ResourceChange': {'LogicalResourceId': 'CustomerManagement', 'ResourceType': 'AWS::CloudFormation::Stack',
                                    'Action': 'Modify', 'Replacement': 'False', 'ChangeSetId': 'child-change'}}
    changes = [{'ResourceChange': {'LogicalResourceId': 'Fn', 'ResourceType': 'AWS::Lambda::Function',
                                  'Action': 'Modify', 'Replacement': 'False'}},
               {'ResourceChange': {'LogicalResourceId': release.ROUTE, 'ResourceType': 'AWS::ApiGatewayV2::Route',
                                  'Action': 'Add', 'Replacement': 'False'}}]
    class CFN:
        def describe_change_set(self, ChangeSetName):
            if ChangeSetName == 'root':
                return {'StackName': release.PARENT, 'Status': 'CREATE_COMPLETE', 'ExecutionStatus': 'AVAILABLE', 'Changes': [root_change]}
            return {'StackId': 'child-stack', 'Changes': changes}
        def get_template(self, **kwargs):
            return {'TemplateBody': after if 'ChangeSetName' in kwargs else before}
    release.inspect_plan(CFN(), 'root', [record])
    changes[0]['ResourceChange']['Replacement'] = 'True'
    with pytest.raises(RuntimeError): release.inspect_plan(CFN(), 'root', [record])
    changes[0]['ResourceChange']['Replacement'] = 'False'
    changes.append({'ResourceChange': {'LogicalResourceId': 'Unrelated', 'ResourceType': 'AWS::IAM::Role', 'Action': 'Modify'}})
    with pytest.raises(RuntimeError): release.inspect_plan(CFN(), 'root', [record])
    changes.pop()
    root_change['ResourceChange']['LogicalResourceId'] = 'MigrationManagement'
    with pytest.raises(RuntimeError): release.inspect_plan(CFN(), 'root', [record])
