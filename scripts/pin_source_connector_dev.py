#!/usr/bin/env python3
"""Pin an immutable migration connector release to DEV SAM parameters only.

The caller supplies a temporary copy of samconfig.toml. Production entries
must remain byte-for-byte unchanged; this script never performs AWS actions.
"""

import argparse
import json
import pathlib
import re
import shlex
import tomllib


SECTIONS = ("default.deploy.parameters", "dev.deploy.parameters")
REPOSITORY_PATTERN = re.compile(
    r"^[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/[a-z0-9._/-]+$"
)
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


def pin_dev_config(contents: str, repository: str, digest: str) -> str:
    if not REPOSITORY_PATTERN.fullmatch(repository):
        raise ValueError("Expected an AWS ECR private repository URI.")
    if not DIGEST_PATTERN.fullmatch(digest):
        raise ValueError("Expected an immutable sha256 image digest.")

    parsed = tomllib.loads(contents)
    dev_tokens = shlex.split(parsed["dev"]["deploy"]["parameters"]["parameter_overrides"])
    dev_parameters = dict(token.split("=", 1) for token in dev_tokens)
    delivery_role = dev_parameters.get("SourceConnectorDeliveryRoleArn", "")
    if not re.fullmatch(
        r"arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9_+=,.@/-]+", delivery_role
    ):
        raise ValueError("DEV must have an approved SourceConnectorDeliveryRoleArn.")

    for section in SECTIONS:
        section_pattern = re.compile(
            rf"(?ms)(^\[{re.escape(section)}\]\n)(.*?)(?=^\[|\Z)"
        )
        found = section_pattern.search(contents)
        if not found:
            raise ValueError(f"Missing SAM configuration section: {section}")

        block = found.group(2)
        parameter_pattern = re.compile(r"(?m)^parameter_overrides\s*=\s*.+$")
        if len(parameter_pattern.findall(block)) != 1:
            raise ValueError(f"Expected one parameter_overrides line in {section}")

        tokens = shlex.split(
            parsed[section.split(".")[0]]["deploy"]["parameters"]["parameter_overrides"]
        )
        parameters = dict(token.split("=", 1) for token in tokens)
        parameters["MigrationConnectorImageRepository"] = repository
        parameters["MigrationConnectorImageDigest"] = digest
        parameters["SourceConnectorDeliveryRoleArn"] = delivery_role

        # JSON string syntax is compatible with TOML's quoted basic strings.
        rendered = " ".join(f'{key}="{value}"' for key, value in parameters.items())
        new_line = "parameter_overrides = " + json.dumps(rendered)
        updated_block = parameter_pattern.sub(lambda _: new_line, block)
        contents = contents[:found.start(2)] + updated_block + contents[found.end(2):]

    # Always round-trip-check before the caller may deploy.
    validated = tomllib.loads(contents)
    for section in SECTIONS:
        name = section.split(".")[0]
        values = dict(
            token.split("=", 1)
            for token in shlex.split(validated[name]["deploy"]["parameters"]["parameter_overrides"])
        )
        assert values["MigrationConnectorImageRepository"] == repository
        assert values["MigrationConnectorImageDigest"] == digest
        assert values["SourceConnectorDeliveryRoleArn"] == delivery_role
    return contents


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=pathlib.Path)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--digest", required=True)
    args = parser.parse_args()
    original = args.config.read_text(encoding="utf-8")
    updated = pin_dev_config(original, args.repository, args.digest)
    args.config.write_text(updated, encoding="utf-8")
    print("Pinned connector repository and digest in temporary default/DEV SAM profiles.")


if __name__ == "__main__":
    main()
