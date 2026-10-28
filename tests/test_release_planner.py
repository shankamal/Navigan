import importlib.util
from pathlib import Path
import subprocess

import pytest


spec = importlib.util.spec_from_file_location("release_planner", Path(__file__).resolve().parents[1] / "scripts/plan-release.py")
planner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(planner)


def command(root, *args):
    return subprocess.check_output(["git", *args], cwd=root).decode().strip()


def commit(root, files):
    for name, content in files.items():
        path = root / name
        if content is None:
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    command(root, "add", "--all")
    command(root, "-c", "user.name=Release tests", "-c", "user.email=release-tests@example.invalid",
            "commit", "--quiet", "--allow-empty", "-m", "test snapshot")
    return command(root, "rev-parse", "HEAD")


@pytest.fixture
def repository(tmp_path):
    command(tmp_path, "init", "--quiet")
    base = commit(tmp_path, {"README.md": "initial", "src/navigan/shared/database.py": "x=1\n"})
    return tmp_path, base


@pytest.mark.parametrize("path,build,checks", [
    ("frontend/src/page.tsx", {"frontend"}, {"frontend"}),
    ("frontend/tests/page.test.tsx", set(), {"frontend"}),
    ("frontend/README.md", set(), set()),
    ("src/navigan/shared/database.py", {"backend", "image-worker"}, {"backend"}),
    ("src/requirements.txt", {"backend", "image-worker"}, {"backend"}),
    ("pyproject.toml", {"backend"}, {"backend"}),
    ("database/migrations/101_feature.sql", {"database"}, {"database"}),
    ("scripts/migrate.py", {"database"}, {"database"}),
    ("terraform/modules/aws-eks/main.tf", {"terraform-runner"}, {"terraform"}),
    ("connector/agent.py", {"cluster-connector"}, {"backend"}),
    ("migration_connector/agent.py", {"migration-connector"}, {"backend"}),
    ("tools-gateway/server.mjs", {"tools-gateway"}, {"gateway"}),
    ("workspace_image_worker/entrypoint.py", {"image-worker"}, {"backend"}),
    ("docs/openapi.json", set(), {"backend", "frontend", "api-contract"}),
    ("docs/design.md", set(), set()),
    ("tests/test_customer.py", set(), {"backend"}),
    (".github/workflows/test.yml", set(), {"release-tooling"}),
])
def test_stage_ownership(path, build, checks):
    affected, validation, _ = planner.classify(path)
    assert affected == build
    assert validation == checks


def test_multiple_commits_since_release_are_included(repository):
    root, base = repository
    commit(root, {"frontend/src/page.tsx": "first UI change"})
    head = commit(root, {"database/migrations/101_feature.sql": "SELECT 1;"})
    plan = planner.build_plan(base, head, root=root)
    assert plan["build"] == ["database", "frontend"]
    assert not plan["reviewRequired"]
    assert not plan["readyForDeployment"]
    assert not plan["deploymentPerformed"]


def test_unknown_paths_do_not_silently_skip(repository):
    root, base = repository
    head = commit(root, {"new-service/handler.go": "package main"})
    plan = planner.build_plan(base, head, root=root)
    assert not plan["readyForBuild"]
    assert plan["reviewRequired"][0]["path"] == "new-service/handler.go"


def test_docs_only_does_not_build_or_deploy(repository):
    root, base = repository
    head = commit(root, {"docs/release.md": "documentation"})
    plan = planner.build_plan(base, head, root=root)
    assert plan["build"] == plan["validation"] == []


def test_rename_preserves_both_sides_for_impact(repository):
    root, base = repository
    base = commit(root, {"frontend/src/old.ts": "same contents\n"})
    command(root, "mv", "frontend/src/old.ts", "frontend/src/new.ts")
    head = commit(root, {})
    records = planner.changes(base, head, root)
    assert records == [{"status": "R", "paths": ["frontend/src/old.ts", "frontend/src/new.ts"]}]
    assert planner.build_plan(base, head, root=root)["build"] == ["frontend"]


@pytest.mark.parametrize("change", ["modify", "delete", "rename"])
def test_existing_migration_changes_require_review(repository, change):
    root, _ = repository
    name = "database/migrations/100_existing.sql"
    base = commit(root, {name: "SELECT 1;"})
    if change == "rename":
        command(root, "mv", name, "database/migrations/101_existing.sql")
        head = commit(root, {})
    else:
        head = commit(root, {name: "SELECT 2;" if change == "modify" else None})
    plan = planner.build_plan(base, head, root=root)
    assert not plan["readyForBuild"]
    assert "immutable" in plan["reviewRequired"][0]["reason"]


def template(timeout=20, runtime="python3.12"):
    return f"""Transform: AWS::Serverless-2016-10-31
Resources:
  Function:
    Type: AWS::Serverless::Function
    Properties:
      CodeUri: ../../src
      Runtime: {runtime}
      Timeout: {timeout}
      Role: !GetAtt Role.Arn
"""


def test_infrastructure_only_change_reuses_backend_input(repository):
    root, _ = repository
    name = "infrastructure/module/template.yaml"
    base = commit(root, {name: template()})
    head = commit(root, {name: template(timeout=30)})
    assert planner.build_plan(base, head, root=root)["build"] == ["infrastructure"]
    assert planner.input_hash("backend", base, root) == planner.input_hash("backend", head, root)


def test_runtime_change_selects_backend_and_changes_cache_key(repository):
    root, _ = repository
    name = "infrastructure/module/template.yaml"
    base = commit(root, {name: template()})
    head = commit(root, {name: template(runtime="python3.13")})
    assert planner.build_plan(base, head, root=root)["build"] == ["backend", "infrastructure"]
    assert planner.input_hash("backend", base, root) != planner.input_hash("backend", head, root)


def test_template_rename_does_not_fail_reading_missing_side(repository):
    root, _ = repository
    base = commit(root, {"infrastructure/old.yaml": template()})
    command(root, "mv", "infrastructure/old.yaml", "infrastructure/new.yaml")
    head = commit(root, {})
    assert set(planner.build_plan(base, head, root=root)["build"]) == {"backend", "infrastructure"}


def test_unrelated_histories_refused(repository):
    root, base = repository
    head = commit(root, {"frontend/src/page.tsx": "change"})
    with pytest.raises(ValueError, match="ancestor"):
        planner.build_plan(head, base, root=root)


def release(component="frontend", digest="a" * 64, portable=True):
    value = {"format": planner.FORMAT, "sourceRevision": "1" * 40, "components": {
        component: {"inputHash": "b" * 64, "sha256": digest, "uri": "registry.example/navigan@sha256:" + digest,
                    "portable": portable}}}
    if component not in planner.IMAGES:
        value["components"][component].update(uri="s3://release-bucket/releases/package.zip", versionId="version-1")
    return value


def record(value):
    return {"environment": "dev", "status": "SUCCEEDED", "configurationHash": "c" * 64, "manifest": value}


def test_unchanged_artifacts_are_reused(repository):
    root, base = repository
    previous = release("backend")
    previous["sourceRevision"] = base
    previous["components"]["backend"]["inputHash"] = planner.input_hash("backend", base, root)
    head = commit(root, {"docs/new.md": "no code"})
    plan = planner.build_plan(base, head, previous, root)
    assert "backend" in plan["reuse"]
    assert not plan["build"]


def test_promotion_never_builds_or_republishes():
    candidate = release(digest="d" * 64)
    plan = planner.promotion_plan(candidate, record(release()), "dev", "c" * 64, "c" * 64)
    assert plan["deploy"] == ["frontend"]
    assert plan["build"] == plan["publish"] == []
    assert not plan["deploymentPerformed"]


def test_config_only_promotion_does_not_rebuild():
    candidate = release()
    plan = planner.promotion_plan(candidate, record(candidate), "dev", "d" * 64, "c" * 64)
    assert plan["configurationChanged"]
    assert not plan["build"] and not plan["deploy"]
    assert plan["reuse"] == ["frontend"]


def test_metadata_only_changes_do_not_redeploy_same_artifact():
    candidate = release()
    previous = release()
    previous["components"]["frontend"]["inputHash"] = "f" * 64
    plan = planner.promotion_plan(candidate, record(previous), "dev", "c" * 64, "c" * 64)
    assert not plan["deploy"]


def test_nonportable_frontend_is_not_silently_promoted():
    plan = planner.promotion_plan(release(digest="d" * 64, portable=False), record(release()), "dev", "c" * 64, "c" * 64)
    assert plan["reviewRequired"][0]["component"] == "frontend"
    assert not plan["readyForDeployment"]


def test_config_change_cannot_assume_a_baked_frontend_accepts_runtime_values():
    candidate = release(portable=False)
    plan = planner.promotion_plan(candidate, record(candidate), "dev", "d" * 64, "c" * 64)
    assert not plan["build"] and not plan["deploy"]
    assert plan["reviewRequired"][0]["component"] == "frontend"


def test_manifest_cannot_drop_unchanged_components():
    with pytest.raises(ValueError, match="retain"):
        planner.promotion_plan({"format": planner.FORMAT, "sourceRevision": "1" * 40, "components": {}},
                               record(release()), "dev", "c" * 64, "c" * 64)


@pytest.mark.parametrize("mutation", ["mutable-tag", "wrong-digest", "missing-checksum", "missing-portability"])
def test_artifact_identity_is_immutable(mutation):
    value = release()
    item = value["components"]["frontend"]
    if mutation == "mutable-tag":
        item["uri"] = "registry.example/navigan:latest"
    elif mutation == "wrong-digest":
        item["uri"] = "registry.example/navigan@sha256:" + "d" * 64
    elif mutation == "missing-checksum":
        item.pop("sha256")
    else:
        item.pop("portable")
    with pytest.raises(ValueError):
        planner.validate_manifest(value)


def test_versioned_packages_required():
    value = release("backend")
    item = value["components"]["backend"]
    item.update(uri="s3://release-bucket/releases/backend.zip", versionId="object-version")
    assert planner.validate_manifest(value) == value
    del item["versionId"]
    with pytest.raises(ValueError, match="version"):
        planner.validate_manifest(value)


def test_environment_and_successful_baseline_required():
    with pytest.raises(ValueError, match="successful"):
        planner.promotion_plan(release(), record(release()), "prod", "c" * 64, "c" * 64)
    bad = record(release())
    bad["status"] = "FAILED"
    with pytest.raises(ValueError, match="successful"):
        planner.promotion_plan(release(), bad, "dev", "c" * 64, "c" * 64)


def test_explicit_baseline_required(monkeypatch):
    monkeypatch.setattr(planner, "git", lambda *_args, **_kwargs: pytest.fail("Must reject before Git/AWS reads"))
    with pytest.raises(ValueError, match="never guessed"):
        planner.main([])


def test_bad_deployed_manifest_is_not_trusted():
    deployed = record(release())
    deployed["manifest"]["components"]["frontend"]["uri"] = "mutable:latest"
    with pytest.raises(ValueError):
        planner.promotion_plan(release(), deployed, "dev", "c" * 64, "c" * 64)


@pytest.mark.parametrize("field,value", [("inputHash", 1), ("sha256", None), ("uri", []), ("portable", "true")])
def test_malformed_manifest_fields_fail_cleanly(field, value):
    artifact = release()
    artifact["components"]["frontend"][field] = value
    with pytest.raises(ValueError):
        planner.validate_manifest(artifact)


def test_null_s3_version_is_not_immutable():
    artifact = release("backend")
    artifact["components"]["backend"]["versionId"] = "null"
    with pytest.raises(ValueError):
        planner.validate_manifest(artifact)


def test_workflow_is_plan_only():
    import yaml
    root = Path(__file__).resolve().parents[1]
    text = (root / ".github/workflows/dev-release-plan.yml").read_text()
    workflow = yaml.load(text, Loader=yaml.BaseLoader)
    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["on"]) == {"pull_request", "workflow_dispatch"}
    assert "persist-credentials: false" in text
    assert "scripts/plan-release.py" in text
    assert "configure-aws-credentials" not in text
    assert "execute-change-set" not in text
    assert "update-service" not in text
