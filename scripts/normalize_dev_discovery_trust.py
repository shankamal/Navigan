#!/usr/bin/env python3
"""Normalize the existing dev discovery trust without rotating its External ID."""

from __future__ import annotations

import argparse
import json

import boto3


ACCOUNT_ID = "905418045935"
ROLE_NAME = "NaviganDiscoveryRole"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="navigan")
    parser.add_argument("--region", default="ap-south-1")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        raise SystemExit("Safety stop: add --apply to update the development role.")

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    if session.client("sts").get_caller_identity()["Account"] != ACCOUNT_ID:
        raise SystemExit("Safety stop: this utility is restricted to the Navigan development account.")

    iam = session.client("iam")
    role = iam.get_role(RoleName=ROLE_NAME)["Role"]
    existing = role["AssumeRolePolicyDocument"]
    statements = existing.get("Statement", [])
    if not statements:
        raise SystemExit("Safety stop: the discovery role has no trust statements.")

    principal = next(
        (
            statement.get("Principal", {}).get("AWS")
            for statement in statements
            if statement.get("Principal", {}).get("AWS")
        ),
        None,
    )
    external_id = next(
        (
            statement.get("Condition", {})
            .get("StringEquals", {})
            .get("sts:ExternalId")
            for statement in statements
            if statement.get("Condition", {})
            .get("StringEquals", {})
            .get("sts:ExternalId")
        ),
        None,
    )
    customer_id = next(
        (
            statement.get("Condition", {})
            .get("StringEquals", {})
            .get("aws:RequestTag/NaviganCustomerId")
            for statement in statements
            if statement.get("Condition", {})
            .get("StringEquals", {})
            .get("aws:RequestTag/NaviganCustomerId")
        ),
        "CUS-a0b7d680310c4cdda60609f0de9bea7e",
    )
    if not (
        isinstance(principal, str)
        and principal.startswith(f"arn:aws:iam::{ACCOUNT_ID}:role/")
        and isinstance(external_id, str)
        and isinstance(customer_id, str)
        and customer_id.startswith("CUS-")
    ):
        raise SystemExit("Safety stop: the existing tenant trust values could not be verified.")

    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AssumeTenantDiscoveryRole",
                "Effect": "Allow",
                "Principal": {"AWS": principal},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {"sts:ExternalId": external_id},
                },
            },
        ],
    }
    iam.update_assume_role_policy(
        RoleName=ROLE_NAME,
        PolicyDocument=json.dumps(policy, separators=(",", ":")),
    )
    print(f"Normalized arn:aws:iam::{ACCOUNT_ID}:role/{ROLE_NAME}")
    print(f"Trusted principal: {principal}")
    print(f"Navigan customer: {customer_id}")
    print("The existing External ID was preserved and was not displayed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
