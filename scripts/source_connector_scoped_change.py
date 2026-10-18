#!/usr/bin/env python3
"""Prepare and validate a migration-only DEV CloudFormation parameter change."""

import argparse
import json
from pathlib import Path


IMAGE_PARAMETERS = {
    "MigrationConnectorImageRepository",
    "MigrationConnectorImageDigest",
}


def prepare_parameters(existing, repository, digest):
    names = [entry["ParameterKey"] for entry in existing]
    if len(names) != len(set(names)) or not IMAGE_PARAMETERS.issubset(set(names)):
        raise ValueError(
            "The deployed DEV template does not have both migration connector "
            "image parameters; refusing a previous-template update."
        )
    result = []
    for name in names:
        if name == "MigrationConnectorImageRepository":
            result.append({"ParameterKey": name, "ParameterValue": repository})
        elif name == "MigrationConnectorImageDigest":
            result.append({"ParameterKey": name, "ParameterValue": digest})
        else:
            result.append({"ParameterKey": name, "UsePreviousValue": True})
    return result


def ensure_migration_only(changeset):
    if changeset.get("Status") != "CREATE_COMPLETE":
        raise ValueError("The DEV change set is not ready for execution.")
    changes = [item.get("ResourceChange", {}) for item in changeset.get("Changes", [])]
    if len(changes) != 1:
        raise ValueError(
            "Expected exactly one MigrationManagement change; "
            "do not execute this DEV change set."
        )
    for change in changes:
        if (
            change.get("LogicalResourceId") != "MigrationManagement"
            or change.get("ResourceType") != "AWS::CloudFormation::Stack"
            or change.get("Action") != "Modify"
            or change.get("Replacement") not in (False, "False", None)
        ):
            raise ValueError(
                "The change set touches resources outside the existing "
                "MigrationManagement stack or replaces a resource. Do not execute."
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="operation", required=True)
    prepare = subcommands.add_parser("prepare")
    prepare.add_argument("--existing", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--repository", required=True)
    prepare.add_argument("--digest", required=True)
    verify = subcommands.add_parser("verify")
    verify.add_argument("--changeset", type=Path, required=True)
    args = parser.parse_args()

    if args.operation == "prepare":
        existing = json.loads(args.existing.read_text(encoding="utf-8"))
        result = prepare_parameters(existing, args.repository, args.digest)
        args.output.write_text(json.dumps(result), encoding="utf-8")
        print("Prepared parameter-only DEV update; existing values preserved.")
    else:
        ensure_migration_only(json.loads(args.changeset.read_text(encoding="utf-8")))
        print("Verified: this DEV change set modifies MigrationManagement only.")


if __name__ == "__main__":
    main()
