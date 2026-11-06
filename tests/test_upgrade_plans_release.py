import importlib.util
import json
from pathlib import Path
import subprocess
import zipfile


ROOT = Path(__file__).parents[1]


def load_release():
    path = ROOT / "scripts/deploy-eks-upgrade-plans-prod.py"
    spec = importlib.util.spec_from_file_location("upgrade_plans_release", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def baseline(tree, path):
    return subprocess.check_output(["git", "show", f"{tree}:{path}"], cwd=ROOT)


def test_execution_policy_is_limited_to_required_eks_resources():
    policy = json.loads((ROOT / "infrastructure/bootstrap/eks-upgrade-execution-policy.json").read_text())
    statements = {statement["Action"]: statement["Resource"] for statement in policy["Statement"]}

    assert statements == {
        "eks:UpdateClusterVersion": "arn:aws:eks:*:*:cluster/*",
        "eks:UpdateAddon": "arn:aws:eks:*:*:addon/*/*/*",
        "eks:UpdateNodegroupVersion": "arn:aws:eks:*:*:nodegroup/*/*/*",
    }
    assert all(resource != "*" for resource in statements.values())


def test_release_replaces_only_reviewed_cluster_modules(tmp_path):
    release = load_release()
    prefix = "navigan/modules/cluster_management/"
    paths = {
        "handler.py": "src/navigan/modules/cluster_management/handler.py",
        "models.py": "src/navigan/modules/cluster_management/models.py",
        "upgrade_readiness.py": "src/navigan/modules/cluster_management/upgrade_readiness.py",
    }
    source = tmp_path / "old.zip"
    target = tmp_path / "new.zip"
    with zipfile.ZipFile(source, "w") as package:
        for member, path in paths.items():
            package.writestr(prefix + member, baseline(release.BASELINE_TREE, path))
        package.writestr("navigan/shared/errors.py", "class ApiError(Exception): pass\n")

    release.package(source, target)

    with zipfile.ZipFile(target) as package:
        for member, path in paths.items():
            assert package.read(prefix + member) == (ROOT / path).read_bytes()
        assert (
            package.read(prefix + "upgrade_plans.py")
            == (ROOT / "src/navigan/modules/cluster_management/upgrade_plans.py").read_bytes()
        )
        assert package.read("navigan/shared/errors.py") == b"class ApiError(Exception): pass\n"


def test_release_accepts_exact_deployed_readiness_import_order(tmp_path):
    release = load_release()
    prefix = "navigan/modules/cluster_management/"
    paths = {
        "handler.py": "src/navigan/modules/cluster_management/handler.py",
        "models.py": "src/navigan/modules/cluster_management/models.py",
        "upgrade_readiness.py": "src/navigan/modules/cluster_management/upgrade_readiness.py",
    }
    source = tmp_path / "old.zip"
    target = tmp_path / "new.zip"
    handler = baseline(release.BASELINE_TREE, paths["handler.py"])
    repository_order = (
        b"from .bootstrap_status import refresh_installer_status\n"
        b"from .tool_access import resolve_tool_access\n"
        b"from .upgrade_readiness import EksUpgradeDiscovery\n"
    )
    deployed_order = (
        b"from .tool_access import resolve_tool_access\n"
        b"from .upgrade_readiness import EksUpgradeDiscovery\n"
        b"from .bootstrap_status import refresh_installer_status\n"
    )
    assert handler.count(repository_order) == 1
    with zipfile.ZipFile(source, "w") as package:
        package.writestr(prefix + "handler.py", handler.replace(repository_order, deployed_order, 1))
        for member in ("models.py", "upgrade_readiness.py"):
            package.writestr(prefix + member, baseline(release.BASELINE_TREE, paths[member]))

    release.package(source, target)

    with zipfile.ZipFile(target) as package:
        assert package.read(prefix + "handler.py") == (ROOT / paths["handler.py"]).read_bytes()


def test_release_rejects_an_unreviewed_live_handler(tmp_path):
    release = load_release()
    prefix = "navigan/modules/cluster_management/"
    source = tmp_path / "old.zip"
    with zipfile.ZipFile(source, "w") as package:
        package.writestr(prefix + "handler.py", "raise RuntimeError('unexpected')\n")
        for member in ("models.py", "upgrade_readiness.py"):
            path = f"src/navigan/modules/cluster_management/{member}"
            package.writestr(prefix + member, baseline(release.BASELINE_TREE, path))

    try:
        release.package(source, tmp_path / "new.zip")
    except RuntimeError as error:
        assert "reviewed production baseline" in str(error)
    else:
        raise AssertionError("Unreviewed deployed code was accepted")
