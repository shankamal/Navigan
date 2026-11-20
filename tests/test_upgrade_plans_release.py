import importlib.util
import ast
import json
from pathlib import Path
import subprocess
import zipfile
import pytest


ROOT = Path(__file__).parents[1]


def load_release():
    path = ROOT / "scripts/deploy-eks-upgrade-plans-prod.py"
    spec = importlib.util.spec_from_file_location("upgrade_plans_release", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def baseline(tree, path):
    return subprocess.check_output(["git", "show", f"{tree}:{path}"], cwd=ROOT)


def test_release_guard_is_pinned_to_last_confirmed_deployed_backend():
    release = load_release()
    assert (
        release.DEPLOYED_PLAN_TREE
        == "a8d572439b8f5097a48a86c442955afafd19f097"
    )


def test_node_group_retry_release_preserves_live_service_and_dependencies(tmp_path, monkeypatch):
    release = load_release()
    module = release.CLUSTER_SERVICE
    service_path = "src/" + module
    original_service = baseline(release.NODE_GROUP_RETRY_BASELINE, service_path)
    deployed_service = original_service + b"\n# Production-only helper\ndef helper():\n    return 42\n"
    target_method = (ROOT / service_path).read_bytes()
    git_source = release.git_source
    monkeypatch.setattr(
        release, "git_source",
        lambda revision, path: target_method if revision == "reviewed" and path == service_path else git_source(revision, path),
    )
    original = tmp_path / "old.zip"
    destination = tmp_path / "new.zip"
    prefix = module.rsplit("/", 1)[0] + "/"
    with zipfile.ZipFile(original, "w") as package:
        package.writestr(module, deployed_service)
        package.writestr(prefix + "handler.py", b"# keep the live handler")
        package.writestr(prefix + "__pycache__/service.cpython-312.pyc", b"old bytecode")
        package.writestr(prefix + "__pycache__/handler.cpython-312.pyc", b"keep handler bytecode")

    release.package_node_group_retry(original, destination, "reviewed")

    with zipfile.ZipFile(destination) as package:
        updated = package.read(module)
        assert ast.dump(release.node_group_request_method(updated)) == ast.dump(
            release.node_group_request_method(target_method)
        )
        start = release.node_group_request_method(deployed_service).lineno - 1
        assert updated.splitlines()[:start] == deployed_service.splitlines()[:start]
        assert updated.endswith(b"\n# Production-only helper\ndef helper():\n    return 42\n")
        assert package.read(prefix + "handler.py") == b"# keep the live handler"
        assert package.read(prefix + "__pycache__/handler.cpython-312.pyc") == b"keep handler bytecode"
        assert prefix + "__pycache__/service.cpython-312.pyc" not in package.namelist()


def test_node_group_retry_release_rejects_unreviewed_live_method(tmp_path, monkeypatch):
    release = load_release()
    module = release.CLUSTER_SERVICE
    path = "src/" + module
    original_service = baseline(release.NODE_GROUP_RETRY_BASELINE, path)
    target_method = (ROOT / path).read_bytes()
    monkeypatch.setattr(
        release, "git_source",
        lambda revision, _: target_method if revision == "reviewed" else original_service,
    )
    original = tmp_path / "old.zip"
    with zipfile.ZipFile(original, "w") as package:
        package.writestr(module, original_service.replace(
            b"Only a failed node-group request can be retried.", b"A different live retry rule.",
        ))

    with pytest.raises(RuntimeError, match="Live node-group method differs"):
        release.package_node_group_retry(original, tmp_path / "new.zip", "reviewed")


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
        assert "reconcile" in normalized
        assert "refresh-reconciliation" in normalized
        assert "apply-reconciliation" in normalized
        assert package.read(prefix + "utility_upgrades.py") == (ROOT / "src" / prefix / "utility_upgrades.py").read_bytes()
        assert package.read(prefix + "utility_gitops.py") == (ROOT / "src" / prefix / "utility_gitops.py").read_bytes()
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


@pytest.mark.parametrize("retry_response", [False, True])
def test_release_updates_reviewed_installed_plans_without_duplicate_members(tmp_path, retry_response):
    release = load_release()
    prefix = "navigan/modules/cluster_management/"
    source, target = tmp_path / "old.zip", tmp_path / "new.zip"
    with zipfile.ZipFile(source, "w") as package:
        reviewed_handler = release.scoped_handler_target(baseline(release.DEPLOYED_PLAN_TREE, "src/" + prefix + "handler.py"))
        package.writestr(prefix + "handler.py", release.retry_response_handler(reviewed_handler) if retry_response else reviewed_handler)
        package.writestr(prefix + "upgrade_readiness.py", baseline(
            release.DEPLOYED_PLAN_TREE, "src/" + prefix + "upgrade_readiness.py"))
        package.writestr(prefix + "upgrade_plans.py", baseline(
            release.DEPLOYED_PLAN_TREE, "src/" + prefix + "upgrade_plans.py"))
    release.package(source, target)
    with zipfile.ZipFile(target) as package:
        assert package.namelist().count(prefix + "upgrade_plans.py") == 1
        assert package.read(prefix + "upgrade_plans.py") == (ROOT / "src" / prefix / "upgrade_plans.py").read_bytes()
        assert 'status = 202 if parts[3] in {"execute", "refresh", "continue", "retry",' in package.read(prefix + "handler.py").decode()


def test_release_rejects_extra_drift_even_when_retry_response_matches(tmp_path):
    release=load_release()
    prefix="navigan/modules/cluster_management/"
    source,target=tmp_path/"old.zip",tmp_path/"new.zip"
    handler=release.retry_response_handler(release.scoped_handler_target(baseline(release.DEPLOYED_PLAN_TREE,"src/"+prefix+"handler.py")))
    handler=handler.replace(b"status = 202 if parts[3]", b"status = 203 if parts[3]")
    with zipfile.ZipFile(source,"w") as package:
        package.writestr(prefix+"handler.py",handler)
        package.writestr(prefix+"upgrade_readiness.py",baseline(release.DEPLOYED_PLAN_TREE,"src/"+prefix+"upgrade_readiness.py"))
        package.writestr(prefix+"upgrade_plans.py",baseline(release.DEPLOYED_PLAN_TREE,"src/"+prefix+"upgrade_plans.py"))
    with pytest.raises(RuntimeError,match="Deployed handler differs"):
        release.package(source,target)


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
    assert '"execute", "refresh", "continue", "reschedule", "reconcile", "refresh-reconciliation", "apply-reconciliation"}' in source
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


def test_readiness_comparison_matches_the_reviewed_normalized_source_diff():
    import ast
    release=load_release()
    source=baseline(release.DEPLOYED_PLAN_TREE,"src/navigan/modules/cluster_management/upgrade_readiness.py")
    # The user's production comparison showed identical ast.unparse output.
    # This invariant must hold on whichever supported Python prepares a release.
    normalized=(ast.unparse(ast.parse(source.decode()))+"\n").encode()
    assert release.normalized_semantic(source)==release.normalized_semantic(normalized)
    changed=normalized.replace(b"'ACTIVE'",b"'DELETING'",1)
    assert changed!=normalized
    assert release.normalized_semantic(changed)!=release.normalized_semantic(source)


def test_normalization_never_accepts_unreviewed_readiness_behavior(tmp_path):
    import pytest
    release=load_release()
    prefix="navigan/modules/cluster_management/"
    original=tmp_path/"drift.zip"
    with zipfile.ZipFile(original,"w") as archive:
        archive.writestr(prefix+"handler.py",release.scoped_handler_target(baseline(release.DEPLOYED_PLAN_TREE,"src/"+prefix+"handler.py")))
        discovery=baseline(release.DEPLOYED_PLAN_TREE,"src/"+prefix+"upgrade_readiness.py")
        archive.writestr(prefix+"upgrade_readiness.py",discovery.replace(b'"ACTIVE"',b'"DELETING"',1))
        archive.writestr(prefix+"upgrade_plans.py",baseline(release.DEPLOYED_PLAN_TREE,"src/"+prefix+"upgrade_plans.py"))
    with pytest.raises(RuntimeError,match="Deployed upgrade-readiness module differs"):
        release.package(original,tmp_path/"rejected.zip")


def utilities_baseline(path):
    release = load_release()
    prefix = 'navigan/modules/cluster_management/'
    contents = {prefix + name + '.py': baseline(release.DEPLOYED_PLAN_TREE, 'src/' + prefix + name + '.py') for name in ('upgrade_plans', 'utility_upgrades', 'upgrade_actors')}
    contents[prefix + 'handler.py'] = release.retry_response_handler(release.scoped_handler_target(baseline(release.DEPLOYED_PLAN_TREE, 'src/' + prefix + 'handler.py')))
    contents[prefix + 'upgrade_readiness.py'] = (ROOT / 'src' / prefix / 'upgrade_readiness.py').read_bytes()
    contents[prefix + 'upgrade_paths.py'] = baseline(release.DEPLOYED_PLAN_TREE, 'src/' + prefix + 'upgrade_paths.py') + b"\ndef production_recovery_guard(): return 'preserve'\n"
    for name in ('github_app', 'repository'):
        contents[prefix + name + '.py'] = (ROOT / 'src' / prefix / (name + '.py')).read_bytes()
    contents['yaml/__init__.py'] = b'# deployed dependency\n'
    contents['navigan/shared/untouched.py'] = b'# unrelated deployed module\n'
    contents[prefix + '__pycache__/upgrade_paths.cpython-312.pyc'] = b'preserve live cache'
    contents[prefix + '__pycache__/utility_upgrades.cpython-312.pyc'] = b'remove replaced cache'
    contents[prefix + '__pycache__/handler.cpython-312.pyc'] = b'remove patched handler cache'
    contents['navigan/modules/customer_management/__pycache__/handler.cpython-312.pyc'] = b'preserve other handler cache'
    with zipfile.ZipFile(path, 'w') as archive:
        for name, data in contents.items(): archive.writestr(name, data)
    return contents


def test_utilities_only_preserves_live_recovery_and_all_unrelated_bytes(tmp_path):
    release = load_release()
    source, target = tmp_path/'old.zip', tmp_path/'new.zip'
    original = utilities_baseline(source)
    release.package(source, target, utilities_only=True)
    prefix = 'navigan/modules/cluster_management/'
    with zipfile.ZipFile(target) as archive:
        for name, data in original.items():
            if name in {prefix+'utility_upgrades.py', prefix+'handler.py', prefix+'__pycache__/handler.cpython-312.pyc'} or '/utility_upgrades.' in name: continue
            assert archive.read(name) == data
        assert archive.read(prefix+'handler.py') == release.utility_query_handler(original[prefix+'handler.py'])
        for module in ('utility_upgrades', 'utility_gitops'):
            assert archive.read(prefix+module+'.py') == (ROOT/'src'/prefix/(module+'.py')).read_bytes()
        assert prefix+'__pycache__/utility_upgrades.cpython-312.pyc' not in archive.namelist()
        assert prefix+'__pycache__/handler.cpython-312.pyc' not in archive.namelist()


@pytest.mark.parametrize('change', ['handler', 'utility', 'missing_yaml', 'missing_github_method'])
def test_utilities_only_keeps_dependency_and_routing_guards(tmp_path, change):
    release = load_release()
    source, target = tmp_path/'old.zip', tmp_path/'new.zip'
    contents = utilities_baseline(source)
    prefix = 'navigan/modules/cluster_management/'
    if change == 'handler': contents[prefix+'handler.py'] += b'\ndef unreviewed_route(): pass\n'
    if change == 'utility': contents[prefix+'utility_upgrades.py'] += b'\ndef unreviewed_utility(): pass\n'
    if change == 'missing_yaml': del contents['yaml/__init__.py']
    if change == 'missing_github_method': contents[prefix+'github_app.py'] = b'class GitHubApp: pass\n'
    with zipfile.ZipFile(source, 'w') as archive:
        for name, data in contents.items(): archive.writestr(name, data)
    with pytest.raises(RuntimeError): release.package(source, target, utilities_only=True)


def test_utilities_only_adds_yaml_without_replacing_production_helpers(tmp_path):
    release=load_release()
    source,target=tmp_path/'old.zip',tmp_path/'new.zip'
    contents=utilities_baseline(source)
    del contents['yaml/__init__.py']
    helper='navigan/modules/cluster_management/github_app.py'
    contents[helper]=b'class GitHubApp:\n def repository_token(self,*args): pass\n def _request(self,*args): pass\n'
    with zipfile.ZipFile(source,'w') as archive:
        for name,data in contents.items():archive.writestr(name,data)
    dependency={'yaml/__init__.py':b'# pinned package fixture\n','yaml/_yaml.cpython-312-x86_64-linux-gnu.so':b'pinned native extension fixture'}
    release.package(source,target,utilities_only=True,yaml_dependency=dependency)
    with zipfile.ZipFile(target) as archive:
        for name,data in contents.items():
            if name in {'navigan/modules/cluster_management/handler.py', 'navigan/modules/cluster_management/__pycache__/handler.cpython-312.pyc'} or name.endswith('utility_upgrades.py') or '/utility_upgrades.' in name:continue
            assert archive.read(name)==data
        for name,data in dependency.items():assert archive.read(name)==data


def test_utility_query_patch_accepts_confirmed_release_and_preserves_recovery(tmp_path):
    release = load_release()
    source, target = tmp_path/'old.zip', tmp_path/'new.zip'
    contents = utilities_baseline(source)
    prefix = 'navigan/modules/cluster_management/'
    contents[prefix+'utility_upgrades.py'] = baseline(release.DEPLOYED_UTILITY_TREE, 'src/'+prefix+'utility_upgrades.py')
    with zipfile.ZipFile(source, 'w') as archive:
        for name, data in contents.items(): archive.writestr(name, data)
    release.package(source, target, utilities_only=True)
    with zipfile.ZipFile(target) as archive:
        handler = archive.read(prefix+'handler.py')
        assert release.utility_query_handler(handler) == handler
        assert b'allow_utility=True' in handler
        assert archive.read(prefix+'upgrade_paths.py') == contents[prefix+'upgrade_paths.py']


def test_utility_query_patch_handles_canonical_production_formatting():
    import ast
    release = load_release()
    path = 'src/navigan/modules/cluster_management/handler.py'
    live = release.retry_response_handler(release.scoped_handler_target(baseline(release.DEPLOYED_PLAN_TREE, path)))
    canonical = ast.unparse(ast.parse(live)).encode()
    fixed = release.utility_query_handler(canonical)
    assert b'allow_utility=True' in fixed
    assert release.utility_query_handler(fixed) == fixed


def test_yaml_dependency_rejects_wrong_checksum():
    release=load_release()
    with pytest.raises(RuntimeError,match='checksum'):
        release.utility_yaml_dependency(lambda _:b'not the pinned wheel')
