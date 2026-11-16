from base64 import b64encode
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock
import hashlib

import pytest

from navigan.modules.cluster_management.utility_gitops import HeadlampGitOps, HEADLAMP_PATH
from navigan.modules.cluster_management.upgrade_plans import utcnow
from navigan.shared.errors import ApiError


def adapter():
    repository = {
        "organization_login": "example",
        "repository_name": "cluster-system",
        "installation_id": 1,
        "default_branch": "main",
        "repository_url": "https://github.com/example/cluster-system",
    }
    template = (
        Path(__file__).parents[1]
        / "src/navigan/modules/cluster_management/system_repo_template/applications/30-headlamp.yaml"
    ).read_text()
    manifest = template.replace("__SYSTEM_REPO_URL__", repository["repository_url"]).replace(
        "__SYSTEM_REPO_REVISION__", "main"
    )
    github = MagicMock()
    github.repository_token.return_value = {"token": "fixture-token"}
    state = {"head": "base", "manifest": manifest, "values": "replicaCount: 2\n", "blob": None, "calls": []}

    def request(method, path, token, body=None):
        state["calls"].append((method, path, body))
        if "/git/ref/heads/" in path:
            return {"object": {"sha": state["head"]}}
        if "/contents/" in path:
            content = state["manifest"] if HEADLAMP_PATH in path else state["values"]
            return {
                "type": "file",
                "encoding": "base64",
                "content": b64encode(content.encode()).decode(),
                "sha": hashlib.sha1(content.encode()).hexdigest(),
                "size": len(content),
            }
        if method == "GET" and "/git/commits/" in path:
            return {"tree": {"sha": "base-tree"}}
        if path.endswith("/git/blobs"):
            state["blob"] = body["content"]
            return {"sha": "target-blob"}
        if path.endswith("/git/trees"):
            return {"sha": "target-tree"}
        if path.endswith("/git/commits"):
            return {"sha": "prepared-commit"}
        if method == "PATCH":
            assert body["force"] is False
            if state["head"] != "base":
                raise ApiError(409, "GITHUB_API_REQUEST_FAILED", "Non-fast-forward")
            state["head"] = body["sha"]
            state["manifest"] = state["blob"]
            return {"object": {"sha": state["head"]}}
        if "/compare/" in path:
            return {"status": "ahead"}
        raise AssertionError((method, path))

    github._request.side_effect = request
    result = HeadlampGitOps(repository, github)
    result.artifact = lambda: {
        "chartVersion": "0.46.0",
        "applicationVersion": "0.46.0",
        "sha256": result.ARTIFACT_SHA,
    }
    return result, state


def test_preparation_changes_only_chart_scalar_and_never_updates_ref():
    tool, state = adapter()
    original = state["manifest"]
    policy = tool.evidence("0.45.0", "0.46.0")
    intent = tool.prepare(policy, "0.46.0", "plan:4")
    assert state["head"] == "base"
    assert not any(method == "PATCH" for method, _, _ in state["calls"])
    assert state["blob"] == original.replace("targetRevision: 0.45.0", 'targetRevision: "0.46.0"', 1)
    tree = next(body for _, path, body in state["calls"] if path.endswith("/git/trees"))
    assert tree == {
        "base_tree": "base-tree",
        "tree": [{"path": HEADLAMP_PATH, "mode": "100644", "type": "blob", "sha": "target-blob"}],
    }
    assert tool.publication_state(policy, intent) == "UNPUBLISHED"
    tool.publish(intent, utcnow() + timedelta(hours=1))
    assert tool.publication_state(policy, intent) == "PUBLISHED"
    assert len([1 for method, _, _ in state["calls"] if method == "PATCH"]) == 1


@pytest.mark.parametrize("change", ["manifest", "values", "head"])
def test_reviewed_repository_drift_blocks_preparation(change):
    tool, state = adapter()
    policy = tool.evidence("0.45.0", "0.46.0")
    state[change] += "\n# changed" if change != "head" else "other"
    with pytest.raises(ApiError):
        tool.prepare(policy, "0.46.0", "plan:4")
    assert not any(method == "POST" for method, _, _ in state["calls"])


def test_concurrent_branch_update_cannot_be_overwritten():
    tool, state = adapter()
    policy = tool.evidence("0.45.0", "0.46.0")
    intent = tool.prepare(policy, "0.46.0", "plan:4")
    assert tool.publication_state(policy, intent) == "UNPUBLISHED"
    state["head"] = "concurrent-commit"
    with pytest.raises(ApiError):
        tool.publish(intent, utcnow() + timedelta(hours=1))
    assert state["head"] == "concurrent-commit"


@pytest.mark.parametrize(
    "values", ["image: {tag: v0.45.0}", "image: {repository: custom/image}", "[invalid, mapping]"]
)
def test_image_overrides_cannot_silently_keep_the_old_image(values):
    tool, state = adapter()
    state["values"] = values
    with pytest.raises(ApiError):
        tool.evidence("0.45.0", "0.46.0")


def test_publication_too_close_to_deadline_makes_no_write():
    tool, state = adapter()
    with pytest.raises(ApiError):
        tool.publish({"commit": "prepared"}, utcnow() + timedelta(seconds=5))
    assert state["calls"] == []


def test_non_descendant_or_modified_target_is_not_accepted_as_publication():
    tool, state = adapter()
    policy = tool.evidence("0.45.0", "0.46.0")
    intent = tool.prepare(policy, "0.46.0", "plan:4")
    state["head"] = "other-commit"
    with pytest.raises(ApiError):
        tool.publication_state(policy, intent)


def test_chart_checksum_failure_blocks_without_extracting(monkeypatch):
    import urllib.request

    response = MagicMock()
    response.__enter__.return_value.read.return_value = b"unreviewed chart"
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: response)
    with pytest.raises(ApiError) as error:
        HeadlampGitOps.artifact()
    assert error.value.code == "UTILITY_ARTIFACT_UNVERIFIED"
