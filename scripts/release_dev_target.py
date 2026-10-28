"""Read DEV ownership/bindings and initialize only its isolated artifact registry."""
from __future__ import annotations

import base64
import copy
import json
import re
import urllib.parse
import urllib.request
import uuid

import release_common as common

require = common.require
STABLE = {"CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE", "IMPORT_COMPLETE"}


def snapshot(session, account, region):
    require(re.fullmatch(r"[0-9]{12}", account) and session.region_name == region,
            "Explicit AWS account/region required.")
    require(session.client("sts").get_caller_identity()["Account"] == account, "Unexpected AWS account.")
    cfn = session.client("cloudformation")
    stacks, functions = {}, {}

    def visit(name, logical, parent=None):
        stack = cfn.describe_stacks(StackName=name)["Stacks"][0]
        require(stack["StackId"].startswith(f"arn:aws:cloudformation:{region}:{account}:stack/")
                and stack["StackStatus"] in STABLE, "DEV stack is not in the expected account/region/stable state.")
        if parent:
            require(stack.get("ParentId") == parent, "Nested stack ownership differs.")
        else:
            require(stack.get("StackName") == common.DEV_STACK and not stack.get("ParentId"), "Only the existing DEV root stack is supported.")
        resources = common.pages(cfn, "list_stack_resources", "StackResourceSummaries", StackName=stack["StackId"])
        resources = [row for row in resources if row.get("PhysicalResourceId") and row.get("ResourceStatus") != "DELETE_COMPLETE"]
        stacks[logical] = {"stack": stack, "resources": resources,
            "original": cfn.get_template(StackName=stack["StackId"], TemplateStage="Original")["TemplateBody"],
            "processed": cfn.get_template(StackName=stack["StackId"], TemplateStage="Processed")["TemplateBody"]}
        for row in resources:
            path = logical + "/" + row["LogicalResourceId"]
            if row["ResourceType"] == "AWS::CloudFormation::Stack":
                visit(row["PhysicalResourceId"], path, stack["StackId"])
            elif row["ResourceType"] == "AWS::Lambda::Function":
                cfg = session.client("lambda").get_function_configuration(FunctionName=row["PhysicalResourceId"])
                require(cfg.get("FunctionArn", "").startswith(f"arn:aws:lambda:{region}:{account}:function:")
                        and cfg.get("State") == "Active" and cfg.get("LastUpdateStatus") == "Successful",
                        "DEV Lambda is not stable or belongs to another account.")
                variables = cfg.get("Environment", {}).get("Variables", {})
                require("DB_NAME" not in variables or variables["DB_NAME"] == common.DEV_DATABASE,
                        "A DEV Lambda is bound to another database.")
                functions[path] = cfg
    visit(common.DEV_STACK, "root")
    root = stacks["root"]["stack"]
    parameters = {item["ParameterKey"]: item["ParameterValue"] for item in root.get("Parameters", [])}
    require(parameters.get("DatabaseName") == common.DEV_DATABASE, "DEV root database identity differs.")
    shared = stacks.get("root/SharedPlatform")
    require(shared, "DEV shared platform ownership was not found.")
    outputs = {item["OutputKey"]: item["OutputValue"] for item in shared["stack"].get("Outputs", [])}
    api = outputs.get("ApiId")
    require(api and isinstance(api, str), "DEV API identity was not found.")
    mappings = session.client("apigatewayv2").get_api_mappings(DomainName="api-dev.navigan.click").get("Items", [])
    require(len(mappings) == 1 and mappings[0].get("ApiMappingKey", "") == ""
            and mappings[0].get("ApiId") == api and mappings[0].get("Stage") == "v1",
            "DEV custom domain does not map exclusively to the owned DEV API/v1 stage.")
    roles = {}
    iam = session.client("iam")
    for record in stacks.values():
        for row in record["resources"]:
            if row["ResourceType"] != "AWS::IAM::Role":
                continue
            name = row["PhysicalResourceId"]
            role = iam.get_role(RoleName=name)["Role"]
            inline = {policy: iam.get_role_policy(RoleName=name, PolicyName=policy)["PolicyDocument"]
                      for policy in common.pages(iam, "list_role_policies", "PolicyNames", RoleName=name)}
            attached = common.pages(iam, "list_attached_role_policies", "AttachedPolicies", RoleName=name)
            roles[name] = {"role": {key: role[key] for key in ("Arn", "RoleId", "Path", "Description", "MaxSessionDuration", "AssumeRolePolicyDocument", "PermissionsBoundary", "Tags") if key in role},
                           "inline": inline, "attached": sorted(attached, key=lambda item: item["PolicyArn"])}
            if "Tags" in roles[name]["role"]:
                roles[name]["role"]["Tags"] = sorted(roles[name]["role"]["Tags"], key=lambda item: item["Key"])
    return {"account": account, "region": region, "stacks": stacks, "functions": functions, "roles": roles, "apiId": api}


def stamp(state):
    return common.sha(common.canonical({
        "stacks": {path: {"id": value["stack"]["StackId"], "updated": value["stack"].get("LastUpdatedTime"),
                           "created": value["stack"].get("CreationTime"), "template": value["original"],
                           "parameters": value["stack"].get("Parameters"),
                           "resources": sorted((row["LogicalResourceId"], row["PhysicalResourceId"]) for row in value["resources"])}
                   for path, value in state["stacks"].items()},
        "functions": {path: {"revision": cfg.get("RevisionId"), "code": cfg.get("CodeSha256")}
                      for path, cfg in state["functions"].items()}, "roles": state.get("roles", {}), "api": state["apiId"]}))


def registry(session, state, bootstrap=False):
    name = common.DEV_STACK + "-release-artifacts"
    cfn = session.client("cloudformation")
    try:
        stack = cfn.describe_stacks(StackName=name)["Stacks"][0]
    except Exception as error:
        missing = getattr(error, "response", {}).get("Error", {}).get("Code") == "ValidationError"
        if not missing or not bootstrap:
            raise
        template = common.yaml_document((common.ROOT / "infrastructure/companion/dev-release-artifacts.yaml").read_text())
        allowed = {"AWS::S3::Bucket", "AWS::S3::BucketPolicy", "AWS::ECR::Repository"}
        require(all(item.get("Type") in allowed for item in template["Resources"].values()),
                "Registry initialization cannot create application, identity or database resources.")
        worker = image_worker(session, state, optional=True)
        execution_role = worker["parameters"]["ExecutionRoleArn"] if worker else ""
        identifier = cfn.create_change_set(StackName=name, ChangeSetName="dev-registry-" + uuid.uuid4().hex[:12],
            ChangeSetType="CREATE", TemplateBody=json.dumps(template),
            Parameters=[{"ParameterKey": "ImageWorkerExecutionRoleArn", "ParameterValue": execution_role}],
            Tags=[{"Key": "navigan:environment", "Value": "dev"}, {"Key": "navigan:purpose", "Value": "release-artifacts"}])["Id"]
        cfn.get_waiter("change_set_create_complete").wait(ChangeSetName=identifier)
        changes = common.pages(cfn, "describe_change_set", "Changes", ChangeSetName=identifier)
        require(len(changes) == len(template["Resources"]) and all(
            item["ResourceChange"].get("Action") == "Add" and item["ResourceChange"].get("ResourceType") in allowed
            and item["ResourceChange"].get("LogicalResourceId") in template["Resources"] for item in changes),
            "Registry change set has unexpected scope.")
        print("Creating only the isolated DEV artifact registry...", flush=True)
        cfn.execute_change_set(ChangeSetName=identifier, ClientRequestToken="dev-registry-" + uuid.uuid4().hex)
        cfn.get_waiter("stack_create_complete").wait(StackName=name)
        stack = cfn.describe_stacks(StackName=name)["Stacks"][0]
    require(stack.get("StackName") == name and stack.get("StackStatus") in STABLE
            and stack["StackId"].startswith(f"arn:aws:cloudformation:{state['region']}:{state['account']}:stack/{name}/"),
            "DEV artifact registry stack identity differs.")
    resources = common.pages(cfn, "list_stack_resources", "StackResourceSummaries", StackName=stack["StackId"])
    require(all(row["ResourceType"] in {"AWS::S3::Bucket", "AWS::S3::BucketPolicy", "AWS::ECR::Repository"}
                for row in resources if row.get("ResourceStatus") != "DELETE_COMPLETE"), "Registry stack owns unexpected resources.")
    bucket = next(row["OutputValue"] for row in stack["Outputs"] if row["OutputKey"] == "ArtifactBucket")
    common.verify_registry(session, bucket, state["account"], state["region"])
    return bucket


def configuration(session, state, bucket, *, components=None):
    params = {item["ParameterKey"]: item["ParameterValue"] for item in state["stacks"]["root"]["stack"]["Parameters"]}
    issuer, audience = params["JwtIssuer"], params["JwtAudience"]
    require(re.fullmatch(r"https://cognito-idp\.[a-z0-9-]+\.amazonaws\.com/[a-z0-9-]+_[A-Za-z0-9]+", issuer)
            and re.fullmatch(r"[A-Za-z0-9]+", audience), "DEV public identity settings are invalid.")
    client = session.client("cognito-idp").describe_user_pool_client(UserPoolId=issuer.rsplit("/", 1)[1], ClientId=audience)["UserPoolClient"]
    require(client.get("ClientId") == audience and not client.get("ClientSecret"), "Expected the existing public DEV app client.")
    migration = next((item for path, item in state["functions"].items() if path.endswith("/MigrationFunction")), {})
    env = migration.get("Environment", {}).get("Variables", {})
    public = {"NAVIGAN_PUBLIC_OIDC_AUTHORITY": issuer, "NAVIGAN_PUBLIC_OIDC_CLIENT_ID": audience,
              "NAVIGAN_PUBLIC_APP_URL": "http://localhost:3001", "NAVIGAN_PUBLIC_CORPORATE_LOGO_URL": ""}
    for key in ("MIGRATION_CONNECTOR_API_BASE_URL", "MIGRATION_CONNECTOR_IMAGE_REPOSITORY", "MIGRATION_CONNECTOR_IMAGE_DIGEST"):
        public["NAVIGAN_PUBLIC_" + key] = env.get(key, "")
    # Inspect the collector only when this manifest manages that component.
    # The legacy initializer has no manifest and retains its discovery behavior.
    worker = image_worker(session, state, optional=True) if components is None or "image-worker" in components else None
    return {"format": "navigan-dev-release-config-v1", "environment": "dev", "account": state["account"],
            "region": state["region"], "stack": common.DEV_STACK, "rootStackId": state["stacks"]["root"]["stack"]["StackId"],
            "database": common.DEV_DATABASE, "artifactBucket": bucket, "apiOrigin": common.DEV_API, "apiBasePath": "/api/v1",
            "frontend": {"mode": "local-preview", "port": 3001, "publicEnvironment": public},
            "imageWorkerEnabled": bool(worker), "parameterOverrides": {}}


def validate_config(config):
    require(config.get("format") == "navigan-dev-release-config-v1" and config.get("environment") == "dev"
            and config.get("stack") == common.DEV_STACK and config.get("database") == common.DEV_DATABASE
            and config.get("apiOrigin") == common.DEV_API and config.get("apiBasePath") == "/api/v1",
            "Only the fixed DEV target is supported; PROD execution is disabled.")
    front = config.get("frontend", {})
    require(front.get("mode") == "local-preview" and front.get("port") == 3001,
            "DEV frontend is a separate local candidate on port 3001; existing port 3000 is preserved.")
    env = front.get("publicEnvironment", {})
    allowed = {"NAVIGAN_PUBLIC_" + key for key in ("OIDC_AUTHORITY", "OIDC_CLIENT_ID", "APP_URL", "CORPORATE_LOGO_URL",
               "MIGRATION_CONNECTOR_API_BASE_URL", "MIGRATION_CONNECTOR_IMAGE_REPOSITORY", "MIGRATION_CONNECTOR_IMAGE_DIGEST")}
    require(set(env) <= allowed and all(isinstance(value, str) for value in env.values())
            and env.get("NAVIGAN_PUBLIC_APP_URL") == "http://localhost:3001", "Invalid DEV public runtime configuration.")
    require(isinstance(config.get("parameterOverrides"), dict), "Expected explicit parameter overrides.")


def image_worker(session, state, optional=False):
    cfn = session.client("cloudformation")
    name = common.DEV_STACK + "-workspace-images"
    try:
        stack = cfn.describe_stacks(StackName=name)["Stacks"][0]
    except Exception as error:
        if optional and getattr(error, "response", {}).get("Error", {}).get("Code") == "ValidationError":
            return None
        raise
    account, region = state["account"], state["region"]
    require(stack.get("StackName") == name and stack["StackId"].startswith(f"arn:aws:cloudformation:{region}:{account}:stack/{name}/")
            and stack["StackStatus"] in STABLE, "DEV collector stack identity differs.")
    parameters = {item["ParameterKey"]: item["ParameterValue"] for item in stack.get("Parameters", [])}
    require(parameters.get("DatabaseName") == common.DEV_DATABASE, "Collector belongs to another database.")
    runtime_name = common.DEV_STACK + "-workspace-image-runtime"
    runtime = cfn.describe_stacks(StackName=runtime_name)["Stacks"][0]
    require(runtime.get("StackName") == runtime_name and runtime["StackId"].startswith(f"arn:aws:cloudformation:{region}:{account}:stack/{runtime_name}/")
            and runtime["StackStatus"] in STABLE, "Collector runtime ownership differs.")
    outputs = {item["OutputKey"]: item["OutputValue"] for item in runtime["Outputs"]}
    require(parameters.get("ClusterArn") == outputs.get("ClusterArn")
            and parameters.get("ExecutionRoleArn") == outputs.get("ExecutionRoleArn"), "Collector runtime bindings differ.")
    resources = common.pages(cfn, "list_stack_resources", "StackResourceSummaries", StackName=stack["StackId"])
    ids = {item["LogicalResourceId"]: item["PhysicalResourceId"] for item in resources}
    ecs = session.client("ecs")
    response = ecs.describe_services(cluster=parameters["ClusterArn"], services=[ids["WorkerService"]])
    require(not response.get("failures") and len(response.get("services", [])) == 1, "DEV image collector service is missing.")
    service = response["services"][0]
    task = ecs.describe_task_definition(taskDefinition=service["taskDefinition"])["taskDefinition"]
    require(service["taskDefinition"] == ids["WorkerTask"] and service.get("pendingCount", 0) == 0
            and service.get("runningCount") == service.get("desiredCount")
            and len(service.get("deployments", [])) == 1 and service["deployments"][0].get("rolloutState") == "COMPLETED",
            "Collector has drift or an unfinished rollout; inspect before replacing its task.")
    return {"stack": stack, "parameters": parameters, "service": service, "task": task,
            "original": cfn.get_template(StackName=stack["StackId"], TemplateStage="Original")["TemplateBody"]}


def function_properties(before, cfg, code):
    props = copy.deepcopy(before)
    for key in ("Handler", "Runtime", "Timeout", "MemorySize", "Description", "Environment", "KMSKeyArn",
                "TracingConfig", "DeadLetterConfig", "Architectures", "EphemeralStorage", "FileSystemConfigs", "LoggingConfig"):
        if key in cfg:
            props[key] = copy.deepcopy(cfg[key])
        else:
            props.pop(key, None)
    props["Environment"] = {"Variables": copy.deepcopy(cfg.get("Environment", {}).get("Variables", {}))}
    # Preserve the same-stack role expression, but reject a changed actual role.
    if not isinstance(props.get("Role"), dict):
        props["Role"] = cfg["Role"]
    vpc = cfg.get("VpcConfig", {})
    if vpc.get("VpcId"):
        props["VpcConfig"] = {key: vpc[key] for key in ("SubnetIds", "SecurityGroupIds", "Ipv6AllowedForDualStack") if key in vpc}
    else:
        props.pop("VpcConfig", None)
    if cfg.get("Layers"):
        props["Layers"] = [item["Arn"] for item in cfg["Layers"]]
    else:
        props.pop("Layers", None)
    bucket, key = common.s3_location(code)
    props["Code"] = {"S3Bucket": bucket, "S3Key": key, "S3ObjectVersion": code["versionId"]}
    return props


def rollback_template(session, state, bucket):
    """Native template with the actual pre-release Lambda bytes and live role policies."""
    s3, iam, lam = session.client("s3"), session.client("iam"), session.client("lambda")
    account, region = state["account"], state["region"]
    roles, code_refs, references = state["roles"], {}, {}
    for logical, cfg in state["functions"].items():
        described = lam.get_function(FunctionName=cfg["FunctionName"])
        require(described["Configuration"].get("RevisionId") == cfg.get("RevisionId")
                and described["Configuration"].get("CodeSha256") == cfg.get("CodeSha256"), "DEV code changed during rollback capture.")
        url = described["Code"]["Location"]
        parsed = urllib.parse.urlsplit(url)
        require(parsed.scheme == "https" and (parsed.hostname or "").endswith(".amazonaws.com"), "Unexpected deployed-package download host.")
        with urllib.request.urlopen(url, timeout=60) as response:
            content = response.read(300 * 1024 * 1024 + 1)
        require(len(content) <= 300 * 1024 * 1024
                and base64.b64encode(bytes.fromhex(common.sha(content))).decode() == cfg["CodeSha256"], "Rollback ZIP checksum differs.")
        code_refs[logical] = common.put_content(s3, bucket, "objects/rollback-code/" + common.sha(content) + ".zip", content, account)

    separate_names = {row["PhysicalResourceId"] for record in state["stacks"].values()
                      for row in record["resources"] if row["ResourceType"] == "AWS::IAM::Policy"}

    def publish(logical):
        record = state["stacks"][logical]
        template = record["processed"]
        template = copy.deepcopy(template if isinstance(template, dict) else common.yaml_document(template))
        template.pop("Transform", None)
        require(not any(item["Type"].startswith("AWS::Serverless::") for item in template["Resources"].values()),
                "Rollback requires fully processed native templates.")
        for row in record["resources"]:
            item = template["Resources"][row["LogicalResourceId"]]
            props = item.setdefault("Properties", {})
            path = logical + "/" + row["LogicalResourceId"]
            kind = row["ResourceType"]
            if kind == "AWS::CloudFormation::Stack":
                props["TemplateURL"] = common.template_url(publish(path), region)
            elif kind == "AWS::Lambda::Function":
                cfg = state["functions"][path]
                item["Properties"] = function_properties(props, cfg, code_refs[path])
                expression = props.get("Role", {}).get("Fn::GetAtt") if isinstance(props.get("Role"), dict) else None
                name = next((r["PhysicalResourceId"] for r in record["resources"] if isinstance(expression, list)
                             and len(expression) == 2 and expression[1] == "Arn" and r["LogicalResourceId"] == expression[0]), None)
                if not name or roles.get(name, {}).get("role", {}).get("Arn") != cfg["Role"]:
                    item["Properties"]["Role"] = cfg["Role"]
                concurrency = lam.get_function_concurrency(FunctionName=state["functions"][path]["FunctionName"])
                if "ReservedConcurrentExecutions" in concurrency:
                    item["Properties"]["ReservedConcurrentExecutions"] = concurrency["ReservedConcurrentExecutions"]
                else:
                    item["Properties"].pop("ReservedConcurrentExecutions", None)
            elif kind == "AWS::IAM::Role":
                live = roles[row["PhysicalResourceId"]]
                props["AssumeRolePolicyDocument"] = live["role"]["AssumeRolePolicyDocument"]
                for key in ("Description", "MaxSessionDuration"):
                    if key in live["role"]:
                        props[key] = live["role"][key]
                tags = [item for item in live["role"].get("Tags", []) if not item["Key"].startswith("aws:")]
                if tags or "Tags" in props:
                    props["Tags"] = tags
                if live["role"].get("PermissionsBoundary"):
                    props["PermissionsBoundary"] = live["role"]["PermissionsBoundary"]["PermissionsBoundaryArn"]
                else:
                    props.pop("PermissionsBoundary", None)
                attached = [policy["PolicyArn"] for policy in live["attached"]]
                inline = [{"PolicyName": name, "PolicyDocument": document} for name, document in live["inline"].items() if name not in separate_names]
                if attached or "ManagedPolicyArns" in props:
                    props["ManagedPolicyArns"] = attached
                if inline or "Policies" in props:
                    props["Policies"] = inline
            elif kind == "AWS::IAM::Policy":
                matches = [role["inline"][row["PhysicalResourceId"]] for role in roles.values() if row["PhysicalResourceId"] in role["inline"]]
                require(matches and len({common.sha(common.canonical(item)) for item in matches}) == 1,
                        "Rollback policy ownership is ambiguous.")
                props["PolicyDocument"] = matches[0]
        content = common.canonical(template)
        result = common.put_content(s3, bucket, "objects/rollback-templates/" + common.sha(content) + ".json", content, account)
        references[logical] = result
        return result
    root = publish("root")
    return {"root": root, "templates": references, "functions": code_refs}
