from copy import deepcopy
from unittest.mock import MagicMock

import pytest
import yaml

from navigan.modules.cluster_management.utility_gitops import headlamp_preflight, HEADLAMP_PATH
from navigan.shared.errors import ApiError
from test_utility_upgrades import service


def test_preflight_reads_only_registered_repository_and_branch():
    plans, repo = service()
    github = plans.github
    evidence = headlamp_preflight(repo.system_repository_access.return_value, "0.45.0", github)
    assert evidence["currentVersion"] == "0.45.0"
    github.read_repository_file.assert_called_once_with(
        123, "customer-org", "cluster-system", HEADLAMP_PATH, branch="main"
    )
    assert [call[0] for call in github.mock_calls] == ["read_repository_file"]


@pytest.mark.parametrize(
    "mutation", ["version", "chart", "source", "values", "branch", "destination", "duplicate", "malformed"]
)
def test_unexpected_manifest_blocks_draft_without_persistence(mutation):
    plans, repo = service()
    manifest = yaml.safe_load(plans.github.read_repository_file.return_value)
    if mutation == "version":
        manifest["spec"]["sources"][0]["targetRevision"] = "0.44.0"
    if mutation == "chart":
        manifest["spec"]["sources"][0]["chart"] = "other"
    if mutation == "source":
        manifest["spec"]["sources"][0]["repoURL"] = "https://untrusted.invalid/chart"
    if mutation == "values":
        manifest["spec"]["sources"][1]["repoURL"] = "https://github.com/other/repo"
    if mutation == "branch":
        manifest["spec"]["sources"][1]["targetRevision"] = "unreviewed"
    if mutation == "destination":
        manifest["spec"]["destination"]["namespace"] = "other"
    if mutation == "duplicate":
        manifest["spec"]["sources"].append(deepcopy(manifest["spec"]["sources"][0]))
    plans.github.read_repository_file.return_value = (
        "not: [yaml" if mutation == "malformed" else yaml.safe_dump(manifest)
    )
    plans._save = MagicMock()
    with pytest.raises(ApiError) as error:
        plans.create(
            "CLU-live",
            {"utilityCode": "headlamp", "targetVersion": "0.46.0", "changeReason": "Upgrade dashboard chart"},
        )
    assert error.value.code == (
        "UTILITY_GITOPS_VERSION_DRIFT" if mutation == "version" else "UTILITY_GITOPS_MANIFEST_INVALID"
    )
    plans._save.assert_not_called()


def test_repository_read_failure_does_not_create_plan():
    plans, _ = service()
    plans.github.read_repository_file.side_effect = ApiError(503, "GITHUB_API_UNAVAILABLE", "Unavailable")
    plans._save = MagicMock()
    with pytest.raises(ApiError):
        plans.create(
            "CLU-live",
            {"utilityCode": "headlamp", "targetVersion": "0.46.0", "changeReason": "Upgrade dashboard chart"},
        )
    plans._save.assert_not_called()
