"""Production collector isolation without live AWS or Docker calls."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location("prod_worker_test", ROOT / "scripts/deploy-workspace-workers-prod.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def settings():
    return {"function": "prod-migration", "roleArn": "arn:aws:iam::905418045935:role/prod-api", "revision": "verified-revision"}


def workspace():
    return {"WorkspaceBucketName": "prod-workspace", "WorkspaceKmsKeyArn": "prod-key"}


def configuration():
    return {"FunctionName": "prod-migration", "FunctionArn": "arn:aws:lambda:ap-south-1:905418045935:function:prod-migration",
        "Role": settings()["roleArn"], "RevisionId": settings()["revision"], "Runtime": "python3.12", "State": "Active",
        "LastUpdateStatus": "Successful", "VpcConfig": {"SubnetIds": ["prod-subnet"], "SecurityGroupIds": ["prod-sg"]},
        "Layers": [{"Arn": "prod-layer"}], "Environment": {"Variables": {
            "DB_NAME": "navigan", "DB_PROXY_HOST": "prod-db", "DB_SECRET_ARN": "prod-secret-ref", "DB_CA_BUNDLE": "/opt/certs/global-bundle.pem",
            "MIGRATION_WORKSPACE_BUCKET": "prod-workspace", "MIGRATION_WORKSPACE_KMS_KEY": "prod-key", "MIGRATION_WORKSPACE_BUCKET_OWNER": "905418045935",
            "MIGRATION_SOURCE_FIRST_ENABLED": "true", "UNRELATED_SECRET": "must-not-copy"}}}


def test_dev_defaults_stay_dev_until_explicit_prod_binding():
    module = load()
    assert module.worker.DATABASE == "navigan_dev" and module.worker.STACK == "navigan-ashok-dev"
    module.bind_production(settings(), workspace())
    assert module.worker.DATABASE == "navigan"
    assert module.worker.STACK == "navigan-custmanagement-cfnstk"
    assert module.worker.REPOSITORY == "navigan/prod-workspace-image-collector"


def test_production_runtime_uses_exact_verified_api_database_and_storage():
    module = load()
    module.bind_production(settings(), workspace())
    env = module.worker.runtime_settings(configuration())
    assert env["DB_NAME"] == "navigan" and env["MIGRATION_WORKSPACE_BUCKET"] == "prod-workspace"
    assert "UNRELATED_SECRET" not in env


@pytest.mark.parametrize("field,value", [("FunctionName", "dev-migration"), ("Role", "arn:aws:iam::905418045935:role/dev-api"),
    ("RevisionId", "stale")])
def test_wrong_or_changed_api_cannot_supply_worker_runtime(field, value):
    module = load()
    module.bind_production(settings(), workspace())
    config = configuration()
    config[field] = value
    with pytest.raises(RuntimeError):
        module.worker.runtime_settings(config)


@pytest.mark.parametrize("key,value", [("DB_NAME", "navigan_dev"), ("MIGRATION_WORKSPACE_BUCKET", "dev-workspace"),
    ("MIGRATION_WORKSPACE_KMS_KEY", "dev-key"), ("MIGRATION_SOURCE_FIRST_ENABLED", "false")])
def test_dev_database_storage_or_unpromoted_api_is_rejected(key, value):
    module = load()
    module.bind_production(settings(), workspace())
    config = configuration()
    config["Environment"]["Variables"][key] = value
    with pytest.raises((RuntimeError, SystemExit)):
        module.worker.runtime_settings(config)


def test_repository_schedule_is_separate_and_disabled_by_default():
    module = load()
    module.bind_production(settings(), workspace())
    config = configuration()
    template = module.worker.repository_template(config, module.worker.runtime_settings(config), "prod-workspace", "key", "version", False)
    worker = template["Resources"]["Worker"]["Properties"]
    assert worker["FunctionName"] == "navigan-custmanagement-cfnstk-workspace-repositories"
    assert worker["Environment"]["Variables"]["DB_NAME"] == "navigan"
    assert worker["VpcConfig"] == config["VpcConfig"] and worker["Role"] == config["Role"]
    assert template["Resources"]["Poll"]["Properties"]["State"] == "DISABLED"


def test_image_foundation_cannot_pull_from_dev_repository():
    module = load()
    module.bind_production(settings(), workspace())
    template = module.worker.image_foundation()
    assert template["Resources"]["Repository"]["Properties"]["RepositoryName"] == "navigan/prod-workspace-image-collector"
    assert "navigan/dev-workspace-image-collector" not in str(template)
