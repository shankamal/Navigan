"""Production frontend promotion boundaries; no live AWS, Docker or HTTP calls."""
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("frontend_release", ROOT / "scripts/deploy-frontend-prod.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
DIGEST = "sha256:" + "a" * 64
IMAGE = release.IMAGE_PREFIX + "@" + DIGEST
OLD = f"arn:aws:ecs:{release.REGION}:{release.ACCOUNT}:task-definition/{release.FAMILY}:8"
NEW = OLD.rsplit(":", 1)[0] + ":9"


def task():
    return {"family": release.FAMILY, "cpu": "256", "memory": "512", "networkMode": "awsvpc",
        "executionRoleArn": "original-execution-role", "taskRoleArn": "original-task-role", "requiresCompatibilities": ["FARGATE"],
        "runtimePlatform": {"cpuArchitecture": "X86_64", "operatingSystemFamily": "LINUX"},
        "containerDefinitions": [{"name": "frontend", "image": "original-image", "user": "1000", "essential": True,
            "environment": [{"name": "NODE_ENV", "value": "production"}, {"name": "NAVIGAN_API_ORIGIN", "value": "https://production-api"},
                            {"name": "NAVIGAN_API_BASE_PATH", "value": "/v1/api/v1"}],
            "healthCheck": {"command": ["CMD", "/nodejs/bin/node", "health-check"]},
            "logConfiguration": {"logDriver": "awslogs", "options": {"awslogs-group": "existing"}}},
            {"name": "unchanged-sidecar", "image": "sidecar-image"}], "volumes": []}


def service(arn=OLD):
    return {"serviceName": release.SERVICE, "status": "ACTIVE", "clusterArn": f"arn:aws:ecs:{release.REGION}:{release.ACCOUNT}:cluster/{release.CLUSTER}",
        "taskDefinition": arn, "desiredCount": 1, "runningCount": 1, "pendingCount": 0,
        "deploymentController": {"type": "ECS"}, "deployments": [{"status": "PRIMARY", "rolloutState": "COMPLETED"}]}


def test_candidate_changes_only_image_and_explicit_runtime_switch():
    before = task()
    after = release.candidate_request(before, IMAGE)
    expected = copy.deepcopy(before)
    expected["containerDefinitions"][0]["image"] = IMAGE
    expected["containerDefinitions"][0]["environment"].append({"name": release.FLAG, "value": "true"})
    assert after == expected and before == task()
    release.validate_candidate(before, after, IMAGE)


def test_existing_flag_is_updated_without_duplicate_or_preview_bypass():
    before = task()
    before["containerDefinitions"][0]["environment"].append({"name": release.FLAG, "value": "false"})
    after = release.candidate_request(before, IMAGE)
    env = release.environment(release.container(after))
    assert env[release.FLAG] == "true" and env["NODE_ENV"] == "production"
    assert "NEXT_PUBLIC_MIGRATION_UI_PREVIEW" not in env


@pytest.mark.parametrize("mutate", [
    lambda t: t.update(taskRoleArn="different-role"),
    lambda t: t.update(cpu="1024"),
    lambda t: t["containerDefinitions"][1].update(image="different-sidecar"),
    lambda t: t["containerDefinitions"][0].update(user="0"),
    lambda t: t["containerDefinitions"][0].update(healthCheck={"command": ["NONE"]}),
    lambda t: t["containerDefinitions"][0]["environment"].append({"name": "NEXT_PUBLIC_MIGRATION_UI_PREVIEW", "value": "true"}),
])
def test_unrelated_task_changes_are_rejected(mutate):
    original = task()
    candidate = release.candidate_request(original, IMAGE)
    mutate(candidate)
    with pytest.raises(RuntimeError, match="changes more"):
        release.validate_candidate(original, candidate, IMAGE)


@pytest.mark.parametrize("image", ["external.example/frontend:latest", release.IMAGE_PREFIX + ":latest",
                                  IMAGE.replace("navigan/frontend", "navigan/dev-frontend")])
def test_only_exact_frontend_repo_digest_is_allowed(image):
    with pytest.raises(RuntimeError, match="immutable image"):
        release.candidate_request(task(), image)


def test_dev_server_and_duplicate_environment_names_are_rejected():
    before = task()
    before["containerDefinitions"][0]["environment"][0]["value"] = "development"
    with pytest.raises(RuntimeError, match="development server"):
        release.candidate_request(before, IMAGE)
    before = task()
    before["containerDefinitions"][0]["environment"].append({"name": "NODE_ENV", "value": "development"})
    with pytest.raises(RuntimeError, match="Duplicate"):
        release.candidate_request(before, IMAGE)


def test_api_metadata_and_reserved_tags_are_not_sent_to_registration():
    before = task()
    accepted = set(before) | {"tags"}
    before.update(taskDefinitionArn=OLD, revision=8, status="ACTIVE", registeredBy="aws-metadata")
    result = release.task_request(before, [{"key": "aws:cloudformation:stack-name", "value": "reserved"},
                                          {"key": "owner", "value": "preserve"}], accepted)
    assert "revision" not in result and "registeredBy" not in result
    assert result["tags"] == [{"key": "owner", "value": "preserve"}]
    assert result["taskRoleArn"] == "original-task-role"


def test_environment_order_does_not_create_a_false_change():
    before = task()
    candidate = release.candidate_request(before, IMAGE)
    candidate["containerDefinitions"][0]["environment"].reverse()
    release.validate_candidate(before, candidate, IMAGE)


def parameters():
    return {"JwtIssuer": "https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_Production",
            "JwtAudience": "productionclient123456", "IdentityUserPoolId": "ap-south-1_Production"}


def test_public_build_settings_come_from_verified_prod_parameters():
    result = release.public_config(parameters(), "navigan.click")
    assert result["NEXT_PUBLIC_APP_URL"] == "https://navigan.click"
    assert result["NEXT_PUBLIC_OIDC_CLIENT_ID"] == "productionclient123456"
    assert result["NEXT_PUBLIC_OIDC_AUTHORITY"] == parameters()["JwtIssuer"]
    assert len(result) == 3


@pytest.mark.parametrize("key,value", [("JwtAudience", "productionclient123456\r"), ("JwtAudience", "one,two"),
    ("JwtIssuer", "http://cognito.example/pool"), ("IdentityUserPoolId", "other-pool")])
def test_malformed_or_conflicting_oidc_settings_are_rejected(key, value):
    params = parameters()
    params[key] = value
    with pytest.raises(RuntimeError):
        release.public_config(params, "navigan.click")


def test_wrong_hostname_and_wrong_task_family_are_rejected():
    with pytest.raises(RuntimeError, match="hostname"):
        release.public_config(parameters(), "localhost")
    before = task()
    before["family"] = "unrelated-service"
    with pytest.raises(RuntimeError, match="family"):
        release.task_request(before, [], set(before))


def test_multiarch_digest_verification_selects_only_linux_amd64():
    amd64, arm64 = "sha256:" + "b" * 64, "sha256:" + "c" * 64
    manifest = {"manifests": [{"digest": amd64, "platform": {"os": "linux", "architecture": "amd64"}},
                              {"digest": arm64, "platform": {"os": "linux", "architecture": "arm64"}}]}
    ecr = SimpleNamespace(batch_get_image=lambda **kw: {"images": [{"imageManifest": json.dumps(manifest)}]})
    assert release.runtime_digests(ecr, DIGEST) == [DIGEST, amd64]


def test_missing_published_manifest_is_rejected():
    ecr = SimpleNamespace(batch_get_image=lambda **kw: {"failures": [{"failureCode": "ImageNotFound"}]})
    with pytest.raises(RuntimeError, match="manifest"):
        release.runtime_digests(ecr, DIGEST)


class ECS:
    def __init__(self, *, changed=False, rollback=False, digest=DIGEST):
        self.live = OLD
        self.changed, self.rollback, self.digest = changed, rollback, digest
        self.calls = []
        self.meta = SimpleNamespace(service_model=SimpleNamespace(operation_model=lambda name:
            SimpleNamespace(input_shape=SimpleNamespace(members=set(task()) | {"tags"}))))

    def describe_services(self, **kw):
        assert kw == {"cluster": release.CLUSTER, "services": [release.SERVICE]}
        return {"services": [service(NEW if self.changed else self.live)]}

    def describe_task_definition(self, taskDefinition, **kw):
        return {"taskDefinition": task() if taskDefinition == OLD else release.candidate_request(task(), IMAGE)}

    def update_service(self, **kw):
        self.calls.append(kw)
        if not self.rollback:
            self.live = kw["taskDefinition"]

    def get_waiter(self, name):
        return SimpleNamespace(wait=lambda **kw: None)

    def list_tasks(self, **kw):
        return {"taskArns": ["running-task"]}

    def describe_tasks(self, **kw):
        return {"tasks": [{"taskDefinitionArn": self.live, "containers": [{"name": release.CONTAINER, "imageDigest": self.digest}]}]}


def setup_execute(monkeypatch, tmp_path, ecs):
    request = release.task_request(task(), [], set(task()) | {"tags"})
    plan = {"format": 1, "account": release.ACCOUNT, "region": release.REGION, "previousTask": OLD, "nextTask": NEW,
        "desiredCount": 1, "baselineSha256": hashlib.sha256(release.canonical(request)).hexdigest(),
        "image": IMAGE, "runtimeDigests": [DIGEST]}
    path = tmp_path / "release-plan.json"
    path.write_text(json.dumps(plan))
    clients = {"ecs": ecs, "sts": SimpleNamespace(get_caller_identity=lambda: {"Account": release.ACCOUNT}),
        "ecr": SimpleNamespace(batch_get_image=lambda **kw: {"images": [{"imageManifest": '{"schemaVersion":2,"layers":[]}'}]})}
    monkeypatch.setattr(release, "backend_readiness", lambda session: None)
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return None
    monkeypatch.setattr(release.urllib.request, "urlopen", lambda url, **kw: Response())
    return SimpleNamespace(client=lambda name: clients[name]), path


def test_execute_changes_only_task_reference_on_the_exact_frontend_service(monkeypatch, tmp_path):
    ecs = ECS()
    session, path = setup_execute(monkeypatch, tmp_path, ecs)
    release.execute(session, path)
    assert ecs.calls == [{"cluster": release.CLUSTER, "service": release.SERVICE, "taskDefinition": NEW}]


def test_changed_baseline_stops_before_any_service_mutation(monkeypatch, tmp_path):
    ecs = ECS(changed=True)
    session, path = setup_execute(monkeypatch, tmp_path, ecs)
    with pytest.raises(RuntimeError, match="baseline changed"):
        release.execute(session, path)
    assert not ecs.calls


def test_stable_service_after_circuit_breaker_rollback_is_not_reported_as_success(monkeypatch, tmp_path):
    ecs = ECS(rollback=True)
    session, path = setup_execute(monkeypatch, tmp_path, ecs)
    with pytest.raises(RuntimeError, match="requested revision"):
        release.execute(session, path)


def test_wrong_running_image_digest_is_not_reported_as_success(monkeypatch, tmp_path):
    ecs = ECS(digest="sha256:" + "f" * 64)
    session, path = setup_execute(monkeypatch, tmp_path, ecs)
    with pytest.raises(RuntimeError, match="image digest"):
        release.execute(session, path)


def test_prepare_archives_aws_timestamp_without_changing_service(monkeypatch, tmp_path):
    # Exercise the legacy serializer using a checkout predating portable runtime configuration.
    monkeypatch.setattr(release, "ROOT", tmp_path)
    timestamp = datetime(2026, 10, 16, 12, 30, tzinfo=timezone.utc)
    described = {"taskDefinition": dict(task(), taskDefinitionArn=OLD, registeredAt=timestamp, revision=8),
                 "tags": [{"key": "owner", "value": "platform"}]}
    snapshot = copy.deepcopy(described)
    original = release.task_request(described["taskDefinition"], described["tags"], set(task()) | {"tags"})
    ecs = ECS()
    registrations = []
    def register(**request):
        registrations.append(request)
        return {"taskDefinition": {"taskDefinitionArn": NEW}}
    ecs.register_task_definition = register
    session = SimpleNamespace(client=lambda name: ecs)
    monkeypatch.setattr(release.boto3, "Session", lambda **kw: session)
    monkeypatch.setattr(release, "check_checkout", lambda: "committed-revision")
    monkeypatch.setattr(release, "readiness", lambda session: (service(), described, original, {"public": "config"}))
    monkeypatch.setattr(release.tempfile, "mkdtemp", lambda **kw: str(tmp_path))
    monkeypatch.setattr(release, "build_image", lambda *args: (IMAGE, [DIGEST]))
    monkeypatch.setattr("sys.argv", ["deploy-frontend-prod.py", "--profile", "navigan", "--prepare"])
    assert release.main() == 0
    saved = json.loads((tmp_path / "original-task.json").read_text())
    assert saved["taskDefinition"]["registeredAt"] == timestamp.isoformat()
    assert saved["taskDefinition"]["taskDefinitionArn"] == OLD
    assert described == snapshot
    assert registrations == [release.candidate_request(original, IMAGE)]
    assert "registeredAt" not in registrations[0]
    assert json.loads((tmp_path / "candidate-task-request.json").read_text()) == registrations[0]
    plan = json.loads((tmp_path / "release-plan.json").read_text())
    assert plan["previousTask"] == OLD and plan["nextTask"] == NEW
    assert ecs.live == OLD and not ecs.calls


def test_portable_source_rejects_missing_public_settings_before_writes(monkeypatch, tmp_path):
    marker = tmp_path / "frontend/src/shared/config/public-config.ts"
    marker.parent.mkdir(parents=True)
    marker.write_text("fixture")
    monkeypatch.setattr(release, "ROOT", tmp_path)
    monkeypatch.setattr(release.boto3, "Session", lambda **kw: None)
    monkeypatch.setattr(release, "check_checkout", lambda: "committed-revision")
    monkeypatch.setattr(release, "readiness", lambda session, **kw: (service(), {}, task(), {}))
    monkeypatch.setattr(release, "build_image", lambda *args: pytest.fail("Legacy build must not run"))
    monkeypatch.setattr("sys.argv", ["deploy-frontend-prod.py", "--profile", "navigan", "--prepare"])
    with pytest.raises(RuntimeError, match="public runtime configuration keys"):
        release.main()


def test_rollback_serializer_rejects_unknown_values_and_task_json_stays_strict():
    with pytest.raises(TypeError, match="not JSON serializable"):
        json.dumps({"unsupported": object()}, default=release.aws_record_default)
    with pytest.raises(TypeError, match="not JSON serializable"):
        release.canonical({"registeredAt": datetime.now(timezone.utc)})


def test_identical_ecr_duplicate_manifests_are_accepted():
    image = {"imageId": {"imageDigest": DIGEST},
        "imageManifestMediaType": "application/vnd.oci.image.manifest.v1+json",
        "imageManifest": '{"schemaVersion":2,"layers":[]}'}
    ecr = SimpleNamespace(batch_get_image=lambda **kw: {"failures": [], "images": [image, copy.deepcopy(image)]})
    assert release.runtime_digests(ecr, DIGEST) == [DIGEST]


@pytest.mark.parametrize("change", [
    {"imageManifest": '{"schemaVersion":2,"layers":[{"digest":"different"}]}'},
    {"imageManifestMediaType": "different/type"},
    {"imageId": {"imageDigest": "sha256:" + "f" * 64}},
])
def test_conflicting_ecr_duplicate_manifests_are_rejected(change):
    image = {"imageId": {"imageDigest": DIGEST},
        "imageManifestMediaType": "application/vnd.oci.image.manifest.v1+json",
        "imageManifest": '{"schemaVersion":2,"layers":[]}'}
    other = dict(copy.deepcopy(image), **change)
    ecr = SimpleNamespace(batch_get_image=lambda **kw: {"images": [image, other]})
    with pytest.raises(RuntimeError, match="manifest"):
        release.runtime_digests(ecr, DIGEST)


def test_duplicate_ecr_index_still_selects_linux_amd64():
    amd64 = "sha256:" + "b" * 64
    image = {"imageId": {"imageDigest": DIGEST},
        "imageManifest": json.dumps({"manifests": [
            {"digest": amd64, "platform": {"os": "linux", "architecture": "amd64"}}]})}
    ecr = SimpleNamespace(batch_get_image=lambda **kw: {"images": [image, copy.deepcopy(image)]})
    assert release.runtime_digests(ecr, DIGEST) == [DIGEST, amd64]


def prod_public():
    return release.public_config(parameters(), "navigan.click")


def test_portable_candidate_preserves_api_sidecars_flags_and_original():
    before = task()
    before["containerDefinitions"][0]["environment"].append({"name": release.FLAG, "value": "false"})
    snapshot = copy.deepcopy(before)
    after = release.candidate_request(before, IMAGE, prod_public())
    expected = copy.deepcopy(before)
    expected["containerDefinitions"][0]["image"] = IMAGE
    expected["containerDefinitions"][0]["environment"] += [
        {"name": key, "value": value} for key, value in release.runtime_public_config(prod_public()).items()]
    assert before == snapshot and after == expected
    assert release.environment(release.container(after))[release.FLAG] == "false"
    release.validate_candidate(before, after, IMAGE, prod_public())
    after["containerDefinitions"][0]["environment"][1]["value"] = "https://api-dev.example.invalid"
    with pytest.raises(RuntimeError, match="changes more"):
        release.validate_candidate(before, after, IMAGE, prod_public())


@pytest.mark.parametrize("name", ["NAVIGAN_PUBLIC_OIDC_CLIENT_ID", "NEXT_PUBLIC_OIDC_CLIENT_ID", "NAVIGAN_PUBLIC_APP_URL"])
def test_portable_candidate_refuses_conflicting_existing_identity(name):
    before = task()
    before["containerDefinitions"][0]["environment"].append({"name": name, "value": "wrong"})
    with pytest.raises(RuntimeError, match="conflicts"):
        release.candidate_request(before, IMAGE, prod_public())


def test_portable_prepare_registers_only_a_candidate_and_saves_format_two(monkeypatch, tmp_path):
    marker = tmp_path / "frontend/src/shared/config/public-config.ts"
    marker.parent.mkdir(parents=True)
    marker.write_text("fixture")
    monkeypatch.setattr(release, "ROOT", tmp_path)
    ecs = ECS()
    requests = []
    ecs.register_task_definition = lambda **kw: (requests.append(kw) or {"taskDefinition": {"taskDefinitionArn": NEW}})
    session = SimpleNamespace(client=lambda name: ecs)
    monkeypatch.setattr(release.boto3, "Session", lambda **kw: session)
    monkeypatch.setattr(release, "check_checkout", lambda: "merged-main-sha")
    checks = []
    monkeypatch.setattr(release, "readiness", lambda session, **kw: (checks.append(kw) or (service(), {}, task(), prod_public())))
    monkeypatch.setattr(release.tempfile, "mkdtemp", lambda **kw: str(tmp_path))
    monkeypatch.setattr(release, "build_image", lambda *args: (IMAGE, [DIGEST]))
    monkeypatch.setattr("sys.argv", ["deploy-frontend-prod.py", "--prepare"])
    assert release.main() == 0
    plan = json.loads((tmp_path / "release-plan.json").read_text())
    assert plan["format"] == 2 and plan["revision"] == "merged-main-sha"
    assert plan["runtimePublicConfig"] == release.runtime_public_config(prod_public())
    assert requests == [release.candidate_request(task(), IMAGE, prod_public())]
    assert checks == [{"check_dependencies": False}]
    assert not ecs.calls and ecs.live == OLD


def portable_execute(monkeypatch, tmp_path):
    ecs = ECS()
    session, path = setup_execute(monkeypatch, tmp_path, ecs)
    plan = json.loads(path.read_text())
    plan.update(format=2, runtimePublicConfig=release.runtime_public_config(prod_public()))
    path.write_text(json.dumps(plan))
    ecs.describe_task_definition = lambda taskDefinition, **kw: {"taskDefinition": task() if taskDefinition == OLD else release.candidate_request(task(), IMAGE, prod_public())}
    monkeypatch.setattr(release, "readiness", lambda session, **kw: (service(), {}, task(), prod_public()))
    import io
    config = {"oidcAuthority": parameters()["JwtIssuer"], "oidcClientId": parameters()["JwtAudience"],
              "appUrl": release.APP_URL, "migrationUiPreview": False}
    class Response(io.BytesIO):
        status = 200
    monkeypatch.setattr(release.urllib.request, "urlopen", lambda *args, **kw: Response(json.dumps(config).encode()))
    return ecs, session, path


def test_portable_execute_verifies_prod_runtime_and_updates_only_frontend(monkeypatch, tmp_path):
    ecs, session, path = portable_execute(monkeypatch, tmp_path)
    release.execute(session, path)
    assert ecs.calls == [{"cluster": release.CLUSTER, "service": release.SERVICE, "taskDefinition": NEW}]


def test_portable_execute_refuses_stale_public_config_before_service_update(monkeypatch, tmp_path):
    ecs, session, path = portable_execute(monkeypatch, tmp_path)
    plan = json.loads(path.read_text())
    plan["runtimePublicConfig"]["NAVIGAN_PUBLIC_OIDC_CLIENT_ID"] = "other"
    path.write_text(json.dumps(plan))
    with pytest.raises(RuntimeError, match="settings changed"):
        release.execute(session, path)
    assert not ecs.calls


@pytest.mark.parametrize("verification_failure", [False, True])
def test_portable_build_tests_one_image_before_publishing(monkeypatch, tmp_path, verification_failure):
    import tarfile
    import io
    calls = []
    def call(command, **kw):
        calls.append(command)
        if verification_failure and "--image" in command:
            raise RuntimeError("Portability check failed")
        if command[:2] == ["git", "archive"]:
            with tarfile.open(command[command.index("--output") + 1], "w") as archive:
                data = b"export const portable=true;"
                info = tarfile.TarInfo("frontend/src/shared/config/public-config.ts")
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
    monkeypatch.setattr(release.subprocess, "check_call", call)
    monkeypatch.setattr(release.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0))
    auth = release.base64.b64encode(b"AWS:fixture-password").decode()
    ecr = SimpleNamespace(get_authorization_token=lambda **kw: {"authorizationData": [{"proxyEndpoint": "https://" + release.REGISTRY, "authorizationToken": auth}]},
        describe_images=lambda **kw: {"imageDetails": [{"imageDigest": DIGEST}]})
    monkeypatch.setattr(release, "runtime_digests", lambda *a: [DIGEST])
    if verification_failure:
        with pytest.raises(RuntimeError, match="Portability check failed"):
            release.build_image(SimpleNamespace(client=lambda name: ecr), tmp_path, "a" * 40, prod_public())
        assert not any(command[:2] == ["docker", "push"] for command in calls)
        return
    image, _ = release.build_image(SimpleNamespace(client=lambda name: ecr), tmp_path, "a" * 40, prod_public())
    build = next(command for command in calls if command[:3] == ["docker", "buildx", "build"])
    assert "--build-arg" not in build
    verification = next(i for i, command in enumerate(calls) if "--image" in command)
    push = next(i for i, command in enumerate(calls) if command[:2] == ["docker", "push"])
    assert verification < push and image == IMAGE


def test_portable_checkout_requires_published_main(monkeypatch):
    monkeypatch.setattr(release, "portable_source", lambda: True)
    def output(command, **kw):
        if command[1] == "branch": return "feature/ui-migration-enhancements\n"
        return "a" * 40
    monkeypatch.setattr(release.subprocess, "check_output", output)
    with pytest.raises(RuntimeError, match="from main"):
        release.check_checkout()


def test_portable_rejects_public_setting_secret_binding_changes():
    before = task()
    before["containerDefinitions"][0]["secrets"] = [{"name": "NAVIGAN_PUBLIC_OIDC_CLIENT_ID", "valueFrom": "arn:retained-secret"}]
    with pytest.raises(RuntimeError, match="ECS secrets"):
        release.candidate_request(before, IMAGE, prod_public())


def test_portable_execute_reports_incorrect_deployed_runtime(monkeypatch, tmp_path):
    ecs, session, path = portable_execute(monkeypatch, tmp_path)
    import io
    class Response(io.BytesIO):
        status = 200
    monkeypatch.setattr(release.urllib.request, "urlopen", lambda *a, **kw: Response(b'{"oidcClientId":"dev-client"}'))
    with pytest.raises(RuntimeError, match="runtime settings differ"):
        release.execute(session, path)
    assert ecs.live == NEW  # A post-rollout failure is never reported as successful.
