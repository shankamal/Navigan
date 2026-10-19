import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("mirror", ROOT / "scripts/mirror-retailflow-images-dev.py")
mirror = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mirror)


@pytest.mark.parametrize(
    "image,canonical,repository",
    [
        ("python:3.12-alpine", "docker.io/library/python:3.12-alpine", "retailflow/docker.io/library/python"),
        (
            "nginxinc/nginx-unprivileged:1.29-alpine",
            "docker.io/nginxinc/nginx-unprivileged:1.29-alpine",
            "retailflow/docker.io/nginxinc/nginx-unprivileged",
        ),
        (
            "registry.example.com:5000/team/api:v1",
            "registry.example.com:5000/team/api:v1",
            "retailflow/registry.example.com-5000/team/api",
        ),
    ],
)
def test_full_image_paths_are_discovered_not_assumed(image, canonical, repository):
    parsed = mirror.source_identity(image)
    assert parsed["source"] == canonical
    assert parsed["repository"] == repository


@pytest.mark.parametrize(
    "image",
    [
        "https://docker.io/python:3",
        "user:password@docker.io/python",
        "python:3\nmalicious",
        "python@sha256:bad",
    ],
)
def test_invalid_or_credentialed_references_are_rejected(image):
    with pytest.raises(ValueError):
        mirror.source_identity(image)


@pytest.mark.parametrize("scenario", ["copy", "existing", "wrong-platform", "wrong-digest", "copy-error"])
def test_registry_copy_verifies_platform_and_ecr_digest_without_daemon(capsys, scenario):
    import base64
    digest = "sha256:" + "b" * 64
    copied = scenario == "existing"
    docker_calls = []

    def aws(*args):
        if args[:2] == ("ecr", "get-authorization-token"):
            return {"authorizationData": [{"authorizationToken": base64.b64encode(b"AWS:secret-ecr-token").decode(), "proxyEndpoint": "https://" + mirror.REGISTRY}]}
        if args[:2] == ("ecr", "describe-repositories"):
            return {"repositories": [{"repositoryUri": mirror.REGISTRY + "/retailflow/docker.io/library/python"}]}
        if args[:2] == ("ecr", "describe-images"):
            if not copied:
                raise mirror.CommandError("ImageNotFoundException")
            return {"imageDetails": [{"imageDigest": "sha256:" + "c" * 64 if scenario == "wrong-digest" else digest}]}
        raise AssertionError(args)

    def docker(command, input=None):
        nonlocal copied
        docker_calls.append(command)
        if "{{json .Manifest}}" in command:
            return json.dumps({"manifests": [{"digest": digest, "platform": {"os": "linux", "architecture": "amd64"}}]})
        if "{{json .Image}}" in command:
            return json.dumps({"architecture": "arm64" if scenario == "wrong-platform" else "amd64", "os": "linux"})
        if "login" in command:
            assert input == "secret-ecr-token\n" and "secret-ecr-token" not in command
        if "create" in command:
            if scenario == "copy-error":
                raise mirror.CommandError("registry copy failed")
            copied = True
        return ""

    if scenario in {"wrong-platform", "wrong-digest", "copy-error"}:
        with pytest.raises((ValueError, mirror.CommandError)):
            mirror.mirror(aws, ["python:3.12-alpine"], docker=docker)
    else:
        result = mirror.mirror(aws, ["python:3.12-alpine"], docker=docker)
        pinned = "docker.io/library/python@" + digest
        assert result[0]["sourceResolvedReferences"] == [pinned]
        assert result[0]["destinationDigestReference"].endswith("@" + digest)
        if scenario == "copy":
            assert ["docker", "buildx", "imagetools", "create", "--prefer-index=false", "--tag", result[0]["destination"], pinned] in docker_calls
        else:
            assert not any("create" in command for command in docker_calls)
        assert "secret-ecr-token" not in json.dumps(result)
    assert not any(command[1] in {"pull", "push", "tag", "image", "version"} for command in docker_calls)
    assert "secret-ecr-token" not in capsys.readouterr().out


def test_registry_access_errors_do_not_trigger_repository_creation():
    operations = []

    def aws(*args):
        operations.append(args)
        raise mirror.CommandError("AccessDeniedException")

    with pytest.raises(mirror.CommandError, match="AccessDeniedException"):
        mirror.ensure_repository(aws, "retailflow/docker.io/library/python")
    assert len(operations) == 1


def test_discovery_does_not_print_pod_env_or_other_namespace_payload(monkeypatch, capsys):
    import subprocess

    payloads = [
        {
            "items": [
                {
                    "kind": "Deployment",
                    "spec": {
                        "template": {
                            "spec": {
                                "containers": [
                                    {
                                        "name": "api",
                                        "image": "python:3.12-alpine",
                                        "env": [{"name": "TOKEN", "value": "do-not-export"}],
                                    }
                                ],
                                "initContainers": [{"name": "init", "image": "busybox:1.37"}],
                            }
                        }
                    },
                },
                {
                    "kind": "CronJob",
                    "spec": {
                        "jobTemplate": {
                            "spec": {
                                "template": {"spec": {"containers": [{"image": "curlimages/curl:8.16.0"}]}}
                            }
                        }
                    },
                },
            ]
        },
        {"items": [{"status": {"nodeInfo": {"architecture": "amd64"}}}]},
    ]
    commands = []

    def output(command, **kwargs):
        commands.append(command)
        return json.dumps(payloads.pop(0))

    monkeypatch.setattr(subprocess, "check_output", output)
    exec(compile(mirror.DISCOVER, "discover.py", "exec"), {})
    result = capsys.readouterr().out
    assert "do-not-export" not in result
    assert json.loads(result)["images"] == ["busybox:1.37", "curlimages/curl:8.16.0", "python:3.12-alpine"]
    assert "retailflow" in commands[0]
    assert all("apply" not in c and "patch" not in c for c in commands)


@pytest.mark.parametrize("source", ["docker.io/library/python:3", "docker.io/library/python@sha256:" + "f" * 64])
def test_resolves_child_manifest_before_local_pull(source):
    child = "sha256:" + "b" * 64
    commands = []
    def docker(command):
        commands.append(command)
        return json.dumps({"manifests": [
            {"digest": "sha256:" + "c" * 64, "platform": {"os": "linux", "architecture": "arm64"}},
            {"digest": child, "platform": {"os": "linux", "architecture": "amd64"}},
        ]})
    assert mirror.platform_reference(docker, source) == "docker.io/library/python@" + child
    assert len(commands) == 1
    assert commands[0][-1] == source


@pytest.mark.parametrize("mode", ["ambiguous", "missing", "digest"])
def test_resolution_rejects_unverified_manifest(mode):
    selected = {"digest": "bad" if mode == "digest" else "sha256:" + "b" * 64, "platform": {"os": "linux", "architecture": "amd64"}}
    entries = [selected, selected] if mode == "ambiguous" else [] if mode == "missing" else [selected]
    with pytest.raises(ValueError):
        mirror.platform_reference(lambda command: json.dumps({"manifests": entries}), "docker.io/library/python:3")


def test_single_platform_manifest_is_pinned_by_registry_digest():
    digest = "sha256:" + "b" * 64
    assert mirror.platform_reference(lambda command: json.dumps({"digest": digest}), "docker.io/library/python:3") == "docker.io/library/python@" + digest
