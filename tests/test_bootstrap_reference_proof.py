from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("reference_release", ROOT / "scripts/deploy-cluster-bootstrap-prod.py")
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
ref = h.references
PREVIEW = f"arn:aws:cloudformation:{h.REGION}:{h.ACCOUNT}:changeSet/bootstrap-preview-test/11111111-2222-3333-4444-555555555555"


def fixture():
    root_id = f"arn:aws:cloudformation:{h.REGION}:{h.ACCOUNT}:stack/{h.PARENT}/root"
    child_id = root_id + "-child"
    shared_id = root_id + "-shared"
    root_parameters = {"TerraformRunnerImageUri": "old", "DatabaseName": "navigan", "PrivateSubnetIds": "subnet-a, subnet-b"}
    child_parameters = {"TerraformRunnerImageUri": "old", "DatabaseName": "navigan", "PrivateSubnetIds": "subnet-a,subnet-b",
                        "ApiId": "testapi", "AuthorizerId": "testauth", "Flag": "false"}
    root = {"Parameters": {name: {"Type": "List<AWS::EC2::Subnet::Id>" if name == "PrivateSubnetIds" else "String"} for name in root_parameters},
            "Resources": {"SharedPlatform": {"Type": "AWS::CloudFormation::Stack"}, "ClusterManagement": {"Type": "AWS::CloudFormation::Stack", "Properties": {"TemplateURL": "old", "Parameters": {
                **{name: {"Ref": name} for name in root_parameters}, "ApiId": {"Fn::GetAtt": ["SharedPlatform", "Outputs.ApiId"]},
                "AuthorizerId": {"Fn::GetAtt": "SharedPlatform.Outputs.AuthorizerId"},
                "PrivateSubnetIds": {"Fn::Join": [",", {"Ref": "PrivateSubnetIds"}]}}}}}}
    resources = {name: {"Type": "AWS::Lambda::Function", "Properties": {"Code": {"S3Bucket": "before"}, "Role": "preserve"}} for name in h.FUNCTIONS}
    resources.update({
        "TerraformProject": {"Type": "AWS::CodeBuild::Project", "Properties": {"Environment": {"Image": {"Ref": "TerraformRunnerImageUri"}}}},
        "BuildStateRule": {"Type": "AWS::Events::Rule", "Properties": {"Targets": [{"Id": "ClusterStatus", "Arn": {"Fn::GetAtt": ["StatusFunction", "Arn"]}}]}},
        "BuildStatePermission": {"Type": "AWS::Lambda::Permission", "Properties": {"Action": "lambda:InvokeFunction", "Principal": "events.amazonaws.com",
            "FunctionName": {"Ref": "StatusFunction"}, "SourceArn": {"Fn::GetAtt": ["BuildStateRule", "Arn"]}}},
        "ClusterIntegration": {"Type": "AWS::ApiGatewayV2::Integration", "Properties": {"ApiId": {"Ref": "ApiId"}, "IntegrationUri": {"Fn::GetAtt": ["ClusterFunction", "Arn"]}}},
        "ApplyRoute": {"Type": "AWS::ApiGatewayV2::Route", "Properties": {"ApiId": {"Ref": "ApiId"}, "AuthorizerId": {"Ref": "AuthorizerId"}, "Target": {"Ref": "ClusterIntegration"}}},
    })
    before = {"Parameters": {name: {"Type": "String", **({"Default": "false"} if name == "Flag" else {})} for name in child_parameters}, "Resources": resources}
    after = deepcopy(before)
    for name in h.FUNCTIONS:
        after["Resources"][name]["Properties"]["Code"] = {"S3Bucket": "new", "S3Key": name, "S3ObjectVersion": "version"}
    saved = {"rootTemplate": root, "childTemplate": before,
             "root": {"StackId": root_id, "Parameters": [{"ParameterKey": k, "ParameterValue": v} for k, v in root_parameters.items()]},
             "child": {"StackId": child_id, "Parameters": [{"ParameterKey": k, "ParameterValue": v} for k, v in child_parameters.items()]},
             "configs": {name: {"FunctionArn": f"arn:aws:lambda:{h.REGION}:{h.ACCOUNT}:function:{name}"} for name in h.FUNCTIONS}}
    plan = {"changeSet": "root-plan", "newImage": "new-image", "childHash": h.fingerprint(after)}
    clients = {name: MagicMock() for name in ("cloudformation", "apigatewayv2", "events")}
    session = MagicMock()
    session.client.side_effect = clients.__getitem__
    meta = {"StackId": child_id, "Status": "CREATE_COMPLETE", "ExecutionStatus": "AVAILABLE", "Parameters": [
        {"ParameterKey": k, **({"ParameterValue": "new-image"} if k == "TerraformRunnerImageUri" else {"UsePreviousValue": True})}
        for k in child_parameters]}
    rows = []
    for name, kind, field, replacement, recreation, source in (
        ("ClusterFunction", "AWS::Lambda::Function", "Code", "False", "Never", None),
        ("StatusFunction", "AWS::Lambda::Function", "Code", "False", "Never", None),
        ("TerraformProject", "AWS::CodeBuild::Project", "Environment", "False", "Never", None),
        ("ClusterIntegration", "AWS::ApiGatewayV2::Integration", "IntegrationUri", "False", "Never", "ClusterFunction.Arn"),
        ("BuildStateRule", "AWS::Events::Rule", "Targets", "False", "Never", "StatusFunction.Arn"),
        ("BuildStatePermission", "AWS::Lambda::Permission", "SourceArn", "Conditional", "Always", "BuildStateRule.Arn"),
    ):
        rows.append({"ResourceChange": {"LogicalResourceId": name, "ResourceType": kind, "Action": "Modify", "Replacement": replacement, "Details": [{
            "Target": {"Attribute": "Properties", "Name": field, "RequiresRecreation": recreation},
            "Evaluation": "Dynamic" if source else "Static", "ChangeSource": "ResourceAttribute" if source else "DirectModification",
            **({"CausingEntity": source} if source else {})}]}})
    meta["Changes"] = rows
    cfn = clients["cloudformation"]
    cfn.describe_change_set.return_value = meta
    cfn.get_template.return_value = {"TemplateBody": after}
    shared = {"StackId": shared_id, "ParentId": root_id, "StackStatus": "UPDATE_COMPLETE", "CreationTime": "initial",
              "Outputs": [{"OutputKey": "ApiId", "OutputValue": "testapi"}, {"OutputKey": "AuthorizerId", "OutputValue": "testauth"}]}
    cfn.describe_stack_resource.return_value = {"StackResourceDetail": {"PhysicalResourceId": shared_id}}
    cfn.describe_stacks.return_value = {"Stacks": [shared]}
    cfn.list_stack_resources.return_value = {"StackResourceSummaries": [{"LogicalResourceId": k, "ResourceType": v["Type"], "PhysicalResourceId": "physical-" + k} for k, v in resources.items()]}
    gateway = clients["apigatewayv2"]
    gateway.get_api.return_value = {"ApiId": "testapi", "ProtocolType": "HTTP", "ApiEndpoint": "https://api.example.test"}
    gateway.get_authorizer.return_value = {"AuthorizerId": "testauth", "AuthorizerType": "JWT", "JwtConfiguration": {"Issuer": "preserve-issuer"}}
    gateway.get_routes.return_value = {"Items": [{"RouteId": "route", "AuthorizationType": "JWT", "AuthorizerId": "testauth"}]}
    gateway.get_integrations.return_value = {"Items": [{"IntegrationId": "integration", "IntegrationUri": saved["configs"]["ClusterFunction"]["FunctionArn"]}]}
    gateway.get_stages.return_value = {"Items": [{"StageName": "v1", "AutoDeploy": True, "DeploymentId": "auto-deployment"}]}
    clients["events"].describe_rule.return_value = {"Name": "physical-BuildStateRule", "Arn": f"arn:aws:events:{h.REGION}:{h.ACCOUNT}:rule/physical-BuildStateRule", "State": "ENABLED"}
    clients["events"].list_targets_by_rule.return_value = {"Targets": [{"Id": "ClusterStatus", "Arn": saved["configs"]["StatusFunction"]["FunctionArn"]}]}
    return session, clients, saved, plan, meta, shared


def test_concrete_preview_proves_old_api_values_and_stable_callback_arns_without_writes():
    session, clients, saved, plan, _, _ = fixture()
    proof = ref.verify(h.proof_context(), session, saved, plan, PREVIEW)
    assert proof["inputs"]["parameters"]["ApiId"] == "testapi"
    assert proof["inputs"]["parameters"]["PrivateSubnetIds"] == "subnet-a,subnet-b"
    ref.unchanged(h.proof_context(), session, saved, plan, proof)
    writes = {"execute_change_set", "create_change_set", "update_function_code", "update_project", "update_route", "put_rule"}
    for client in clients.values():
        assert not {call[0] for call in client.method_calls} & writes


@pytest.mark.parametrize("fault", ["api_value", "authorizer_value", "image_value", "sibling_updating", "sibling_parent", "expression", "default_drift", "redacted"])
def test_binding_resolution_rejects_changes_and_unknown_values(fault):
    session, clients, saved, plan, _, shared = fixture()
    if fault == "api_value": shared["Outputs"][0]["OutputValue"] = "different-api"
    elif fault == "authorizer_value": shared["Outputs"][1]["OutputValue"] = "different-authorizer"
    elif fault == "image_value": saved["rootTemplate"]["Resources"]["ClusterManagement"]["Properties"]["Parameters"]["TerraformRunnerImageUri"] = "other-image"
    elif fault == "sibling_updating": shared["StackStatus"] = "UPDATE_IN_PROGRESS"
    elif fault == "sibling_parent": shared["ParentId"] = "another-root"
    elif fault == "expression": saved["rootTemplate"]["Resources"]["ClusterManagement"]["Properties"]["Parameters"]["ApiId"] = {"Fn::ImportValue": "unknown"}
    elif fault == "default_drift": saved["childTemplate"]["Parameters"]["Flag"]["Default"] = "true"
    else: saved["root"]["Parameters"][1]["ParameterValue"] = "****"
    with pytest.raises(ValueError): ref.resolve_inputs(h.proof_context(), clients["cloudformation"], saved, plan)


@pytest.mark.parametrize("fault", ["route_replacement", "function_replacement", "project_property", "wrong_arn_source", "permission_true", "definition", "parameter", "wrong_stack", "unavailable", "wrong_template"])
def test_concrete_preview_keeps_actual_replacements_and_unrelated_changes_blocked(fault):
    session, clients, saved, plan, meta, _ = fixture()
    rows = meta["Changes"]
    if fault == "route_replacement":
        rows.append({"ResourceChange": {"LogicalResourceId": "ApplyRoute", "ResourceType": "AWS::ApiGatewayV2::Route", "Action": "Modify", "Replacement": "True", "Details": [{"Target": {"Attribute": "Properties", "Name": "ApiId"}}]}})
    elif fault == "function_replacement": rows[0]["ResourceChange"]["Replacement"] = "True"
    elif fault == "project_property": rows[2]["ResourceChange"]["Details"][0]["Target"]["Name"] = "ServiceRole"
    elif fault == "wrong_arn_source": rows[-1]["ResourceChange"]["Details"][0]["CausingEntity"] = "OtherRule.Arn"
    elif fault == "permission_true": rows[-1]["ResourceChange"]["Replacement"] = "True"
    elif fault == "definition": saved["childTemplate"]["Resources"]["ClusterIntegration"]["Properties"]["ApiId"] = "changed"
    elif fault == "parameter": meta["Parameters"][0]["ParameterValue"] = "other-image"
    elif fault == "wrong_stack": meta["StackId"] = "wrong"
    elif fault == "unavailable": meta["ExecutionStatus"] = "OBSOLETE"
    else: plan["childHash"] = "changed"
    with pytest.raises(ValueError): ref.verify(h.proof_context(), session, saved, plan, PREVIEW)


@pytest.mark.parametrize("fault", ["api_auth", "callback_target", "rule_identity", "physical_identity"])
def test_live_identity_changes_invalidate_reference_proof(fault):
    session, clients, saved, plan, _, _ = fixture()
    proof = ref.verify(h.proof_context(), session, saved, plan, PREVIEW)
    if fault == "api_auth": clients["apigatewayv2"].get_routes.return_value["Items"][0]["AuthorizationType"] = "NONE"
    elif fault == "callback_target": clients["events"].list_targets_by_rule.return_value["Targets"][0]["Arn"] = "different"
    elif fault == "rule_identity": clients["events"].describe_rule.return_value["Arn"] = "different"
    else: clients["cloudformation"].list_stack_resources.return_value["StackResourceSummaries"][0]["PhysicalResourceId"] = "different"
    with pytest.raises(ValueError): ref.unchanged(h.proof_context(), session, saved, plan, proof)


def test_post_deployment_allows_auto_deployment_metadata_but_preserves_api_configuration():
    session, clients, saved, plan, _, _ = fixture()
    proof = ref.verify(h.proof_context(), session, saved, plan, PREVIEW)
    clients["apigatewayv2"].get_stages.return_value["Items"][0]["DeploymentId"] = "new-auto-deployment"
    ref.after_deployment(h.proof_context(), session, saved, proof)
    clients["apigatewayv2"].get_authorizer.return_value["JwtConfiguration"]["Issuer"] = "other-issuer"
    with pytest.raises(ValueError): ref.after_deployment(h.proof_context(), session, saved, proof)


def parent_preview():
    session, clients, saved, plan, meta, _ = fixture()
    cfn = clients["cloudformation"]
    after = deepcopy(cfn.get_template.return_value["TemplateBody"])
    root_after = deepcopy(saved["rootTemplate"])
    root_after["Resources"]["ClusterManagement"]["Properties"]["TemplateURL"] = "new"
    plan["rootHash"] = h.fingerprint(root_after)
    root_parameters = deepcopy(saved["root"]["Parameters"])
    root_parameters[0]["ParameterValue"] = plan["newImage"]
    root_meta = {"StackId": saved["root"]["StackId"], "Status": "CREATE_COMPLETE", "ExecutionStatus": "AVAILABLE",
                 "Parameters": root_parameters, "Changes": [{"ResourceChange": {"LogicalResourceId": "ClusterManagement",
                 "ResourceType": "AWS::CloudFormation::Stack", "Action": "Modify", "Replacement": "False", "ChangeSetId": "nested-parent"}}]}
    parent_rows = deepcopy(meta["Changes"])
    parent_rows.append({"ResourceChange": {"LogicalResourceId": "ApplyRoute", "ResourceType": "AWS::ApiGatewayV2::Route", "Action": "Modify", "Replacement": "True", "Details": [
        {"Target": {"Attribute": "Properties", "Name": "ApiId", "RequiresRecreation": "Always"}, "Evaluation": "Static", "ChangeSource": "ParameterReference", "CausingEntity": "ApiId"}]}})
    cfn.describe_change_set.side_effect = lambda **kw: meta if kw["ChangeSetName"] == PREVIEW else root_meta if kw["ChangeSetName"] == plan["changeSet"] else {"StackId": saved["child"]["StackId"], "Changes": parent_rows}
    cfn.get_template.side_effect = lambda **kw: {"TemplateBody": root_after if kw["ChangeSetName"] == plan["changeSet"] else after}
    return session, clients, saved, plan, parent_rows


def test_parent_warnings_require_a_matching_live_concrete_reference_proof():
    session, clients, saved, plan, _ = parent_preview()
    cfn = clients["cloudformation"]
    with pytest.raises(ValueError): h.inspect_change_set(cfn, saved, plan)
    proof = ref.verify(h.proof_context(), session, saved, plan, PREVIEW)
    h.inspect_change_set(cfn, saved, plan, reference_proof=proof)
    cfn.execute_change_set.assert_not_called()


@pytest.mark.parametrize("fault", ["other_release", "function_replacement", "changed_dependency"])
def test_reference_proof_does_not_permit_other_release_or_real_resource_changes(fault):
    session, clients, saved, plan, rows = parent_preview()
    proof = ref.verify(h.proof_context(), session, saved, plan, PREVIEW)
    if fault == "other_release": proof["releaseChangeSet"] = "other-release"
    elif fault == "function_replacement": rows[0]["ResourceChange"]["Replacement"] = "True"
    else: rows[-1]["ResourceChange"]["Details"][0]["Target"]["Name"] = "AuthorizationType"
    with pytest.raises(ValueError): h.inspect_change_set(clients["cloudformation"], saved, plan, reference_proof=proof)
    clients["cloudformation"].execute_change_set.assert_not_called()


def fresh_parent_fixture():
    session, clients, saved, plan, _ = parent_preview()
    cfn = clients["cloudformation"]
    root_after = deepcopy(saved["rootTemplate"])
    root_after["Resources"]["ClusterManagement"]["Properties"]["TemplateURL"] = "new"
    meta = {"StackId": saved["root"]["StackId"], "Status": "CREATE_COMPLETE", "ExecutionStatus": "AVAILABLE", "IncludeNestedStacks": False,
            "Parameters": [{"ParameterKey": item["ParameterKey"], **({"ParameterValue": plan["newImage"]} if item["ParameterKey"] == "TerraformRunnerImageUri" else {"UsePreviousValue": True})} for item in saved["root"]["Parameters"]],
            "Changes": [{"ResourceChange": {"LogicalResourceId": "ClusterManagement", "ResourceType": "AWS::CloudFormation::Stack", "Action": "Modify", "Replacement": "False"}}]}
    cfn.describe_change_set.side_effect = None
    cfn.describe_change_set.return_value = meta
    cfn.get_template.side_effect = None
    cfn.get_template.return_value = {"TemplateBody": root_after}
    cfn.create_change_set.return_value = {"Id": "fresh-parent"}
    return session, clients, saved, plan, meta


def test_replanning_keeps_parent_ownership_and_never_executes_old_or_diagnostic_plans(tmp_path):
    session, clients, saved, plan, _ = fresh_parent_fixture()
    identifier = ref.parent_plan(h.proof_context(), session, saved, plan, tmp_path)
    assert identifier == "fresh-parent"
    request = clients["cloudformation"].create_change_set.call_args.kwargs
    assert request["StackName"] == h.PARENT and request["IncludeNestedStacks"] is False
    assert h.fingerprint(json.loads(request["TemplateBody"])) == plan["rootHash"]
    clients["cloudformation"].execute_change_set.assert_not_called()
    assert json.loads((tmp_path / "resolved-parent-plan.json").read_text())["sourceChangeSet"] == plan["changeSet"]


@pytest.mark.parametrize("fault", ["nested_plan", "replacement", "other_module", "parameter", "template", "unavailable"])
def test_fresh_parent_plan_is_not_a_replacement_or_binding_change_escape_hatch(fault):
    session, clients, saved, plan, meta = fresh_parent_fixture()
    if fault == "nested_plan": meta["Changes"][0]["ResourceChange"]["ChangeSetId"] = "bad-child"
    elif fault == "replacement": meta["Changes"][0]["ResourceChange"]["Replacement"] = "True"
    elif fault == "other_module": meta["Changes"][0]["ResourceChange"]["LogicalResourceId"] = "SharedPlatform"
    elif fault == "parameter": meta["Parameters"][1] = {"ParameterKey": "DatabaseName", "ParameterValue": "other-db"}
    elif fault == "template": plan["rootHash"] = "different"
    else: meta["ExecutionStatus"] = "OBSOLETE"
    with pytest.raises(ValueError): ref.inspect_parent(h.proof_context(), clients["cloudformation"], saved, plan, "fresh-parent")
    clients["cloudformation"].execute_change_set.assert_not_called()


def test_execute_selects_only_the_fresh_parent_after_all_preflight_checks(tmp_path, monkeypatch):
    session, clients, saved, plan, _, _ = fixture()
    plan.update(format=h.FORMAT, account=h.ACCOUNT, region=h.REGION, parent=h.PARENT, baseline=str(tmp_path))
    plan["newImage"] = f"{h.ACCOUNT}.dkr.ecr.{h.REGION}.amazonaws.com/navigan-terraform-runner@sha256:" + "a" * 64
    path = tmp_path / "release-plan.json"
    path.write_text(json.dumps(plan))
    monkeypatch.setattr(h, "baseline", lambda path: saved)
    monkeypatch.setattr(h, "preflight", lambda *args: None)
    monkeypatch.setattr(h, "inspect_change_set", lambda *args, **kwargs: None)
    monkeypatch.setattr(ref, "verify", lambda *args: {"preview": PREVIEW})
    monkeypatch.setattr(ref, "parent_plan", lambda *args: "fresh-parent")
    monkeypatch.setattr(ref, "unchanged", lambda *args: None)
    monkeypatch.setattr(ref, "inspect_parent", lambda *args: None)
    # Stop immediately after recording the selected execution target, before
    # post-deployment AWS verification; no real clients are used in this test.
    clients["cloudformation"].execute_change_set.side_effect = RuntimeError("execution target recorded")
    with pytest.raises(RuntimeError, match="execution target recorded"):
        h.execute(session, path, PREVIEW)
    clients["cloudformation"].execute_change_set.assert_called_once_with(ChangeSetName="fresh-parent")
