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


def test_release_preserves_live_modules_and_adds_only_scoped_plan_code(tmp_path):
    release = load_release()
    prefix = "navigan/modules/cluster_management/"
    handler_path = "src/navigan/modules/cluster_management/handler.py"
    readiness_path = "src/navigan/modules/cluster_management/upgrade_readiness.py"
    source = tmp_path / "old.zip"
    target = tmp_path / "new.zip"
    live_handler = release.deployed_handler_baseline(
        baseline(release.BASELINE_TREE, handler_path)
    )
    live_readiness = baseline(release.BASELINE_TREE, readiness_path)
    live_models = b"# live models remain untouched\n"
    with zipfile.ZipFile(source, "w") as package:
        package.writestr(prefix + "handler.py", live_handler)
        package.writestr(prefix + "models.py", live_models)
        package.writestr(prefix + "upgrade_readiness.py", live_readiness)
        package.writestr("navigan/shared/errors.py", "class ApiError(Exception): pass\n")

    release.package(source, target)

    with zipfile.ZipFile(target) as package:
        scoped_handler = release.scoped_handler_target(
            (ROOT / handler_path).read_bytes()
        )
        assert package.read(prefix + "handler.py") == scoped_handler
        normalized = release.semantic(scoped_handler)
        assert "upgrade_connector" not in normalized
        assert "ConnectorUpgradeRequest" not in normalized
        assert "EksUpgradePlans" in normalized
        assert package.read(prefix + "models.py") == live_models
        assert package.read(prefix + "upgrade_readiness.py") == live_readiness
        assert (
            package.read(prefix + "upgrade_plans.py")
            == (ROOT / "src/navigan/modules/cluster_management/upgrade_plans.py").read_bytes()
        )
        assert package.read("navigan/shared/errors.py") == b"class ApiError(Exception): pass\n"


def test_deployed_baseline_matches_observed_production_semantics():
    release = load_release()
    handler = release.deployed_handler_baseline(
        baseline(release.BASELINE_TREE, "src/navigan/modules/cluster_management/handler.py")
    )
    normalized = release.semantic(handler)

    assert "ConnectorUpgradeRequest" not in normalized
    assert "upgrade_connector" not in normalized
    assert "EksUpgradeDiscovery" in normalized
    assert "summary" in normalized


def test_release_rejects_an_unreviewed_live_handler(tmp_path):
    release = load_release()
    prefix = "navigan/modules/cluster_management/"
    source = tmp_path / "old.zip"
    with zipfile.ZipFile(source, "w") as package:
        package.writestr(prefix + "handler.py", "raise RuntimeError('unexpected')\n")
        package.writestr(
            prefix + "upgrade_readiness.py",
            baseline(
                release.BASELINE_TREE,
                "src/navigan/modules/cluster_management/upgrade_readiness.py",
            ),
        )

    try:
        release.package(source, tmp_path / "new.zip")
    except RuntimeError as error:
        assert "reviewed production baseline" in str(error)
    else:
        raise AssertionError("Unreviewed deployed code was accepted")
