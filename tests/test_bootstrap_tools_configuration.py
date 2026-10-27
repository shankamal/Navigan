from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


m = load("tools_configuration", ROOT / "scripts/configure-bootstrap-tools-prod.py")
reference_tests = load("tools_reference_fixtures", ROOT / "tests/test_bootstrap_reference_proof.py")
repair = load("tools_gitops_repair", ROOT / "scripts/repair-cluster-tools-gitops.py")


def fixture(tmp_path):
    session, clients, saved, _, meta, shared = reference_tests.fixture()
    for key in ("root", "child"):
        saved[key]["Parameters"].append({"ParameterKey": "PlatformToolsBaseUrl", "ParameterValue": m.URL})
        saved[key]["StackStatus"] = "UPDATE_COMPLETE"
    for key in ("rootTemplate", "childTemplate"):
        saved[key]["Parameters"]["PlatformToolsBaseUrl"] = {"Type": "String", "Default": ""}
    saved["rootTemplate"]["Resources"]["ClusterManagement"]["Properties"]["Parameters"]["PlatformToolsBaseUrl"] = {"Ref": "PlatformToolsBaseUrl"}
    cluster_env = {"DB_NAME": "navigan", m.KEY: m.URL, "PLATFORM_TOOLS_GATEWAY_ENABLED": "true", "PLATFORM_TOOLS_TUNNEL_ENABLED": "true"}
    status_env = {"DB_NAME": "navigan"}
    for name, env in (("ClusterFunction", cluster_env), ("StatusFunction", status_env)):
        saved["configs"][name].update({"FunctionName": name, "Environment": {"Variables": env}, "CodeSha256": "preserved-code",
                                        "State": "Active", "LastUpdateStatus": "Successful"})
        saved["childTemplate"]["Resources"][name]["Properties"]["Environment"] = {"Variables": deepcopy(env)}
    saved["childTemplate"]["Resources"]["ClusterFunction"]["Properties"]["Environment"]["Variables"][m.KEY] = {"Ref": "PlatformToolsBaseUrl"}
    saved["project"] = {"name": "runner", "environment": {"image": "old"}}
    saved["image"] = "old"
    root, child = m.desired(saved, "new-child-url")
    (tmp_path / "root-updated-template.json").write_text(json.dumps(root))
    plan = {"directory": str(tmp_path), "format": m.FORMAT, "account": m.h.ACCOUNT, "region": m.h.REGION, "parent": m.h.PARENT,
            "newImage": "old", "rootHash": m.h.fingerprint(root), "childHash": m.h.fingerprint(child),
            "preview": "child-preview", "changeSet": "parent-only"}
    meta["IncludeNestedStacks"] = False
    meta["Parameters"] = [{"ParameterKey": item["ParameterKey"], "UsePreviousValue": True} for item in saved["child"]["Parameters"]]
    status_change = deepcopy(meta["Changes"][1])
    status_change["ResourceChange"]["Details"][0]["Target"]["Name"] = "Environment"
    meta["Changes"] = [status_change]
    clients["cloudformation"].get_template.return_value = {"TemplateBody": child}
    return session, clients, saved, plan, meta, root, child


def test_sam_binds_the_same_tools_parameter_for_manual_and_automatic_bootstrap():
    template = m.h.audit.template_body((ROOT / "infrastructure/modules/cluster-management/template.yaml").read_text())
    for function in ("ClusterFunction", "StatusFunction"):
        assert template["Resources"][function]["Properties"]["Environment"]["Variables"][m.KEY] == {"Ref": "PlatformToolsBaseUrl"}


def test_url_only_template_delta_preserves_code_flags_images_permissions_and_all_other_resources(tmp_path):
    _, _, saved, _, _, root, child = fixture(tmp_path)
    m.validate_templates(saved, root, child)
    expected = deepcopy(saved["childTemplate"])
    expected["Resources"]["StatusFunction"]["Properties"]["Environment"]["Variables"][m.KEY] = {"Ref": "PlatformToolsBaseUrl"}
    assert child == expected
    assert "PLATFORM_TOOLS_GATEWAY_ENABLED" not in child["Resources"]["StatusFunction"]["Properties"]["Environment"]["Variables"]


@pytest.mark.parametrize("fault", ["live_gateway", "flag", "root_url", "child_url", "binding", "status_existing", "status_template_existing", "code", "other_resource", "root"])
def test_unknown_configuration_and_broader_template_edits_are_blocked(tmp_path, fault):
    _, _, saved, _, _, root, child = fixture(tmp_path)
    if fault == "live_gateway": saved["configs"]["ClusterFunction"]["Environment"]["Variables"][m.KEY] = "https://dev.navigan.click/tools"
    elif fault == "flag": saved["configs"]["ClusterFunction"]["Environment"]["Variables"]["PLATFORM_TOOLS_TUNNEL_ENABLED"] = "false"
    elif fault in {"root_url", "child_url"}:
        key = "root" if fault == "root_url" else "child"
        saved[key]["Parameters"][-1]["ParameterValue"] = "https://other.example/tools"
    elif fault == "binding": saved["childTemplate"]["Resources"]["ClusterFunction"]["Properties"]["Environment"]["Variables"][m.KEY] = "https://unknown.example/tools"
    elif fault == "status_existing": saved["configs"]["StatusFunction"]["Environment"]["Variables"][m.KEY] = m.URL
    elif fault == "status_template_existing": saved["childTemplate"]["Resources"]["StatusFunction"]["Properties"]["Environment"]["Variables"][m.KEY] = m.URL
    elif fault == "code": child["Resources"]["StatusFunction"]["Properties"]["Code"] = {"ZipFile": "unexpected"}
    elif fault == "other_resource": child["Resources"]["ApplyRoute"]["Properties"]["ApiId"] = "changed"
    else: root["Description"] = "unrelated"
    with pytest.raises(ValueError): m.validate_templates(saved, root, child)


def test_concrete_environment_preview_keeps_api_and_callback_identity_checks(tmp_path):
    session, clients, saved, plan, _, _, _ = fixture(tmp_path)
    proof = m.verify_child(session, saved, plan)
    assert proof["inputs"]["parameters"]["PlatformToolsBaseUrl"] == m.URL
    assert proof["snapshot"]["api"]["api"]["ApiId"] == "testapi"
    clients["cloudformation"].execute_change_set.assert_not_called()


def test_exact_literal_gateway_url_is_preserved_and_new_status_binding_uses_verified_parameter(tmp_path):
    session, clients, saved, plan, _, _, _ = fixture(tmp_path)
    saved["childTemplate"]["Resources"]["ClusterFunction"]["Properties"]["Environment"]["Variables"][m.KEY] = m.URL
    root, child = m.desired(saved, "new-child-url")
    assert child["Resources"]["ClusterFunction"] == saved["childTemplate"]["Resources"]["ClusterFunction"]
    assert child["Resources"]["StatusFunction"]["Properties"]["Environment"]["Variables"][m.KEY] == {"Ref": "PlatformToolsBaseUrl"}
    plan["childHash"] = m.h.fingerprint(child)
    clients["cloudformation"].get_template.return_value = {"TemplateBody": child}
    m.verify_child(session, saved, plan)
    clients["cloudformation"].execute_change_set.assert_not_called()


@pytest.mark.parametrize("scope", ["root", "child", "runtime"])
def test_literal_url_acceptance_does_not_bypass_parameter_and_runtime_consistency(tmp_path, scope):
    _, _, saved, _, _, _, _ = fixture(tmp_path)
    saved["childTemplate"]["Resources"]["ClusterFunction"]["Properties"]["Environment"]["Variables"][m.KEY] = m.URL
    if scope == "runtime":
        saved["configs"]["ClusterFunction"]["Environment"]["Variables"][m.KEY] = "https://unknown.example/tools"
    else:
        saved[scope]["Parameters"][-1]["ParameterValue"] = "https://unknown.example/tools"
    with pytest.raises(ValueError): m.desired(saved)


@pytest.mark.parametrize("fault", ["replacement", "field", "extra", "missing", "parameter", "duplicate", "nested", "stack", "template"])
def test_concrete_preview_rejects_replacements_other_resources_and_binding_changes(tmp_path, fault):
    session, clients, saved, plan, meta, _, child = fixture(tmp_path)
    row = meta["Changes"][0]["ResourceChange"]
    if fault == "replacement": row["Replacement"] = "True"
    elif fault == "field": row["Details"][0]["Target"]["Name"] = "Code"
    elif fault == "extra": meta["Changes"].append({"ResourceChange": {"LogicalResourceId": "ClusterFunction"}})
    elif fault == "missing": meta["Changes"] = []
    elif fault == "parameter": meta["Parameters"][-1] = {"ParameterKey": "PlatformToolsBaseUrl", "ParameterValue": "different"}
    elif fault == "duplicate": meta["Changes"].append(deepcopy(meta["Changes"][0]))
    elif fault == "nested": meta["IncludeNestedStacks"] = True
    elif fault == "stack": meta["StackId"] = "other"
    else: child["Resources"]["ClusterFunction"]["Properties"]["Code"] = {"ZipFile": "other"}
    with pytest.raises(ValueError): m.verify_child(session, saved, plan)
    clients["cloudformation"].execute_change_set.assert_not_called()


def after_fixture(tmp_path):
    session, clients, saved, plan, _, root, child = fixture(tmp_path)
    proof = m.verify_child(session, saved, plan)
    cfn = clients["cloudformation"]
    cfn.describe_stacks.side_effect = lambda StackName: {"Stacks": [deepcopy(saved["root"] if StackName == saved["root"]["StackId"] else saved["child"])]}
    cfn.get_template.side_effect = lambda StackName, **kwargs: {"TemplateBody": root if StackName == saved["root"]["StackId"] else child}
    configs = deepcopy(saved["configs"])
    configs["StatusFunction"]["Environment"]["Variables"][m.KEY] = m.URL
    clients["lambda"] = MagicMock()
    clients["lambda"].get_function_configuration.side_effect = lambda FunctionName: configs[FunctionName]
    clients["codebuild"] = MagicMock()
    clients["codebuild"].batch_get_projects.return_value = {"projects": [deepcopy(saved["project"])]}
    return session, clients, saved, plan, proof, configs


def test_postverification_accepts_only_url_environment_delta_and_unchanged_code_and_runner(tmp_path):
    session, _, saved, plan, proof, _ = after_fixture(tmp_path)
    m.verify_after(session, saved, plan, proof, {})


@pytest.mark.parametrize("fault", ["code", "url", "other_env", "cluster_env", "runner", "api", "status"])
def test_postverification_detects_configuration_and_runtime_drift(tmp_path, fault):
    session, clients, saved, plan, proof, configs = after_fixture(tmp_path)
    if fault == "code": configs["StatusFunction"]["CodeSha256"] = "changed"
    elif fault == "url": configs["StatusFunction"]["Environment"]["Variables"][m.KEY] = "wrong"
    elif fault == "other_env": configs["StatusFunction"]["Environment"]["Variables"]["DB_NAME"] = "other"
    elif fault == "cluster_env": configs["ClusterFunction"]["Environment"]["Variables"][m.KEY] = "wrong"
    elif fault == "runner": clients["codebuild"].batch_get_projects.return_value["projects"][0]["environment"]["image"] = "changed"
    elif fault == "api": clients["apigatewayv2"].get_routes.return_value["Items"][0]["AuthorizationType"] = "NONE"
    else: configs["StatusFunction"]["LastUpdateStatus"] = "Failed"
    with pytest.raises(ValueError): m.verify_after(session, saved, plan, proof, {})


def test_execution_targets_parent_only_and_records_request_before_mutation(tmp_path, monkeypatch):
    session, clients, saved, plan, _, _, _ = fixture(tmp_path)
    proof = m.verify_child(session, saved, plan)
    for name, value in (("release-plan.json", plan), ("reference-proof.json", proof), ("sibling-noop-proof.json", {})):
        (tmp_path / name).write_text(json.dumps(value))
    monkeypatch.setattr(m, "saved_capture", lambda path: saved)
    monkeypatch.setattr(m.h, "preflight", lambda *args: None)
    monkeypatch.setattr(m.h.references, "inspect_parent", lambda *args, **kwargs: {})
    monkeypatch.setattr(m, "verify_after", lambda *args: None)
    def requested(**kwargs):
        assert (tmp_path / "execution.json").exists()
        assert kwargs == {"ChangeSetName": "parent-only"}
    clients["cloudformation"].execute_change_set.side_effect = requested
    m.execute(session, tmp_path / "release-plan.json")
    clients["cloudformation"].execute_change_set.assert_called_once_with(ChangeSetName="parent-only")
    assert (tmp_path / "verification.json").exists()
    with pytest.raises(ValueError, match="already requested"): m.execute(session, tmp_path / "release-plan.json")


def test_prepare_stages_scoped_previews_and_never_executes_them(tmp_path, monkeypatch):
    session, clients, saved, _, _, _, child = fixture(tmp_path)
    record = tmp_path / "record"
    record.mkdir()
    monkeypatch.setattr(m.tempfile, "mkdtemp", lambda **kwargs: str(record))
    capture = MagicMock()
    monkeypatch.setattr(m.h.audit, "capture", capture)
    monkeypatch.setattr(m, "saved_capture", lambda path: saved)
    monkeypatch.setattr(m.h, "preflight", MagicMock())
    monkeypatch.setattr(m.h.storage, "verify_storage", lambda *args: {"bucket": "existing-private-bucket"})
    upload = MagicMock(return_value=({}, "new-child-url"))
    monkeypatch.setattr(m.h, "upload", upload)
    previews = MagicMock(side_effect=["child-preview", "parent-only"])
    monkeypatch.setattr(m, "create_preview", previews)
    monkeypatch.setattr(m.h.references, "inspect_parent", lambda *args: {})
    path = m.prepare(session)
    assert path == record / "release-plan.json"
    assert json.loads(upload.call_args.args[-1]) == child
    assert upload.call_count == 1
    assert capture.call_args.args[1].inspect_runner is False
    assert previews.call_args_list[0].args[1]["StackId"] == saved["child"]["StackId"]
    assert previews.call_args_list[1].args[1]["StackId"] == saved["root"]["StackId"]
    clients["cloudformation"].execute_change_set.assert_not_called()
    assert not (record / "execution.json").exists()


CLUSTER, CONNECTOR = "CLU-" + "a" * 32, "KCC-" + "b" * 32


def gitops():
    import yaml
    root = ROOT / "src/navigan/modules/cluster_management/system_repo_template/values"
    connector = (root / "connector.yaml").read_text().replace("__CONNECTOR_ID__", CONNECTOR).replace("__NAVIGAN_TOOLS_TUNNEL_URL__", "")
    monitoring = (root / "monitoring.yaml").read_text().replace("__CLUSTER_ID__", CLUSTER).replace("__NAVIGAN_TOOLS_BASE_URL__", "")
    return {"values/connector.yaml": connector, "values/monitoring.yaml": monitoring}


def test_gitops_repair_changes_exactly_three_urls_preserving_credentials_images_and_other_values():
    import yaml
    before = gitops()
    result = repair.repair_texts(before, CLUSTER, CONNECTOR, m.URL)
    for path in before:
        old, new = yaml.safe_load(before[path]), yaml.safe_load(result[path])
        if path.endswith("connector.yaml"):
            new["navigan"]["toolsTunnelUrl"] = old["navigan"]["toolsTunnelUrl"]
        else:
            new["grafana"]["grafana.ini"]["server"]["root_url"] = old["grafana"]["grafana.ini"]["server"]["root_url"]
            new["prometheus"]["prometheusSpec"]["externalUrl"] = old["prometheus"]["prometheusSpec"]["externalUrl"]
        assert new == old
    assert "wss://navigan.click/tools/tunnel" in result["values/connector.yaml"]
    assert m.URL + "/clusters/" + CLUSTER + "/grafana/" in result["values/monitoring.yaml"]
    assert repair.repair_texts(result, CLUSTER, CONNECTOR, m.URL) == result


@pytest.mark.parametrize("fault", ["connector", "cluster", "existing_url", "monitoring_url", "duplicate", "http", "credentials", "query"])
def test_gitops_repair_rejects_wrong_cluster_identity_and_unreviewed_urls(fault):
    texts = gitops()
    url, cluster, connector = m.URL, CLUSTER, CONNECTOR
    if fault == "connector": connector = "KCC-" + "c" * 32
    elif fault == "cluster": cluster = "CLU-" + "c" * 32
    elif fault == "existing_url": texts["values/connector.yaml"] = texts["values/connector.yaml"].replace("toolsTunnelUrl: ", "toolsTunnelUrl: wss://other.example/tools/tunnel")
    elif fault == "monitoring_url": texts["values/monitoring.yaml"] = texts["values/monitoring.yaml"].replace("root_url: /clusters/", "root_url: https://other.example/clusters/")
    elif fault == "duplicate": texts["values/connector.yaml"] += "\nother:\n  toolsTunnelUrl: ''\n"
    elif fault == "http": url = "http://navigan.click/tools"
    elif fault == "credentials": url = "https://user:password@navigan.click/tools"
    else: url = m.URL + "?token=private"
    with pytest.raises(ValueError): repair.repair_texts(texts, cluster, connector, url)
