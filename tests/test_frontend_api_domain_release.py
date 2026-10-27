import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import botocore.session
import pytest


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


m = load("frontend_api_release", "scripts/deploy-frontend-api-domain-prod.py")
fixtures = load("frontend_api_fixtures", "tests/test_frontend_prod_release.py")
OLD = fixtures.OLD.rsplit(":", 1)[0] + ":23"
NEXT = OLD.rsplit(":", 1)[0] + ":24"
DIGEST = "sha256:" + "a" * 64
IMAGE = m.front.IMAGE_PREFIX + "@" + DIGEST
OLD_URL = "https://prod123.execute-api.ap-south-1.amazonaws.com/v1/api/v1"


def setup(tmp_path, monkeypatch):
    original = fixtures.task()
    original["containerDefinitions"][0]["image"] = IMAGE
    original["containerDefinitions"][1]["image"] = "example.test/sidecar@" + DIGEST
    original["containerDefinitions"][0]["environment"][1]["value"] = OLD_URL.split("/v1/")[0]
    original["containerDefinitions"][0]["environment"].append({"name": "MIGRATION_SOURCE_FIRST_ENABLED", "value": "true"})
    described = {"taskDefinition": {**original, "taskDefinitionArn": OLD, "status": "ACTIVE", "revision": 23}, "tags": [{"key": "owner", "value": "preserved"}]}
    service = fixtures.service(OLD)
    service.update(serviceArn=f"arn:aws:ecs:{m.front.REGION}:{m.front.ACCOUNT}:service/{m.front.CLUSTER}/{m.front.SERVICE}",
                   networkConfiguration={"awsvpcConfiguration": {"subnets": ["private-subnet"]}},
                   deploymentConfiguration={"minimumHealthyPercent": 100, "maximumPercent": 200, "deploymentCircuitBreaker": {"enable": True, "rollback": True}})
    stack = {"StackId": f"arn:aws:cloudformation:{m.front.REGION}:{m.front.ACCOUNT}:stack/navigan-frontend/id", "StackStatus": "UPDATE_COMPLETE"}
    resources = [{"LogicalResourceId": "Cluster", "PhysicalResourceId": m.front.CLUSTER},
                 {"LogicalResourceId": "Service", "PhysicalResourceId": service["serviceArn"]},
                 {"LogicalResourceId": "TaskDefinition", "PhysicalResourceId": OLD.rsplit(":", 1)[0] + ":1"}]
    baseline = {"stack": stack, "resources": resources, "template": {"TemplateBody": "{}"}, "service": service, "task": described}
    capture = tmp_path / "capture"
    capture.mkdir()
    m.write(capture / "frontend-capture.json", baseline)
    ecs, cfn, ecr = MagicMock(), MagicMock(), MagicMock()
    ecs.meta.service_model = botocore.session.get_session().get_service_model("ecs")
    ecs.describe_services.side_effect = lambda **kw: {"services": [copy.deepcopy(service)]}
    definitions = {OLD: copy.deepcopy(described)}
    ecs.describe_task_definition.side_effect = lambda taskDefinition, **kw: copy.deepcopy(definitions[taskDefinition])
    def register(**kw):
        definitions[NEXT] = {"taskDefinition": {**copy.deepcopy(kw), "taskDefinitionArn": NEXT, "status": "ACTIVE"}, "tags": kw.get("tags", [])}
        definitions[NEXT]["taskDefinition"].pop("tags", None)
        return {"taskDefinition": {"taskDefinitionArn": NEXT}}
    ecs.register_task_definition.side_effect = register
    def update(**kw): service["taskDefinition"] = kw["taskDefinition"]
    ecs.update_service.side_effect = update
    ecs.get_paginator.return_value.paginate.return_value = [{"taskArns": ["task"]}]
    tasks = lambda: {"tasks": [{"taskDefinitionArn": service["taskDefinition"], "lastStatus": "RUNNING", "healthStatus": "HEALTHY",
        "overrides": {"containerOverrides": [{"name": "frontend"}]}, "containers": [{"name": "frontend", "imageDigest": DIGEST}]}]}
    ecs.describe_tasks.side_effect = lambda **kw: tasks()
    cfn.describe_stacks.side_effect = lambda **kw: {"Stacks": [copy.deepcopy(stack)]}
    cfn.list_stack_resources.side_effect = lambda **kw: {"StackResourceSummaries": copy.deepcopy(resources)}
    cfn.get_template.return_value = {"TemplateBody": "{}"}
    ecr.batch_get_image.return_value = {"images": [{"imageId": {"imageDigest": DIGEST}, "imageManifest": '{"schemaVersion":2,"layers":[]}'}]}
    clients = {"ecs": ecs, "cloudformation": cfn, "ecr": ecr, "sts": MagicMock()}
    clients["sts"].get_caller_identity.return_value = {"Account": m.front.ACCOUNT}
    session = SimpleNamespace(client=lambda name: clients[name])
    gate = m.domain_gate
    monkeypatch.setattr(m, "domain_gate", MagicMock(return_value=OLD_URL))
    monkeypatch.setattr(m.domain, "probe", MagicMock(return_value=200))
    def directory(**kw):
        path = tmp_path / "release"
        path.mkdir()
        return str(path)
    monkeypatch.setattr(m.tempfile, "mkdtemp", directory)
    return SimpleNamespace(session=session, ecs=ecs, cfn=cfn, service=service, definitions=definitions,
        baseline=baseline, capture=capture, domain_path=tmp_path / "domain-plan.json", clients=clients, gate=gate,
        path=tmp_path / "release/release-plan.json")


def prepare(f):
    m.prepare(f.session, f.capture, f.domain_path)
    return m.read(f.path)


def test_prepare_copies_live_revision_and_only_changes_two_urls_without_updating_service(tmp_path, monkeypatch):
    f = setup(tmp_path, monkeypatch)
    plan = prepare(f)
    assert plan["previousTask"] == OLD and plan["nextTask"] == NEXT
    assert f.baseline["resources"][2]["PhysicalResourceId"].endswith(":1")
    before = m.original_request(f.ecs, f.definitions[OLD])
    after = f.ecs.register_task_definition.call_args.kwargs
    expected = copy.deepcopy(before)
    for item in m.front.container(expected)["environment"]:
        if item["name"] in m.NEW: item["value"] = m.NEW[item["name"]]
    assert after == expected
    assert m.front.container(after)["image"] == IMAGE
    assert m.front.environment(m.front.container(after))["MIGRATION_SOURCE_FIRST_ENABLED"] == "true"
    f.ecs.update_service.assert_not_called()
    assert (f.path.parent / "baseline.json").stat().st_mode & 0o777 == 0o600
    assert f.path.parent.stat().st_mode & 0o777 == 0o700
    assert set(f.clients) == {"ecs", "cloudformation", "ecr", "sts"}


@pytest.mark.parametrize("fault", ["service_task", "desired", "network", "stack", "template", "resource", "definition", "running_image", "unhealthy", "overrides", "min_healthy", "duplicate_env", "mutable_image"])
def test_prepare_blocks_drift_or_unsafe_runtime_before_registration(tmp_path, monkeypatch, fault):
    f = setup(tmp_path, monkeypatch)
    if fault == "service_task": f.service["taskDefinition"] = NEXT
    elif fault == "desired": f.service["desiredCount"] = 2
    elif fault == "network": f.service["networkConfiguration"] = {}
    elif fault == "stack": f.cfn.describe_stacks.side_effect = lambda **kw: {"Stacks": [{**f.baseline["stack"], "LastUpdatedTime": "new"}]}
    elif fault == "template": f.cfn.get_template.return_value = {"TemplateBody": "changed"}
    elif fault == "resource": f.cfn.list_stack_resources.side_effect = lambda **kw: {"StackResourceSummaries": []}
    elif fault == "definition": f.definitions[OLD]["taskDefinition"]["cpu"] = "1024"
    elif fault in {"running_image", "unhealthy", "overrides"}:
        tasks = f.ecs.describe_tasks()["tasks"]
        if fault == "running_image": tasks[0]["containers"][0]["imageDigest"] = "sha256:" + "b" * 64
        elif fault == "unhealthy": tasks[0]["healthStatus"] = "UNHEALTHY"
        else: tasks[0]["overrides"]["containerOverrides"][0]["environment"] = [{"name": "secret", "value": "never-print"}]
        f.ecs.describe_tasks.side_effect = None
        f.ecs.describe_tasks.return_value = {"tasks": tasks}
    elif fault == "min_healthy":
        f.baseline["service"]["deploymentConfiguration"]["minimumHealthyPercent"] = 0
        m.write(f.capture / "frontend-capture.json", f.baseline)
    else:
        container = f.baseline["task"]["taskDefinition"]["containerDefinitions"][0]
        if fault == "duplicate_env": container["environment"].append(copy.deepcopy(container["environment"][1]))
        else: container["image"] = m.front.IMAGE_PREFIX + ":latest"
        m.write(f.capture / "frontend-capture.json", f.baseline)
    with pytest.raises((ValueError, RuntimeError)): m.prepare(f.session, f.capture, f.domain_path)
    f.ecs.register_task_definition.assert_not_called()
    f.ecs.update_service.assert_not_called()


def test_execute_journals_exact_service_task_update_and_verifies_same_image(tmp_path, monkeypatch):
    f = setup(tmp_path, monkeypatch)
    prepare(f)
    def update(**kw):
        assert (f.path.parent / "execution.json").exists()
        f.service["taskDefinition"] = kw["taskDefinition"]
    f.ecs.update_service.side_effect = update
    m.execute(f.session, f.path)
    f.ecs.update_service.assert_called_once_with(cluster=m.front.CLUSTER, service=m.front.SERVICE, taskDefinition=NEXT)
    record = m.read(f.path.parent / "verification.json")
    assert record["frontendConfigurationVerified"] and record["cloudFormationDriftPending"]
    assert record["image"] == IMAGE and record["authenticatedBrowserAcceptance"] is False
    with pytest.raises(ValueError, match="already requested"): m.execute(f.session, f.path)
    assert f.ecs.update_service.call_count == 1


def test_candidate_and_update_requests_match_actual_sdk_shapes(tmp_path, monkeypatch):
    from botocore.validate import validate_parameters
    f = setup(tmp_path, monkeypatch)
    prepare(f)
    model = botocore.session.get_session().get_service_model("ecs")
    validate_parameters(f.ecs.register_task_definition.call_args.kwargs,
                        model.operation_model("RegisterTaskDefinition").input_shape)
    m.execute(f.session, f.path)
    validate_parameters(f.ecs.update_service.call_args.kwargs,
                        model.operation_model("UpdateService").input_shape)


@pytest.mark.parametrize("fault", ["image", "flag", "role", "cpu", "sidecar", "healthcheck", "environment", "service", "cfn", "plan"])
def test_execute_blocks_unrelated_candidate_or_fresh_baseline_changes(tmp_path, monkeypatch, fault):
    f = setup(tmp_path, monkeypatch)
    plan = prepare(f)
    task = f.definitions[NEXT]["taskDefinition"]
    front = task["containerDefinitions"][0]
    if fault == "image": front["image"] = m.front.IMAGE_PREFIX + "@sha256:" + "f" * 64
    elif fault == "flag": front["environment"].append({"name": "unapproved_flag", "value": "true"})
    elif fault == "role": task["taskRoleArn"] = "other"
    elif fault == "cpu": task["cpu"] = "1024"
    elif fault == "sidecar": task["containerDefinitions"][1]["image"] += "other"
    elif fault == "healthcheck": front["healthCheck"] = {"command": ["NONE"]}
    elif fault == "environment": front["environment"][0]["value"] = "unapproved"
    elif fault == "service": f.service["networkConfiguration"] = {}
    elif fault == "cfn": f.cfn.get_template.return_value = {"TemplateBody": "changed"}
    else:
        plan["image"] += "tampered"
        m.write(f.path, plan)
    with pytest.raises((ValueError, RuntimeError)): m.execute(f.session, f.path)
    f.ecs.update_service.assert_not_called()
    assert not (f.path.parent / "execution.json").exists()


def test_rollback_restores_saved_task_without_requiring_the_new_domain(tmp_path, monkeypatch):
    f = setup(tmp_path, monkeypatch)
    prepare(f)
    m.execute(f.session, f.path)
    m.domain_gate.side_effect = ValueError("domain unavailable")
    m.execute(f.session, f.path, rollback=True)
    assert f.ecs.update_service.call_args.kwargs["taskDefinition"] == OLD
    assert m.read(f.path.parent / "rollback-verification.json")["apiUrl"] == OLD_URL
    with pytest.raises(ValueError, match="already requested"): m.execute(f.session, f.path, rollback=True)


@pytest.mark.parametrize("fault", ["automatic_rollback", "wrong_digest", "health_http"])
def test_failed_rollout_is_never_reported_as_success_and_can_be_inspected(tmp_path, monkeypatch, fault):
    f = setup(tmp_path, monkeypatch)
    prepare(f)
    if fault == "automatic_rollback": f.ecs.update_service.side_effect = lambda **kw: None
    elif fault == "wrong_digest":
        original_reader = f.ecs.describe_tasks.side_effect
        def tasks_after_update(**kw):
            result = original_reader(**kw)
            if f.service["taskDefinition"] == NEXT:
                result["tasks"][0]["containers"][0]["imageDigest"] = "sha256:" + "f" * 64
            return result
        f.ecs.describe_tasks.side_effect = tasks_after_update
    else: m.domain.probe.return_value = 502
    with pytest.raises(ValueError): m.execute(f.session, f.path)
    assert (f.path.parent / "execution.json").exists()
    assert not (f.path.parent / "verification.json").exists()


@pytest.mark.parametrize("fault", [None, "dev", "failed", "wrong_plan", "missing_endpoint", "wrong_status", "stale"])
def test_domain_gate_requires_exact_recent_prod_authenticated_evidence(tmp_path, monkeypatch, fault):
    f = setup(tmp_path, monkeypatch)
    record = {"environment": "prod", "changeSet": "domain-change", "passed": True,
        "observedAt": datetime.now(timezone.utc).isoformat(), "requests": [
            {"endpoint": p, "passed": True, "sameJson": True, "existing": {"status": 200}, "custom": {"status": 200}}
            for p in m.parity.ENDPOINTS]}
    if fault == "dev": record["environment"] = "dev"
    elif fault == "failed": record["passed"] = False
    elif fault == "wrong_plan": record["changeSet"] = "different"
    elif fault == "missing_endpoint": record["requests"].pop()
    elif fault == "wrong_status": record["requests"][0]["custom"]["status"] = 401
    elif fault == "stale": record["observedAt"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    m.write(tmp_path / "authenticated-verification.json", record)
    monkeypatch.setattr(m.parity, "targets", MagicMock(return_value=({"environment": "prod", "changeSet": "domain-change"}, OLD_URL, m.NEW[m.KEYS[0]] + m.NEW[m.KEYS[1]])))
    verification = MagicMock()
    monkeypatch.setattr(m.domain, "verify", verification)
    if fault:
        with pytest.raises(ValueError): f.gate(f.session, f.domain_path, authenticated=True)
        verification.assert_not_called()
    else:
        assert f.gate(f.session, f.domain_path, authenticated=True) == OLD_URL
        verification.assert_called_once()


@pytest.mark.parametrize("fault", [None, "api", "stage", "path", "extra", "tls", "unavailable", "dev_url"])
def test_future_image_release_accepts_only_same_prod_domain_mapping(fault):
    gateway = MagicMock()
    config = {"EndpointType": "REGIONAL", "SecurityPolicy": "TLS_1_2", "DomainNameStatus": "AVAILABLE"}
    mapping = {"ApiId": "prod123", "Stage": "v1", "ApiMappingKey": ""}
    mappings = [mapping]
    if fault == "api": mapping["ApiId"] = "dev123"
    elif fault == "stage": mapping["Stage"] = "other"
    elif fault == "path": mapping["ApiMappingKey"] = "api/v1"
    elif fault == "extra": mappings.append(copy.deepcopy(mapping))
    elif fault == "tls": config["SecurityPolicy"] = "TLS_1_0"
    elif fault == "unavailable": config["DomainNameStatus"] = "PENDING"
    gateway.get_domain_name.return_value = {"DomainNameConfigurations": [config]}
    gateway.get_api_mappings.return_value = {"Items": mappings}
    session = SimpleNamespace(client=lambda name: gateway)
    custom = "https://api-dev.navigan.click/api/v1" if fault == "dev_url" else "https://api.navigan.click/api/v1"
    if fault:
        with pytest.raises(RuntimeError): m.front.verify_api_target(session, custom, OLD_URL)
    else:
        m.front.verify_api_target(session, custom, OLD_URL)
        m.front.verify_api_target(session, OLD_URL, OLD_URL)
