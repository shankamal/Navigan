from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock
import urllib.error

from botocore.exceptions import ClientError
import pytest

ROOT = Path(__file__).parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


m = load("domain_release", ROOT / "scripts/deploy-api-domain.py")
a = load("domain_audit_fixtures", ROOT / "tests/test_api_domain_readiness.py")
ACCOUNT, REGION = "111111111111", "ap-south-1"


def fixture(tmp_path, monkeypatch):
    session, clients, args = a.fixture()
    gateway = clients["apigatewayv2"]
    gateway.get_routes.side_effect = None
    gateway.get_routes.return_value = {"Items": [{"RouteId": "summary", "RouteKey": "GET " + m.PROBE, "AuthorizationType": "JWT", "AuthorizerId": "jwt"}]}
    gateway.get_authorizers.return_value = {"Items": [{"AuthorizerId": "jwt", "AuthorizerType": "JWT"}]}
    gateway.get_api_mappings.return_value = {"Items": []}
    clients["acm"].get_paginator.return_value.paginate.return_value = [{"CertificateSummaryList": []}]
    original, raw = m.audit.audit(session, args)
    capture = tmp_path / "capture"
    capture.mkdir(mode=0o700)
    m.write(capture / "summary.json", original)
    m.write(capture / "observations.json", raw)
    clients["cloudformation"] = cfn = MagicMock()
    stack_id = f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/navigan-dev-api-domain/stack-id"
    change_id = f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:changeSet/api-domain-test/change-id"
    review = {"StackId": stack_id, "StackName": "navigan-dev-api-domain", "StackStatus": "REVIEW_IN_PROGRESS", "CreationTime": datetime.now(timezone.utc)}
    def describe(StackName):
        if StackName == "navigan-dev-api-domain":
            raise ClientError({"Error": {"Code": "ValidationError", "Message": "Stack does not exist"}}, "DescribeStacks")
        return {"Stacks": [review]}
    cfn.describe_stacks.side_effect = describe
    cfn.create_change_set.return_value = {"Id": change_id, "StackId": stack_id}
    params = {"ApiId": "dev123", "StageName": "v1", "DomainName": "api-dev.navigan.click", "HostedZoneId": "public"}
    meta = {"StackId": stack_id, "Status": "CREATE_COMPLETE", "ExecutionStatus": "AVAILABLE", "IncludeNestedStacks": False,
            "Parameters": [{"ParameterKey": key, "ParameterValue": value} for key, value in params.items()],
            "Changes": [{"ResourceChange": {"LogicalResourceId": key, "ResourceType": value, "Action": "Add", "Replacement": "False"}} for key, value in m.TYPES.items()]}
    cfn.describe_change_set.return_value = meta
    template = m.checked_template()
    cfn.get_template.return_value = {"TemplateBody": json.dumps(template)}
    proof = {"zoneName": "navigan.click", "nameservers": ["ns1.example.test"], "verifiedBy": ["dns.google"]}
    monkeypatch.setattr(m, "delegation", MagicMock(return_value=proof))
    def directory(**kwargs):
        path = tmp_path / "release"
        path.mkdir(mode=0o700)
        return str(path)
    monkeypatch.setattr(m.tempfile, "mkdtemp", directory)
    return session, clients, args, capture, original, raw, meta


def test_template_only_adds_certificate_domain_root_mapping_and_alias():
    template = m.checked_template()
    assert set(template["Resources"]) == set(m.TYPES)
    assert not {"AWS::ApiGatewayV2::Api", "AWS::ApiGatewayV2::Stage", "AWS::Lambda::Function", "AWS::IAM::Role", "AWS::ECS::Service"} & set(m.TYPES.values())
    assert template["Resources"]["Certificate"]["Properties"]["ValidationMethod"] == "DNS"
    assert template["Resources"]["Certificate"]["Properties"]["DomainValidationOptions"] == [{"DomainName": {"Ref": "DomainName"}, "HostedZoneId": {"Ref": "HostedZoneId"}}]
    assert template["Resources"]["RootMapping"]["Properties"] == {"ApiId": {"Ref": "ApiId"}, "Stage": {"Ref": "StageName"}, "DomainName": {"Ref": "ApiDomain"}}
    assert template["Resources"]["ApiDomain"]["Properties"]["DomainNameConfigurations"] == [{"EndpointType": "REGIONAL", "SecurityPolicy": "TLS_1_2", "CertificateArn": {"Ref": "Certificate"}}]


def test_prepare_checks_dns_and_snapshot_and_creates_only_an_unexecuted_companion_plan(tmp_path, monkeypatch):
    session, clients, _, capture, _, _, _ = fixture(tmp_path, monkeypatch)
    path = m.prepare(session, capture, "dev", ACCOUNT, REGION)
    plan = m.read(path)
    assert plan["parameters"]["DomainName"] == "api-dev.navigan.click"
    request = clients["cloudformation"].create_change_set.call_args.kwargs
    assert request["ChangeSetType"] == "CREATE" and request["StackName"] == "navigan-dev-api-domain"
    assert request["IncludeNestedStacks"] is False and "Capabilities" not in request
    assert (path.parent / "baseline/observations.json").exists()
    m.delegation.assert_called_once()
    clients["cloudformation"].execute_change_set.assert_not_called()


@pytest.mark.parametrize("fault", ["api", "stage", "routes", "authorization", "other_domain", "existing_domain", "dns", "certificate", "zone", "caa", "stack", "dns_delegation"])
def test_preparation_rejects_existing_resources_and_drift_before_creating_a_change_set(tmp_path, monkeypatch, fault):
    session, clients, _, capture, _, _, _ = fixture(tmp_path, monkeypatch)
    gateway = clients["apigatewayv2"]
    if fault == "api":
        old = gateway.get_api.side_effect
        gateway.get_api.side_effect = lambda **kwargs: {**old(**kwargs), "Name": "changed"}
    elif fault == "stage": gateway.get_stages.return_value["Items"][0]["AutoDeploy"] = False
    elif fault == "routes": gateway.get_routes.return_value["Items"].append({"RouteId": "new", "RouteKey": "GET /other"})
    elif fault == "authorization": gateway.get_authorizers.return_value["Items"][0]["JwtConfiguration"] = {"Audience": ["changed"]}
    elif fault in {"other_domain", "existing_domain"}:
        old = gateway.get_domain_name.side_effect
        target = "api.navigan.click" if fault == "other_domain" else "api-dev.navigan.click"
        gateway.get_domain_name.side_effect = lambda DomainName: {} if DomainName == target else (_ for _ in ()).throw(old)
    elif fault == "dns":
        clients["route53"].list_resource_record_sets.side_effect = lambda **kwargs: {"ResourceRecordSets": [{"Name": "api-dev.navigan.click.", "Type": "A", "ResourceRecords": [{"Value": "192.0.2.1"}]}]} if kwargs["StartRecordName"] == "api-dev.navigan.click." else {"ResourceRecordSets": []}
    elif fault == "certificate": clients["acm"].get_paginator.return_value.paginate.return_value = [{"CertificateSummaryList": [{"CertificateArn": "existing"}]}]
    elif fault == "zone": clients["route53"].get_paginator.return_value.paginate.return_value[0]["HostedZones"][1]["Id"] = "different"
    elif fault == "caa":
        clients["route53"].list_resource_record_sets.side_effect = lambda **kwargs: {"ResourceRecordSets": [{"Name": "navigan.click.", "Type": "CAA", "ResourceRecords": [{"Value": '0 issue "other.test"'}]}]} if kwargs["StartRecordName"] == "navigan.click." else {"ResourceRecordSets": []}
    elif fault == "stack":
        clients["cloudformation"].describe_stacks.side_effect = None
        clients["cloudformation"].describe_stacks.return_value = {"Stacks": [{"StackStatus": "CREATE_COMPLETE"}]}
    else: m.delegation.side_effect = ValueError("Delegation mismatch")
    with pytest.raises(ValueError): m.prepare(session, capture, "dev", ACCOUNT, REGION)
    clients["cloudformation"].create_change_set.assert_not_called()


@pytest.mark.parametrize("fault", ["modify", "remove", "replace", "extra", "missing", "duplicate", "parameters", "template", "stack", "update", "nested", "import", "parent", "review_identity"])
def test_prepared_plan_must_be_exactly_four_additions_with_no_existing_resource_actions(tmp_path, monkeypatch, fault):
    session, clients, _, capture, _, _, meta = fixture(tmp_path, monkeypatch)
    plan = m.read(m.prepare(session, capture, "dev", ACCOUNT, REGION))
    row = meta["Changes"][0]["ResourceChange"]
    if fault in {"modify", "remove"}: row["Action"] = fault.title()
    elif fault == "replace": row["Replacement"] = "True"
    elif fault == "extra": meta["Changes"].append({"ResourceChange": {"LogicalResourceId": "Api", "ResourceType": "AWS::ApiGatewayV2::Api", "Action": "Add"}})
    elif fault == "missing": meta["Changes"].pop()
    elif fault == "duplicate": meta["Changes"].append(deepcopy(meta["Changes"][0]))
    elif fault == "parameters": meta["Parameters"][0]["ParameterValue"] = "other-api"
    elif fault == "template": clients["cloudformation"].get_template.return_value["TemplateBody"] = "{}"
    elif fault == "stack": meta["StackId"] = "other-stack"
    elif fault in {"update", "parent", "review_identity"}:
        stack = clients["cloudformation"].describe_stacks(StackName=plan["stackId"])["Stacks"][0]
        if fault == "update": stack["StackStatus"] = "UPDATE_COMPLETE"
        elif fault == "parent": stack["ParentId"] = "parent-stack"
        else: stack["StackId"] = "other-stack"
    elif fault == "import": meta["ImportExistingResources"] = True
    else: meta["IncludeNestedStacks"] = True
    with pytest.raises(ValueError): m.inspect_plan(clients["cloudformation"], plan)
    clients["cloudformation"].execute_change_set.assert_not_called()


def test_execute_journals_and_runs_only_the_saved_companion_change_set(tmp_path, monkeypatch):
    session, clients, _, capture, _, _, _ = fixture(tmp_path, monkeypatch)
    path = m.prepare(session, capture, "dev", ACCOUNT, REGION)
    cfn = clients["cloudformation"]
    cfn.describe_stacks.side_effect = None
    plan = m.read(path)
    cfn.describe_stacks.return_value = {"Stacks": [{"StackId": plan["stackId"], "StackName": plan["stackName"], "StackStatus": "REVIEW_IN_PROGRESS"}]}
    verification = MagicMock()
    monkeypatch.setattr(m, "verify", verification)
    def execute(**kwargs):
        assert (path.parent / "execution.json").exists()
        assert kwargs["ChangeSetName"] == m.read(path)["changeSet"]
    cfn.execute_change_set.side_effect = execute
    m.execute(session, path, ACCOUNT, REGION)
    assert cfn.execute_change_set.call_count == 1
    verification.assert_called_once_with(session, path, ACCOUNT, REGION)
    with pytest.raises(ValueError, match="already requested"): m.execute(session, path, ACCOUNT, REGION)


def test_create_preview_fixture_matches_the_actual_sdk_response_shapes(tmp_path, monkeypatch):
    import botocore.session
    from botocore.validate import validate_parameters
    session, clients, _, capture, _, _, meta = fixture(tmp_path, monkeypatch)
    path = m.prepare(session, capture, "dev", ACCOUNT, REGION)
    plan = m.read(path)
    model = botocore.session.get_session().get_service_model("cloudformation")
    assert "ChangeSetType" not in model.operation_model("DescribeChangeSet").output_shape.members
    validate_parameters(meta, model.operation_model("DescribeChangeSet").output_shape)
    validate_parameters(clients["cloudformation"].describe_stacks(StackName=plan["stackId"]), model.operation_model("DescribeStacks").output_shape)
    m.inspect_plan(clients["cloudformation"], plan)
    clients["cloudformation"].execute_change_set.assert_not_called()


def verified_fixture(tmp_path, monkeypatch):
    session, clients, _, capture, _, _, _ = fixture(tmp_path, monkeypatch)
    path = m.prepare(session, capture, "dev", ACCOUNT, REGION)
    plan = m.read(path)
    cfn, gateway = clients["cloudformation"], clients["apigatewayv2"]
    cfn.describe_stacks.side_effect = None
    cfn.describe_stacks.return_value = {"Stacks": [{"StackStatus": "CREATE_COMPLETE", "Parameters": [{"ParameterKey": key, "ParameterValue": value} for key, value in plan["parameters"].items()]}]}
    cert_arn = f"arn:aws:acm:{REGION}:{ACCOUNT}:certificate/new"
    cfn.list_stack_resources.return_value = {"StackResourceSummaries": [{"LogicalResourceId": key, "ResourceType": value, "ResourceStatus": "CREATE_COMPLETE", "PhysicalResourceId": cert_arn if key == "Certificate" else "mapping" if key == "RootMapping" else "new-resource"} for key, value in m.TYPES.items()]}
    config = {"EndpointType": "REGIONAL", "SecurityPolicy": "TLS_1_2", "DomainNameStatus": "AVAILABLE", "CertificateArn": cert_arn, "ApiGatewayDomainName": "d-new.execute-api.ap-south-1.amazonaws.com", "HostedZoneId": "ZREGIONAL"}
    domain = {"DomainNameConfigurations": [config]}
    missing = gateway.get_domain_name.side_effect
    gateway.get_domain_name.side_effect = lambda DomainName: domain if DomainName == "api-dev.navigan.click" else (_ for _ in ()).throw(missing)
    mapping = {"ApiMappingId": "mapping", "ApiId": "dev123", "Stage": "v1", "ApiMappingKey": ""}
    gateway.get_api_mappings.return_value = {"Items": [mapping]}
    alias = {"Name": "api-dev.navigan.click.", "Type": "A", "AliasTarget": {"DNSName": config["ApiGatewayDomainName"] + ".", "HostedZoneId": "ZREGIONAL", "EvaluateTargetHealth": False}}
    clients["route53"].list_resource_record_sets.side_effect = lambda **kwargs: {"ResourceRecordSets": [alias]} if kwargs["StartRecordName"] == "api-dev.navigan.click." else {"ResourceRecordSets": []}
    now = datetime.now(timezone.utc)
    cert = {"CertificateArn": cert_arn, "DomainName": "api-dev.navigan.click", "Status": "ISSUED", "KeyAlgorithm": "RSA_2048", "NotBefore": now - timedelta(days=1), "NotAfter": now + timedelta(days=30)}
    clients["acm"].get_paginator.return_value.paginate.return_value = [{"CertificateSummaryList": [{"CertificateArn": cert_arn}]}]
    clients["acm"].describe_certificate.return_value = {"Certificate": cert}
    monkeypatch.setattr(m, "probe", MagicMock(return_value=401))
    monkeypatch.setattr(m.time, "sleep", lambda seconds: None)
    return session, clients, path, config, mapping, alias, cert


def test_verify_checks_new_resource_bindings_tls_401_and_unchanged_apis_without_reexecution(tmp_path, monkeypatch):
    session, clients, path, _, _, _, _ = verified_fixture(tmp_path, monkeypatch)
    m.verify(session, path, ACCOUNT, REGION)
    record = m.read(path.parent / "verification.json")
    assert record["oldEndpointRetained"] and record["tlsAndUnauthenticated401Verified"]
    assert record["authenticatedAcceptance"] is False and record["frontendChanged"] is False
    clients["cloudformation"].execute_change_set.assert_not_called()


@pytest.mark.parametrize("fault", ["domain", "mapping_id", "mapping_stage", "mapping_path", "alias", "certificate", "routes", "tls", "old_http", "new_http", "parameter", "extra_resource"])
def test_verify_rejects_incorrect_dns_certificate_mapping_identity_and_behavior(tmp_path, monkeypatch, fault):
    session, clients, path, config, mapping, alias, cert = verified_fixture(tmp_path, monkeypatch)
    if fault == "domain": config["DomainNameStatus"] = "PENDING"
    elif fault == "mapping_id": mapping["ApiMappingId"] = "other"
    elif fault == "mapping_stage": mapping["Stage"] = "other"
    elif fault == "mapping_path": mapping["ApiMappingKey"] = "api/v1"
    elif fault == "alias": alias["AliasTarget"]["DNSName"] = "other.example.test"
    elif fault == "certificate": cert["Status"] = "PENDING_VALIDATION"
    elif fault == "routes": clients["apigatewayv2"].get_routes.return_value["Items"][0]["AuthorizationType"] = "NONE"
    elif fault == "tls": m.probe.side_effect = lambda url: 401 if "execute-api" in url else (_ for _ in ()).throw(urllib.error.URLError("TLS error"))
    elif fault == "old_http": m.probe.return_value = 403
    elif fault == "new_http": m.probe.side_effect = lambda url: 401 if "execute-api" in url else 404
    elif fault == "parameter": clients["cloudformation"].describe_stacks.return_value["Stacks"][0]["Parameters"][0]["ParameterValue"] = "other"
    else: clients["cloudformation"].list_stack_resources.return_value["StackResourceSummaries"].append({"LogicalResourceId": "Other", "ResourceType": "AWS::Lambda::Function", "ResourceStatus": "CREATE_COMPLETE"})
    with pytest.raises(ValueError): m.verify(session, path, ACCOUNT, REGION)
    assert not (path.parent / "verification.json").exists()
    clients["cloudformation"].execute_change_set.assert_not_called()


@pytest.mark.parametrize("fault", ["mismatch", "nxdomain", "unreachable"])
def test_delegation_requires_public_ns_answers_matching_the_selected_zone(monkeypatch, fault):
    request = MagicMock()
    request.__enter__.return_value = request
    if fault == "unreachable": monkeypatch.setattr(m.urllib.request, "urlopen", MagicMock(side_effect=urllib.error.URLError("unreachable")))
    else:
        monkeypatch.setattr(m.urllib.request, "urlopen", lambda *args, **kwargs: request)
        monkeypatch.setattr(m.json, "load", lambda response: {"Status": 3 if fault == "nxdomain" else 0, "Answer": [{"name": "navigan.click.", "type": 2, "data": "wrong.example.test."}]})
    with pytest.raises(ValueError): m.delegation("navigan.click", ["ns1.example.test"])


def test_delegation_supports_one_unreachable_resolver_but_rejects_disagreement(monkeypatch):
    request = MagicMock()
    request.__enter__.return_value = request
    monkeypatch.setattr(m.urllib.request, "urlopen", MagicMock(side_effect=[urllib.error.URLError("unreachable"), request]))
    monkeypatch.setattr(m.json, "load", lambda response: {"Status": 0, "Answer": [{"name": "navigan.click.", "type": 2, "data": "NS1.EXAMPLE.TEST."}]})
    result = m.delegation("navigan.click", ["ns1.example.test"])
    assert result["verifiedBy"] == ["cloudflare-dns.com"] and result["unreachableResolvers"] == ["dns.google"]
