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


@pytest.mark.parametrize("platform_failure", [False, True])
def test_mirror_pushes_inspected_image_id_and_verifies_ecr_without_exposing_password(capsys, platform_failure):
    import base64

    calls = []
    image_id = "sha256:" + "a" * 64
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
        if "--raw" in command:
            return json.dumps({"manifests": [{"digest": digest, "platform": {"os": "linux", "architecture": "amd64"}}]})
        if "inspect" in command:
            return json.dumps(
                {"Id": image_id, "Architecture": "amd64", "Os": "linux", "RepoDigests": ["python@" + digest]}
            )
        if "login" in command:
            assert "secret-ecr-token" not in command and input == "secret-ecr-token\n"
        if "push" in command:
            push_attempts += 1
            if platform_failure and push_attempts == 1:
                raise mirror.CommandError("image with reference target was found but does not provide any platform")
            pushed = True
        return ""

    result = mirror.mirror(aws, ["docker.io/library/python:3.12-alpine"], docker=docker)
    tag_call = next(c for c, _ in docker_calls if "tag" in c)
    assert tag_call[2] == image_id
    assert push_attempts == (2 if platform_failure else 1)
    if platform_failure:
        assert ["docker", "tag", "docker.io/library/python@" + digest, result[0]["destination"]] in [c for c, _ in docker_calls]
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


def test_platform_recovery_pulls_child_digest_and_tags_pinned_reference(capsys):
    config_id = "sha256:" + "a" * 64
    child_digest = "sha256:" + "b" * 64
    source = "docker.io/library/python:3.12-alpine"
    target = mirror.REGISTRY + "/retailflow/docker.io/library/python:test"
    calls = []

    def docker(command):
        calls.append(command)
        if "--raw" in command:
            return json.dumps({"manifests": [
                {"digest": child_digest, "platform": {"os": "linux", "architecture": "amd64"}},
                {"digest": "sha256:" + "c" * 64, "platform": {"os": "linux", "architecture": "arm64"}},
            ]})
        if "inspect" in command:
            return json.dumps({"Id": config_id, "Os": "linux", "Architecture": "amd64"})
        return ""

    mirror.recover_platform_push(docker, source, {"Id": config_id}, target)
    pinned = "docker.io/library/python@" + child_digest
    assert ["docker", "pull", pinned] in calls
    assert ["docker", "tag", pinned, target] in calls
    assert calls[-1] == ["docker", "push", target]
    assert not any("prune" in command for command in calls)
    assert "Recovering Docker platform metadata" in capsys.readouterr().out


@pytest.mark.parametrize("mode", ["ambiguous", "missing", "digest", "architecture", "identity"])
def test_platform_recovery_fails_closed_for_unverified_images(mode):
    digest = "sha256:" + "b" * 64
    selected = {"digest": digest, "platform": {"os": "linux", "architecture": "amd64"}}
    pushed = []

    def docker(command):
        if "--raw" in command:
            entries = [selected, selected] if mode == "ambiguous" else [] if mode == "missing" else [selected]
            if mode == "digest":
                selected["digest"] = "invalid"
            return json.dumps({"manifests": entries})
        if "inspect" in command:
            return json.dumps({"Id": "changed" if mode == "identity" else "original", "Os": "linux", "Architecture": "arm64" if mode == "architecture" else "amd64"})
        if "push" in command:
            pushed.append(command)
        return ""

    with pytest.raises(ValueError):
        mirror.recover_platform_push(docker, "docker.io/library/python:3", {"Id": "original"}, "target")
    assert not pushed
