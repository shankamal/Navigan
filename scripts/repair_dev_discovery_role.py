#!/usr/bin/env python3
"""Repair the development NaviganDiscoveryRole tenant-bound trust policy."""

from __future__ import annotations

import argparse
import json
import secrets

import boto3


DEV_ACCOUNT_ID = "905418045935"
DEV_STACK_NAME = "navigan-ashok-dev"
DISCOVERY_ROLE_NAME = "NaviganDiscoveryRole"


def output_value(cloudformation, key: str) -> str:
    stack = cloudformation.describe_stacks(StackName=DEV_STACK_NAME)["Stacks"][0]
    value = next(
        (
            item["OutputValue"]
            for item in stack.get("Outputs", [])
            if item.get("OutputKey") == key
        ),
        None,
    )
    if not value:
        raise RuntimeError(f"Stack output {key!r} was not found.")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Update only the development NaviganDiscoveryRole trust policy "
            "for tenant-bound SourceIdentity and session tags."
        )
    )
    parser.add_argument("--profile", default="navigan")
    parser.add_argument("--region", default="ap-south-1")
    parser.add_argument("--customer-id", required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Required safety acknowledgement before changing the IAM trust policy.",
    )
    args = parser.parse_args()

    if not args.apply:
        raise SystemExit("Safety stop: review the command and add --apply.")
    if not args.customer_id.startswith("CUS-") or len(args.customer_id) > 50:
        raise SystemExit("Safety stop: provide a valid Navigan CUS- customer ID.")

    external_id = secrets.token_urlsafe(32)

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    account_id = session.client("sts").get_caller_identity()["Account"]
    if account_id != DEV_ACCOUNT_ID:
        raise SystemExit(
            f"Safety stop: connected to AWS account {account_id}, expected development account {DEV_ACCOUNT_ID}."
        )

    cloudformation = session.client("cloudformation")
    function_name = output_value(cloudformation, "EnvironmentFunctionName")
    execution_role_arn = session.client("lambda").get_function_configuration(
        FunctionName=function_name
    )["Role"]

    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "NaviganTenantBoundDiscovery",
                "Effect": "Allow",
                "Principal": {"AWS": execution_role_arn},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {
                        "sts:ExternalId": external_id,
                    },
                },
            }
        ],
    }

    iam = session.client("iam")
    role = iam.get_role(RoleName=DISCOVERY_ROLE_NAME)["Role"]
    expected_role_arn = f"arn:aws:iam::{DEV_ACCOUNT_ID}:role/{DISCOVERY_ROLE_NAME}"
    if role["Arn"] != expected_role_arn:
        raise SystemExit(
            f"Safety stop: resolved role {role['Arn']}, expected {expected_role_arn}."
        )

    iam.update_assume_role_policy(
        RoleName=DISCOVERY_ROLE_NAME,
        PolicyDocument=json.dumps(trust_policy, separators=(",", ":")),
    )
    updated = iam.get_role(RoleName=DISCOVERY_ROLE_NAME)["Role"][
        "AssumeRolePolicyDocument"
    ]
    print(f"Updated {expected_role_arn}")
    print(f"Trusted principal: {execution_role_arn}")
    print(f"Navigan customer: {args.customer_id}")
    print("Allowed STS action: sts:AssumeRole")
    print()
    print("Generated External ID (copy this into the Navigan environment form):")
    print(external_id)
    print()
    print("This value is displayed once and is not stored by this utility.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
