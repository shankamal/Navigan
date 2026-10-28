import ast
import importlib.util
import io
import json
from pathlib import Path
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('workspace_parity', ROOT / 'scripts/align-dev-workspace-with-prod.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def package(workspace, extra=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as z:
        z.writestr(release.WORKSPACE, workspace)
        z.writestr(release.PREFIX + 'service.py', b'# unchanged service')
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return stream.getvalue()


@pytest.fixture
def source_versions(monkeypatch):
    old, new = b'# production baseline\n', b'# newer development source\n'
    monkeypatch.setattr(release, 'PROD_HASH', release.sha(old))
    monkeypatch.setattr(release, 'DEV_HASH', release.sha(new))
    return old, new


def test_updates_only_workspace_and_removes_its_stale_bytecode(source_versions):
    old, new = source_versions
    extra = {'navigan/shared/access.py': b'preserve access', 'native.so': b'preserve native library',
             release.PREFIX + '__pycache__/artifact_workspace.cpython-312.pyc': b'stale',
             release.PREFIX + '__pycache__/service.cpython-312.pyc': b'preserve'}
    result = release.members(release.build(package(new, extra), package(old)))
    assert result[release.WORKSPACE] == old
    assert release.PREFIX + '__pycache__/artifact_workspace.cpython-312.pyc' not in result
    for name, data in extra.items():
        if 'artifact_workspace' not in name:
            assert result[name] == data


def test_already_matching_is_noop(source_versions):
    old, _ = source_versions
    assert release.build(package(old), package(old)) is None


def test_unreviewed_prod_source_is_rejected(source_versions):
    _, new = source_versions
    with pytest.raises(RuntimeError, match='PROD workspace differs'):
        release.build(package(new), package(b'# unknown production'))


def test_unreviewed_dev_source_is_rejected(source_versions):
    old, _ = source_versions
    with pytest.raises(RuntimeError, match='Unexpected DEV workspace'):
        release.build(package(b'# unknown development'), package(old))


def test_other_module_differences_are_rejected(source_versions):
    old, new = source_versions
    with pytest.raises(RuntimeError, match='outside the reviewed workspace file'):
        release.build(package(new, {release.PREFIX + 'unexpected.py': b'# extra'}), package(old))


def test_duplicate_zip_members_rejected():
    stream = io.BytesIO()
    with pytest.warns(UserWarning):
        with zipfile.ZipFile(stream, 'w') as z:
            z.writestr('same', b'a')
            z.writestr('same', b'b')
    with pytest.raises(RuntimeError, match='Duplicate ZIP'):
        release.members(stream.getvalue())


def test_invalid_plan_rejected_before_aws(tmp_path):
    path = tmp_path / 'plan.json'
    path.write_text(json.dumps({'format': 'prod-plan'}))
    with pytest.raises(RuntimeError, match='Invalid DEV parity'):
        release.execute(object(), path)


def test_environment_changes_detected_without_serializing_values():
    original = {'Environment': {'Variables': {'DB_NAME': 'navigan_dev', 'TOKEN': 'private'}}}
    changed = {'Environment': {'Variables': {'DB_NAME': 'navigan', 'TOKEN': 'private'}}}
    assert release.config_fingerprint(original) != release.config_fingerprint(changed)
    assert 'private' not in release.config_fingerprint(original)


def test_legacy_dev_package_includes_new_workspace_dependency():
    tree = ast.parse((ROOT / 'scripts/deploy-source-connection-screen-dev.py').read_text())
    constants = {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body
                 if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                 and node.targets[0].id in ('FILES', 'ADDITIVE_FILES')}
    assert 'workspace_reuse.py' in constants['FILES']
    assert 'workspace_reuse.py' in constants['ADDITIVE_FILES']


def test_execute_writes_only_dev_code_and_preserves_configuration(source_versions, monkeypatch, tmp_path):
    old, new = source_versions
    original, production = package(new), package(old)
    updated = release.build(original, production)
    dev_config = {'FunctionName': 'navigan-ashok-dev-migration', 'RevisionId': 'dev-revision',
                  'CodeSha256': release.zip_sha(original), 'Environment': {'Variables': {'DB_NAME': 'navigan_dev'}}}
    prod_config = {'FunctionName': 'navigan-custmanagement-cfnstk-migration', 'RevisionId': 'prod-revision',
                   'CodeSha256': release.zip_sha(production)}
    dev, prod = {'Configuration': dev_config}, {'Configuration': prod_config}
    plan = {'format': release.FORMAT, 'account': release.ACCOUNT, 'region': release.REGION,
            'dev': release.identity(dev), 'prod': release.identity(prod),
            'newSha': release.zip_sha(updated), 'configuration': release.config_fingerprint(dev_config)}
    path = tmp_path / 'release-plan.json'
    path.write_text(json.dumps(plan))
    (tmp_path / 'dev-original.zip').write_bytes(original)
    (tmp_path / 'dev-updated.zip').write_bytes(updated)
    monkeypatch.setattr(release, 'runtime', lambda session, label: dev if label == 'dev' else prod)
    monkeypatch.setattr(release, 'download', lambda response: production)
    calls = []

    class Lambda:
        def update_function_code(self, **kwargs):
            calls.append(kwargs)
            dev_config['CodeSha256'] = release.zip_sha(kwargs['ZipFile'])

        def get_waiter(self, name):
            assert name == 'function_updated'
            return self

        def wait(self, **kwargs):
            assert kwargs == {'FunctionName': 'navigan-ashok-dev-migration'}

    class Session:
        def client(self, name):
            assert name == 'lambda'
            return Lambda()

    release.execute(Session(), path)
    assert len(calls) == 1
    assert calls[0]['FunctionName'] == 'navigan-ashok-dev-migration'
    assert calls[0]['RevisionId'] == 'dev-revision'
    assert dev_config['Environment']['Variables']['DB_NAME'] == 'navigan_dev'
    assert prod_config['CodeSha256'] == release.zip_sha(production)
