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


@pytest.mark.parametrize("local_id", ["config", "manifest", "wrong-platform"])
def test_mirror_pushes_pinned_manifest_and_verifies_ecr_without_exposing_password(capsys, local_id):
    import base64

    calls = []
    image_id = "sha256:" + ("a" if local_id == "config" else "d") * 64
    digest = "sha256:" + "b" * 64
    pushed = False
    push_attempts = 0

    def aws(*args):
        calls.append(args)
        if args[:2] == ("ecr", "get-authorization-token"):
            return {
                "authorizationData": [
                    {
                        "authorizationToken": base64.b64encode(b"AWS:secret-ecr-token").decode(),
                        "proxyEndpoint": "https://" + mirror.REGISTRY,
                    }
                ]
            }
        if args[:2] == ("ecr", "describe-repositories"):
            raise mirror.CommandError("RepositoryNotFoundException")
        if args[:2] == ("ecr", "create-repository"):
            assert "IMMUTABLE" in args
            return {"repository": {"repositoryUri": mirror.REGISTRY + "/retailflow/docker.io/library/python"}}
        if args[:2] == ("ecr", "describe-images"):
            if not pushed:
                raise mirror.CommandError("ImageNotFoundException")
            return {"imageDetails": [{"imageDigest": digest}]}
        raise AssertionError(args)

    docker_calls = []

    def docker(command, input=None):
        nonlocal pushed, push_attempts
        docker_calls.append((command, input))
        if "imagetools" in command:
            return json.dumps({"digest": "sha256:" + "e" * 64, "manifests": [{"digest": digest, "platform": {"os": "linux", "architecture": "amd64"}}]})
        if "inspect" in command:
            return json.dumps(
                {"Id": image_id, "Architecture": "arm64" if local_id == "wrong-platform" else "amd64", "Os": "linux", "RepoDigests": ["python@" + digest]}
            )
        if "login" in command:
            assert "secret-ecr-token" not in command and input == "secret-ecr-token\n"
        if "push" in command:
            push_attempts += 1
            pushed = True
        return ""

    if local_id == "wrong-platform":
        with pytest.raises(ValueError, match="platform does not match"):
            mirror.mirror(aws, ["docker.io/library/python:3.12-alpine"], docker=docker)
        assert not any("push" in command for command, _ in docker_calls)
        return
    result = mirror.mirror(aws, ["docker.io/library/python:3.12-alpine"], docker=docker)
    tag_call = next(c for c, _ in docker_calls if "tag" in c)
    pinned = "docker.io/library/python@" + digest
    assert tag_call[2] == pinned
    assert ["docker", "pull", pinned] in [c for c, _ in docker_calls]
    assert all("--platform" not in c for c, _ in docker_calls)
    assert result[0]["sourceResolvedReferences"] == [pinned]
    assert push_attempts == 1
    assert result[0]["destinationDigestReference"].endswith("@" + digest)
    assert result[0]["destination"].startswith(mirror.REGISTRY + "/retailflow/docker.io/library/python:")
    assert "secret-ecr-token" not in capsys.readouterr().out
    assert "secret-ecr-token" not in json.dumps(result)
    assert all(c[0] == "docker" for c, _ in docker_calls)


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
