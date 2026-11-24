from base64 import b64decode
from hashlib import sha1
from unittest.mock import Mock

import pytest
import yaml

from navigan.modules.cluster_management.github_app import GitHubApp
from navigan.modules.cluster_management.system_repository import (
    EBS_STORAGE_APPLICATION,
    EBS_STORAGE_DIRECTORY,
    render_ebs_storage,
)
from navigan.shared.errors import ApiError


def blob_sha(data):
    return sha1(f"blob {len(data)}\0".encode() + data, usedforsecurity=False).hexdigest()


@pytest.fixture
def gitops_review():
    def review(tenant, *, existing=None, head=None, compare=None, race=False):
        repository = {
            "organization_login": tenant,
            "repository_name": "customer-eks-system",
            "repository_url": f"https://github.com/{tenant}/customer-eks-system",
            "default_branch": "platform",
            "installation_id": 123,
        }
        files = render_ebs_storage(repository["repository_url"], repository["default_branch"])
        path = f"/repos/{tenant}/customer-eks-system"
        ref = f"{path}/git/ref/heads/navigan/ebs-csi-storage"
        app = GitHubApp(secrets_client=Mock())
        app.repository_token = Mock(return_value={"token": "repo-token"})
        reference_reads = 0

        def request(method, endpoint, token, body=None):
            nonlocal reference_reads
            assert token == "repo-token"
            if endpoint == f"{path}/git/ref/heads/platform":
                return {"object": {"sha": "base"}}
            if endpoint == f"{path}/git/commits/base":
                return {"tree": {"sha": "base-tree"}}
            if endpoint == f"{path}/git/trees/base-tree?recursive=1":
                return {"tree": existing or []}
            if endpoint == ref:
                reference_reads += 1
                if head or (race and reference_reads == 2):
                    return {"object": {"sha": head or "concurrent"}}
                raise ApiError(404, "NOT_FOUND", "Missing review branch.")
            if endpoint == f"{path}/git/blobs" and method == "POST":
                return {"sha": blob_sha(b64decode(body["content"]))}
            if endpoint == f"{path}/git/trees" and method == "POST":
                assert body["base_tree"] == "base-tree"
                assert {entry["path"] for entry in body["tree"]} == set(files)
                return {"sha": "review-tree"}
            if endpoint == f"{path}/git/commits" and method == "POST":
                assert body["parents"] == ["base"]
                assert body["tree"] == "review-tree"
                return {"sha": "review-commit"}
            if endpoint == f"{path}/git/refs" and method == "POST":
                assert body == {"ref": "refs/heads/navigan/ebs-csi-storage", "sha": "review-commit"}
                if race:
                    raise ApiError(422, "REFERENCE_EXISTS", "Review branch already exists.")
                return {}
            if endpoint == f"{path}/compare/base...{head or ('concurrent' if race else 'review-commit')}":
                return compare or {
                    "total_commits": 1,
                    "files": [
                        {"filename": name, "status": "added", "sha": blob_sha(content.encode())}
                        for name, content in files.items()
                    ],
                }
            raise AssertionError((method, endpoint))

        app._request = Mock(side_effect=request)
        return app, repository, files

    return review


def prepare(app, repository, files):
    return app.prepare_storage_review(
        repository,
        files,
        application_path=EBS_STORAGE_APPLICATION,
        storage_directory=EBS_STORAGE_DIRECTORY,
    )


@pytest.mark.parametrize(("tenant", "race"), [("customer-one", False), ("customer-two", True)])
def test_review_uses_only_the_registered_repository_and_review_ref(gitops_review, tenant, race):
    app, repository, files = gitops_review(tenant, race=race)
    result = prepare(app, repository, files)
    assert result["status"] == "REVIEW_READY"
    assert result["reviewUrl"] == (
        f"https://github.com/{tenant}/customer-eks-system/compare/platform...navigan/ebs-csi-storage?expand=1"
    )
    assert yaml.safe_load(files[EBS_STORAGE_APPLICATION])["spec"]["source"] == {
        "repoURL": repository["repository_url"], "targetRevision": "platform", "path": "storage-classes",
    }
    app.repository_token.assert_called_once_with(123, "customer-eks-system", write=True)
    assert "PATCH" not in {call.args[0] for call in app._request.call_args_list}


def test_matching_manifests_need_no_review_branch(gitops_review):
    _, _, files = gitops_review("customer-one")
    entries = [
        {"path": path, "mode": "100644", "sha": blob_sha(content.encode())}
        for path, content in files.items()
    ]
    app, repository, files = gitops_review("customer-one", existing=entries)
    assert prepare(app, repository, files) == {"status": "MANIFESTS_PRESENT", "baseBranch": "platform"}
    assert {call.args[0] for call in app._request.call_args_list} == {"GET"}


def test_retries_reuse_the_review_branch_and_reject_unrelated_changes(gitops_review):
    app, repository, files = gitops_review("customer-one", head="existing")
    assert prepare(app, repository, files)["status"] == "REVIEW_READY"
    assert {call.args[0] for call in app._request.call_args_list} == {"GET"}

    app, repository, files = gitops_review(
        "customer-one",
        head="existing",
        compare={"total_commits": 1, "files": [{"filename": "applications/unrelated.yaml"}]},
    )
    with pytest.raises(ApiError, match="different storage manifests") as caught:
        prepare(app, repository, files)
    assert caught.value.code == "EBS_CSI_GITOPS_CONFLICT"
    assert {call.args[0] for call in app._request.call_args_list} == {"GET"}


@pytest.mark.parametrize("filename", ["storage-classes/ebs-gp3.yaml", "storage-classes/another-class.yaml"])
def test_existing_storage_customizations_are_preserved(gitops_review, filename):
    app, repository, files = gitops_review(
        "customer-one", existing=[{"path": filename, "mode": "100644", "sha": "custom"}],
    )
    with pytest.raises(ApiError) as caught:
        prepare(app, repository, files)
    assert caught.value.code == "EBS_CSI_GITOPS_CONFLICT"
    assert {call.args[0] for call in app._request.call_args_list} == {"GET"}
