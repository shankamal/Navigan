#!/usr/bin/env python3
"""Build selected committed inputs once and publish an immutable release manifest.

No application deployment or live SQL. Can reuse existing private artifact storage.
An initial release requires an explicit component list; subsequent releases use
the previous complete build manifest, never the previous Git push.
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
import tarfile
import time
import urllib.error
import urllib.request
import uuid

import boto3

import release_common as common
import release_database as database

require, sha, canonical = common.require, common.sha, common.canonical
IMAGES = {
    "frontend": ("frontend/Dockerfile", "frontend"),
    "image-worker": ("workspace_image_worker/Dockerfile", "."),
    "cluster-connector": ("connector/Dockerfile", "connector"),
    "migration-connector": ("migration_connector/Dockerfile", "."),
    "terraform-runner": ("provisioning/runner/Dockerfile", "."),
    "tools-gateway": ("tools-gateway/Dockerfile", "tools-gateway"),
}


def export_source(revision, destination):
    destination.mkdir()
    archive = destination.parent / "committed-source.tar"
    subprocess.check_call(["git", "archive", "--format=tar", "--output", str(archive), revision], cwd=common.ROOT)
    with tarfile.open(archive) as stream:
        stream.extractall(destination, filter="data")


def lambda_contract(source):
    contracts = set()
    for path in (source / "infrastructure/modules").glob("*/template.yaml"):
        template = common.yaml_document(path.read_text())
        defaults = template.get("Globals", {}).get("Function", {})
        for item in template.get("Resources", {}).values():
            if item.get("Type") != "AWS::Serverless::Function":
                continue
            props = {**defaults, **item["Properties"]}
            location = props.get("CodeUri")
            require(isinstance(location, str) and (path.parent / location).resolve() == source / "src",
                    "A Lambda has a separate build context; add a versioned build recipe before release.")
            contracts.add((props["Runtime"], tuple(props.get("Architectures", ["x86_64"]))))
    require(len(contracts) == 1, "Multiple Lambda build contracts require separate package recipes.")
    runtime, architectures = contracts.pop()
    require(runtime == "python3.12" and architectures == ("x86_64",), "Unsupported Lambda build contract.")
    return runtime, list(architectures)


def build_backend(source, directory):
    runtime, architectures = lambda_contract(source)
    template = {"Transform": "AWS::Serverless-2016-10-31", "Resources": {"BackendPackage": {
        "Type": "AWS::Serverless::Function", "Properties": {"CodeUri": str(source / "src"),
        "Runtime": runtime, "Architectures": architectures, "Handler": "navigan.modules.customer_management.handler.lambda_handler"}}}}
    path = directory / "backend-build.json"
    common.write(path, template)
    build = directory / "sam-build"
    common.run(["sam", "build", "--template-file", str(path), "--build-dir", str(build), "--use-container"],
               source, directory / "backend-build.log")
    files = {p.relative_to(build / "BackendPackage").as_posix(): p.read_bytes()
             for p in (build / "BackendPackage").rglob("*") if p.is_file() and not p.name.endswith(".pyc")}
    require("navigan/modules/customer_management/handler.py" in files, "SAM did not produce the expected Lambda package.")
    require(sum(map(len, files.values())) <= 250 * 1024 * 1024, "Lambda package exceeds the uncompressed limit.")
    return common.deterministic_zip(files), {"runtime": runtime, "architectures": architectures}


def template_files(source):
    root = source / "infrastructure/template.yaml"
    result = {}

    def visit(path):
        path = path.resolve()
        require(path.is_relative_to(source.resolve()) and path.is_file(), "Nested template is outside committed source.")
        relative = path.relative_to(source).as_posix()
        if relative in result:
            return
        value = common.yaml_document(path.read_text())
        result[relative] = value
        for resource in value.get("Resources", {}).values():
            props = resource.get("Properties", {})
            key = {"AWS::Serverless::Application": "Location", "AWS::CloudFormation::Stack": "TemplateURL"}.get(resource.get("Type"))
            if key:
                require(isinstance(props.get(key), str) and not re.match(r"[a-z]+://", props[key]),
                        "Authored nested templates must be local committed files.")
                visit(path.parent / props[key])
    visit(root)
    return result


def publish_templates(source, backend, s3, bucket, account, region, prefix):
    require(backend, "An initial SAM release requires a built backend artifact; later infrastructure-only releases reuse it.")
    templates = template_files(source)
    refs, rendered = {}, {}
    code_bucket, code_key = common.s3_location(backend)

    def publish(relative):
        if relative in refs:
            return refs[relative]
        value = copy.deepcopy(templates[relative])
        path = source / relative
        defaults = value.get("Globals", {}).get("Function", {})
        for resource in value.get("Resources", {}).values():
            kind, props = resource.get("Type"), resource.get("Properties", {})
            if kind == "AWS::Serverless::Function":
                location = props.get("CodeUri", defaults.get("CodeUri"))
                require(isinstance(location, str) and (path.parent / location).resolve() == source / "src",
                        "Lambda source does not match the published backend package.")
                props["CodeUri"] = {"Bucket": code_bucket, "Key": code_key, "Version": backend["versionId"]}
            key = {"AWS::Serverless::Application": "Location", "AWS::CloudFormation::Stack": "TemplateURL"}.get(kind)
            if key:
                child = (path.parent / props[key]).resolve().relative_to(source).as_posix()
                props[key] = common.template_url(publish(child), region)
        if "CodeUri" in defaults:
            value["Globals"]["Function"].pop("CodeUri")
        content = canonical(value)
        item = common.put_content(s3, bucket, "objects/templates/" + sha(content) + ".json", content, account)
        refs[relative], rendered[relative] = item, content
        return item

    root = publish("infrastructure/template.yaml")
    files = {path + ".json": data for path, data in rendered.items()}
    files["template-index.json"] = canonical({"format": 1, "root": root, "templates": refs})
    return common.deterministic_zip(files), {"rootTemplate": root, "templateCount": len(refs)}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def http(url, *, token=None):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    with urllib.request.build_opener(NoRedirect()).open(urllib.request.Request(url, headers=headers), timeout=15) as response:
        require(response.status == 200, "HTTP verification failed.")
        return response.read(2 * 1024 * 1024)


def docker_auth(session, directory, account, region):
    env = {**os.environ, "DOCKER_CONFIG": str(directory / "docker-auth")}
    auth = session.client("ecr").get_authorization_token(registryIds=[account])["authorizationData"][0]
    host = f"{account}.dkr.ecr.{region}.amazonaws.com"
    require(auth["proxyEndpoint"] == "https://" + host, "Unexpected ECR registry.")
    username, password = base64.b64decode(auth["authorizationToken"]).decode().split(":", 1)
    require(username == "AWS", "Unexpected registry authentication.")
    try:
        common.run(["docker", "login", "--username", "AWS", "--password-stdin", host], directory,
                   directory / "registry.log", env=env, data=password.encode())
    except Exception:
        subprocess.run(["docker", "logout", host], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        raise
    return env


def image_runtime_check(image, directory, env):
    """Start the exact same local image twice with different public runtime values."""
    identity = subprocess.check_output(["docker", "image", "inspect", image, "--format", "{{.Id}}"], env=env).decode().strip()
    for label in ("dev", "prod"):
        name = "navigan-portability-" + uuid.uuid4().hex[:12]
        command = ["docker", "run", "--detach", "--name", name, "--publish", "127.0.0.1::3000",
                   "--env", f"NAVIGAN_PUBLIC_OIDC_AUTHORITY=https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_{label}Fixture",
                   "--env", "NAVIGAN_PUBLIC_OIDC_CLIENT_ID=" + label + "fixtureclient",
                   "--env", "NAVIGAN_PUBLIC_APP_URL=https://" + label + ".example.invalid",
                   "--env", "NAVIGAN_API_ORIGIN=https://api-dev.example.invalid", "--env", "NAVIGAN_API_BASE_PATH=/api/v1", image]
        try:
            common.run(command, directory, directory / "portability.log", env=env)
            port = subprocess.check_output(["docker", "port", name, "3000/tcp"], env=env).decode().strip()
            require(re.fullmatch(r"127\.0\.0\.1:[0-9]+", port), "Unexpected portability-test port.")
            deadline = time.monotonic() + 120
            while True:
                try:
                    config = json.loads(http("http://" + port + "/api/runtime-config"))
                    break
                except (OSError, ValueError, urllib.error.URLError):
                    require(time.monotonic() < deadline, "Runtime configuration test did not become healthy.")
                    time.sleep(2)
            require(config["oidcClientId"] == label + "fixtureclient"
                    and config["appUrl"] == "https://" + label + ".example.invalid", "Image retained baked environment values.")
            http("http://" + port + "/healthz")
            http("http://" + port + "/login")
            actual = subprocess.check_output(["docker", "inspect", name, "--format", "{{.Image}}"], env=env).decode().strip()
            require(actual == identity, "Portability test used a different image.")
        finally:
            subprocess.run(["docker", "rm", "--force", name], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"contract": common.CONTRACT, "passed": True, "imageId": identity,
            "configurations": ["dev-fixture", "prod-fixture"]}


def repository_uri(component, repositories, account, region):
    prefix = f"{account}.dkr.ecr.{region}.amazonaws.com/"
    if repositories is None:
        return prefix + common.REGISTRY_PREFIX + "/" + component
    value = repositories.get(component, "")
    require(value.startswith(prefix) and re.fullmatch(r"[a-z0-9]+(?:[._/-][a-z0-9]+)*", value[len(prefix):]),
            "Configure the existing ECR repository for selected component: " + component)
    return value


def build_image(component, source, directory, session, account, region, recipe, repositories=None):
    expected = repository_uri(component, repositories, account, region)
    repository = expected.split("/", 1)[1]
    ecr = session.client("ecr")
    metadata = ecr.describe_repositories(repositoryNames=[repository])["repositories"][0]
    # Use an existing repository, leave its settings unchanged and deploy by digest.
    require(metadata["repositoryUri"] == expected, "Unexpected component repository.")
    image = expected + ":build-" + recipe[:20] + "-" + uuid.uuid4().hex[:8]
    dockerfile, context = IMAGES[component]
    common.run(["docker", "buildx", "build", "--platform", "linux/amd64", "--load", "--provenance=false", "--sbom=false",
                "--tag", image, "--file", str(source / dockerfile), str(source / context)], source, directory / (component + "-build.log"))
    env = docker_auth(session, directory, account, region)
    proof = None
    try:
        if component == "frontend":
            proof = image_runtime_check(image, directory, env)
        common.run(["docker", "push", image], source, directory / (component + "-push.log"), env=env)
    finally:
        subprocess.run(["docker", "logout", expected.split("/", 1)[0]], env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    digest = ecr.describe_images(repositoryName=repository, imageIds=[{"imageTag": image.rsplit(":", 1)[1]}])["imageDetails"][0]["imageDigest"]
    require(re.fullmatch(r"sha256:[a-f0-9]{64}", digest), "Registry did not return an immutable digest.")
    result = {"uri": expected + "@" + digest, "sha256": digest.split(":", 1)[1]}
    if proof:
        result["runtimeConfigProof"] = proof
    return result


def verify_artifact(session, component, item, account, region):
    if component in common.planner.IMAGES:
        common.verify_image(session, component, item, account, region)
    else:
        common.object_bytes(session.client("s3"), item, account)


def build_manifest(session, source, revision, selected, previous, bucket, account, region, directory, validate, repositories=None):
    components = copy.deepcopy((previous or {}).get("components", {}))
    for name in (set(selected) | set(components)) & common.planner.IMAGES:
        expected = repository_uri(name, repositories, account, region)
        if name in components and name not in selected:
            require(components[name]["uri"] == expected + "@sha256:" + components[name]["sha256"],
                    "Retained image repository differs from the configured repository.")
    s3 = session.client("s3")
    recipe_hash = sha(b"".join((common.ROOT / "scripts" / name).read_bytes()
                              for name in ("build-release.py", "release_common.py", "release_database.py", "plan-release.py")))
    results = []
    # Backend binding updates require packaging new template references, not another Lambda build.
    if "backend" in selected:
        selected = set(selected) | {"infrastructure"}
    for component in common.planner.COMPONENTS:
        if component not in selected:
            if component in components:
                verify_artifact(session, component, components[component], account, region)
            continue
        inputs = common.planner.input_hash(component, revision)
        dependencies = {"backend": {key: components.get("backend", {}).get(key) for key in ("sha256", "uri", "versionId")}} if component == "infrastructure" else {}
        output_repository = repository_uri(component, repositories, account, region) if component in common.planner.IMAGES else None
        recipe = sha(canonical({"inputHash": inputs, "recipeHash": recipe_hash, "dependencies": dependencies, "repository": output_repository}))
        key = "registry/" + component + "/" + recipe + ".json"
        cached = common.get_optional(s3, bucket, key, account)
        if cached:
            item = cached[0]
            require(item.get("inputHash") == inputs and item.get("recipeHash") == recipe_hash
                    and item.get("dependencies", {}) == dependencies, "Cached build receipt differs.")
            common.planner.validate_manifest({"format": common.planner.FORMAT, "sourceRevision": revision, "components": {component: item}})
            verify_artifact(session, component, item, account, region)
            if output_repository:
                require(item["uri"] == output_repository + "@sha256:" + item["sha256"], "Cached image repository differs.")
            components[component] = item
            results.append({"component": component, "action": "reused-built-artifact"})
            continue
        # Independent per-input build lock: a concurrent run cannot build the same recipe twice.
        lock_key = "build-locks/" + component + "/" + recipe + ".json"
        lock = common.put_bytes(s3, bucket, lock_key, canonical({"recipe": recipe}), account, IfNoneMatch="*")
        try:
            validate(component, source, directory)
            extra = {}
            prefix = "artifacts/" + component + "/" + recipe
            if component == "backend":
                content, extra = build_backend(source, directory)
            elif component == "database":
                content = database.bundle(source)
            elif component == "infrastructure":
                content, extra = publish_templates(source, components.get("backend"), s3, bucket, account, region, prefix)
            else:
                item = build_image(component, source, directory, session, account, region, recipe, repositories)
            if component not in common.planner.IMAGES:
                item = {**common.put_content(s3, bucket, "objects/" + component + "/" + sha(content) + ".zip", content, account), **extra}
            item.update(inputHash=inputs, recipeHash=recipe_hash, dependencies=dependencies, portable=True,
                        builtFromRevision=revision, buildContract=common.CONTRACT)
            verify_artifact(session, component, item, account, region)
            common.put_bytes(s3, bucket, key, canonical(item), account, IfNoneMatch="*")
            components[component] = item
            results.append({"component": component, "action": "built-and-published"})
        finally:
            s3.delete_object(Bucket=bucket, Key=lock_key, VersionId=lock["versionId"], ExpectedBucketOwner=account)
    result = {"format": common.planner.FORMAT, "sourceRevision": revision, "components": components,
              "buildContract": common.CONTRACT, "builtAt": datetime.now(timezone.utc).isoformat()}
    common.planner.validate_manifest(result)
    return result, results


def validations(component, source, directory):
    # The new CI wrapper and this local path use the same committed validation commands.
    if component == "frontend":
        common.run(["docker", "run", "--rm", "--mount", "type=bind,src=" + str(source) + ",dst=/input,readonly",
                    "node:22-bookworm-slim", "/bin/sh", "-c",
                    "cp -a /input /tmp/source && cd /tmp/source/frontend && npm ci --no-audit --no-fund && npm run typecheck && npm test"],
                   source, directory / "frontend-checks.log")
    elif component in {"backend", "database", "release-tooling", "api-contract", "template-consistency", "gateway", "terraform", "cluster-connector", "migration-connector", "image-worker", "tools-gateway", "terraform-runner"}:
        common.run(["bash", str(source / "scripts/ci/verify-backend-container.sh")], source,
                   directory / (component + "-checks.log"))
    elif component == "infrastructure":
        for relative in template_files(source):
            common.run(["sam", "validate", "--lint", "--template-file", str(source / relative)],
                       source, directory / "template-checks.log")
    else:
        require(False, "Unknown selected validation family; refusing to skip it.")


def dependency_closure(selected, previous):
    selected = set(selected)
    retained = (previous or {}).get("components", {})
    if selected & {"backend", "infrastructure"}:
        selected.add("infrastructure")
        selected.update(name for name in ("backend", "database") if name not in retained)
    return selected


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile")
    parser.add_argument("--region", required=True)
    parser.add_argument("--expected-account", required=True)
    parser.add_argument("--artifact-bucket", required=True)
    parser.add_argument("--repositories-file", type=Path, help="Explicit component-to-existing-ECR-repository URI map")
    parser.add_argument("--revision", default="HEAD")
    parser.add_argument("--baseline-manifest", type=Path)
    parser.add_argument("--enroll", help="Explicit additional components absent from the baseline manifest")
    parser.add_argument("--initial", help="Explicit initial component list, for example frontend,backend,infrastructure,database")
    args = parser.parse_args(argv)
    repositories = common.read(args.repositories_file) if args.repositories_file else None
    require(repositories is None or isinstance(repositories, dict) and set(repositories) <= common.planner.IMAGES
            and all(isinstance(value, str) for value in repositories.values()), "Invalid existing repository configuration.")
    require(bool(args.initial) != bool(args.baseline_manifest), "Choose an explicit initial component list or a previous manifest.")
    revision = common.planner.revision(args.revision)
    previous = common.planner.manifest(args.baseline_manifest) if args.baseline_manifest else None
    if previous:
        plan = common.planner.build_plan(previous["sourceRevision"], revision, previous)
        require(plan["readyForBuild"], "Impact plan requires review before a build.")
        selected = set(plan["build"])
        if args.enroll:
            enrolled = set(args.enroll.split(","))
            require(enrolled <= set(common.planner.COMPONENTS) and not enrolled & set(previous["components"]),
                    "Enrollment accepts only previously unmanaged components.")
            selected.update(enrolled)
    else:
        require(not args.enroll, "Enrollment requires an existing manifest.")
        selected = set(args.initial.split(","))
        require(selected and selected <= set(common.planner.COMPONENTS), "Unknown initial component.")
        plan = {"initialComponents": sorted(selected), "readyForBuild": True}
    selected = dependency_closure(selected, previous)
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    common.verify_registry(session, args.artifact_bucket, args.expected_account, args.region)
    directory = common.workspace("navigan-release-build-")
    print("Private build record: " + str(directory), flush=True)
    common.write(directory / "impact-plan.json", plan)
    source = directory / "source"
    export_source(revision, source)
    validated = set()

    def validate(component, checkout, records):
        family = component if component in {"frontend", "infrastructure"} else "backend"
        if family not in validated:
            validations(component, checkout, records)
            validated.add(family)

    # Test-only and contract-only changes still run their checks without an artifact build.
    for family in plan.get("validation", []):
        validate(family, source, directory)
    result, stages = build_manifest(session, source, revision, selected, previous, args.artifact_bucket,
                                    args.expected_account, args.region, directory, validate, repositories)
    reference = common.put_bytes(session.client("s3"), args.artifact_bucket,
                                 "releases/" + revision + "/" + sha(canonical(result)) + ".json",
                                 canonical(result), args.expected_account, IfNoneMatch="*")
    common.write(directory / "release-manifest.json", result)
    common.write(directory / "manifest-reference.json", reference)
    print(json.dumps({"sourceRevision": revision, "stages": stages, "deploymentPerformed": False,
                      "manifest": str(directory / "release-manifest.json")}, indent=2))
    return directory


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        detail = str(error) if isinstance(error, common.ReleaseError) else type(error).__name__
        raise SystemExit("Release build stopped: " + detail + " Inspect the private stage record; no application deployment was requested.") from None
