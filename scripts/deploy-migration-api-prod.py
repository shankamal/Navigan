#!/usr/bin/env python3
"""Prepare a scoped PROD migration API change set; execute only a checked saved plan.

Default is read-only. --prepare saves rollback files, uploads versioned artifacts
and creates a CloudFormation change set without executing it. --execute PLAN
rechecks scope and production revision before execution. Source agents, connector
Lambda, collectors, frontend and authentication configuration are not updated.
"""
from __future__ import annotations

import argparse
import ast
import base64
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import quote
import urllib.request
import uuid
import zipfile

import boto3

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("prod_storage_release", ROOT / "scripts/deploy-migration-storage-prod.py")
storage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(storage)
ACCOUNT, REGION, PARENT = storage.ACCOUNT, storage.REGION, storage.PARENT
POLICY = "NaviganProdDeploymentDiscoveryPolicy"
POLICY_NAME = "NaviganProductionDeploymentDiscovery"
PERMISSION = "NaviganProdSourceInvokePermission"
ROUTES = (
    "GET /api/v1/source-clusters/{sourceClusterId}/deployment-sources",
    "PUT /api/v1/source-clusters/{sourceClusterId}/deployment-sources",
    "GET /api/v1/migrations/{migrationId}/deployment-evidence",
    "POST /api/v1/migrations/{migrationId}/deployment-evidence",
    "GET /api/v1/migrations/{migrationId}/artifact-workspaces",
    "POST /api/v1/migrations/{migrationId}/artifact-workspaces",
    "GET /api/v1/migrations/{migrationId}/artifact-workspaces/{workspaceId}",
    "POST /api/v1/migrations/{migrationId}/artifact-workspaces/{workspaceId}/collection-jobs",
    "POST /api/v1/migrations/{migrationId}/artifact-workspaces/{workspaceId}/exports",
    "POST /api/v1/source-clusters",
    "GET /api/v1/source-clusters",
    "GET /api/v1/source-clusters/{sourceClusterId}",
    "PUT /api/v1/source-clusters/{sourceClusterId}",
    "POST /api/v1/source-clusters/{sourceClusterId}/enrollments",
    "POST /api/v1/source-clusters/{sourceClusterId}/install",
)
ROUTE_IDS = {route: f"NaviganProdArtifactRoute{i}" for i, route in enumerate(ROUTES)}
ALLOWED_CHILD = {"MigrationFunction": "AWS::Lambda::Function", POLICY: "AWS::IAM::Policy",
                 PERMISSION: "AWS::Lambda::Permission", **{key: "AWS::ApiGatewayV2::Route" for key in ROUTE_IDS.values()}}
PREFIX = "navigan/modules/migration_management/"


def require(condition, message):
    storage.require(condition, message)


def body(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            raise RuntimeError("Expected a processed JSON CloudFormation template; stopped before deployment") from None
    require(isinstance(value, dict) and isinstance(value.get("Resources"), dict), "Invalid processed CloudFormation template")
    require(not any(r.get("Type", "").startswith("AWS::Serverless::") for r in value["Resources"].values()),
            "Expected a processed template, not unexpanded SAM resources")
    return value


def all_items(client, operation, key, **kwargs):
    items, token = [], None
    while True:
        page = getattr(client, operation)(**kwargs, **({"NextToken": token} if token else {}))
        items.extend(page.get(key, []))
        token = page.get("NextToken")
        if not token:
            return items


def check_checkout():
    storage.check_checkout()
    paths = ["scripts/deploy-migration-api-prod.py", "src/navigan/modules/migration_management",
             "src/navigan/modules/cluster_management/github_app.py"]
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--", *paths], cwd=ROOT, text=True)
    require(not dirty.strip(), "Review/commit local API release edits first; unrelated local files are preserved")


def runtime(session, settings):
    cfn = session.client("cloudformation")
    parent = cfn.describe_stacks(StackName=PARENT)["Stacks"][0]
    child = cfn.describe_stacks(StackName=settings["nested"])["Stacks"][0]
    require(child["StackStatus"] in storage.STABLE, "Migration stack must be stable")
    params = {p["ParameterKey"]: p["ParameterValue"] for p in child.get("Parameters", [])}
    api = params.get("ApiId", "")
    require(bool(re.fullmatch(r"[a-z0-9]+", api)), "Missing production API ID in migration stack parameters")
    require(params.get("DatabaseName") == "navigan", "Nested stack database must be navigan")
    config = session.client("lambda").get_function_configuration(FunctionName=settings["function"])
    require(config.get("PackageType", "Zip") == "Zip" and config.get("Runtime") == "python3.12"
            and config.get("Architectures", ["x86_64"]) == ["x86_64"], "Expected Python 3.12 x86_64 ZIP Lambda")
    resources = all_items(cfn, "list_stack_resources", "StackResourceSummaries", StackName=settings["nested"])
    integration = next((r["PhysicalResourceId"] for r in resources if r["LogicalResourceId"] == "MigrationIntegration"), None)
    require(bool(integration), "Production migration integration was not found")
    gateway = session.client("apigatewayv2")
    require(gateway.get_stage(ApiId=api, StageName="v1").get("AutoDeploy") is True,
            "PROD API v1 is not auto-deployed; prepare a separately reviewed stage deployment before promotion")
    target = gateway.get_integration(ApiId=api, IntegrationId=integration)
    require(target.get("IntegrationUri") == config["FunctionArn"], "Migration integration points at an unexpected Lambda")
    routes = all_items(gateway, "get_routes", "Items", ApiId=api)
    reference = next((r for r in routes if r["RouteKey"] == "GET /api/v1/migrations/{migrationId}"), None)
    require(reference and reference.get("AuthorizationType") == "JWT" and reference.get("AuthorizerId")
            and reference.get("Target") == "integrations/" + integration, "Expected an existing JWT-protected production migration route")
    authorizer = gateway.get_authorizer(ApiId=api, AuthorizerId=reference["AuthorizerId"])
    require(authorizer.get("AuthorizerType") == "JWT", "Production route authorizer must remain JWT")
    env = dict(config.get("Environment", {}).get("Variables", {}))
    if not env.get("GITHUB_APP_ID") or not env.get("GITHUB_APP_PRIVATE_KEY_SECRET_ARN"):
        cluster = next((o["OutputValue"] for o in parent.get("Outputs", []) if o["OutputKey"] == "ClusterManagementStackId"), None)
        if cluster:
            cluster_fn = cfn.describe_stack_resource(StackName=cluster, LogicalResourceId="ClusterFunction")["StackResourceDetail"]["PhysicalResourceId"]
            existing = session.client("lambda").get_function_configuration(FunctionName=cluster_fn).get("Environment", {}).get("Variables", {})
            for key in ("GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY_SECRET_ARN"):
                if not env.get(key) and existing.get(key):
                    env[key] = existing[key]
    root_template = body(cfn.get_template(StackName=PARENT, TemplateStage="Processed")["TemplateBody"])
    child_template = body(cfn.get_template(StackName=settings["nested"], TemplateStage="Processed")["TemplateBody"])
    return parent, config, api, reference, routes, env, root_template, child_template


def policy_document(session, env):
    roles = json.loads(env.get("SOURCE_REGISTRY_ALLOWED_ROLE_ARNS", "[]"))
    require(isinstance(roles, list) and all(isinstance(role, str) and re.fullmatch(r"arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]+", role) for role in roles),
            "Registry allowlist must contain exact role ARNs")
    statements = [
        {"Effect": "Allow", "Action": ["sts:AssumeRole"], "Resource": ["arn:aws:iam::*:role/navigan-source-discovery/*", *roles]},
        {"Effect": "Allow", "Action": ["secretsmanager:CreateSecret", "secretsmanager:PutSecretValue", "secretsmanager:GetSecretValue"],
         "Resource": f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:navigan/source-connections/*"},
    ]
    secret = env.get("GITHUB_APP_PRIVATE_KEY_SECRET_ARN")
    if secret:
        require(secret.startswith(f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:"), "Unexpected GitHub App secret account/region")
        statements.append({"Effect": "Allow", "Action": ["secretsmanager:GetSecretValue"], "Resource": secret})
        key = session.client("secretsmanager").describe_secret(SecretId=secret).get("KmsKeyId")
        if key:
            arn = session.client("kms").describe_key(KeyId=key)["KeyMetadata"]["Arn"]
            require(arn.startswith(f"arn:aws:kms:{REGION}:{ACCOUNT}:key/"), "Unexpected GitHub secret KMS key")
            statements.append({"Effect": "Allow", "Action": ["kms:Decrypt"], "Resource": arn})
    return {"Version": "2012-10-17", "Statement": statements}


def child_template(original, config, api, reference, routes, env, workspace, code, policy):
    result = copy.deepcopy(original)
    resources = result["Resources"]
    require(resources.get("MigrationFunction", {}).get("Type") == "AWS::Lambda::Function", "Processed MigrationFunction is missing")
    props = resources["MigrationFunction"]["Properties"]
    props["Code"] = code
    variables = dict(env)
    variables.update(MIGRATION_SOURCE_FIRST_ENABLED="true", SOURCE_REGISTRY_PRINCIPAL_ARN=config["Role"],
                     MIGRATION_WORKSPACE_BUCKET=workspace["WorkspaceBucketName"],
                     MIGRATION_WORKSPACE_KMS_KEY=workspace["WorkspaceKmsKeyArn"], MIGRATION_WORKSPACE_BUCKET_OWNER=ACCOUNT)
    require(variables.get("DB_NAME") == "navigan", "Do not change production database identity")
    props["Environment"] = {"Variables": variables}
    dependencies = resources["MigrationFunction"].get("DependsOn", [])
    dependencies = [dependencies] if isinstance(dependencies, str) else list(dependencies)
    if POLICY not in dependencies:
        dependencies.append(POLICY)
    resources["MigrationFunction"]["DependsOn"] = dependencies
    resources[POLICY] = {"Type": "AWS::IAM::Policy", "Properties": {
        "PolicyName": POLICY_NAME, "Roles": [config["Role"].rsplit("/", 1)[-1]], "PolicyDocument": policy}}
    desired = {"AuthorizationType": "JWT", "AuthorizerId": reference["AuthorizerId"],
               "AuthorizationScopes": reference.get("AuthorizationScopes", []), "Target": reference["Target"]}
    existing = {r["RouteKey"]: r for r in routes}
    for route in ROUTES:
        if route in existing:
            require(all(existing[route].get(k, [] if k == "AuthorizationScopes" else None) == v for k, v in desired.items()),
                    "Existing artifact route has unexpected protection/integration: " + route)
            continue
        logical = ROUTE_IDS[route]
        require(logical not in resources, "Route logical ID collision: " + logical)
        resources[logical] = {"Type": "AWS::ApiGatewayV2::Route", "Properties": {"ApiId": api, "RouteKey": route, **desired}}
    if PERMISSION not in resources:
        resources[PERMISSION] = {"Type": "AWS::Lambda::Permission", "Properties": {
            "Action": "lambda:InvokeFunction", "FunctionName": {"Ref": "MigrationFunction"},
            "Principal": "apigateway.amazonaws.com", "SourceAccount": ACCOUNT,
            "SourceArn": f"arn:aws:execute-api:{REGION}:{ACCOUNT}:{api}/v1/*/api/v1/source-clusters*"}}
    require(all(result["Resources"].get(key) == value for key, value in original["Resources"].items()
                if key not in {"MigrationFunction", POLICY, PERMISSION}), "Unrelated nested resources changed")
    return result


def parent_template(original, url):
    result = copy.deepcopy(original)
    nested = result["Resources"].get("MigrationManagement", {})
    require(nested.get("Type") == "AWS::CloudFormation::Stack", "Expected the existing migration nested stack")
    nested["Properties"]["TemplateURL"] = url
    return result


def package_api(original, directory, source=ROOT):
    prefix = source / "src" / PREFIX
    replacements = {PREFIX + p.name: p.read_bytes() for p in prefix.glob("*.py")}
    for required in ("handler.py", "service.py", "repository.py", "artifact_workspace.py", "workspace_export.py", "workspace_worker.py", "image_worker.py"):
        require(PREFIX + required in replacements, "Current source module is missing: " + required)
    github = "navigan/modules/cluster_management/github_app.py"
    replacements[github] = (source / "src" / github).read_bytes()
    for name, content in replacements.items():
        ast.parse(content, filename=name)
    wheel_dir = directory / "wheels"
    wheel_dir.mkdir()
    subprocess.check_call([sys.executable, "-m", "pip", "download", "--no-deps", "--only-binary=:all:",
        "--platform", "manylinux2014_x86_64", "--python-version", "312", "--implementation", "cp", "--abi", "cp312",
        "--dest", str(wheel_dir), "PyYAML==6.0.2"])
    wheels = list(wheel_dir.glob("PyYAML-*.whl")) + list(wheel_dir.glob("pyyaml-*.whl"))
    require(len(wheels) == 1, "Expected one pinned Lambda-compatible PyYAML wheel")
    with zipfile.ZipFile(wheels[0]) as wheel:
        replacements.update({n: wheel.read(n) for n in wheel.namelist() if n.startswith(("yaml/", "_yaml/")) and not n.endswith("/")})
    target = directory / "MigrationFunction-updated.zip"
    with zipfile.ZipFile(original) as old, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as new:
        names = old.namelist()
        require(len(names) == len(set(names)), "Original Lambda package contains duplicate members")
        require(all(PREFIX + n in names for n in ("handler.py", "service.py", "repository.py")), "Unexpected original Lambda ZIP structure")
        for entry in old.infolist():
            if entry.filename.endswith(".pyc") and ("/migration_management/" in entry.filename or
                    ("/cluster_management/" in entry.filename and Path(entry.filename).name.startswith("github_app."))):
                continue
            content = replacements.pop(entry.filename, None)
            new.writestr(entry, old.read(entry.filename) if content is None else content)
        for name, content in sorted(replacements.items()):
            new.writestr(name, content)
    require(target.stat().st_size <= 250 * 1024 * 1024, "Updated package is unexpectedly large")
    with zipfile.ZipFile(target) as package:
        require(sum(p.file_size for p in package.infolist()) <= 250 * 1024 * 1024, "Lambda uncompressed package limit exceeded")
    return target


def upload(session, workspace, directory, name, content):
    sha = hashlib.sha256(content).hexdigest()
    key = f"deployment-packages/prod-migration-api/{sha}/{name}"
    result = session.client("s3").put_object(Bucket=workspace["WorkspaceBucketName"], Key=key, Body=content,
        ExpectedBucketOwner=ACCOUNT, ServerSideEncryption="aws:kms", SSEKMSKeyId=workspace["WorkspaceKmsKeyArn"])
    version = result.get("VersionId")
    require(version and version != "null", "Immutable versioned deployment upload required")
    code = {"S3Bucket": workspace["WorkspaceBucketName"], "S3Key": key, "S3ObjectVersion": version}
    url = f"https://{workspace['WorkspaceBucketName']}.s3.{REGION}.amazonaws.com/{key}?versionId={quote(version, safe='')}"
    return code, url


def inspect_plan(cfn, identifier):
    root = cfn.describe_change_set(ChangeSetName=identifier)
    require(root.get("Status") == "CREATE_COMPLETE" and root.get("ExecutionStatus") == "AVAILABLE", "Change set is not executable")
    require(root.get("StackName") == PARENT, "Unexpected root stack")
    changes = all_items(cfn, "describe_change_set", "Changes", ChangeSetName=identifier)
    require(len(changes) == 1, "Root change set must modify only MigrationManagement")
    change = changes[0].get("ResourceChange", {})
    require(change.get("LogicalResourceId") == "MigrationManagement" and change.get("ResourceType") == "AWS::CloudFormation::Stack"
            and change.get("Action") == "Modify" and change.get("Replacement", "False") == "False", "Unrelated/destructive parent change rejected")
    nested = change.get("ChangeSetId")
    require(bool(nested), "Nested change-set details are required; no execution allowed")
    child = cfn.describe_change_set(ChangeSetName=nested)
    require(child.get("StackId", "").startswith(f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/{PARENT}-MigrationManagement-"), "Unexpected nested change-set target")
    child_changes = all_items(cfn, "describe_change_set", "Changes", ChangeSetName=nested)
    require(bool(child_changes), "Nested change set has no inspectable changes")
    for item in child_changes:
        resource = item.get("ResourceChange", {})
        logical = resource.get("LogicalResourceId")
        require(logical in ALLOWED_CHILD and resource.get("ResourceType") == ALLOWED_CHILD[logical], "Unexpected nested resource change: " + str(logical))
        require(resource.get("Action") in {"Add", "Modify"} and resource.get("Replacement", "False") == "False"
                and not resource.get("ChangeSetId"), "Nested deletion/replacement/import rejected")
        require(logical != "MigrationFunction" or resource.get("Action") == "Modify", "Existing MigrationFunction must not be recreated")
        print(f"  {resource['Action']} {logical} ({resource['ResourceType']})")
    return changes, child_changes


def stamp(stack):
    return str(stack.get("LastUpdatedTime") or stack["CreationTime"])


def execute(session, path):
    plan = json.loads(path.read_text())
    require(plan.get("format") == 1 and plan.get("account") == ACCOUNT and plan.get("region") == REGION, "Invalid PROD release plan")
    require(str(plan.get("changeSet", "")).startswith(f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:changeSet/"), "Unexpected change-set ARN")
    require(session.client("sts").get_caller_identity()["Account"] == ACCOUNT, "Unexpected AWS account")
    cfn = session.client("cloudformation")
    parent = cfn.describe_stacks(StackName=PARENT)["Stacks"][0]
    require(parent["StackStatus"] in storage.STABLE and stamp(parent) == plan["parentStamp"], "Parent stack changed since preparation")
    current = session.client("lambda").get_function_configuration(FunctionName=plan["function"])
    require(current["FunctionArn"].startswith(f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{PARENT}-"), "Unexpected Lambda target")
    require(current["RevisionId"] == plan["revision"] and current["CodeSha256"] == plan["originalCodeSha256"], "Production API changed since preparation")
    inspect_plan(cfn, plan["changeSet"])
    cfn.execute_change_set(ChangeSetName=plan["changeSet"])
    print("Waiting for scoped production migration API update", flush=True)
    cfn.get_waiter("stack_update_complete").wait(StackName=PARENT, WaiterConfig={"Delay": 10, "MaxAttempts": 180})
    current = session.client("lambda").get_function_configuration(FunctionName=plan["function"])
    require(current["CodeSha256"] == plan["newCodeSha256"] and current.get("LastUpdateStatus") == "Successful", "Deployed API package does not match release")
    env = current.get("Environment", {}).get("Variables", {})
    require(env.get("DB_NAME") == "navigan" and env.get("MIGRATION_SOURCE_FIRST_ENABLED") == "true"
            and env.get("MIGRATION_WORKSPACE_BUCKET") == plan["workspaceBucket"], "Production API configuration verification failed")
    print("PROD migration API deployed. Collectors, source agents and frontend have not been updated. Authenticated workflow smoke tests remain required.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="navigan")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--execute", type=Path, metavar="PLAN")
    args = parser.parse_args()
    session = boto3.Session(profile_name=args.profile, region_name=REGION)
    if args.execute:
        execute(session, args.execute)
        return 0
    check_checkout()
    settings = storage.preflight(session)
    workspace = storage.verify_storage(session, "artifact-workspace")
    parent, config, api, reference, routes, env, root, child = runtime(session, settings)
    policy = policy_document(session, env)
    # Detect route/policy collisions before any uploads or change-set writes.
    child_template(child, config, api, reference, routes, env, workspace, {"S3Bucket": "preflight"}, policy)
    if POLICY not in child["Resources"]:
        names = [name for page in session.client("iam").get_paginator("list_role_policies").paginate(RoleName=settings["role"])
                 for name in page["PolicyNames"]]
        require(POLICY_NAME not in names, "An unmanaged policy has the reserved release name; do not overwrite it")
    print("PROD database, storage, API identity and JWT reference verified")
    print("GitHub App configuration: " + ("present" if env.get("GITHUB_APP_ID") and env.get("GITHUB_APP_PRIVATE_KEY_SECRET_ARN") else "missing; configure before repository collection"))
    if not args.prepare:
        print("Read-only readiness check passed. Use --prepare to create a scoped, unexecuted change set.")
        return 0
    directory = Path(tempfile.mkdtemp(prefix="navigan-prod-migration-api-"))
    directory.chmod(0o700)
    print("Private rollback/release record: " + str(directory), flush=True)
    for name, value in (("parent-original-template.json", root), ("migration-original-template.json", child), ("MigrationFunction-original-configuration.json", config)):
        (directory / name).write_text(json.dumps(value, indent=2))
    deployed = session.client("lambda").get_function(FunctionName=settings["function"])
    require(deployed["Configuration"]["RevisionId"] == config["RevisionId"], "API changed before package download")
    original = directory / "MigrationFunction-original.zip"
    with urllib.request.urlopen(deployed["Code"]["Location"], timeout=60) as response, original.open("wb") as stream:
        shutil.copyfileobj(response, stream)
    require(base64.b64encode(hashlib.sha256(original.read_bytes()).digest()).decode() == config["CodeSha256"], "Downloaded original package checksum mismatch")
    package = package_api(original, directory)
    code, _ = upload(session, workspace, directory, "migration-api.zip", package.read_bytes())
    updated_child = child_template(child, config, api, reference, routes, env, workspace, code, policy)
    _, child_url = upload(session, workspace, directory, "migration-template.json", json.dumps(updated_child).encode())
    updated_root = parent_template(root, child_url)
    _, root_url = upload(session, workspace, directory, "parent-template.json", json.dumps(updated_root).encode())
    for name, value in (("migration-updated-template.json", updated_child), ("parent-updated-template.json", updated_root)):
        (directory / name).write_text(json.dumps(value, indent=2))
    request = dict(StackName=PARENT, ChangeSetName="navigan-prod-migration-api-" + uuid.uuid4().hex[:16], ChangeSetType="UPDATE",
        TemplateURL=root_url, IncludeNestedStacks=True, Capabilities=["CAPABILITY_NAMED_IAM", "CAPABILITY_AUTO_EXPAND"],
        Parameters=[{"ParameterKey": p["ParameterKey"], "UsePreviousValue": True} for p in parent.get("Parameters", [])])
    if parent.get("RoleARN"):
        request["RoleARN"] = parent["RoleARN"]
    cfn = session.client("cloudformation")
    identifier = cfn.create_change_set(**request)["Id"]
    print("Prepared change set: " + identifier, flush=True)
    cfn.get_waiter("change_set_create_complete").wait(ChangeSetName=identifier, WaiterConfig={"Delay": 5, "MaxAttempts": 180})
    root_changes, child_changes = inspect_plan(cfn, identifier)
    plan = {"format": 1, "account": ACCOUNT, "region": REGION, "changeSet": identifier, "parentStamp": stamp(parent),
            "function": settings["function"], "revision": config["RevisionId"], "originalCodeSha256": config["CodeSha256"],
            "newCodeSha256": base64.b64encode(hashlib.sha256(package.read_bytes()).digest()).decode(),
            "workspaceBucket": workspace["WorkspaceBucketName"], "rootChanges": root_changes, "migrationChanges": child_changes}
    path = directory / "release-plan.json"
    path.write_text(json.dumps(plan, indent=2))
    print("Scoped API change set validated; not executed. Release plan: " + str(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
