"""The operator's build/deploy commands reuse resources and keep builds separate."""
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import release_common as common

simple = common.load("tested_simple_release", common.ROOT / "scripts/simple-release.py")
builder = common.load("tested_simple_builder", common.ROOT / "scripts/build-release.py")
ACCOUNT = "123456789012"
PREFIX = f"{ACCOUNT}.dkr.ecr.ap-south-1.amazonaws.com/"


def config(tmp_path):
    value = {"profile": "navigan", "region": "ap-south-1", "account": ACCOUNT,
             "artifactBucket": "existing-sam-artifacts", "repositories": {"frontend": PREFIX + "navigan/frontend"},
             "initialComponents": ["frontend"]}
    path = tmp_path / "dev.json"
    common.write(path, value)
    return path, value


def test_settings_allow_existing_resources_without_release_tags(tmp_path):
    path, value = config(tmp_path)
    assert simple.settings(path) == value
    assert builder.repository_uri("frontend", value["repositories"], ACCOUNT, "ap-south-1") == PREFIX + "navigan/frontend"


@pytest.mark.parametrize("change", [
    {"artifactBucket": "YOUR_EXISTING_BUCKET"},
    {"region": "us-east-1"},
    {"repositories": {"frontend": "999999999999.dkr.ecr.ap-south-1.amazonaws.com/prod/frontend"}},
    {"repositories": {"frontend": PREFIX + "navigan/frontend:latest"}},
    {"repositories": {"frontend": PREFIX + "navigan/frontend@sha256:" + "a" * 64}},
    {"DATABASE_PASSWORD": "not-allowed"},
])
def test_invalid_or_secret_configuration_rejected(tmp_path, change):
    path, value = config(tmp_path)
    common.write(path, {**value, **change})
    with pytest.raises(common.ReleaseError): simple.settings(path)


def test_missing_configuration_creates_no_resources_or_local_state(tmp_path):
    with pytest.raises(common.ReleaseError, match="One-time setup"):
        simple.main(["build", "--config", str(tmp_path / "missing.json")])
    assert not list(tmp_path.iterdir())


def test_build_remembers_complete_manifest_and_does_not_deploy(monkeypatch, tmp_path):
    path, cfg = config(tmp_path)
    built = tmp_path / "built"
    built.mkdir()
    manifest = {"format": common.planner.FORMAT, "sourceRevision": "a" * 40, "components": {}}
    common.write(built / "release-manifest.json", manifest)
    commands = []
    def load(name, *args):
        if name == "simple_release_settings": return builder
        assert name == "simple_release_builder"
        return SimpleNamespace(main=lambda args: commands.append(args) or built)
    monkeypatch.setattr(common, "load", load)
    monkeypatch.setattr(simple.boto3, "Session", lambda **kw: pytest.fail("Build wrapper must not initialize deployment"))
    simple.main(["build", "--config", str(path)])
    assert "--initial" in commands[0] and "frontend" in commands[0]
    assert "--repositories-file" in commands[0]
    assert common.read(tmp_path / "state/last-build-manifest.json") == manifest
    simple.main(["build", "--config", str(path)])
    assert "--baseline-manifest" in commands[1] and "--initial" not in commands[1]


def test_deploy_consumes_manifest_without_build_or_registry_creation(monkeypatch, tmp_path):
    path, cfg = config(tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    manifest_path = state / "last-build-manifest.json"
    common.write(manifest_path, {"fixture": "already built"})
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    common.write(prepared / "release-plan.json", {"id": "saved-plan"})
    calls = []
    def prepare(session, target_path, artifact_path):
        assert artifact_path == manifest_path
        assert common.read(target_path)["repositories"] == cfg["repositories"]
        calls.append("prepare")
        return prepared
    executor = SimpleNamespace(prepare=prepare, execute=lambda session, plan: calls.append(("execute", plan)))
    def load(name, *args):
        if name == "simple_release_settings": return builder
        assert name == "simple_release_executor"
        return executor
    monkeypatch.setattr(common, "load", load)
    monkeypatch.setattr(common, "verify_registry", lambda *args: calls.append("verify-existing-bucket"))
    monkeypatch.setattr(simple.boto3, "Session", lambda **kw: object())
    monkeypatch.setattr(simple.target, "snapshot", lambda *args: {})
    monkeypatch.setattr(simple.target, "configuration", lambda *args: {"existingDev": True})
    monkeypatch.setattr(simple.target, "registry", lambda *args: pytest.fail("Never bootstrap a registry"))
    simple.main(["deploy", "--config", str(path)])
    assert calls == ["verify-existing-bucket", "prepare", ("execute", prepared / "release-plan.json")]
    assert common.read(state / "last-deployment.json") == {"plan": str(prepared / "release-plan.json")}


@pytest.mark.parametrize("status", [{"requestedAt": "fixture"}, {"recordPublished": {"uri": "fixture"}},
                                  {"recordPublished": {"uri": "fixture"}, "lockReleased": True, "rollbackRequested": "fixture"}])
def test_deploy_after_interruption_requires_recovery_not_a_new_plan(monkeypatch, tmp_path, status):
    path, cfg = config(tmp_path)
    directory = tmp_path / "state"
    directory.mkdir()
    plan = tmp_path / "attempt/release-plan.json"
    common.write(directory / "last-deployment.json", {"plan": str(plan)})
    common.write(plan.parent / "execution.json", status)
    executor = SimpleNamespace(prepare=lambda *args: pytest.fail("Must not create another attempt"),
                               verify=lambda *args: None)
    original = common.load
    monkeypatch.setattr(common, "load", lambda name, *args: executor if name == "simple_release_executor" else original(name, *args))
    monkeypatch.setattr(simple.boto3, "Session", lambda **kw: object())
    with pytest.raises(common.ReleaseError, match="unfinished"):
        simple.main(["deploy", "--config", str(path)])
    simple.main(["deploy", "--config", str(path), "--verify"])


def test_normal_entry_points_have_no_resource_creation():
    source = (common.ROOT / "scripts/simple-release.py").read_text()
    assert "target.registry(" not in source and "bootstrap" not in source
    for name in ("build.sh", "deploy.sh"):
        shell = (common.ROOT / "scripts" / name).read_text()
        assert "simple-release.py" in shell
        assert "cloudformation deploy" not in shell and "create-repository" not in shell


def test_prod_not_an_available_simple_command():
    with pytest.raises(SystemExit) as caught:
        simple.main(["deploy", "--environment", "prod"])
    assert caught.value.code == 2


def test_existing_bucket_requires_versioning_but_not_special_tags():
    methods = {"head_bucket": lambda **kw: {}, "get_bucket_location": lambda **kw: {"LocationConstraint": "ap-south-1"},
               "get_bucket_versioning": lambda **kw: {"Status": "Enabled"},
               "get_public_access_block": lambda **kw: {"PublicAccessBlockConfiguration": {
                   key: True for key in ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")}}}
    s3 = SimpleNamespace(**methods)
    session = SimpleNamespace(region_name="ap-south-1", client=lambda name: s3 if name == "s3" else SimpleNamespace(get_caller_identity=lambda: {"Account": ACCOUNT}))
    common.verify_registry(session, "existing-sam-artifacts", ACCOUNT, "ap-south-1")


def test_existing_shared_repository_is_verified_by_digest():
    digest = "a" * 64
    calls = []
    def images(**kw):
        calls.append(kw)
        return {"imageDetails": [{"imageDigest": "sha256:" + digest}]}
    session = SimpleNamespace(client=lambda name: SimpleNamespace(describe_images=images))
    common.verify_image(session, "frontend", {"uri": PREFIX + "navigan/frontend@sha256:" + digest, "sha256": digest,
        "runtimeConfigProof": {"contract": common.CONTRACT, "passed": True, "configurations": ["dev-fixture", "prod-fixture"]}}, ACCOUNT, "ap-south-1")
    assert calls == [{"repositoryName": "navigan/frontend", "imageIds": [{"imageDigest": "sha256:" + digest}]}]
