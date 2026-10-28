#!/usr/bin/env python3
"""Persistent private-runner entry point; manual DEV pilot, never PROD."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import shutil

import boto3

import release_common as common
import release_dev_target as target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True, help="Private persistent runner directory containing dev-config.json")
    parser.add_argument("--profile")
    parser.add_argument("--action", required=True, choices=["build-prepare", "execute", "verify", "rollback"])
    parser.add_argument("--plan-id")
    parser.add_argument("--initial", default="frontend")
    parser.add_argument("--enroll")
    args = parser.parse_args(argv)
    home = args.home.resolve()
    common.require(home.is_dir() and not args.home.is_symlink() and home.stat().st_mode & 0o077 == 0,
                   "Runner home must be an existing private directory (mode 700).")
    cfg = common.read(home / "dev-config.json")
    target.validate_config(cfg)
    common.require(not args.plan_id or re.fullmatch(r"[a-f0-9]{32}", args.plan_id), "Invalid saved plan ID.")
    executor = common.load("dev_release_entry", common.ROOT / "scripts/deploy-release-dev.py")
    session = boto3.Session(profile_name=args.profile, region_name=cfg["region"])
    if args.action == "build-prepare":
        common.require(not args.plan_id, "A build cannot replace a saved deployment plan.")
        builder = common.load("dev_build_entry", common.ROOT / "scripts/build-release.py")
        arguments = ["--region", cfg["region"], "--expected-account", cfg["account"], "--artifact-bucket", cfg["artifactBucket"]]
        if args.profile:
            arguments += ["--profile", args.profile]
        baseline = home / "last-build-manifest.json"
        if baseline.exists():
            arguments += ["--baseline-manifest", str(baseline)]
            if args.enroll:
                arguments += ["--enroll", args.enroll]
        else:
            common.require(not args.enroll, "Use --initial for the first manifest.")
            arguments += ["--initial", args.initial]
        directory = builder.main(arguments)
        common.write(baseline, common.read(directory / "release-manifest.json"))
        prepared = executor.prepare(session, home / "dev-config.json", directory / "release-manifest.json")
        plan = common.read(prepared / "release-plan.json")
        destination = home / "plans" / plan["id"]
        shutil.copytree(prepared, destination)
        destination.chmod(0o700)
        print("Saved runner plan ID: " + plan["id"])
        print("Review summary.json before the separate execute action.")
        print("Private plan: " + str(destination / "release-plan.json"))
    else:
        common.require(args.plan_id, "Execution, verification and rollback require the saved plan ID.")
        path = home / "plans" / args.plan_id / "release-plan.json"
        common.require(path.is_file(), "Saved plan not found on this persistent runner.")
        getattr(executor, args.action)(session, path)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        message = str(error) if isinstance(error, common.ReleaseError) else type(error).__name__
        raise SystemExit("DEV runner stopped: " + message + ". Inspect its private record; PROD is unsupported.") from None
