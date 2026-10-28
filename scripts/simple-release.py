#!/usr/bin/env python3
"""Two commands: build selected artifacts, then deploy the same build to DEV."""
from __future__ import annotations

import argparse
from pathlib import Path
import re

import boto3

import release_common as common
import release_dev_target as target


def settings(path):
    common.require(path.is_file(), "One-time setup: copy scripts/release-config.example.json to .navigan-release/dev.json and set your existing account, artifact bucket and ECR repository names. No AWS resources were created.")
    cfg = common.read(path)
    allowed = {"profile", "region", "account", "artifactBucket", "repositories", "initialComponents"}
    common.require(isinstance(cfg, dict) and set(cfg) <= allowed, "Unexpected release setting; keep tokens and database credentials out of this file.")
    common.require(re.fullmatch(r"[0-9]{12}", cfg.get("account", "")) and cfg.get("region") == "ap-south-1",
                   "Configure the existing AWS account and Mumbai region.")
    common.require(re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", cfg.get("artifactBucket", "")),
                   "Configure the existing artifact bucket name, without s3://.")
    repositories = cfg.get("repositories")
    common.require(isinstance(repositories, dict) and set(repositories) <= common.planner.IMAGES,
                   "Configure existing repositories by component.")
    builder = common.load("simple_release_settings", common.ROOT / "scripts/build-release.py")
    for component in repositories:
        common.require(isinstance(repositories[component], str), "Invalid ECR repository setting.")
        builder.repository_uri(component, repositories, cfg["account"], cfg["region"])
    initial = cfg.get("initialComponents", ["frontend"])
    common.require(isinstance(initial, list) and initial and set(initial) <= set(common.planner.COMPONENTS),
                   "Invalid initial component list.")
    return cfg


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["build", "deploy"])
    parser.add_argument("--environment", choices=["dev"], default="dev")
    parser.add_argument("--config", type=Path, default=common.ROOT / ".navigan-release/dev.json")
    parser.add_argument("--manifest", type=Path, help="Optional exact existing build manifest to deploy")
    parser.add_argument("--enroll", help="Build: add previously unmanaged components, comma-separated")
    recovery = parser.add_mutually_exclusive_group()
    recovery.add_argument("--verify", action="store_true")
    recovery.add_argument("--rollback", action="store_true")
    args = parser.parse_args(argv)
    common.require(args.action == "deploy" or not (args.manifest or args.verify or args.rollback), "Recovery and explicit artifact deployment belong to deploy.sh.")
    common.require(args.action == "build" or not args.enroll, "Enrollment belongs to build.sh.")
    cfg = settings(args.config)
    state_dir = args.config.resolve().parent / "state"
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    state_dir.chmod(0o700)
    profile = ["--profile", cfg["profile"]] if cfg.get("profile") else []
    baseline = state_dir / "last-build-manifest.json"
    if args.action == "build":
        builder = common.load("simple_release_builder", common.ROOT / "scripts/build-release.py")
        repositories = state_dir / "repositories.json"
        common.write(repositories, cfg["repositories"])
        command = [*profile, "--region", cfg["region"], "--expected-account", cfg["account"],
                   "--artifact-bucket", cfg["artifactBucket"], "--repositories-file", str(repositories)]
        if baseline.exists():
            command += ["--baseline-manifest", str(baseline)]
            if args.enroll:
                command += ["--enroll", args.enroll]
        else:
            common.require(not args.enroll, "Set initialComponents for the first build; use --enroll for later additions.")
            command += ["--initial", ",".join(cfg.get("initialComponents", ["frontend"]))]
        built = builder.main(command)
        common.write(baseline, common.read(built / "release-manifest.json"))
        print("Build complete. Saved manifest: " + str(baseline))
        print("Next: bash scripts/deploy.sh dev")
        return
    executor = common.load("simple_release_executor", common.ROOT / "scripts/deploy-release-dev.py")
    session = boto3.Session(profile_name=cfg.get("profile"), region_name=cfg["region"])
    pointer = state_dir / "last-deployment.json"
    if args.verify or args.rollback:
        common.require(pointer.exists() and not args.manifest, "Recovery requires the saved deployment; do not select another manifest.")
        path = Path(common.read(pointer)["plan"])
        getattr(executor, "rollback" if args.rollback else "verify")(session, path)
        return
    if pointer.exists():
        prior = Path(common.read(pointer)["plan"])
        journal = prior.parent / "execution.json"
        if journal.exists():
            status = common.read(journal)
            common.require(status.get("rollbackComplete") or (status.get("recordPublished") and status.get("lockReleased")
                           and not status.get("rollbackRequested")),
                           "Previous deployment is unfinished. Use deploy.sh dev --verify or --rollback; it will not be repeated.")
    manifest = args.manifest or baseline
    common.require(manifest.is_file(), "Run bash scripts/build.sh dev first, or provide --manifest with an existing build.")
    candidate = common.planner.manifest(manifest)
    common.verify_registry(session, cfg["artifactBucket"], cfg["account"], cfg["region"])
    live = target.snapshot(session, cfg["account"], cfg["region"])
    deployment = target.configuration(session, live, cfg["artifactBucket"], components=set(candidate["components"]))
    deployment["repositories"] = cfg["repositories"]
    config_path = state_dir / "dev-target.json"
    common.write(config_path, deployment)
    prepared = executor.prepare(session, config_path, manifest)
    path = prepared / "release-plan.json"
    common.write(pointer, {"plan": str(path)})
    executor.execute(session, path)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        detail = str(error) if isinstance(error, common.ReleaseError) else type(error).__name__
        raise SystemExit("Release stopped: " + detail) from None
