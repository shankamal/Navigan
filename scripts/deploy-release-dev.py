#!/usr/bin/env python3
"""DEV-only manifest deployment: init, prepare, execute, verify or rollback.

Never builds or republishes an application artifact. Existing local DEV on port
3000 and PROD are not deployment targets. Candidate frontend uses localhost:3001.
SQL is executed only through the runner's separately supplied DEV migration DSN.
"""
from __future__ import annotations

import argparse
import base64
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid

import boto3

import release_common as common
import release_database as database
import release_dev_target as target

builder = common.load("immutable_release_builder", Path(__file__).with_name("build-release.py"))
require, canonical, sha = common.require, common.canonical, common.sha
FORMAT = "navigan-dev-deployment-plan-v1"
SUPPORTED = {"frontend", "backend", "infrastructure", "database", "image-worker"}
CURRENT = "deployments/dev/current.json"
LOCK = "locks/dev-deployment.json"


def identity(item):
    return {key: item.get(key) for key in ("uri", "sha256", "versionId")}


def selected_components(manifest, previous, config_hash, config=None):
    old = (previous or {}).get("manifest", {}).get("components", {})
    require(set(old) <= set(manifest["components"]), "A release cannot silently remove previously managed components.")
    selected = {name for name, item in manifest["components"].items() if name not in old or identity(item) != identity(old[name])}
    if previous and previous.get("configurationHash") != config_hash:
        before = previous.get("configuration")
        require(isinstance(before, dict) and config is not None, "Configuration-only release needs the previous verified configuration.")
        if before.get("frontend") != config.get("frontend"):
            selected.add("frontend")
        if before.get("parameterOverrides") != config.get("parameterOverrides"):
            selected.add("infrastructure")
    require(selected <= SUPPORTED, "A selected component has no isolated DEV deployment binding.")
    return selected


def template_index(session, manifest, account):
    item = manifest["components"]["infrastructure"]
    files = common.unzip(common.object_bytes(session.client("s3"), item, account))
    index = json.loads(files["template-index.json"])
    require(index.get("format") == 1 and index.get("root") == item.get("rootTemplate"), "Template bundle index differs.")
    for path, ref in index["templates"].items():
        data = common.object_bytes(session.client("s3"), ref, account)
        require(files[path + ".json"] == data, "Published nested template bytes differ from the approved bundle.")
    return index, json.loads(common.object_bytes(session.client("s3"), index["root"], account))


def verify_shared_bindings(session, state, index, root):
    """An app release cannot redirect owned DEV module routes to another API."""
    shared = root["Resources"].get("SharedPlatform", {})
    require(shared.get("Type") == "AWS::Serverless::Application", "Shared platform topology requires separate review.")
    for name in ("JwtIssuer", "JwtAudience"):
        require(shared.get("Properties", {}).get("Parameters", {}).get(name) == {"Ref": name}, "Shared identity binding changed.")
    for name, resource in root["Resources"].items():
        if name == "SharedPlatform" or resource.get("Type") != "AWS::Serverless::Application":
            continue
        parameters = resource.get("Properties", {}).get("Parameters", {})
        for key in ("ApiId", "AuthorizerId"):
            require(parameters.get(key) == {"Fn::GetAtt": ["SharedPlatform", "Outputs." + key]}, "A module API/authorizer binding changed.")
    reference = index["templates"]["infrastructure/shared/template.yaml"]
    proposed = json.loads(common.object_bytes(session.client("s3"), reference, state["account"]))
    before = state["stacks"]["root/SharedPlatform"]["processed"]
    before = before if isinstance(before, dict) else common.yaml_document(before)
    require(common.native_form(before.get("Outputs")) == common.native_form(proposed.get("Outputs")), "Shared API outputs changed; use a separate reviewed infrastructure release.")
    kinds = {"AWS::ApiGatewayV2::Api", "AWS::ApiGatewayV2::Authorizer", "AWS::ApiGatewayV2::Stage"}
    select = lambda document: {name: {key: item[key] for key in ("Type", "Properties") if key in item}
                               for name, item in document.get("Resources", {}).items() if item.get("Type") in kinds}
    require(common.native_form(select(before)) == common.native_form(select(proposed)), "Existing API identity/authentication/stage changes require separate review.")


def parameter_arguments(template, state, config, manifest, selected):
    existing = {row["ParameterKey"]: row["ParameterValue"] for row in state["stacks"]["root"]["stack"]["Parameters"]}
    migration = next((cfg for path, cfg in state["functions"].items() if path.endswith("/MigrationFunction")), {})
    cluster = next((cfg for path, cfg in state["functions"].items() if path.endswith("/ClusterFunction")), {})
    runtime = migration.get("Environment", {}).get("Variables", {})
    cluster_env = cluster.get("Environment", {}).get("Variables", {})
    derived = {"DeploymentEnvironment": "dev", "DatabaseName": common.DEV_DATABASE}
    mapping = {"MigrationSourceFirstEnabled": "MIGRATION_SOURCE_FIRST_ENABLED", "MigrationWorkspaceBucketName": "MIGRATION_WORKSPACE_BUCKET",
               "MigrationWorkspaceKmsKeyArn": "MIGRATION_WORKSPACE_KMS_KEY", "MigrationWorkspaceBucketOwner": "MIGRATION_WORKSPACE_BUCKET_OWNER",
               "SourceConnectorDeliveryRoleArn": "SOURCE_CONNECTOR_DELIVERY_ROLE_ARN", "GitHubAppId": "GITHUB_APP_ID",
               "GitHubAppPrivateKeySecretArn": "GITHUB_APP_PRIVATE_KEY_SECRET_ARN"}
    for key, variable in mapping.items():
        if variable in runtime:
            derived[key] = runtime[variable]
    if "SOURCE_REGISTRY_ALLOWED_ROLE_ARNS" in runtime:
        roles = json.loads(runtime["SOURCE_REGISTRY_ALLOWED_ROLE_ARNS"])
        require(isinstance(roles, list) and all(isinstance(role, str) for role in roles), "Registry-role settings are invalid.")
        derived["SourceRegistryAllowedRoleArns"] = ",".join(roles)
    for key, variable in (("PlatformToolsBaseUrl", "PLATFORM_TOOLS_BASE_URL"), ("PlatformToolsGatewayEnabled", "PLATFORM_TOOLS_GATEWAY_ENABLED"),
                          ("PlatformToolsTunnelEnabled", "PLATFORM_TOOLS_TUNNEL_ENABLED")):
        if variable in cluster_env:
            derived[key] = cluster_env[variable]
    overrides = config["parameterOverrides"]
    forbidden = {"DatabaseName", "DatabaseProxyHost", "ApiDatabaseSecretArn", "EventsDatabaseSecretArn", "JwtIssuer", "JwtAudience",
                 "IdentityUserPoolId", "PrivateSubnetIds", "LambdaSecurityGroupIds", "SecretsKmsKeyArn", "DeploymentEnvironment"}
    require(not (set(overrides) & forbidden) and set(overrides) <= set(template.get("Parameters", {})),
            "This DEV pilot cannot change identity, database or network bindings.")
    require(not any(template["Parameters"][name].get("NoEcho") for name in overrides), "Use managed secret references; never store secret values in deployment configuration.")
    derived.update(overrides)
    if "terraform-runner" in selected:
        derived["TerraformRunnerImageUri"] = manifest["components"]["terraform-runner"]["uri"]
    if "cluster-connector" in selected:
        derived["ConnectorImageUri"] = manifest["components"]["cluster-connector"]["uri"]
    if "migration-connector" in selected:
        uri = manifest["components"]["migration-connector"]["uri"]
        derived["MigrationConnectorImageRepository"], derived["MigrationConnectorImageDigest"] = uri.split("@", 1)
    result, defaults = [], []
    for name, definition in template.get("Parameters", {}).items():
        if name in derived:
            value = derived[name]
            require(isinstance(value, str) and value != "****", "A derived deployment parameter is invalid.")
            result.append({"ParameterKey": name, "ParameterValue": value})
        elif name in existing:
            result.append({"ParameterKey": name, "UsePreviousValue": True})
        elif "Default" in definition:
            defaults.append(name)
            result.append({"ParameterKey": name, "ParameterValue": str(definition["Default"])})
        else:
            raise ValueError("An explicit new deployment parameter is required; inspect the private parameter report.")
    return result, defaults


def inspect_changes(cfn, identifier, root_stack, *, worker=False, state=None):
    rows, blocked, seen = [], [], set()

    def visit(current):
        require(current not in seen, "Repeated nested change-set reference.")
        seen.add(current)
        described = cfn.describe_change_set(ChangeSetName=current)
        prefix = root_stack.split("/", 1)[0] + "/" + common.DEV_STACK + "-"
        require(described["StackId"] == root_stack or described["StackId"].startswith(prefix), "Change set is outside DEV ownership.")
        if current != identifier:
            require(described.get("RootChangeSetId") == identifier and described.get("ParentChangeSetId") in seen,
                    "Nested change set is not part of the reviewed DEV hierarchy.")
        entries = common.pages(cfn, "describe_change_set", "Changes", ChangeSetName=current)
        before = next((record for record in (state or {}).get("stacks", {}).values()
                       if record["stack"]["StackId"] == described["StackId"]), None)
        after = None

        def unchanged_identity(item):
            nonlocal after
            if not before or not item.get("Details") or not all(detail.get("Evaluation") == "Dynamic" for detail in item["Details"]):
                return False
            if after is None:
                after = cfn.get_template(ChangeSetName=current, TemplateStage="Processed")["TemplateBody"]
                after = after if isinstance(after, dict) else common.yaml_document(after)
            original = before["processed"]
            original = original if isinstance(original, dict) else common.yaml_document(original)
            name = item["LogicalResourceId"]
            left = original.get("Resources", {}).get(name, {})
            right = after.get("Resources", {}).get(name, {})
            left = {key: value for key, value in left.items() if key != "Metadata"}
            right = {key: value for key, value in right.items() if key != "Metadata"}
            if common.native_form(left) != common.native_form(right):
                return False
            old_params = {row["ParameterKey"]: row["ParameterValue"] for row in before["stack"].get("Parameters", [])}
            new_params = {row["ParameterKey"]: row.get("ParameterValue", old_params.get(row["ParameterKey"]) if row.get("UsePreviousValue") else None)
                          for row in described.get("Parameters", [])}
            references = set()

            def visit_value(value):
                if isinstance(value, dict):
                    if isinstance(value.get("Ref"), str): references.add(value["Ref"])
                    attr = value.get("Fn::GetAtt")
                    if isinstance(attr, list) and attr: references.add(attr[0])
                    if isinstance(attr, str): references.add(attr.split(".", 1)[0])
                    sub = value.get("Fn::Sub")
                    if isinstance(sub, str): references.update(name.split(".", 1)[0] for name in re.findall(r"\$\{([^!][^}]+)\}", sub))
                    for child in value.values(): visit_value(child)
                elif isinstance(value, list):
                    for child in value: visit_value(child)
            visit_value(left)
            changed = {entry["ResourceChange"]["LogicalResourceId"]: entry["ResourceChange"] for entry in entries}
            for reference in references:
                if reference in old_params:
                    if old_params[reference] == "****" or new_params.get(reference) != old_params[reference]: return False
                elif reference in changed:
                    dependency = changed[reference]
                    if dependency["Action"] != "Modify" or dependency.get("Replacement") != "False": return False
                elif reference not in original.get("Resources", {}) and not reference.startswith("AWS::"):
                    return False
            return True

        for entry in entries:
            item = entry["ResourceChange"]
            kind, action, replacement = item["ResourceType"], item["Action"], item.get("Replacement", "False")
            row = {"logicalId": item["LogicalResourceId"], "type": kind, "action": action, "replacement": replacement}
            rows.append(row)
            if worker:
                allowed = (action == "Modify" and ((kind == "AWS::ECS::TaskDefinition" and item["LogicalResourceId"] == "WorkerTask")
                           or (kind == "AWS::ECS::Service" and item["LogicalResourceId"] == "WorkerService" and replacement == "False")))
            else:
                allowed_types = {"AWS::CloudFormation::Stack", "AWS::Lambda::Function", "AWS::Lambda::Permission", "AWS::IAM::Role", "AWS::IAM::Policy",
                                 "AWS::ApiGatewayV2::Route", "AWS::ApiGatewayV2::Integration", "AWS::Events::Rule", "AWS::CodeBuild::Project",
                                 "AWS::Logs::LogGroup", "AWS::CloudWatch::Alarm"}
                allowed = kind in allowed_types and action in {"Add", "Modify"} and replacement == "False"
                dependents = {"AWS::Lambda::Permission", "AWS::ApiGatewayV2::Integration", "AWS::ApiGatewayV2::Route", "AWS::Events::Rule", "AWS::CodeBuild::Project"}
                if not allowed and kind in dependents and action == "Modify" and replacement in {"Conditional", "True"}:
                    allowed = unchanged_identity(item)
                    if allowed: row["unchangedBindingProof"] = True
            if not allowed:
                blocked.append(row)
            if kind == "AWS::CloudFormation::Stack" and item.get("ChangeSetId"):
                visit(item["ChangeSetId"])
    visit(identifier)
    return rows, blocked


def create_plan(cfn, stack, *, url=None, parameters=None, worker=False, state=None):
    request = {"StackName": stack["StackId"], "ChangeSetName": "dev-release-" + uuid.uuid4().hex[:12],
               "ChangeSetType": "UPDATE", "IncludeNestedStacks": not worker, "Parameters": parameters,
               "Capabilities": ["CAPABILITY_NAMED_IAM", "CAPABILITY_AUTO_EXPAND"]}
    request.update({"TemplateURL": url} if url else {"UsePreviousTemplate": True})
    if stack.get("RoleARN"):
        request["RoleARN"] = stack["RoleARN"]
    identifier = cfn.create_change_set(**request)["Id"]
    try:
        cfn.get_waiter("change_set_create_complete").wait(ChangeSetName=identifier)
    except Exception:
        current = cfn.describe_change_set(ChangeSetName=identifier)
        no_changes = current.get("Status") == "FAILED" and ("didn't contain changes" in current.get("StatusReason", "")
                     or "No updates are to be performed" in current.get("StatusReason", ""))
        require(no_changes, "DEV change-set preparation failed; inspect the saved AWS change set.")
        return {"changeSet": identifier, "stack": stack["StackId"], "noChanges": True, "changes": [], "blocked": []}
    rows, blocked = inspect_changes(cfn, identifier, stack["StackId"], worker=worker, state=state)
    return {"changeSet": identifier, "stack": stack["StackId"], "noChanges": False, "changes": rows, "blocked": blocked}


def worker_stamp(worker):
    if not worker:
        return None
    return sha(canonical({"stack": worker["stack"]["StackId"], "parameters": worker["parameters"], "template": worker["original"],
                          "task": worker["service"]["taskDefinition"], "desired": worker["service"]["desiredCount"], "definition": worker["task"]}))


def verify_target_manifest(session, manifest, state, selected, *, worker=None):
    if "backend" in manifest["components"]:
        expected = base64.b64encode(bytes.fromhex(manifest["components"]["backend"]["sha256"])).decode()
        require(all(cfg.get("CodeSha256") == expected for cfg in state["functions"].values()), "The requested Lambda package is not retained by every owned DEV function.")
    if worker and "image-worker" in manifest["components"]:
        expected = manifest["components"]["image-worker"]["uri"]
        container = next(row for row in worker["task"]["containerDefinitions"] if row["name"] == "collector")
        require(container["image"] == expected, "Collector task does not retain the selected image.")
        count = worker["service"]["desiredCount"]
        if count:
            ecs = session.client("ecs")
            arns = ecs.list_tasks(cluster=worker["parameters"]["ClusterArn"], serviceName=worker["service"]["serviceArn"], desiredStatus="RUNNING")["taskArns"]
            result = ecs.describe_tasks(cluster=worker["parameters"]["ClusterArn"], tasks=arns)
            require(not result.get("failures") and len(result.get("tasks", [])) == count, "Collector running task count differs.")
            for task in result["tasks"]:
                image = next(row for row in task["containers"] if row["name"] == "collector")
                require(task["taskDefinitionArn"] == worker["service"]["taskDefinition"] and image.get("imageDigest") == expected.rsplit("@", 1)[1],
                        "Collector running image differs from the approved artifact.")


def prepare(session, config_path, manifest_path):
    config, manifest = common.read(config_path), common.planner.manifest(manifest_path)
    target.validate_config(config)
    account, region, bucket = config["account"], config["region"], config["artifactBucket"]
    common.verify_registry(session, bucket, account, region)
    state = target.snapshot(session, account, region)
    require(state["stacks"]["root"]["stack"]["StackId"] == config["rootStackId"], "DEV root was replaced after initialization.")
    params = {row["ParameterKey"]: row["ParameterValue"] for row in state["stacks"]["root"]["stack"]["Parameters"]}
    public = config["frontend"]["publicEnvironment"]
    require(public.get("NAVIGAN_PUBLIC_OIDC_AUTHORITY") == params["JwtIssuer"]
            and public.get("NAVIGAN_PUBLIC_OIDC_CLIENT_ID") == params["JwtAudience"], "Frontend identity does not match the owned DEV API.")
    s3 = session.client("s3")
    saved = common.get_optional(s3, bucket, CURRENT, account)
    previous = saved[0] if saved else None
    if previous and previous.get("status") == "BASELINE_RESTORED":
        require(previous.get("environment") == "dev" and previous.get("rootStackId") == config["rootStackId"], "Baseline restore record belongs to another target.")
        previous = None
    if previous:
        require(previous.get("status") == "SUCCEEDED" and previous.get("environment") == "dev"
                and previous.get("rootStackId") == config["rootStackId"], "Invalid last-successful DEV record.")
        common.planner.validate_manifest(previous["manifest"])
        previous_worker = target.image_worker(session, state) if "image-worker" in previous["manifest"]["components"] else None
        verify_target_manifest(session, previous["manifest"], state, set(), worker=previous_worker)
    config_hash = sha(canonical(config))
    selected = selected_components(manifest, previous, config_hash, config)
    for name, item in manifest["components"].items():
        require(item.get("portable") is True and item.get("buildContract") == common.CONTRACT,
                "An artifact is not portable or has no verified build contract.")
        builder.verify_artifact(session, name, item, account, region)
        if name in common.planner.IMAGES and config.get("repositories") is not None:
            expected = builder.repository_uri(name, config["repositories"], account, region)
            require(item["uri"] == expected + "@sha256:" + item["sha256"], "Build artifact does not match the configured existing ECR repository.")
    root_needed = bool(selected & {"backend", "infrastructure", "cluster-connector", "migration-connector", "terraform-runner"})
    require(not root_needed or {"backend", "infrastructure", "database"} <= set(manifest["components"]),
            "An initial SAM adoption requires backend, template and database artifacts.")
    require("frontend" not in selected or "frontend" in manifest["components"], "Frontend configuration needs a retained frontend artifact.")
    directory = common.workspace("navigan-dev-deployment-")
    print("Private DEV deployment record: " + str(directory), flush=True)
    common.write(directory / "baseline.json", state)
    common.write(directory / "previous-record.json", previous)
    plan = {"format": FORMAT, "id": uuid.uuid4().hex, "config": config, "configurationHash": config_hash,
            "manifest": manifest, "manifestHash": sha(canonical(manifest)), "selected": sorted(selected),
            "baselineStamp": target.stamp(state), "previousEtag": saved[1] if saved else None,
            "preparedAt": datetime.now(timezone.utc).isoformat(), "cloudPlans": [], "pendingMigrations": [],
            "databaseRequired": root_needed or "database" in selected, "rootNeeded": root_needed}
    plan["captureHashes"] = {name: sha(canonical(common.read(directory / name)))
                             for name in ("baseline.json", "previous-record.json")}
    common.write(directory / "release-plan.json", plan)
    if plan["databaseRequired"]:
        dsn = os.environ.get("MIGRATION_DATABASE_URL")
        require(dsn, "Set the private DEV migration connection in this runner before preparing a database/SAM release.")
        content = common.object_bytes(s3, manifest["components"]["database"], account)
        plan["pendingMigrations"] = database.inspect(dsn, content)
    if "image-worker" in selected:
        require(config.get("imageWorkerEnabled"), "No existing isolated DEV collector target is bound.")
        worker = target.image_worker(session, state)
        plan["workerStamp"] = worker_stamp(worker)
        common.write(directory / "worker-baseline.json", worker)
        plan["captureHashes"]["worker-baseline.json"] = sha(canonical(common.read(directory / "worker-baseline.json")))
        arguments = [{"ParameterKey": row["ParameterKey"], **({"ParameterValue": manifest["components"]["image-worker"]["uri"]}
                     if row["ParameterKey"] == "WorkerImage" else {"UsePreviousValue": True})} for row in worker["stack"]["Parameters"]]
        plan["cloudPlans"].append({**create_plan(session.client("cloudformation"), worker["stack"], parameters=arguments, worker=True), "kind": "worker"})
    if root_needed:
        index, template = template_index(session, manifest, account)
        verify_shared_bindings(session, state, index, template)
        arguments, defaults = parameter_arguments(template, state, config, manifest, selected)
        common.write(directory / "parameter-plan.json", {"arguments": arguments, "newDefaults": defaults})
        # Capture actual working runtime bytes before preparing the candidate.
        plan["rollback"] = target.rollback_template(session, state, bucket)
        plan["cloudPlans"].insert(0, {**create_plan(session.client("cloudformation"), state["stacks"]["root"]["stack"],
            url=common.template_url(index["root"], region), parameters=arguments, state=state), "kind": "root"})
        plan["rootTemplate"] = index["root"]
    require(target.stamp(target.snapshot(session, account, region)) == plan["baselineStamp"], "DEV changed during preparation; inspect saved plans before retrying.")
    plan["blocked"] = [row for item in plan["cloudPlans"] for row in item["blocked"]]
    common.write(directory / "release-plan.json", plan)
    plan_ref = common.put_bytes(s3, bucket, "plans/dev/" + plan["id"] + "/plan.json", canonical(plan), account, IfNoneMatch="*")
    common.write(directory / "plan-reference.json", plan_ref)
    summary = {"environment": "dev", "selected": plan["selected"], "skipped": sorted(set(common.planner.COMPONENTS) - selected),
               "pendingMigrationCount": len(plan["pendingMigrations"]), "changes": [row for item in plan["cloudPlans"] for row in item["changes"]],
               "blocked": plan["blocked"], "deploymentPerformed": False, "readyToExecute": not plan["blocked"]}
    common.write(directory / "summary.json", summary)
    print(json.dumps(summary, indent=2))
    print("Saved DEV plan: " + str(directory / "release-plan.json"))
    return directory


def load_plan(session, path):
    path = Path(path)
    plan = common.read(path)
    require(plan.get("format") == FORMAT and re.fullmatch(r"[a-f0-9]{32}", plan.get("id", "")), "Invalid DEV deployment plan.")
    config = plan["config"]
    target.validate_config(config)
    common.verify_registry(session, config["artifactBucket"], config["account"], config["region"])
    ref = common.read(path.parent / "plan-reference.json")
    require(json.loads(common.object_bytes(session.client("s3"), ref, config["account"])) == plan,
            "Local plan differs from the saved immutable reviewed plan.")
    common.planner.validate_manifest(plan["manifest"])
    require(sha(canonical(plan["manifest"])) == plan["manifestHash"] and sha(canonical(config)) == plan["configurationHash"],
            "Plan manifest/configuration binding differs.")
    for name, expected in plan.get("captureHashes", {}).items():
        require(name in {"baseline.json", "previous-record.json", "worker-baseline.json"}
                and sha(canonical(common.read(path.parent / name))) == expected, "Saved baseline/rollback capture differs from the immutable plan.")
    return plan


def fresh_cloud_plan(session, item, state=None):
    cfn = session.client("cloudformation")
    current = cfn.describe_change_set(ChangeSetName=item["changeSet"])
    require(current["StackId"] == item["stack"], "Change-set target identity differs.")
    if item["noChanges"]:
        require(current.get("Status") == "FAILED", "Saved no-op preview state differs.")
        return
    require(current.get("Status") == "CREATE_COMPLETE" and current.get("ExecutionStatus") == "AVAILABLE", "Change set is no longer available.")
    rows, blocked = inspect_changes(cfn, item["changeSet"], item["stack"], worker=item["kind"] == "worker", state=state)
    require(rows == item["changes"] and not blocked, "Fresh change-set scope differs or requires manual review.")


def wait_stack(cfn, name, identifier):
    deadline = time.monotonic() + 3600
    while time.monotonic() < deadline:
        current = cfn.describe_stacks(StackName=name)["Stacks"][0]
        execution = cfn.describe_change_set(ChangeSetName=identifier).get("ExecutionStatus")
        if current["StackStatus"] == "UPDATE_COMPLETE" and execution == "EXECUTE_COMPLETE":
            return
        require(execution != "EXECUTE_FAILED" and current["StackStatus"] in {"UPDATE_COMPLETE", "UPDATE_IN_PROGRESS", "UPDATE_COMPLETE_CLEANUP_IN_PROGRESS"},
                "CloudFormation did not retain the requested update; inspect rollback events.")
        time.sleep(5)
    raise ValueError("DEV update is still unsettled; use --verify instead of repeating execution.")


def token_value():
    # Optional application acceptance credential, separate from AWS deployment authentication.
    # Ordinary deploy/verify/rollback commands never prompt for a browser token.
    token = os.environ.get("NAVIGAN_DEV_SMOKE_TOKEN")
    if not token or not token.strip():
        return None
    token = token.strip()
    if token.lower().startswith("bearer "):
        token = token.split(None, 1)[1]
    require(re.fullmatch(r"[A-Za-z0-9._~+/-]+=*", token or "") and len(token) < 16384, "Invalid smoke token format.")
    return token


def smoke(config, token, frontend=False, port=3001):
    if not token:
        return []  # Protected APIs require login; health/artifact checks still run separately.
    require(isinstance(port, int) and 1 <= port <= 65535, "Invalid local verification port.")
    base = (("http://127.0.0.1:" + str(port) + "/api/platform") if frontend else config["apiOrigin"] + config["apiBasePath"])
    statuses = []
    for endpoint in ("/customers/summary", "/environments/summary", "/clusters/summary"):
        result = json.loads(builder.http(base + endpoint, token=token))
        require(isinstance(result, dict) and isinstance(result.get("total"), int) and result["total"] >= 0
                and isinstance(result.get("byStatus"), dict) and isinstance(result.get("byProvider"), dict), "Authenticated summary response is incompatible.")
        statuses.append({"endpoint": endpoint, "status": 200})
    return statuses


def inspect_container(name):
    require(re.fullmatch(r"navigan-dev-preview-[a-f0-9]{12}(?:-probe)?", name or ""), "Unexpected DEV preview container identity.")
    result = subprocess.run(["docker", "inspect", name], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if result.returncode:
        return None
    return json.loads(result.stdout)[0]


def frontend_before(previous):
    import socket
    with socket.socket() as sock:
        listening = sock.connect_ex(("127.0.0.1", 3001)) == 0
    if not listening:
        return None
    old = (previous or {}).get("frontend")
    require(old, "Port 3001 is occupied by an unmanaged process; it will not be stopped.")
    actual = inspect_container(old["container"])
    require(actual and actual["State"]["Running"] and actual["Config"].get("Labels", {}).get("navigan.release") == old.get("releaseLabel", previous["planId"])
            and actual["Config"]["Image"] == old["image"], "Port 3001 is not the recorded managed DEV preview.")
    bindings = actual.get("NetworkSettings", {}).get("Ports", {}).get("3000/tcp", []) or []
    require(any(row.get("HostIp") == "127.0.0.1" and row.get("HostPort") == "3001" for row in bindings), "Recorded preview has different port bindings.")
    return old


def verify_frontend_runtime(config, runtime):
    fields = {"oidcAuthority": "OIDC_AUTHORITY", "oidcClientId": "OIDC_CLIENT_ID", "appUrl": "APP_URL",
              "corporateLogoUrl": "CORPORATE_LOGO_URL", "migrationConnectorApiBaseUrl": "MIGRATION_CONNECTOR_API_BASE_URL",
              "migrationConnectorImageRepository": "MIGRATION_CONNECTOR_IMAGE_REPOSITORY",
              "migrationConnectorImageDigest": "MIGRATION_CONNECTOR_IMAGE_DIGEST"}
    env = config["frontend"]["publicEnvironment"]
    require(all(runtime.get(key) == env.get("NAVIGAN_PUBLIC_" + value, "") for key, value in fields.items())
            and runtime.get("migrationUiPreview") is False, "Frontend public runtime configuration differs.")


def start_frontend(session, plan, directory, token, journal):
    config, item = plan["config"], plan["manifest"]["components"]["frontend"]
    env = None
    name = "navigan-dev-preview-" + plan["id"][:12]
    previous = common.read(directory / "previous-record.json")
    old = frontend_before(previous)
    variables = {**config["frontend"]["publicEnvironment"], "NAVIGAN_API_ORIGIN": config["apiOrigin"], "NAVIGAN_API_BASE_PATH": config["apiBasePath"]}
    env_file = directory / "frontend-runtime.env"
    require(all("\n" not in value and "\r" not in value for value in variables.values()), "Invalid runtime environment value.")
    env_file.write_text("".join(key + "=" + value + "\n" for key, value in variables.items()))
    env_file.chmod(0o600)
    preview = {"container": name, "port": 3001, "image": item["uri"], "mode": "local-preview", "releaseLabel": plan["id"]}
    journal["frontend"] = preview
    journal["previousLocalFrontend"] = old
    common.write(directory / "execution.json", journal)

    def healthy(port):
        deadline = time.monotonic() + 120
        while True:
            try:
                result = json.loads(builder.http("http://127.0.0.1:" + str(port) + "/api/runtime-config"))
                verify_frontend_runtime(config, result)
                builder.http("http://127.0.0.1:" + str(port) + "/healthz")
                return
            except (OSError, ValueError):
                require(time.monotonic() < deadline, "Frontend candidate did not become healthy.")
                time.sleep(2)

    probe = name + "-probe"
    try:
        print("Frontend: pulling the saved image digest...", flush=True)
        env = builder.docker_auth(session, directory, config["account"], config["region"])
        common.run(["docker", "pull", item["uri"]], directory, directory / "frontend.log", env=env)
        print("Frontend: checking candidate startup and runtime configuration...", flush=True)
        common.run(["docker", "run", "--detach", "--name", probe, "--label", "navigan.release=" + plan["id"],
                    "--publish", "127.0.0.1::3000", "--env-file", str(env_file), item["uri"]], directory, directory / "frontend.log", env=env)
        port = subprocess.check_output(["docker", "port", probe, "3000/tcp"], env=env).decode().strip()
        require(re.fullmatch(r"127\.0\.0\.1:[0-9]+", port), "Unexpected candidate test port.")
        candidate_port = int(port.rsplit(":", 1)[1])
        healthy(candidate_port)
        smoke(config, token, frontend=True, port=candidate_port)
        if old:
            common.run(["docker", "stop", old["container"]], directory, directory / "frontend.log", env=env)
        try:
            common.run(["docker", "run", "--detach", "--name", name, "--label", "navigan.release=" + plan["id"],
                        "--publish", "127.0.0.1:3001:3000", "--env-file", str(env_file), item["uri"]], directory, directory / "frontend.log", env=env)
            healthy(3001)
        except Exception:
            failed = inspect_container(name)
            if failed and failed["Config"].get("Labels", {}).get("navigan.release") == plan["id"]:
                subprocess.run(["docker", "rm", "--force", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if old:
                common.run(["docker", "start", old["container"]], directory, directory / "frontend.log", env=env)
            raise
        print("Frontend: running at http://localhost:3001", flush=True)
        return preview
    finally:
        subprocess.run(["docker", "rm", "--force", probe], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if env is not None:
            subprocess.run(["docker", "logout", item["uri"].split("/", 1)[0]], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def lock(session, plan):
    config = plan["config"]
    return common.put_bytes(session.client("s3"), config["artifactBucket"], LOCK, canonical({"planId": plan["id"]}),
                            config["account"], IfNoneMatch="*")


def unlock(session, plan, reference):
    config = plan["config"]
    try:
        value = json.loads(common.object_bytes(session.client("s3"), reference, config["account"]))
    except Exception as error:
        if getattr(error, "response", {}).get("Error", {}).get("Code") in {"NoSuchVersion", "NoSuchKey"}:
            return  # This exact lock version is already released; never delete a new owner's lock.
        raise
    require(value == {"planId": plan["id"]}, "Deployment lock ownership differs.")
    bucket, key = common.s3_location(reference)
    session.client("s3").delete_object(Bucket=bucket, Key=key, VersionId=reference["versionId"], ExpectedBucketOwner=config["account"])


def execute(session, path):
    path = Path(path)
    plan = load_plan(session, path)
    require(not plan["blocked"], "Prepared scope requires review; no execution is permitted.")
    require(not (path.parent / "execution.json").exists(), "Execution was already requested; use --verify or --rollback, never repeat it.")
    config = plan["config"]
    state = target.snapshot(session, config["account"], config["region"])
    require(target.stamp(state) == plan["baselineStamp"], "DEV changed after preparation.")
    current = common.get_optional(session.client("s3"), config["artifactBucket"], CURRENT, config["account"])
    require((current[1] if current else None) == plan["previousEtag"], "Last successful DEV release changed.")
    for name, item in plan["manifest"]["components"].items():
        builder.verify_artifact(session, name, item, config["account"], config["region"])
    for item in plan["cloudPlans"]:
        fresh_cloud_plan(session, item, state)
    if "image-worker" in plan["selected"]:
        require(worker_stamp(target.image_worker(session, state)) == plan["workerStamp"], "DEV collector changed after preparation.")
    token = token_value()
    smoke(config, token)  # Run authenticated preflight only when explicitly supplied.
    if "frontend" in plan["selected"]:
        frontend_before(common.read(path.parent / "previous-record.json"))
    if plan["databaseRequired"]:
        require(os.environ.get("MIGRATION_DATABASE_URL"), "Private DEV migration connection is required.")
    reference = lock(session, plan)
    journal = {"planId": plan["id"], "requestedAt": datetime.now(timezone.utc).isoformat(), "lock": reference, "completedStages": []}
    common.write(path.parent / "execution.json", journal)
    if plan["databaseRequired"]:
        content = common.object_bytes(session.client("s3"), plan["manifest"]["components"]["database"], config["account"])
        database.apply(os.environ["MIGRATION_DATABASE_URL"], content, plan["pendingMigrations"])
        journal["completedStages"].append("database")
        common.write(path.parent / "execution.json", journal)
    for item in plan["cloudPlans"]:
        if not item["noChanges"]:
            session.client("cloudformation").execute_change_set(ChangeSetName=item["changeSet"], ClientRequestToken="dev-" + plan["id"] + "-" + item["kind"])
            wait_stack(session.client("cloudformation"), item["stack"], item["changeSet"])
        journal["completedStages"].append(item["kind"])
        common.write(path.parent / "execution.json", journal)
    if "frontend" in plan["selected"]:
        journal["frontend"] = start_frontend(session, plan, path.parent, token, journal)
        journal["completedStages"].append("frontend")
        common.write(path.parent / "execution.json", journal)
    verify(session, path, token=token)


def verify(session, path, token=None):
    path = Path(path)
    plan = load_plan(session, path)
    journal = common.read(path.parent / "execution.json")
    require(journal.get("planId") == plan["id"], "Execution journal belongs to another plan.")
    require(not journal.get("rollbackRequested"), "Rollback is in progress; inspect its journal before candidate verification.")
    config = plan["config"]
    state = target.snapshot(session, config["account"], config["region"])
    worker = None
    if "image-worker" in plan["manifest"]["components"]:
        deadline = time.monotonic() + 180
        while True:
            try:
                worker = target.image_worker(session, state)
                break
            except common.ReleaseError:
                require(time.monotonic() < deadline, "Collector rollout is unsettled; inspect it before retrying verification.")
                time.sleep(5)
    verify_target_manifest(session, plan["manifest"], state, set(plan["selected"]), worker=worker)
    before = common.read(path.parent / "baseline.json")
    for logical, record in before["stacks"].items():
        expected = {row["LogicalResourceId"]: row for row in record["resources"] if row["ResourceType"] != "AWS::Lambda::Permission"}
        actual = {row["LogicalResourceId"]: row for row in state["stacks"][logical]["resources"]}
        require(all(name in actual and actual[name]["PhysicalResourceId"] == row["PhysicalResourceId"] for name, row in expected.items()),
                "An existing DEV physical resource identity changed unexpectedly.")
    for item in plan["cloudPlans"]:
        if not item["noChanges"]:
            current = session.client("cloudformation").describe_change_set(ChangeSetName=item["changeSet"])
            require(current.get("ExecutionStatus") == "EXECUTE_COMPLETE", "Requested change set has not completed.")
    if plan["databaseRequired"]:
        content = common.object_bytes(session.client("s3"), plan["manifest"]["components"]["database"], config["account"])
        require(not database.inspect(os.environ["MIGRATION_DATABASE_URL"], content), "Database migrations remain pending.")
    previous = common.read(path.parent / "previous-record.json")
    frontend = journal.get("frontend") or (previous or {}).get("frontend")
    if "frontend" in plan["manifest"]["components"]:
        require(frontend and frontend["image"] == plan["manifest"]["components"]["frontend"]["uri"], "Frontend candidate was not started or retained.")
        actual = json.loads(subprocess.check_output(["docker", "inspect", frontend["container"]]))[0]
        require(actual["State"]["Running"] and actual["Config"]["Image"] == frontend["image"], "Frontend candidate image/state differs.")
        runtime = json.loads(builder.http("http://127.0.0.1:3001/api/runtime-config"))
        verify_frontend_runtime(config, runtime)
        builder.http("http://127.0.0.1:3001/healthz")
        builder.http("http://127.0.0.1:3001/login")
    results = smoke(config, token or token_value(), frontend="frontend" in plan["manifest"]["components"])
    completed = {"environment": "dev", "status": "SUCCEEDED", "planId": plan["id"], "rootStackId": config["rootStackId"],
                 "configurationHash": plan["configurationHash"], "configuration": config, "manifest": plan["manifest"], "frontend": frontend,
                 "verifiedAt": datetime.now(timezone.utc).isoformat(), "authenticatedChecks": results,
                 "authenticatedAcceptance": "PASSED" if results else "NOT_REQUESTED",
                 "rootTemplate": plan.get("rootTemplate"), "snapshotStamp": target.stamp(state)}
    if not journal.get("recordPublished"):
        current = common.get_optional(session.client("s3"), config["artifactBucket"], CURRENT, config["account"])
        if current and current[0].get("planId") == plan["id"]:
            require(current[0].get("manifest") == plan["manifest"] and current[0].get("configurationHash") == plan["configurationHash"],
                    "An existing release record has different artifacts/configuration.")
            reference = {"uri": "s3://" + config["artifactBucket"] + "/" + CURRENT,
                         "versionId": current[2], "sha256": sha(canonical(current[0]))}
        else:
            condition = {"IfMatch": plan["previousEtag"]} if plan["previousEtag"] else {"IfNoneMatch": "*"}
            reference = common.put_bytes(session.client("s3"), config["artifactBucket"], CURRENT, canonical(completed), config["account"], **condition)
        journal["recordPublished"] = reference
        common.write(path.parent / "execution.json", journal)
    if not journal.get("lockReleased"):
        unlock(session, plan, journal["lock"])
        journal["lockReleased"] = True
        common.write(path.parent / "execution.json", journal)
    common.write(path.parent / "verification.json", completed)
    print("DEV deployment verified; artifact/runtime checks passed and deployment record saved.")
    print("Authenticated API checks: " + ("passed." if results else "not requested; verify sign-in in the browser."))
    if frontend:
        print("DEV candidate frontend: http://localhost:3001 (existing port 3000 and PROD unchanged)")


def rollback(session, path):
    path = Path(path)
    plan = load_plan(session, path)
    journal = common.read(path.parent / "execution.json")
    require(not journal.get("rollbackComplete"), "This rollback has already completed.")
    config = plan["config"]
    state = target.snapshot(session, config["account"], config["region"])
    require(state["stacks"]["root"]["stack"]["StackId"] == config["rootStackId"], "DEV root identity differs.")
    require(journal.get("planId") == plan["id"], "Rollback journal belongs to another release.")
    token = token_value()
    current = common.get_optional(session.client("s3"), config["artifactBucket"], CURRENT, config["account"])
    if not journal.get("rollbackRequested"):
        if journal.get("recordPublished"):
            require(current and current[0].get("planId") == plan["id"], "A newer successful release exists; refusing to roll it back through an older plan.")
            journal["lock"] = lock(session, plan)
        else:
            require((current[1] if current else None) == plan["previousEtag"], "Last-successful record changed; inspect before rollback.")
        journal["rollbackRequested"] = datetime.now(timezone.utc).isoformat()
        journal["rollbackPreviousEtag"] = current[1] if current else None
        journal["rollbackStages"] = {}
        common.write(path.parent / "execution.json", journal)

    def restore_stage(kind, create):
        saved = journal["rollbackStages"].get(kind)
        if saved and saved.get("completed"):
            return
        if not saved:
            saved = create()
            require(not saved["blocked"], "Rollback scope requires inspection; no restore was executed.")
            journal["rollbackStages"][kind] = saved
            common.write(path.parent / "execution.json", journal)
        if not saved["noChanges"]:
            if not saved.get("requested"):
                saved["requested"] = True
                common.write(path.parent / "execution.json", journal)
                session.client("cloudformation").execute_change_set(ChangeSetName=saved["changeSet"], ClientRequestToken="restore-" + plan["id"] + "-" + kind)
            else:
                execution = session.client("cloudformation").describe_change_set(ChangeSetName=saved["changeSet"])
                require(execution.get("ExecutionStatus") in {"EXECUTE_IN_PROGRESS", "EXECUTE_COMPLETE"},
                        "A previous rollback request is ambiguous or failed; inspect its saved change set instead of repeating it.")
            wait_stack(session.client("cloudformation"), saved["stack"], saved["changeSet"])
        saved["completed"] = True
        common.write(path.parent / "execution.json", journal)
    if plan["rootNeeded"]:
        baseline = common.read(path.parent / "baseline.json")
        root = plan["rollback"]["root"]
        template = json.loads(common.object_bytes(session.client("s3"), root, config["account"]))
        args = [{"ParameterKey": row["ParameterKey"], **({"UsePreviousValue": True} if row["ParameterValue"] == "****" else {"ParameterValue": row["ParameterValue"]})}
                for row in baseline["stacks"]["root"]["stack"]["Parameters"] if row["ParameterKey"] in template.get("Parameters", {})]
        restore_stage("root", lambda: create_plan(session.client("cloudformation"), state["stacks"]["root"]["stack"],
                               url=common.template_url(root, config["region"]), parameters=args, state=state))
        after = target.snapshot(session, config["account"], config["region"])
        require(all(after["functions"][name]["CodeSha256"] == cfg["CodeSha256"]
                    and after["functions"][name].get("Environment", {}).get("Variables", {}) == cfg.get("Environment", {}).get("Variables", {})
                    for name, cfg in baseline["functions"].items()), "Working pre-release Lambda bytes/configuration were not restored.")
    if "image-worker" in plan["selected"]:
        before = common.read(path.parent / "worker-baseline.json")
        now = target.image_worker(session, target.snapshot(session, config["account"], config["region"]))
        arguments = [{"ParameterKey": row["ParameterKey"], **({"ParameterValue": before["parameters"]["WorkerImage"]}
                     if row["ParameterKey"] == "WorkerImage" else {"UsePreviousValue": True})} for row in now["stack"]["Parameters"]]
        restore_stage("worker", lambda: create_plan(session.client("cloudformation"), now["stack"], parameters=arguments, worker=True))
    if journal.get("frontend"):
        name = journal["frontend"]["container"]
        actual = inspect_container(name)
        if actual:
            require(actual["Config"].get("Labels", {}).get("navigan.release") == plan["id"], "Refusing to remove an unrelated container.")
            subprocess.check_call(["docker", "rm", "--force", name], stdout=subprocess.DEVNULL)
        old = journal.get("previousLocalFrontend")
        if old:
            actual = inspect_container(old["container"])
            require(actual and actual["Config"].get("Image") == old["image"]
                    and actual["Config"].get("Labels", {}).get("navigan.release") == old["releaseLabel"], "Previous local preview identity differs.")
            subprocess.check_call(["docker", "start", old["container"]], stdout=subprocess.DEVNULL)
            old_config = common.read(path.parent / "previous-record.json")["configuration"]
            runtime = json.loads(builder.http("http://127.0.0.1:3001/api/runtime-config"))
            verify_frontend_runtime(old_config, runtime)
            builder.http("http://127.0.0.1:3001/healthz")
            smoke(old_config, token, frontend=True)
    results = smoke(config, token)
    previous = common.read(path.parent / "previous-record.json")
    if previous:
        restored = copy.deepcopy(previous)
        restored.update(planId="rollback-" + plan["id"], rollbackOf=plan["id"], verifiedAt=datetime.now(timezone.utc).isoformat(),
                        authenticatedChecks=results, authenticatedAcceptance="PASSED" if results else "NOT_REQUESTED")
        if "database" in journal["completedStages"]:
            restored["manifest"]["components"]["database"] = plan["manifest"]["components"]["database"]
    else:
        restored = {"status": "BASELINE_RESTORED", "environment": "dev", "rootStackId": config["rootStackId"],
                    "planId": "rollback-" + plan["id"], "verifiedAt": datetime.now(timezone.utc).isoformat(),
                    "forwardDatabaseArtifact": plan["manifest"]["components"].get("database"), "authenticatedChecks": results,
                    "authenticatedAcceptance": "PASSED" if results else "NOT_REQUESTED"}
    condition = {"IfMatch": journal["rollbackPreviousEtag"]} if journal["rollbackPreviousEtag"] else {"IfNoneMatch": "*"}
    if not journal.get("rollbackRecordPublished"):
        latest = common.get_optional(session.client("s3"), config["artifactBucket"], CURRENT, config["account"])
        if latest and latest[0].get("planId") == "rollback-" + plan["id"]:
            require(latest[0].get("rootStackId") == config["rootStackId"] and latest[0].get("status") == restored["status"],
                    "Saved rollback record differs.")
            journal["rollbackRecordPublished"] = {"uri": "s3://" + config["artifactBucket"] + "/" + CURRENT,
                                                 "versionId": latest[2], "sha256": sha(canonical(latest[0]))}
        else:
            journal["rollbackRecordPublished"] = common.put_bytes(session.client("s3"), config["artifactBucket"], CURRENT,
                                                                   canonical(restored), config["account"], **condition)
        common.write(path.parent / "execution.json", journal)
    unlock(session, plan, journal["lock"])
    journal["rollbackComplete"] = datetime.now(timezone.utc).isoformat()
    journal["lockReleased"] = True
    common.write(path.parent / "execution.json", journal)
    print("DEV application rollback verified. Forward database migrations and the existing port-3000 frontend were retained.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile")
    parser.add_argument("--region")
    parser.add_argument("--expected-account")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--bootstrap-registry", action="store_true")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--init", action="store_true")
    modes.add_argument("--prepare", action="store_true")
    modes.add_argument("--execute", type=Path)
    modes.add_argument("--verify", type=Path)
    modes.add_argument("--rollback", type=Path)
    args = parser.parse_args()
    if args.init:
        require(args.region and args.expected_account and not args.config and not args.manifest, "Initialization requires explicit account and region.")
        session = boto3.Session(profile_name=args.profile, region_name=args.region)
        state = target.snapshot(session, args.expected_account, args.region)
        bucket = target.registry(session, state, args.bootstrap_registry)
        config = target.configuration(session, state, bucket)
        directory = common.workspace("navigan-dev-release-config-")
        common.write(directory / "dev-config.json", config)
        print("Private DEV configuration: " + str(directory / "dev-config.json"))
        print("Artifact bucket: " + bucket)
        print("No application, live database or PROD deployment was performed.")
        return
    require(not args.bootstrap_registry, "Registry initialization is a separate explicit step.")
    if args.prepare:
        require(args.config and args.manifest, "Preparation requires DEV configuration and the built manifest.")
        config = common.read(args.config)
    else:
        require(not args.config and not args.manifest, "Execution targets come only from the saved reviewed plan.")
        config = common.read(args.execute or args.verify or args.rollback)["config"]
    target.validate_config(config)
    require(not args.region or args.region == config["region"], "Region differs from the saved DEV target.")
    require(not args.expected_account or args.expected_account == config["account"], "Account differs from the saved DEV target.")
    session = boto3.Session(profile_name=args.profile, region_name=config["region"])
    if args.prepare:
        prepare(session, args.config, args.manifest)
    elif args.execute:
        execute(session, args.execute)
    elif args.verify:
        verify(session, args.verify)
    else:
        rollback(session, args.rollback)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        detail = str(error) if isinstance(error, common.ReleaseError) else type(error).__name__
        raise SystemExit("DEV release stopped: " + detail + " Inspect the private plan/journal. After an execution request use --verify or --rollback; do not repeat execution. PROD is not a supported target.") from None
