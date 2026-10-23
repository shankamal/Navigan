#!/usr/bin/env python3
"""Prepare an immutable PROD frontend image/task; execute only the saved release plan.

Default: read-only readiness check. --prepare exports committed frontend source,
builds/pushes its image and registers a task revision without changing the service.
--execute PLAN verifies the task diff and current baseline, then updates only the
Navigan frontend service. Existing API/auth/network/IAM settings are preserved.
"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import urllib.request
import uuid

import boto3

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("frontend_prod_storage", ROOT / "scripts/deploy-migration-storage-prod.py")
storage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(storage)
ACCOUNT, REGION = storage.ACCOUNT, storage.REGION
CLUSTER = "navigan-frontend-Cluster-bw32Pkwxn8Cs"
SERVICE = "navigan-frontend-Service-vMtHq9h7A9mz"
FAMILY = "navigan-frontend-TaskDefinition-j9W80aX9PBkf"
CONTAINER = "frontend"
REPOSITORY = "navigan/frontend"
REGISTRY = f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com"
IMAGE_PREFIX = REGISTRY + "/" + REPOSITORY
APP_URL = "https://navigan.click"
FLAG = "MIGRATION_SOURCE_FIRST_ENABLED"


def require(condition, message):
    storage.require(condition, message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def read_service(ecs):
    result = ecs.describe_services(cluster=CLUSTER, services=[SERVICE])
    require(not result.get("failures") and len(result.get("services", [])) == 1, "Navigan frontend service was not found")
    service = result["services"][0]
    require(service.get("serviceName") == SERVICE and service.get("status") == "ACTIVE", "Unexpected/inactive frontend service")
    require(service.get("clusterArn", "").startswith(f"arn:aws:ecs:{REGION}:{ACCOUNT}:cluster/{CLUSTER}"), "Unexpected frontend cluster account/region")
    require(service.get("deploymentController", {}).get("type", "ECS") == "ECS", "Expected the existing rolling ECS deployment controller")
    return service


def stable(service):
    deployments = service.get("deployments", [])
    return (service.get("desiredCount", 0) > 0 and service.get("runningCount") == service["desiredCount"]
            and service.get("pendingCount", 0) == 0 and len(deployments) == 1
            and deployments[0].get("status") == "PRIMARY" and deployments[0].get("rolloutState") == "COMPLETED")


def environment(container):
    values = container.get("environment", [])
    result = {p["name"]: p["value"] for p in values}
    require(len(result) == len(values), "Duplicate frontend environment names require review")
    return result


def container(task):
    matches = [c for c in task.get("containerDefinitions", []) if c.get("name") == CONTAINER]
    require(len(matches) == 1, "Expected exactly one frontend container")
    return matches[0]


def normalize(request):
    result = copy.deepcopy(request)
    frontend = container(result)
    environment(frontend)  # Duplicate names have order-dependent behavior; reject them.
    if "environment" in frontend:
        frontend["environment"].sort(key=lambda item: item["name"])
    if "tags" in result:
        result["tags"].sort(key=lambda item: item["key"])
    return result


def task_request(task, tags, accepted):
    require(task.get("family") == FAMILY, "Unexpected frontend task family")
    request = {k: copy.deepcopy(v) for k, v in task.items() if k in accepted and k != "tags"}
    user_tags = [copy.deepcopy(t) for t in tags if not t["key"].startswith("aws:")]
    if user_tags:
        request["tags"] = user_tags
    return normalize(request)


def candidate_request(original, image):
    require(bool(re.fullmatch(re.escape(IMAGE_PREFIX) + r"@sha256:[a-f0-9]{64}", image)), "Use an immutable image from the PROD frontend repository")
    result = copy.deepcopy(original)
    frontend = container(result)
    current = environment(frontend)
    require(current.get("NODE_ENV", "production") == "production", "Do not run a development server in production")
    frontend["image"] = image
    values = frontend.setdefault("environment", [])
    existing = next((p for p in values if p["name"] == FLAG), None)
    if existing:
        existing["value"] = "true"
    else:
        values.append({"name": FLAG, "value": "true"})
    return result


def public_config(parameters, hostname):
    require(hostname == "navigan.click", "Unexpected production frontend hostname")
    issuer, client = parameters.get("JwtIssuer", ""), parameters.get("JwtAudience", "")
    require(bool(re.fullmatch(r"https://cognito-idp\.ap-south-1\.amazonaws\.com/(ap-south-1_[A-Za-z0-9]+)", issuer)), "Invalid production Cognito issuer")
    require(bool(re.fullmatch(r"[A-Za-z0-9]{10,128}", client)), "Expected one exact public Cognito client ID without whitespace")
    pool = issuer.rsplit("/", 1)[-1]
    require(parameters.get("IdentityUserPoolId", pool) == pool, "Cognito pool references disagree")
    return {"NEXT_PUBLIC_OIDC_AUTHORITY": issuer, "NEXT_PUBLIC_OIDC_CLIENT_ID": client, "NEXT_PUBLIC_APP_URL": APP_URL}


def check_checkout():
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    require(branch == storage.BRANCH, "Use the existing approved branch/checkout")
    # Build git archive, never the working tree: preserve generated next-env.d.ts and local files.
    paths = ["frontend/src", "frontend/public", "frontend/package.json", "frontend/package-lock.json", "frontend/Dockerfile",
             "frontend/.dockerignore", "frontend/next.config.ts", "frontend/tsconfig.json", "scripts/deploy-frontend-prod.py"]
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--", *paths], cwd=ROOT, text=True)
    require(not dirty.strip(), "Review/commit local frontend release-source edits first; no files were discarded")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def backend_readiness(session):
    settings = storage.preflight(session)
    workspace = storage.verify_storage(session, "artifact-workspace")
    env = session.client("lambda").get_function_configuration(FunctionName=settings["function"]).get("Environment", {}).get("Variables", {})
    require(env.get("MIGRATION_SOURCE_FIRST_ENABLED") == "true" and env.get("MIGRATION_WORKSPACE_BUCKET") == workspace["WorkspaceBucketName"],
            "Production migration API is not ready for the new UI")
    cfn = session.client("cloudformation")
    repo = cfn.describe_stacks(StackName=storage.PARENT + "-workspace-repositories")["Stacks"][0]
    outputs = {p["OutputKey"]: p["OutputValue"] for p in repo.get("Outputs", [])}
    require(session.client("events").describe_rule(Name=outputs["ScheduleName"])["State"] == "ENABLED", "Repository collector schedule must be enabled")
    image = cfn.describe_stacks(StackName=storage.PARENT + "-workspace-images")["Stacks"][0]
    params = {p["ParameterKey"]: p["ParameterValue"] for p in image.get("Parameters", [])}
    outputs = {p["OutputKey"]: p["OutputValue"] for p in image.get("Outputs", [])}
    cluster = params["ClusterArn"]
    require(cluster.startswith(f"arn:aws:ecs:{REGION}:{ACCOUNT}:cluster/{storage.PARENT}-workspace-image-runtime-"), "Unexpected collector cluster")
    service = session.client("ecs").describe_services(cluster=cluster, services=[outputs["WorkerServiceName"]])
    require(not service.get("failures") and len(service.get("services", [])) == 1, "Image worker service is missing")
    require(stable(service["services"][0]), "Image collector must be running/stable before frontend promotion")


def readiness(session):
    require(session.client("sts").get_caller_identity()["Account"] == ACCOUNT, "Unexpected AWS account")
    backend_readiness(session)
    cfn, ecs = session.client("cloudformation"), session.client("ecs")
    service = read_service(ecs)
    require(stable(service), "Current frontend must be stable before release preparation")
    described = ecs.describe_task_definition(taskDefinition=service["taskDefinition"], include=["TAGS"])
    task = described["taskDefinition"]
    require(task.get("runtimePlatform", {}).get("cpuArchitecture", "X86_64") == "X86_64", "Expected existing x86_64 frontend")
    accepted = ecs.meta.service_model.operation_model("RegisterTaskDefinition").input_shape.members
    original = task_request(task, described.get("tags", []), accepted)
    env = environment(container(original))
    parent = cfn.describe_stacks(StackName=storage.PARENT)["Stacks"][0]
    params = {p["ParameterKey"]: p["ParameterValue"] for p in parent.get("Parameters", [])}
    frontend = cfn.describe_stacks(StackName="navigan-frontend")["Stacks"][0]
    front_params = {p["ParameterKey"]: p["ParameterValue"] for p in frontend.get("Parameters", [])}
    public = public_config(params, front_params.get("FrontendHostname", ""))
    client = session.client("cognito-idp").describe_user_pool_client(UserPoolId=params["JwtIssuer"].rsplit("/", 1)[-1],
        ClientId=public["NEXT_PUBLIC_OIDC_CLIENT_ID"])["UserPoolClient"]
    require(client.get("ClientId") == public["NEXT_PUBLIC_OIDC_CLIENT_ID"] and not client.get("ClientSecret"), "Expected an existing public production Cognito client")
    nested = cfn.describe_stack_resource(StackName=storage.PARENT, LogicalResourceId="MigrationManagement")["StackResourceDetail"]["PhysicalResourceId"]
    nested_params = {p["ParameterKey"]: p["ParameterValue"] for p in cfn.describe_stacks(StackName=nested)["Stacks"][0].get("Parameters", [])}
    expected = f"https://{nested_params['ApiId']}.execute-api.{REGION}.amazonaws.com/v1/api/v1"
    current = env.get("NAVIGAN_API_ORIGIN", "").rstrip("/") + "/" + env.get("NAVIGAN_API_BASE_PATH", "").strip("/")
    require(current == expected, "Existing frontend API target does not match PROD; do not copy DEV or default API settings")
    ecr = session.client("ecr").describe_repositories(repositoryNames=[REPOSITORY])["repositories"][0]
    require(ecr.get("repositoryUri") == IMAGE_PREFIX, "Unexpected frontend image repository")
    return service, described, original, public


def runtime_digests(ecr, digest):
    response = ecr.batch_get_image(repositoryName=REPOSITORY, imageIds=[{"imageDigest": digest}])
    require(not response.get("failures") and len(response.get("images", [])) == 1, "Published frontend manifest cannot be verified")
    manifest = json.loads(response["images"][0]["imageManifest"])
    accepted = [digest]
    if "manifests" in manifest:
        platform = [m for m in manifest["manifests"] if m.get("platform", {}).get("os") == "linux" and m.get("platform", {}).get("architecture") == "amd64"]
        require(len(platform) == 1 and re.fullmatch(r"sha256:[a-f0-9]{64}", platform[0].get("digest", "")), "Expected one linux/amd64 frontend manifest")
        accepted.append(platform[0]["digest"])
    return accepted


def build_image(session, directory, revision, public):
    subprocess.check_call(["docker", "info"], stdout=subprocess.DEVNULL)
    subprocess.check_call(["docker", "buildx", "version"], stdout=subprocess.DEVNULL)
    archive = directory / "committed-frontend.tar"
    subprocess.check_call(["git", "archive", "--format=tar", "--output", str(archive), revision, "frontend"], cwd=ROOT)
    context = directory / "source"
    context.mkdir()
    with tarfile.open(archive) as stream:
        stream.extractall(context, filter="data")
    image = IMAGE_PREFIX + ":release-" + revision[:12] + "-" + uuid.uuid4().hex[:12]
    # Private Docker configuration; no user Docker config or environment files are sourced.
    docker_env = {**os.environ, "DOCKER_CONFIG": str(directory / "docker-auth")}
    auth = session.client("ecr").get_authorization_token(registryIds=[ACCOUNT])["authorizationData"][0]
    require(auth["proxyEndpoint"] == "https://" + REGISTRY, "Unexpected ECR login registry")
    username, password = base64.b64decode(auth["authorizationToken"]).decode().split(":", 1)
    require(username == "AWS", "Unexpected ECR username")
    subprocess.run(["docker", "login", "--username", "AWS", "--password-stdin", REGISTRY], input=password,
        text=True, check=True, env=docker_env, timeout=60)
    del auth, password
    try:
        command = ["docker", "buildx", "build", "--platform", "linux/amd64", "--provenance=false", "--sbom=false", "--load", "--pull",
            "--label", "org.opencontainers.image.revision=" + revision, "--tag", image, "--file", str(context / "frontend/Dockerfile")]
        for key, value in public.items():
            command.extend(["--build-arg", key + "=" + value])
        command.append(str(context / "frontend"))
        subprocess.check_call(command, env=docker_env)
        (directory / "built-image.json").write_text(json.dumps({"imageTag": image, "revision": revision, "publicConfig": public}, indent=2))
        print("Built image: " + image, flush=True)
        try:
            subprocess.check_call(["docker", "push", image], env=docker_env, timeout=600)
        except subprocess.TimeoutExpired:
            raise RuntimeError("Push exceeded ten minutes; image retained locally: " + image + ". Service is unchanged.") from None
    finally:
        subprocess.run(["docker", "logout", REGISTRY], env=docker_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    ecr = session.client("ecr")
    tag = image.rsplit(":", 1)[-1]
    digest = ecr.describe_images(repositoryName=REPOSITORY, imageIds=[{"imageTag": tag}])["imageDetails"][0]["imageDigest"]
    require(bool(re.fullmatch(r"sha256:[a-f0-9]{64}", digest)), "Published image digest is invalid")
    return IMAGE_PREFIX + "@" + digest, runtime_digests(ecr, digest)


def validate_candidate(original, candidate, image):
    expected = candidate_request(original, image)
    require(normalize(candidate) == normalize(expected), "Candidate task changes more than frontend image/migration flag; stopped")


def execute(session, path):
    plan = json.loads(path.read_text())
    require(plan.get("format") == 1 and plan.get("account") == ACCOUNT and plan.get("region") == REGION, "Invalid PROD frontend plan")
    require(session.client("sts").get_caller_identity()["Account"] == ACCOUNT, "Unexpected AWS account")
    backend_readiness(session)
    ecs = session.client("ecs")
    service = read_service(ecs)
    require(stable(service) and service["taskDefinition"] == plan["previousTask"] and service["desiredCount"] == plan["desiredCount"],
            "Frontend baseline changed after preparation; no service update performed")
    require(plan["nextTask"].startswith(f"arn:aws:ecs:{REGION}:{ACCOUNT}:task-definition/{FAMILY}:"), "Unexpected candidate task family/account")
    accepted = ecs.meta.service_model.operation_model("RegisterTaskDefinition").input_shape.members
    original = ecs.describe_task_definition(taskDefinition=plan["previousTask"], include=["TAGS"])
    candidate = ecs.describe_task_definition(taskDefinition=plan["nextTask"], include=["TAGS"])
    before = task_request(original["taskDefinition"], original.get("tags", []), accepted)
    after = task_request(candidate["taskDefinition"], candidate.get("tags", []), accepted)
    require(hashlib.sha256(canonical(before)).hexdigest() == plan["baselineSha256"], "Original task configuration does not match the release record")
    validate_candidate(before, after, plan["image"])
    digests = runtime_digests(session.client("ecr"), plan["image"].split("@", 1)[1])
    require(digests == plan["runtimeDigests"], "Published frontend manifest changed")
    ecs.update_service(cluster=CLUSTER, service=SERVICE, taskDefinition=plan["nextTask"])
    print("Updating only Navigan frontend service; rollback task: " + plan["previousTask"], flush=True)
    ecs.get_waiter("services_stable").wait(cluster=CLUSTER, services=[SERVICE], WaiterConfig={"Delay": 15, "MaxAttempts": 80})
    current = read_service(ecs)
    require(stable(current) and current["taskDefinition"] == plan["nextTask"], "Service did not retain the requested revision; inspect rollout/rollback events")
    arns = ecs.list_tasks(cluster=CLUSTER, serviceName=SERVICE, desiredStatus="RUNNING")["taskArns"]
    require(bool(arns), "Frontend has no running tasks")
    tasks = ecs.describe_tasks(cluster=CLUSTER, tasks=arns)
    require(not tasks.get("failures") and len(tasks.get("tasks", [])) == current["desiredCount"], "Running task verification failed")
    for task in tasks["tasks"]:
        require(task["taskDefinitionArn"] == plan["nextTask"], "An old frontend task is still running")
        actual = next((c for c in task["containers"] if c["name"] == CONTAINER), {})
        require(actual.get("imageDigest") in digests, "Running frontend image digest does not match the release")
    for endpoint in ("/healthz", "/login"):
        with urllib.request.urlopen(APP_URL + endpoint, timeout=30) as response:
            require(response.status == 200, "Frontend public smoke check failed: " + endpoint)
    print("PROD frontend deployed: " + plan["nextTask"])
    print("Running image verified: " + plan["image"])
    print("Health/login HTTP checks passed. Fresh authenticated UI/workflow checks are still required.")


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
    revision = check_checkout()
    service, described, original, public = readiness(session)
    print("PROD backend/collectors, current frontend and public Cognito configuration verified")
    print("Current frontend / rollback task: " + service["taskDefinition"])
    if not args.prepare:
        print("Read-only check passed. Use --prepare to build/push and register a candidate; the service will remain unchanged.")
        return 0
    directory = Path(tempfile.mkdtemp(prefix="navigan-prod-frontend-"))
    directory.chmod(0o700)
    print("Private frontend release record: " + str(directory), flush=True)
    (directory / "original-task.json").write_text(json.dumps(described, indent=2))
    (directory / "public-build-config.json").write_text(json.dumps(public, indent=2))
    image, digests = build_image(session, directory, revision, public)
    candidate = candidate_request(original, image)
    (directory / "candidate-task-request.json").write_text(json.dumps(candidate, indent=2))
    ecs = session.client("ecs")
    now = read_service(ecs)
    require(stable(now) and now["taskDefinition"] == service["taskDefinition"] and now["desiredCount"] == service["desiredCount"], "Frontend changed while the image was building")
    registered = ecs.register_task_definition(**candidate)["taskDefinition"]["taskDefinitionArn"]
    plan = {"format": 1, "account": ACCOUNT, "region": REGION, "revision": revision,
        "previousTask": service["taskDefinition"], "nextTask": registered, "desiredCount": service["desiredCount"],
        "baselineSha256": hashlib.sha256(canonical(original)).hexdigest(), "image": image, "runtimeDigests": digests}
    path = directory / "release-plan.json"
    path.write_text(json.dumps(plan, indent=2))
    print("Candidate registered: " + registered)
    print("Immutable image: " + image)
    print("Frontend service unchanged. Release plan: " + str(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
