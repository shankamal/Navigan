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
        assert package.read(prefix + "utility_upgrades.py") == (ROOT / "src" / prefix / "utility_upgrades.py").read_bytes()
        assert package.read(prefix + "upgrade_paths.py") == (ROOT / "src" / prefix / "upgrade_paths.py").read_bytes()
        assert package.read(prefix + "upgrade_actors.py") == (ROOT / "src" / prefix / "upgrade_actors.py").read_bytes()
        assert package.read(prefix + "models.py") == live_models
        assert package.read(prefix + "upgrade_readiness.py") == (ROOT / "src" / prefix / "upgrade_readiness.py").read_bytes()
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


def test_release_updates_reviewed_installed_plans_without_duplicate_members(tmp_path):
    release = load_release()
    prefix = "navigan/modules/cluster_management/"
    source, target = tmp_path / "old.zip", tmp_path / "new.zip"
    with zipfile.ZipFile(source, "w") as package:
        package.writestr(prefix + "handler.py", release.scoped_handler_target(
            baseline(release.DEPLOYED_PLAN_TREE, "src/" + prefix + "handler.py")))
        package.writestr(prefix + "upgrade_readiness.py", baseline(
            release.DEPLOYED_PLAN_TREE, "src/" + prefix + "upgrade_readiness.py"))
        package.writestr(prefix + "upgrade_plans.py", baseline(
            release.DEPLOYED_PLAN_TREE, "src/" + prefix + "upgrade_plans.py"))
    release.package(source, target)
    with zipfile.ZipFile(target) as package:
        assert package.namelist().count(prefix + "upgrade_plans.py") == 1
        assert package.read(prefix + "upgrade_plans.py") == (ROOT / "src" / prefix / "upgrade_plans.py").read_bytes()


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


def test_production_baseline_includes_both_rescheduling_handler_fixes():
    release = load_release()
    handler = release.scoped_handler_target(baseline(
        release.DEPLOYED_PLAN_TREE, "src/navigan/modules/cluster_management/handler.py"
    ))
    source = handler.decode()
    assert '"refresh", "reschedule"}' in source
    assert 'if (create_upgrade_plan or upgrade_plan_action) and body.get("scheduledFor")' in source
    plans = baseline(release.DEPLOYED_PLAN_TREE, "src/navigan/modules/cluster_management/upgrade_plans.py").decode()
    assert 'if action == "reschedule":' in plans
    assert 'MAINTENANCE_SCHEDULE_OVERDUE' in plans


def test_release_rejects_drift_even_when_rescheduling_is_present(tmp_path):
    import pytest
    release = load_release()
    prefix = "navigan/modules/cluster_management/"
    handler = release.scoped_handler_target(baseline(release.DEPLOYED_PLAN_TREE, "src/" + prefix + "handler.py"))
    # A recognized route does not permit unrelated behavior changes.
    handler = handler.replace(b're.fullmatch(r"UPG-[a-f0-9]{32}", parts[2] or "")', b'True')
    source = tmp_path / "drift.zip"
    with zipfile.ZipFile(source, "w") as package:
        package.writestr(prefix + "handler.py", handler)
        package.writestr(prefix + "upgrade_readiness.py", baseline(release.DEPLOYED_PLAN_TREE, "src/" + prefix + "upgrade_readiness.py"))
        package.writestr(prefix + "upgrade_plans.py", baseline(release.DEPLOYED_PLAN_TREE, "src/" + prefix + "upgrade_plans.py"))
    with pytest.raises(RuntimeError, match="Deployed handler differs"):
        release.package(source, tmp_path / "rejected.zip")


def test_release_requires_path_schema_and_scoped_execution_privilege():
    from unittest.mock import MagicMock
    import pytest
    release=load_release()
    session=MagicMock()
    session.client.return_value.describe_db_clusters.return_value={"DBClusters":[{"DBClusterArn":"cluster"}]}
    parent={"Parameters":[{"ParameterKey":"DatabaseName","ParameterValue":"navigan"},{"ParameterKey":"ApiDatabaseSecretArn","ParameterValue":"secret"}]}
    session.client.return_value.execute_statement.return_value={"formattedRecords":json.dumps([{"table_name":"table","runtime_grants":True,"utility_table":"utility","utility_grants":True,"planning_privilege":True}])}
    with pytest.raises(RuntimeError,match="029–033"):
        release.verify_database(session,parent)
    session.client.return_value.execute_statement.return_value={"formattedRecords":json.dumps([{"table_name":"table","runtime_grants":True,"utility_table":"utility","utility_grants":True,"planning_privilege":True,"path_column":True,"execution_privilege":True}])}
    release.verify_database(session,parent)


def test_assembled_production_package_serves_options_with_real_discovery(tmp_path):
    """Catch dependency mismatches hidden by a mocked Discovery service."""
    import runpy
    from unittest.mock import MagicMock
    from navigan.modules.cluster_management.upgrade_paths import ScopedEksUpgradePlans
    from navigan.shared.access import EffectiveAccess, Scope
    release=load_release()
    prefix="navigan/modules/cluster_management/"
    source,target=tmp_path/"production.zip",tmp_path/"updated.zip"
    deployed_discovery=baseline(release.DEPLOYED_PLAN_TREE,"src/"+prefix+"upgrade_readiness.py")
    assert "def client(" in deployed_discovery.decode()
    with zipfile.ZipFile(source,"w") as archive:
        archive.writestr(prefix+"handler.py",release.scoped_handler_target(baseline(release.DEPLOYED_PLAN_TREE,"src/"+prefix+"handler.py")))
        archive.writestr(prefix+"upgrade_readiness.py",deployed_discovery)
        for module in ["upgrade_plans.py","utility_upgrades.py","upgrade_paths.py"]:
            archive.writestr(prefix+module,baseline(release.DEPLOYED_PLAN_TREE,"src/"+prefix+module))
        archive.writestr(prefix+"__pycache__/upgrade_readiness.cpython-312.pyc",b"stale cached module")
    release.package(source,target)
    with zipfile.ZipFile(target) as archive:
        assert not any("upgrade_readiness." in n and n.endswith(".pyc") for n in archive.namelist())
        namespace={"__name__":"packaged_discovery"}
        exec(compile(archive.read(prefix+"upgrade_readiness.py"),"packaged_discovery","exec"),namespace)
    fixtures=runpy.run_path(str(ROOT/"tests/test_eks_upgrade_readiness.py"))
    eks=fixtures["eks_client"]();sts=MagicMock();secrets=MagicMock()
    sts.assume_role.return_value={"Credentials":{"AccessKeyId":"test","SecretAccessKey":"test","SessionToken":"test"}}
    secrets.get_secret_value.return_value={"SecretString":"test-external-id"}
    discovery=namespace["EksUpgradeDiscovery"](sts,secrets,lambda *args,**kwargs:eks)
    repo=MagicMock();repo.get.return_value=fixtures["managed_cluster"]()
    repo.pinned_environment_snapshot.return_value=({},fixtures["environment"]())
    access=EffectiveAccess("engineer","Engineer",0,frozenset({"cluster.upgrade.plan"}),(Scope("PLATFORM"),))
    result=ScopedEksUpgradePlans(repo,access,"test",discovery).options("CLU-test")
    assert result["currentVersion"]=="1.33" and result["targetVersions"]==["1.34","1.35"]
    assert result["nodeGroups"][0]["name"]=="system"
    assert result["addons"][0]["name"]=="coredns"
    eks.update_cluster_version.assert_not_called()
    eks.update_nodegroup_version.assert_not_called()
    eks.update_addon.assert_not_called()
