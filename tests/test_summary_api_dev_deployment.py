"""DEV-specific boundaries supplement the shared summary release tests."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('dev_summary_release', ROOT / 'scripts/deploy-summary-apis-dev.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def test_exact_dev_storage_and_parent_binding():
    assert release.PARENT == 'navigan-ashok-dev'
    assert release.support.storage.PARENT == release.PARENT
    assert release.ROUTE == 'NaviganDevSummaryRoute'
    assert release.PERMISSION == 'NaviganDevSummaryInvoke'


def test_prod_plan_is_rejected_before_any_aws_call(tmp_path):
    plan = tmp_path / 'prod.json'
    plan.write_text(json.dumps({'format': 'navigan-summary-prod-v1', 'account': release.ACCOUNT,
                                'region': release.REGION}))
    with pytest.raises(RuntimeError, match='Wrong release plan'):
        release.execute(object(), plan)


def test_prod_parent_is_rejected_before_nested_read():
    class CFN:
        def describe_stacks(self, StackName):
            assert StackName == 'navigan-ashok-dev'
            return {'Stacks': [{'StackStatus': 'UPDATE_COMPLETE', 'Parameters': [
                {'ParameterKey': 'DatabaseName', 'ParameterValue': 'navigan'}]}]}

    class Session:
        def client(self, name):
            if name == 'sts':
                return SimpleNamespace(get_caller_identity=lambda: {'Account': release.ACCOUNT})
            return CFN()

    with pytest.raises(RuntimeError, match='Not DEV database'):
        release.preflight(Session())


def test_upload_stays_in_dev_workspace_and_requires_version():
    calls = []

    class S3:
        def put_object(self, **kwargs):
            calls.append(kwargs)
            return {'VersionId': 'immutable-version'}

    session = SimpleNamespace(client=lambda name: S3())
    workspace = {'WorkspaceBucketName': 'verified-dev-workspace', 'WorkspaceKmsKeyArn': 'dev-key'}
    code, url = release.upload(session, workspace, None, 'customers.zip', b'package')
    assert calls[0]['Bucket'] == code['S3Bucket'] == workspace['WorkspaceBucketName']
    assert calls[0]['Key'].startswith('deployment-packages/dev-summary-api/')
    assert calls[0]['ExpectedBucketOwner'] == release.ACCOUNT
    assert calls[0]['SSEKMSKeyId'] == 'dev-key'
    assert code['S3ObjectVersion'] == 'immutable-version'
    assert 'versionId=immutable-version' in url


def test_storage_and_deploy_helpers_default_targets_stay_isolated():
    # Loading DEV's isolated helper does not change the production helper module.
    spec = importlib.util.spec_from_file_location('isolated_prod_summary', ROOT / 'scripts/deploy-summary-apis-prod.py')
    prod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prod)
    assert prod.PARENT == prod.support.storage.PARENT == 'navigan-custmanagement-cfnstk'
    assert release.PARENT == release.support.storage.PARENT == 'navigan-ashok-dev'
