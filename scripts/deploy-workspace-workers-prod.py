#!/usr/bin/env python3
"""Deploy dedicated PROD collectors using the tested DEV deployment mechanism.

Default: read-only review. --repository --enable-schedule --apply starts the
repository poller. --image --apply builds a production image and stages its
private service at zero tasks. Start images only after verifying registry role
trust/networking. This script never updates the API or source connector.
"""
import importlib.util
from pathlib import Path
import subprocess

import boto3

ROOT = Path(__file__).resolve().parents[1]


def load_script(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


worker = load_script("prod_workspace_worker_release", "deploy-workspace-workers-dev.py")
storage = load_script("prod_workspace_storage_release", "deploy-migration-storage-prod.py")


def bind_production(settings, workspace):
    """Select PROD constants without changing DEV defaults or bypassing validation."""
    worker.STACK = storage.PARENT
    worker.DATABASE = "navigan"
    worker.LABEL = "PROD"
    worker.REPOSITORY = "navigan/prod-workspace-image-collector"
    worker.__doc__ = __doc__
    original = worker.runtime_settings

    def checked_runtime(config):
        storage.require(config.get("FunctionName") == settings["function"] and config.get("Role") == settings["roleArn"],
                        "Worker runtime must come from the verified production migration API")
        storage.require(config.get("RevisionId") == settings["revision"], "API changed during worker preparation")
        env = original(config)
        storage.require(config.get("Environment", {}).get("Variables", {}).get("MIGRATION_SOURCE_FIRST_ENABLED") == "true",
                        "Promote the production migration API first")
        storage.require(env["MIGRATION_WORKSPACE_BUCKET"] == workspace["WorkspaceBucketName"] and
                        env["MIGRATION_WORKSPACE_KMS_KEY"] == workspace["WorkspaceKmsKeyArn"], "Worker storage must match the verified PROD workspace")
        return env

    worker.runtime_settings = checked_runtime


def main():
    # Parse using the existing worker CLI so --help needs no AWS credentials.
    import sys
    if "--help" in sys.argv or "-h" in sys.argv:
        bind_production({}, {})
        worker.main()
        return
    import argparse
    profile_parser = argparse.ArgumentParser(add_help=False)
    profile_parser.add_argument("--profile", default="navigan")
    profile, _ = profile_parser.parse_known_args()
    storage.check_checkout()
    paths = ["src/navigan", "workspace_image_worker", "infrastructure/modules/migration-management/image-collector-service.yaml",
             "scripts/deploy-workspace-workers-dev.py", "scripts/deploy-workspace-workers-prod.py"]
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--", *paths], cwd=ROOT, text=True)
    storage.require(not dirty.strip(), "Review/commit local collector release edits first; unrelated files are preserved")
    session = boto3.Session(profile_name=profile.profile, region_name=storage.REGION)
    settings = storage.preflight(session)
    workspace = storage.verify_storage(session, "artifact-workspace")
    bind_production(settings, workspace)
    worker.main()


if __name__ == "__main__":
    main()
