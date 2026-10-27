"""Resolve unchanged nested-stack bindings before accepting dependency warnings.

Never executes a preview or changes a binding. The parent release remains the
only executed change set. Unknown expressions, changed identities and actual
replacements in the concrete preview remain blocked.
"""
import copy
import json
import re
import uuid


def resolve_inputs(h, cfn, saved, plan):
    root = saved["rootTemplate"]
    values = h.parameters(saved["root"])
    values["TerraformRunnerImageUri"] = plan["newImage"]
    definitions = root.get("Parameters", {})
    siblings = {}
    pseudo = {"AWS::Region": h.REGION, "AWS::AccountId": h.ACCOUNT, "AWS::Partition": "aws",
              "AWS::StackName": h.PARENT, "AWS::StackId": saved["root"]["StackId"], "AWS::URLSuffix": "amazonaws.com"}

    def resolve(value):
        if isinstance(value, list):
            return [resolve(item) for item in value]
        if not isinstance(value, dict):
            h.require(isinstance(value, (str, int, float, bool)), "Unsupported nested parameter value.")
            return value
        if set(value) == {"Ref"}:
            name = value["Ref"]
            if name in pseudo:
                return pseudo[name]
            h.require(name in definitions and name in values, "Unknown root parameter reference.")
            kind = definitions[name].get("Type", "String")
            h.require(not kind.startswith("AWS::SSM::") and values[name] != "****", "Mutable or redacted parameter cannot be independently resolved.")
            return [part.strip() for part in values[name].split(",")] if kind == "CommaDelimitedList" or kind.startswith("List<") else values[name]
        if set(value) == {"Fn::GetAtt"}:
            parts = value["Fn::GetAtt"]
            parts = parts.split(".", 1) if isinstance(parts, str) else parts
            h.require(isinstance(parts, list) and len(parts) == 2 and parts[1].startswith("Outputs."), "Only sibling stack outputs may be resolved.")
            name, output = parts[0], parts[1][len("Outputs."):]
            h.require(name != "ClusterManagement" and root["Resources"].get(name, {}).get("Type") == "AWS::CloudFormation::Stack", "Changed or unknown output producer.")
            if name not in siblings:
                physical = cfn.describe_stack_resource(StackName=saved["root"]["StackId"], LogicalResourceId=name)["StackResourceDetail"]["PhysicalResourceId"]
                stack = cfn.describe_stacks(StackName=physical)["Stacks"][0]
                h.audit.validate_stack(stack, h.ACCOUNT, h.REGION, saved["root"]["StackId"])
                siblings[name] = {"stackId": physical, "stamp": h.stamp(stack), "outputs": {
                    item["OutputKey"]: item["OutputValue"] for item in stack.get("Outputs", [])}}
            h.require(output in siblings[name]["outputs"], "Sibling output is missing.")
            return siblings[name]["outputs"][output]
        if set(value) == {"Fn::Join"}:
            delimiter, items = value["Fn::Join"]
            items = resolve(items)
            h.require(isinstance(delimiter, str) and isinstance(items, list), "Invalid nested Join.")
            return delimiter.join(string(item) for item in items)
        h.require(False, "Unsupported nested parameter expression requires review.")

    def string(value):
        if isinstance(value, list):
            return ",".join(string(item) for item in value)
        h.require(isinstance(value, (str, int, float, bool)), "Invalid resolved parameter value.")
        return str(value).lower() if isinstance(value, bool) else str(value)

    expected = h.parameters(saved["child"])
    expected["TerraformRunnerImageUri"] = plan["newImage"]
    bindings = root["Resources"]["ClusterManagement"]["Properties"]["Parameters"]
    h.require(set(bindings) <= set(expected), "Unexpected parent-to-child parameter binding.")
    resolved = {}
    for name in expected:
        if name in bindings:
            resolved[name] = string(resolve(bindings[name]))
        else:
            definition = saved["childTemplate"].get("Parameters", {}).get(name, {})
            h.require("Default" in definition, "An omitted required child parameter cannot be resolved.")
            resolved[name] = string(definition["Default"])
        h.require(resolved[name] == expected[name], "Parent binding would change child parameter: " + name)
    return {"parameters": resolved, "siblings": siblings}


def names(details):
    return {item.get("Target", {}).get("Name") for item in details}


def dependency(h, row, before, after, *, concrete):
    logical, kind = row["LogicalResourceId"], row["ResourceType"]
    h.require(row.get("Action") == "Modify" and not row.get("ChangeSetId"), "Dependency additions/deletions/nesting are blocked.")
    h.require(before.get(logical) == after.get(logical) and before.get(logical, {}).get("Type") == kind,
              "A dependency definition changed: " + logical)
    details = row.get("Details") or []
    h.require(details and all(item.get("Target", {}).get("Attribute") == "Properties" for item in details), "Unknown dependency change details.")
    allowed = {"ClusterIntegration": ("AWS::ApiGatewayV2::Integration", "IntegrationUri", "ClusterFunction.Arn", "Never", "False"),
               "BuildStateRule": ("AWS::Events::Rule", "Targets", "StatusFunction.Arn", "Never", "False"),
               "BuildStatePermission": ("AWS::Lambda::Permission", "SourceArn", "BuildStateRule.Arn", "Always", "Conditional")}
    if concrete:
        h.require(logical in allowed, "Unexpected dependency in concrete preview: " + logical)
        wanted_kind, field, producer, recreation, replacement = allowed[logical]
        h.require(kind == wanted_kind and row.get("Replacement") == replacement and all(
            item["Target"].get("Name") == field and item["Target"].get("RequiresRecreation") == recreation
            and item.get("Evaluation") == "Dynamic" and item.get("ChangeSource") == "ResourceAttribute"
            and item.get("CausingEntity") == producer for item in details), "Concrete dependency is not the verified stable-ARN case.")
    else:
        if logical in {"BuildStateRule", "BuildStatePermission"}:
            return dependency(h, row, before, after, concrete=True)
        fields = {"AWS::ApiGatewayV2::Route": {"ApiId", "AuthorizerId", "Target"},
                  "AWS::ApiGatewayV2::Integration": {"ApiId", "IntegrationUri"},
                  "AWS::Lambda::Permission": {"SourceArn"}}
        h.require(kind in fields and names(details) <= fields[kind], "Unrelated parent dependency: " + logical)
        h.require(row.get("Replacement") in {"False", "True", "Conditional"}, "Unknown parent replacement result.")


def snapshot(h, session, saved, inputs):
    cfn = session.client("cloudformation")
    resources = h.items(cfn, "list_stack_resources", "StackResourceSummaries", StackName=saved["child"]["StackId"])
    physical = {r["LogicalResourceId"]: {"type": r["ResourceType"], "id": r["PhysicalResourceId"]}
                for r in resources if r.get("PhysicalResourceId") and r.get("ResourceStatus") != "DELETE_COMPLETE"}
    api_id, authorizer = inputs["parameters"]["ApiId"], inputs["parameters"]["AuthorizerId"]
    gateway = session.client("apigatewayv2")
    api = gateway.get_api(ApiId=api_id)
    api.pop("ResponseMetadata", None)
    auth = gateway.get_authorizer(ApiId=api_id, AuthorizerId=authorizer)
    auth.pop("ResponseMetadata", None)
    h.require(api.get("ApiId") == api_id and api.get("ProtocolType") == "HTTP"
              and auth.get("AuthorizerId") == authorizer and auth.get("AuthorizerType") == "JWT", "Existing API/JWT identity could not be verified.")
    api_state = {"api": api, "authorizer": auth}
    for operation, key, name in (("get_routes", "RouteId", "routes"), ("get_integrations", "IntegrationId", "integrations"), ("get_stages", "StageName", "stages")):
        rows, token = [], None
        while True:
            page = getattr(gateway, operation)(ApiId=api_id, **({"NextToken": token} if token else {}))
            rows.extend(page.get("Items", []))
            token = page.get("NextToken")
            if not token:
                break
        if name == "stages":
            for row in rows:
                row.pop("LastUpdatedDate", None)
                row.pop("LastDeploymentStatusMessage", None)
                if row.get("AutoDeploy"):
                    row.pop("DeploymentId", None)
        api_state[name] = sorted(rows, key=lambda item: item[key])
    before = saved["childTemplate"]["Resources"]
    rule = before["BuildStateRule"]["Properties"]
    permission = before["BuildStatePermission"]["Properties"]
    h.require(rule.get("EventBusName", "default") == "default" and permission.get("SourceArn") == {"Fn::GetAtt": ["BuildStateRule", "Arn"]}
              and permission.get("FunctionName") == {"Ref": "StatusFunction"}
              and permission.get("Principal") == "events.amazonaws.com" and permission.get("Action") == "lambda:InvokeFunction",
              "Unknown EventBridge permission identity.")
    rule_name = physical["BuildStateRule"]["id"]
    events = session.client("events")
    actual = events.describe_rule(Name=rule_name)
    actual.pop("ResponseMetadata", None)
    h.require(actual.get("Arn") == f"arn:aws:events:{h.REGION}:{h.ACCOUNT}:rule/{rule_name}", "EventBridge rule ARN differs from its physical identity.")
    targets = h.items(events, "list_targets_by_rule", "Targets", Rule=rule_name)
    desired = copy.deepcopy(rule.get("Targets"))
    h.require(isinstance(desired, list), "Rule targets are missing.")
    for target in desired:
        h.require(target.get("Arn") == {"Fn::GetAtt": ["StatusFunction", "Arn"]}, "Unexpected rule target identity.")
        target["Arn"] = saved["configs"]["StatusFunction"]["FunctionArn"]
    h.require(sorted(targets, key=lambda item: item["Id"]) == sorted(desired, key=lambda item: item["Id"]), "Live rule targets differ from the preserved template.")
    return copy.deepcopy({"physical": physical, "api": api_state, "rule": actual, "targets": targets})


def verify(h, session, saved, plan, preview_arn):
    h.require(re.fullmatch(rf"arn:aws:cloudformation:{h.REGION}:{h.ACCOUNT}:changeSet/[A-Za-z0-9-]+/[a-f0-9-]+", preview_arn), "Unexpected concrete preview ARN.")
    cfn = session.client("cloudformation")
    meta = cfn.describe_change_set(ChangeSetName=preview_arn)
    h.require(meta.get("StackId") == saved["child"]["StackId"] and meta.get("Status") == "CREATE_COMPLETE"
              and meta.get("ExecutionStatus") == "AVAILABLE" and not meta.get("ParentChangeSetId"), "Concrete preview is not an independent, available child-stack preview.")
    inputs = resolve_inputs(h, cfn, saved, plan)
    previous = h.parameters(saved["child"])
    chosen = {}
    for item in meta.get("Parameters", []):
        name = item["ParameterKey"]
        h.require(name not in chosen, "Duplicate concrete preview parameter.")
        if item.get("UsePreviousValue"):
            h.require(name in previous and item.get("ParameterValue") in (None, previous[name]), "Previous-value parameter differs from the captured binding.")
            chosen[name] = previous[name]
        else:
            chosen[name] = item.get("ParameterValue")
    h.require(chosen == inputs["parameters"], "Concrete preview parameters differ from the independently resolved parent inputs.")
    proposed = h.audit.template_body(cfn.get_template(StackName=saved["child"]["StackId"], ChangeSetName=preview_arn, TemplateStage="Processed")["TemplateBody"])
    h.require(h.fingerprint(proposed) == plan["childHash"], "Concrete preview template differs from the prepared release.")
    before, after = saved["childTemplate"]["Resources"], proposed["Resources"]
    rows = h.items(cfn, "describe_change_set", "Changes", ChangeSetName=preview_arn)
    seen = set()
    for entry in rows:
        row = entry["ResourceChange"]
        logical = row["LogicalResourceId"]
        h.require(logical not in seen, "Duplicate concrete preview resource.")
        seen.add(logical)
        if logical in {*h.FUNCTIONS, "TerraformProject"}:
            kind = "AWS::Lambda::Function" if logical in h.FUNCTIONS else "AWS::CodeBuild::Project"
            field = "Code" if logical in h.FUNCTIONS else "Environment"
            h.require(row.get("Action") == "Modify" and row.get("Replacement") == "False" and row.get("ResourceType") == kind
                      and not row.get("ChangeSetId") and row.get("Details") and names(row["Details"]) == {field}
                      and all(item.get("Target", {}).get("Attribute") == "Properties" and item["Target"].get("RequiresRecreation") == "Never" for item in row["Details"]),
                      "Concrete preview contains a replacement or an unrelated primary-resource change.")
        else:
            dependency(h, row, before, after, concrete=True)
    h.require(set(h.FUNCTIONS) | {"TerraformProject"} <= seen, "Concrete preview is incomplete.")
    return {"preview": preview_arn, "releaseChangeSet": plan["changeSet"], "childHash": plan["childHash"], "newImage": plan["newImage"],
            "inputs": inputs, "snapshot": snapshot(h, session, saved, inputs),
            "concreteResources": sorted(seen)}


def unchanged(h, session, saved, plan, proof):
    fresh = verify(h, session, saved, plan, proof["preview"])
    h.require(h.fingerprint(fresh) == h.fingerprint(proof), "Reference proof or live API/rule identities changed before execution.")


def after_deployment(h, session, saved, proof):
    current = snapshot(h, session, saved, proof["inputs"])
    h.require(h.fingerprint(current) == h.fingerprint(proof["snapshot"]), "API, authorizer, rule or resource identities/configuration changed during the release.")


def parent_plan(h, session, saved, plan, directory):
    """Replan the parent without baking unresolved sibling refs into child plans.

The independently checked child preview supplies nested scope evidence. Parent
bindings stay intrinsic and unchanged; neither the rejected hierarchy nor the
standalone diagnostic child preview is executed.
"""
    cfn = session.client("cloudformation")
    root = h.audit.template_body(cfn.get_template(StackName=saved["root"]["StackId"], ChangeSetName=plan["changeSet"], TemplateStage="Processed")["TemplateBody"])
    h.require(h.fingerprint(root) == plan["rootHash"], "Prepared parent template changed.")
    body = json.dumps(root)
    h.require(len(body.encode()) <= 51200, "Parent template is too large for an upload-free replan.")
    request = {"StackName": h.PARENT, "ChangeSetName": "navigan-bootstrap-concrete-" + uuid.uuid4().hex[:12],
               "ChangeSetType": "UPDATE", "TemplateBody": body, "IncludeNestedStacks": False,
               "Capabilities": ["CAPABILITY_NAMED_IAM", "CAPABILITY_AUTO_EXPAND"],
               "Parameters": [{"ParameterKey": item["ParameterKey"], **(
                   {"ParameterValue": plan["newImage"]} if item["ParameterKey"] == "TerraformRunnerImageUri" else {"UsePreviousValue": True})}
                   for item in saved["root"].get("Parameters", [])]}
    if saved["root"].get("RoleARN"):
        request["RoleARN"] = saved["root"]["RoleARN"]
    identifier = cfn.create_change_set(**request)["Id"]
    record = {"sourceChangeSet": plan["changeSet"], "executionChangeSet": identifier,
              "rootHash": plan["rootHash"], "childHash": plan["childHash"], "newImage": plan["newImage"]}
    h.audit.write_json(directory / "resolved-parent-plan.json", record)
    print("Fresh parent change set: " + identifier, flush=True)
    cfn.get_waiter("change_set_create_complete").wait(ChangeSetName=identifier, WaiterConfig={"Delay": 5, "MaxAttempts": 180})
    inspect_parent(h, cfn, saved, plan, identifier)
    return identifier


def inspect_parent(h, cfn, saved, plan, identifier):
    meta = cfn.describe_change_set(ChangeSetName=identifier)
    h.require(meta.get("StackId") == saved["root"]["StackId"] and meta.get("Status") == "CREATE_COMPLETE"
              and meta.get("ExecutionStatus") == "AVAILABLE" and meta.get("IncludeNestedStacks") is False,
              "Fresh parent change set is unavailable or contains precomputed nested plans.")
    wanted = h.parameters(saved["root"])
    wanted["TerraformRunnerImageUri"] = plan["newImage"]
    actual = {}
    previous = h.parameters(saved["root"])
    for item in meta.get("Parameters", []):
        key = item["ParameterKey"]
        h.require(key not in actual, "Duplicate parent parameter.")
        if item.get("UsePreviousValue"):
            h.require(key in previous and item.get("ParameterValue") in (None, previous[key]), "Parent previous-value binding differs.")
            actual[key] = previous[key]
        else:
            actual[key] = item.get("ParameterValue")
    h.require(actual == wanted, "Fresh parent plan changes unrelated parameters.")
    rows = h.items(cfn, "describe_change_set", "Changes", ChangeSetName=identifier)
    h.require(len(rows) == 1, "Fresh parent plan affects another module.")
    row = rows[0]["ResourceChange"]
    h.require((row.get("LogicalResourceId"), row.get("ResourceType"), row.get("Action"), row.get("Replacement"))
              == ("ClusterManagement", "AWS::CloudFormation::Stack", "Modify", "False") and not row.get("ChangeSetId"),
              "Fresh parent plan creates, deletes, replaces or precomputes nested resources.")
    template = h.audit.template_body(cfn.get_template(StackName=saved["root"]["StackId"], ChangeSetName=identifier, TemplateStage="Processed")["TemplateBody"])
    h.require(h.fingerprint(template) == plan["rootHash"], "Fresh parent template differs from the reviewed release.")
