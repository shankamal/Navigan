import ast
from pathlib import Path
import runpy
import zipfile
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
release = runpy.run_path(str(ROOT / "scripts/deploy-upgrade-role-compatibility-prod.py"))


def original_access():
    source = (ROOT / "src/navigan/shared/access.py").read_text()
    return source.replace('            "cluster.upgrade.plan",\n', "", 1)


def test_only_legacy_maker_catalogue_changes():
    original = original_access()
    patched = release["patch_access"](original)
    assert patched.count('"cluster.upgrade.plan"') == 1
    assert patched.replace('            "cluster.upgrade.plan",\n', "", 1) == original
    assert release["patch_access"](patched) == patched
    # No fallback grant is introduced in dynamic authorization evaluation.
    old_tree, new_tree = ast.parse(original), ast.parse(patched)
    old_evaluator = next(n for n in old_tree.body if isinstance(n, ast.ClassDef) and n.name == "AccessEvaluator")
    new_evaluator = next(n for n in new_tree.body if isinstance(n, ast.ClassDef) and n.name == "AccessEvaluator")
    assert ast.dump(old_evaluator) == ast.dump(new_evaluator)


def test_unrecognized_role_catalogue_stops_release():
    with pytest.raises(RuntimeError, match="role catalogue"):
        release["patch_access"]("OTHER_PRIVILEGES = {}\n")
    with pytest.raises(RuntimeError, match="maker role"):
        release["patch_access"](original_access().replace('"cluster.create"', '"different.create"'))


def test_package_preserves_existing_modules_and_assets(tmp_path):
    original = tmp_path / "original.zip"
    with zipfile.ZipFile(original, "w") as archive:
        archive.writestr(release["MEMBER"], original_access())
        archive.writestr("navigan/modules/cluster_management/handler.py", b"deployed handler, including reschedule")
        archive.writestr("existing-asset.txt", b"unchanged")
        archive.writestr("navigan/shared/__pycache__/access.cpython-312.pyc", b"stale")
    target = release["package"](original, tmp_path / "updated.zip")
    with zipfile.ZipFile(target) as archive:
        assert archive.read("existing-asset.txt") == b"unchanged"
        assert archive.read("navigan/modules/cluster_management/handler.py") == b"deployed handler, including reschedule"
        assert b'"cluster.upgrade.plan"' in archive.read(release["MEMBER"])
        assert not any(name.endswith(".pyc") for name in archive.namelist())


def test_duplicate_package_members_rejected(tmp_path):
    original = tmp_path / "original.zip"
    with zipfile.ZipFile(original, "w") as archive:
        archive.writestr(release["MEMBER"], original_access())
        with pytest.warns(UserWarning):
            archive.writestr(release["MEMBER"], original_access())
    with pytest.raises(RuntimeError, match="Invalid Lambda archive"):
        release["package"](original, tmp_path / "updated.zip")


def change_set_client(resource_change):
    client = MagicMock()
    client.describe_change_set.side_effect = [
        {"Status": "CREATE_COMPLETE", "Changes": [{"ResourceChange": {
            "LogicalResourceId": "AccessManagement", "Action": "Modify", "Replacement": "False",
            "ResourceType": "AWS::CloudFormation::Stack", "ChangeSetId": "child"}}]},
        {"Status": "CREATE_COMPLETE", "Changes": [{"ResourceChange": resource_change}]},
    ]
    return client


def test_change_set_rejects_unrelated_iam_changes():
    client = change_set_client({"LogicalResourceId": "AccessFunctionRole", "Action": "Modify",
        "Replacement": "False", "ResourceType": "AWS::IAM::Role"})
    plan = {"releases": {"AccessManagement": {"before": {"Resources": {}}}}}
    with pytest.raises(RuntimeError, match="Unrelated nested change"):
        release["inspect"](client, "root", plan)


def test_change_set_accepts_scoped_function_update():
    client = change_set_client({"LogicalResourceId": "AccessFunction", "Action": "Modify",
        "Replacement": "False", "ResourceType": "AWS::Lambda::Function"})
    release["inspect"](client, "root", {"releases": {"AccessManagement": {"before": {"Resources": {}}}}})
