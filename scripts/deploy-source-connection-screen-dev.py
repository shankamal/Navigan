#!/usr/bin/env python3
"""Deploy DEV migration discovery APIs, dependencies and optional existing-connector upgrade."""

import argparse
import io
import json
from pathlib import Path
import subprocess
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = "905418045935"
STACK = "navigan-ashok-dev"
FILES = [
    "models.py",
    "service.py",
    "repository.py",
    "handler.py",
    "connector_handler.py",
    "assessment_engine.py",
    "deployment_sources.py",
    "source_authentication.py",
    "source_connector_installation.py",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="navigan")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--upgrade-source-connector",
        action="store_true",
        help="Also update the existing DB Schenker DEV connector through SSM; no interactive session or re-enrollment.",
    )
    parser.add_argument(
        "--finish-deployment",
        action="store_true",
        help="Resume routes, permissions, environment and optional connector upgrade after both Lambda code uploads succeeded.",
    )
    args = parser.parse_args()

    def aws(*parts):
        output = subprocess.check_output(
            ["aws", "--profile", args.profile, "--region", "ap-south-1", "--output", "json", *parts],
            text=True,
        )
        # Successful write-only operations (for example IAM put-role-policy) emit no JSON.
        return json.loads(output) if output.strip() else {}

    aws.profile = args.profile
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != "new_migration_approach_18oct26":
        raise SystemExit("Run this only on new_migration_approach_18oct26.")
    if aws("sts", "get-caller-identity")["Account"] != ACCOUNT:
        raise SystemExit("Unexpected AWS account.")
    stack = aws("cloudformation", "describe-stacks", "--stack-name", STACK)["Stacks"][0]
    child = next(
        item["OutputValue"] for item in stack["Outputs"] if item["OutputKey"] == "MigrationManagementStackId"
    )
    if not child.startswith(f"arn:aws:cloudformation:ap-south-1:{ACCOUNT}:stack/"):
        raise SystemExit("Unexpected migration nested stack.")
    backup = Path(tempfile.mkdtemp(prefix="navigan-source-connection-dev-"))
    backup.chmod(0o700)
    if args.finish_deployment:
        function_name = aws(
            "cloudformation",
            "describe-stack-resource",
            "--stack-name",
            child,
            "--logical-resource-id",
            "MigrationFunction",
        )["StackResourceDetail"]["PhysicalResourceId"]
        config = aws("lambda", "get-function-configuration", "--function-name", function_name)
        if (
            config.get("State") != "Active"
            or config.get("LastUpdateStatus") != "Successful"
            or not config.get("FunctionArn", "").startswith(f"arn:aws:lambda:ap-south-1:{ACCOUNT}:function:")
        ):
            raise SystemExit("DEV MigrationFunction is not stable; finish deployment stopped.")
        if not args.apply:
            print(
                "Ready to finish DEV discovery configuration without re-uploading Lambda packages. Use --apply."
            )
            return
        finish_deployment(aws, stack, child, function_name, backup, args)
        return
    staged = []
    for logical in ["MigrationFunction", "MigrationConnectorFunction"]:
        function_name = aws(
            "cloudformation",
            "describe-stack-resource",
            "--stack-name",
            child,
            "--logical-resource-id",
            logical,
        )["StackResourceDetail"]["PhysicalResourceId"]
        deployed = aws("lambda", "get-function", "--function-name", function_name)
        config = deployed["Configuration"]
        if (
            config.get("PackageType", "Zip") != "Zip"
            or config["State"] != "Active"
            or config.get("LastUpdateStatus") != "Successful"
        ):
            raise SystemExit("Migration Lambda is not a stable zip deployment.")
        if not config["FunctionArn"].startswith(f"arn:aws:lambda:ap-south-1:{ACCOUNT}:function:"):
            raise SystemExit("Unexpected Lambda ARN.")
        original = urllib.request.urlopen(deployed["Code"]["Location"], timeout=60).read()
        (backup / f"{logical}-original.zip").write_bytes(original)
        (backup / f"{logical}-configuration.json").write_text(json.dumps(config, indent=2))
        artifact = backup / f"{logical}-updated.zip"
        prefix = "navigan/modules/migration_management/"
        replacements = {prefix + file: (ROOT / "src" / prefix / file).read_bytes() for file in FILES}
        if logical == "MigrationFunction":
            app = "navigan/modules/cluster_management/github_app.py"
            replacements[app] = (ROOT / "src" / app).read_bytes()
        # Bundle pinned PyYAML for static manifest inspection. Lambda is Linux x86_64 / CPython 3.12.
        if logical == "MigrationFunction":
            wheels = backup / "wheels"
            wheels.mkdir(exist_ok=True)
            subprocess.check_call(
                [
                    "python3",
                    "-m",
                    "pip",
                    "download",
                    "--no-deps",
                    "--only-binary=:all:",
                    "--platform",
                    "manylinux2014_x86_64",
                    "--python-version",
                    "312",
                    "--implementation",
                    "cp",
                    "--abi",
                    "cp312",
                    "--dest",
                    str(wheels),
                    "PyYAML==6.0.2",
                ]
            )
            with zipfile.ZipFile(
                next(p for p in wheels.glob("*.whl") if p.name.lower().startswith("pyyaml-"))
            ) as wheel:
                replacements.update(
                    {
                        name: wheel.read(name)
                        for name in wheel.namelist()
                        if name.startswith(("yaml/", "_yaml/")) and not name.endswith("/")
                    }
                )
        with (
            zipfile.ZipFile(io.BytesIO(original)) as old,
            zipfile.ZipFile(artifact, "w", zipfile.ZIP_DEFLATED) as new,
        ):
            missing = {prefix + name for name in FILES if name not in {"deployment_sources.py", "source_authentication.py"}} - set(
                old.namelist()
            )
            if missing:
                raise SystemExit(f"Unexpected deployed package structure: {sorted(missing)}")
            for entry in old.infolist():
                if entry.filename.endswith(".pyc") and "/migration_management/" in entry.filename:
                    continue
                new.writestr(entry, replacements.get(entry.filename, old.read(entry.filename)))
            for package_path in set(replacements) - set(old.namelist()):
                new.writestr(package_path, replacements[package_path])
        if artifact.stat().st_size > 50 * 1024 * 1024:
            raise SystemExit("Package exceeds direct Lambda upload limit.")
        if config["FunctionName"] != function_name:
            raise SystemExit("Deployed Lambda identity does not match the stack resource.")
        staged.append((logical, function_name, config, artifact))
    print(f"Prepared two DEV migration packages. Backup: {backup}")
    if not args.apply:
        print(
            "Review complete. Use --apply to update only these Lambda functions and enable the DEV source-first flag."
        )
        return
    # The connector is updated first so manual drafts cannot be claimed by an old worker.
    for logical, name, config, artifact in reversed(staged):
        aws(
            "lambda",
            "update-function-code",
            "--function-name",
            name,
            "--revision-id",
            config["RevisionId"],
            "--zip-file",
            f"fileb://{artifact}",
        )
        subprocess.check_call(
            [
                "aws",
                "--profile",
                args.profile,
                "--region",
                "ap-south-1",
                "lambda",
                "wait",
                "function-updated",
                "--function-name",
                name,
            ]
        )
        print(f"Updated {logical}.")
    _, name, _, _ = staged[0]
    current = aws("lambda", "get-function-configuration", "--function-name", name)
    variables = dict(current.get("Environment", {}).get("Variables", {}))
    variables["MIGRATION_SOURCE_FIRST_ENABLED"] = "true"
    env = backup / "migration-environment.json"
    env.write_text(json.dumps({"Variables": variables}))
    aws(
        "lambda",
        "update-function-configuration",
        "--function-name",
        name,
        "--revision-id",
        current["RevisionId"],
        "--environment",
        f"file://{env}",
    )
    subprocess.check_call(
        [
            "aws",
            "--profile",
            args.profile,
            "--region",
            "ap-south-1",
            "lambda",
            "wait",
            "function-updated",
            "--function-name",
            name,
        ]
    )
    verified = aws("lambda", "get-function-configuration", "--function-name", name)
    if verified.get("Environment", {}).get("Variables", {}).get("MIGRATION_SOURCE_FIRST_ENABLED") != "true":
        raise SystemExit("DEV flag verification failed.")
    finish_deployment(aws, stack, child, staged[0][1], backup, args)


def finish_deployment(aws, stack, child, function_name, backup, args):
    configure_deployment_discovery(aws, stack, child, function_name, backup)
    if args.upgrade_source_connector:
        subprocess.check_call(
            [
                "python3",
                str(ROOT / "scripts/upgrade-source-connector-dev.py"),
                "--profile",
                args.profile,
                "--apply",
            ]
        )
    print(
        "DEV migration deployment discovery enabled. Four JWT routes and scoped read permissions configured; database schema unchanged."
    )


def configure_deployment_discovery(aws, stack, child, function_name, backup):
    """Add only migration discovery routes and metadata read permissions in this DEV stack."""
    resources = aws("cloudformation", "list-stack-resources", "--stack-name", child)["StackResourceSummaries"]
    integration = next(
        r["PhysicalResourceId"] for r in resources if r["LogicalResourceId"] == "MigrationIntegration"
    )
    # API ID is pinned by the already configured migration connector base URL.
    config = aws("lambda", "get-function-configuration", "--function-name", function_name)
    variables = dict(config.get("Environment", {}).get("Variables", {}))
    import re

    match = re.fullmatch(
        r"https://([a-z0-9]+)\.execute-api\.ap-south-1\.amazonaws\.com/v1/api/v1",
        variables.get("MIGRATION_CONNECTOR_API_BASE_URL", ""),
    )
    if not match:
        raise SystemExit("Unexpected DEV migration API URL.")
    api = match[1]
    routes = aws("apigatewayv2", "get-routes", "--api-id", api)["Items"]
    reference = next(r for r in routes if r["RouteKey"] == "GET /api/v1/migrations/{migrationId}")
    if reference.get("AuthorizationType") != "JWT" or not reference.get("AuthorizerId"):
        raise SystemExit("Existing migration route is not JWT protected.")
    for route in [
        "GET /api/v1/source-clusters/{sourceClusterId}/deployment-sources",
        "PUT /api/v1/source-clusters/{sourceClusterId}/deployment-sources",
        "GET /api/v1/migrations/{migrationId}/deployment-evidence",
        "POST /api/v1/migrations/{migrationId}/deployment-evidence",
    ]:
        present = next((r for r in routes if r["RouteKey"] == route), None)
        desired = {
            "Target": "integrations/" + integration,
            "AuthorizationType": "JWT",
            "AuthorizerId": reference["AuthorizerId"],
            "AuthorizationScopes": reference.get("AuthorizationScopes", []),
        }
        if present:
            if any(present.get(k, []) != v for k, v in desired.items()):
                raise SystemExit(
                    "Existing deployment discovery route has unexpected protection or integration."
                )
            continue
        request = {"ApiId": api, "RouteKey": route, **desired}
        path = backup / ("route-" + str(len(list(backup.glob("route-*")))) + ".json")
        path.write_text(json.dumps(request))
        aws("apigatewayv2", "create-route", "--cli-input-json", "file://" + str(path))
    stage = aws("apigatewayv2", "get-stage", "--api-id", api, "--stage-name", "v1")
    if not stage.get("AutoDeploy"):
        aws(
            "apigatewayv2",
            "create-deployment",
            "--api-id",
            api,
            "--stage-name",
            "v1",
            "--description",
            "DEV migration deployment discovery routes",
        )
    variables["SOURCE_REGISTRY_PRINCIPAL_ARN"] = config["Role"]
    statements = [
        {"Effect": "Allow", "Action": ["sts:AssumeRole"], "Resource": "arn:aws:iam::*:role/navigan-source-discovery/*"},
        {"Effect": "Allow", "Action": ["secretsmanager:CreateSecret", "secretsmanager:PutSecretValue", "secretsmanager:GetSecretValue"],
         "Resource": f"arn:aws:secretsmanager:ap-south-1:{ACCOUNT}:secret:navigan/source-connections/*"},
    ]
    cluster_child = next(
        (o["OutputValue"] for o in stack["Outputs"] if o["OutputKey"] == "ClusterManagementStackId"), None
    )
    if cluster_child:
        cluster_name = aws(
            "cloudformation",
            "describe-stack-resource",
            "--stack-name",
            cluster_child,
            "--logical-resource-id",
            "ClusterFunction",
        )["StackResourceDetail"]["PhysicalResourceId"]
        cluster_env = (
            aws("lambda", "get-function-configuration", "--function-name", cluster_name)
            .get("Environment", {})
            .get("Variables", {})
        )
        for key in ["GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY_SECRET_ARN"]:
            if cluster_env.get(key):
                variables[key] = cluster_env[key]
        secret = variables.get("GITHUB_APP_PRIVATE_KEY_SECRET_ARN")
        if secret:
            if not secret.startswith(f"arn:aws:secretsmanager:ap-south-1:{ACCOUNT}:secret:"):
                raise SystemExit("Unexpected GitHub App secret location.")
            statements.append(
                {"Effect": "Allow", "Action": ["secretsmanager:GetSecretValue"], "Resource": secret}
            )
            key_id = aws("secretsmanager", "describe-secret", "--secret-id", secret).get("KmsKeyId")
            if key_id:
                key_arn = aws("kms", "describe-key", "--key-id", key_id)["KeyMetadata"]["Arn"]
                statements.append({"Effect": "Allow", "Action": ["kms:Decrypt"], "Resource": key_arn})
    policy = backup / "deployment-discovery-read-policy.json"
    policy.write_text(json.dumps({"Version": "2012-10-17", "Statement": statements}))
    aws(
        "iam",
        "put-role-policy",
        "--role-name",
        config["Role"].rsplit("/", 1)[-1],
        "--policy-name",
        "NaviganDeploymentDiscoveryReadOnly",
        "--policy-document",
        "file://" + str(policy),
    )
    env = backup / "deployment-discovery-environment.json"
    env.write_text(json.dumps({"Variables": variables}))
    current = aws("lambda", "get-function-configuration", "--function-name", function_name)
    aws(
        "lambda",
        "update-function-configuration",
        "--function-name",
        function_name,
        "--revision-id",
        current["RevisionId"],
        "--environment",
        "file://" + str(env),
    )
    subprocess.check_call(
        [
            "aws",
            "--profile",
            getattr(aws, "profile", "navigan"),
            "--region",
            "ap-south-1",
            "lambda",
            "wait",
            "function-updated",
            "--function-name",
            function_name,
        ]
    )


if __name__ == "__main__":
    main()
