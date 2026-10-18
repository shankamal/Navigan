#!/usr/bin/env python3
"""Create a DEV CloudFormation template changing only its MigrationManagement child.

The input MUST be the processed template returned by CloudFormation, not a
locally regenerated root template (whose other nested templates might drift).
"""

import argparse
import copy
import json
from pathlib import Path


MIGRATION_RESOURCE = "MigrationManagement"
EXPECTED_ROOT_TYPE = "AWS::CloudFormation::Stack"
EXPECTED_BUCKET = "aws-sam-cli-managed-default-samclisourcebucket-xj9yzigmdgri"


def patch_template(raw, new_url, repository, digest, delivery_role):
    original = raw.get("TemplateBody")
    if not isinstance(original, dict) or not isinstance(original.get("Resources"), dict):
        raise ValueError("CloudFormation did not return a processed JSON root template")

    original_child = original["Resources"].get(MIGRATION_RESOURCE)
    if not isinstance(original_child, dict) or original_child.get("Type") != EXPECTED_ROOT_TYPE:
        raise ValueError("Expected the deployed MigrationManagement nested stack")

    existing_properties = original_child.get("Properties", {})
    old_url = existing_properties.get("TemplateURL", "")
    prefix = f"https://s3.ap-south-1.amazonaws.com/{EXPECTED_BUCKET}/"
    if not isinstance(old_url, str) or not old_url.startswith(prefix):
        raise ValueError("Unexpected existing MigrationManagement template location")
    if not new_url.startswith(prefix) or new_url == old_url:
        raise ValueError("Refusing missing, unexpected, or unchanged new template URL")

    existing_parameters = existing_properties.get("Parameters", {})
    if not isinstance(existing_parameters, dict):
        raise ValueError("Existing nested stack parameters are not a mapping")
    for name in (
        "MigrationConnectorImageRepository",
        "MigrationConnectorImageDigest",
        "SourceConnectorDeliveryRoleArn",
    ):
        if name in existing_parameters:
            raise ValueError(f"Unexpected existing nested stack parameter: {name}")

    if not repository.startswith(
        "905418045935.dkr.ecr.ap-south-1.amazonaws.com/navigan/migration-source-connector"
    ) or repository.endswith("/"):
        raise ValueError("Unexpected connector image repository")
    if len(digest) != 71 or not digest.startswith("sha256:") or any(
        letter not in "0123456789abcdef" for letter in digest[7:]
    ):
        raise ValueError("Invalid immutable connector image digest")
    if delivery_role != "arn:aws:iam::905418045935:role/NaviganSourceConnectorDeliveryRole":
        raise ValueError("Unexpected source connector delivery role")

    patched = copy.deepcopy(original)
    child = patched["Resources"][MIGRATION_RESOURCE]
    child["Properties"]["TemplateURL"] = new_url
    child["Properties"]["Parameters"].update(
        MigrationConnectorImageRepository=repository,
        MigrationConnectorImageDigest=digest,
        SourceConnectorDeliveryRoleArn=delivery_role,
    )

    # Keep every sibling capability and every other top-level field identical.
    if (
        {k: v for k, v in patched.items() if k != "Resources"}
        != {k: v for k, v in original.items() if k != "Resources"}
        or {k: v for k, v in patched["Resources"].items() if k != MIGRATION_RESOURCE}
        != {k: v for k, v in original["Resources"].items() if k != MIGRATION_RESOURCE}
    ):
        raise ValueError("Template unexpectedly changed resources outside MigrationManagement")
    return patched


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--response", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--new-url", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--delivery-role", required=True)
    args = parser.parse_args()
    response = json.loads(args.response.read_text(encoding="utf-8"))
    root = patch_template(
        response, args.new_url, args.repository, args.digest, args.delivery_role
    )
    args.output.write_text(json.dumps(root, indent=2) + "\n", encoding="utf-8")
    print("Verified: processed root template preserves all resources except MigrationManagement.")


if __name__ == "__main__":
    main()
