#!/usr/bin/env python3
"""Patch only the two deployed DEV migration Lambda packages; preserve routes and dependencies."""
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
FILES = ["models.py", "service.py", "repository.py", "connector_handler.py", "assessment_engine.py"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="navigan")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    def aws(*parts):
        return json.loads(subprocess.check_output(["aws", "--profile", args.profile, "--region", "ap-south-1", "--output", "json", *parts], text=True))

    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != "new_migration_approach_18oct26":
        raise SystemExit("Run this only on new_migration_approach_18oct26.")
    if aws("sts", "get-caller-identity")["Account"] != ACCOUNT:
        raise SystemExit("Unexpected AWS account.")
    stack = aws("cloudformation", "describe-stacks", "--stack-name", STACK)["Stacks"][0]
    child = next(item["OutputValue"] for item in stack["Outputs"] if item["OutputKey"] == "MigrationManagementStackId")
    if not child.startswith(f"arn:aws:cloudformation:ap-south-1:{ACCOUNT}:stack/"):
        raise SystemExit("Unexpected migration nested stack.")
    backup = Path(tempfile.mkdtemp(prefix="navigan-source-connection-dev-"))
    backup.chmod(0o700)
    staged = []
    for logical in ["MigrationFunction", "MigrationConnectorFunction"]:
        name = aws("cloudformation", "describe-stack-resource", "--stack-name", child, "--logical-resource-id", logical)["StackResourceDetail"]["PhysicalResourceId"]
        deployed = aws("lambda", "get-function", "--function-name", name)
        config = deployed["Configuration"]
        if config.get("PackageType", "Zip") != "Zip" or config["State"] != "Active" or config.get("LastUpdateStatus") != "Successful":
            raise SystemExit("Migration Lambda is not a stable zip deployment.")
        if not config["FunctionArn"].startswith(f"arn:aws:lambda:ap-south-1:{ACCOUNT}:function:"):
            raise SystemExit("Unexpected Lambda ARN.")
        original = urllib.request.urlopen(deployed["Code"]["Location"], timeout=60).read()
        (backup / f"{logical}-original.zip").write_bytes(original)
        (backup / f"{logical}-configuration.json").write_text(json.dumps(config, indent=2))
        artifact = backup / f"{logical}-updated.zip"
        prefix = "navigan/modules/migration_management/"
        replacements = {prefix + file: (ROOT / "src" / prefix / file).read_bytes() for file in FILES}
        with zipfile.ZipFile(io.BytesIO(original)) as old, zipfile.ZipFile(artifact, "w", zipfile.ZIP_DEFLATED) as new:
            missing = set(replacements) - set(old.namelist())
            if missing:
                raise SystemExit(f"Unexpected deployed package structure: {sorted(missing)}")
            for entry in old.infolist():
                if entry.filename.endswith(".pyc") and "/migration_management/" in entry.filename:
                    continue
                new.writestr(entry, replacements.get(entry.filename, old.read(entry.filename)))
        if artifact.stat().st_size > 50 * 1024 * 1024:
            raise SystemExit("Package exceeds direct Lambda upload limit.")
        staged.append((logical, name, config, artifact))
    print(f"Prepared two DEV migration packages. Backup: {backup}")
    if not args.apply:
        print("Review complete. Use --apply to update only these Lambda functions and enable the DEV source-first flag.")
        return
    # The connector is updated first so manual drafts cannot be claimed by an old worker.
    for logical, name, config, artifact in reversed(staged):
        aws("lambda", "update-function-code", "--function-name", name, "--revision-id", config["RevisionId"], "--zip-file", f"fileb://{artifact}")
        subprocess.check_call(["aws", "--profile", args.profile, "--region", "ap-south-1", "lambda", "wait", "function-updated", "--function-name", name])
        print(f"Updated {logical}.")
    _, name, _, _ = staged[0]
    current = aws("lambda", "get-function-configuration", "--function-name", name)
    variables = dict(current.get("Environment", {}).get("Variables", {}))
    variables["MIGRATION_SOURCE_FIRST_ENABLED"] = "true"
    env = backup / "migration-environment.json"
    env.write_text(json.dumps({"Variables": variables}))
    aws("lambda", "update-function-configuration", "--function-name", name, "--revision-id", current["RevisionId"], "--environment", f"file://{env}")
    subprocess.check_call(["aws", "--profile", args.profile, "--region", "ap-south-1", "lambda", "wait", "function-updated", "--function-name", name])
    verified = aws("lambda", "get-function-configuration", "--function-name", name)
    if verified.get("Environment", {}).get("Variables", {}).get("MIGRATION_SOURCE_FIRST_ENABLED") != "true":
        raise SystemExit("DEV flag verification failed.")
    print("DEV source connection backend enabled. No API Gateway, IAM, database or other capability resources changed.")


if __name__ == "__main__":
    main()
