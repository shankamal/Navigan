"""Seed deterministic customer examples into the isolated Navigan dev database."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass

ALLOWED_DATABASE = "navigan_dev"
SEED_ACTOR = "navigan-demo-seed"


@dataclass(frozen=True)
class SampleCustomer:
    customer_id: str
    name: str
    status: str
    providers: tuple[str, ...]
    age_days: int


SAMPLES = (
    SampleCustomer("CUS-DEMO-0001", "Navigan Demo - Acme Retail", "ACTIVE", ("AWS", "AZURE"), 38),
    SampleCustomer("CUS-DEMO-0002", "Navigan Demo - Alpine Banking", "ACTIVE", ("AWS",), 34),
    SampleCustomer("CUS-DEMO-0003", "Navigan Demo - BlueSky Media", "ACTIVE", ("AWS", "GCP"), 31),
    SampleCustomer("CUS-DEMO-0004", "Navigan Demo - Cedar Health", "ACTIVE", ("AWS",), 28),
    SampleCustomer("CUS-DEMO-0005", "Navigan Demo - Delta Logistics", "APPROVED", ("AWS",), 24),
    SampleCustomer("CUS-DEMO-0006", "Navigan Demo - Ember Energy", "APPROVED", ("AWS", "OCI"), 22),
    SampleCustomer("CUS-DEMO-0007", "Navigan Demo - FinPeak Capital", "UNDER_REVIEW", ("AWS",), 18),
    SampleCustomer("CUS-DEMO-0008", "Navigan Demo - GreenField Foods", "UNDER_REVIEW", ("AWS", "AZURE"), 16),
    SampleCustomer("CUS-DEMO-0009", "Navigan Demo - Horizon Travel", "SUBMITTED", ("AWS",), 13),
    SampleCustomer("CUS-DEMO-0010", "Navigan Demo - Inkwell Publishing", "SUBMITTED", ("AWS",), 11),
    SampleCustomer("CUS-DEMO-0011", "Navigan Demo - Juniper Telecom", "DRAFT", ("AWS",), 8),
    SampleCustomer("CUS-DEMO-0012", "Navigan Demo - Keystone Manufacturing", "DRAFT", ("AWS", "GCP"), 6),
    SampleCustomer("CUS-DEMO-0013", "Navigan Demo - Lumina Education", "REJECTED", ("AWS",), 19),
    SampleCustomer("CUS-DEMO-0014", "Navigan Demo - Meridian Insurance", "REJECTED", ("AWS",), 15),
    SampleCustomer("CUS-DEMO-0015", "Navigan Demo - Northstar Labs", "SUSPENDED", ("AWS",), 27),
    SampleCustomer("CUS-DEMO-0016", "Navigan Demo - Oakline Services", "DEACTIVATED", ("AWS",), 36),
)

VALID_STATUSES = {
    "DRAFT",
    "SUBMITTED",
    "UNDER_REVIEW",
    "APPROVED",
    "REJECTED",
    "ACTIVE",
    "SUSPENDED",
    "DEACTIVATED",
}


def validate_samples() -> None:
    assert 10 <= len(SAMPLES) <= 20
    assert {sample.status for sample in SAMPLES} == VALID_STATUSES
    assert len({sample.customer_id for sample in SAMPLES}) == len(SAMPLES)
    assert len({sample.name.casefold() for sample in SAMPLES}) == len(SAMPLES)
    assert sum(sample.status == "ACTIVE" for sample in SAMPLES) >= 4
    assert all("AWS" in sample.providers for sample in SAMPLES)


def string_param(name: str, value: str) -> dict:
    return {"name": name, "value": {"stringValue": value}}


CUSTOMER_SQL = """
INSERT INTO customer_management.customers (
  customer_id, onboarding_request_id, name, description, status,
  created_by, created_at, updated_by, updated_at,
  submitted_by, submitted_at, approved_by, approved_at,
  rejected_by, rejected_at, rejection_reason,
  activated_by, activated_at, suspended_by, suspended_at, suspension_reason,
  deactivated_by, deactivated_at, deactivation_reason, review_cycle, version
)
VALUES (
  :customer_id, :request_id, :name,
  'Deterministic sample customer for Navigan development and UI validation.', :status,
  :actor, now() - (:age_days || ' days')::interval, :actor, now(),
  CASE WHEN :status <> 'DRAFT' THEN :actor END,
  CASE WHEN :status <> 'DRAFT' THEN now() - ((CAST(:age_days AS integer) - 1) || ' days')::interval END,
  CASE WHEN :status IN ('APPROVED','ACTIVE','SUSPENDED','DEACTIVATED') THEN :actor END,
  CASE WHEN :status IN ('APPROVED','ACTIVE','SUSPENDED','DEACTIVATED') THEN now() - ((CAST(:age_days AS integer) - 2) || ' days')::interval END,
  CASE WHEN :status = 'REJECTED' THEN :actor END,
  CASE WHEN :status = 'REJECTED' THEN now() - ((CAST(:age_days AS integer) - 2) || ' days')::interval END,
  CASE WHEN :status = 'REJECTED' THEN 'Sample governance information was incomplete.' END,
  CASE WHEN :status IN ('ACTIVE','SUSPENDED','DEACTIVATED') THEN :actor END,
  CASE WHEN :status IN ('ACTIVE','SUSPENDED','DEACTIVATED') THEN now() - ((CAST(:age_days AS integer) - 3) || ' days')::interval END,
  CASE WHEN :status = 'SUSPENDED' THEN :actor END,
  CASE WHEN :status = 'SUSPENDED' THEN now() - interval '1 day' END,
  CASE WHEN :status = 'SUSPENDED' THEN 'Sample account maintenance window.' END,
  CASE WHEN :status = 'DEACTIVATED' THEN :actor END,
  CASE WHEN :status = 'DEACTIVATED' THEN now() - interval '1 day' END,
  CASE WHEN :status = 'DEACTIVATED' THEN 'Sample customer lifecycle completed.' END,
  CASE WHEN :status IN ('DRAFT','SUBMITTED') THEN 0 ELSE 1 END,
  1
)
ON CONFLICT (customer_id) DO NOTHING
"""

PROVIDER_SQL = """
INSERT INTO customer_management.customer_cloud_providers (
  customer_id, provider_code, created_by
)
VALUES (:customer_id, :provider, :actor)
ON CONFLICT (customer_id, provider_code) DO NOTHING
"""

CONTACT_SQL = """
INSERT INTO customer_management.customer_contacts (
  contact_id, customer_id, contact_type, name, email
)
VALUES (:contact_id, :customer_id, 'PRIMARY', :contact_name, :email)
ON CONFLICT (contact_id) DO NOTHING
"""

HISTORY_SQL = """
INSERT INTO customer_management.customer_status_history (
  customer_id, previous_status, new_status, changed_by, reason, comments, correlation_id
)
SELECT :customer_id, NULL, :status, :actor, 'Development sample seed',
       'Deterministic sample record', :correlation_id
WHERE NOT EXISTS (
  SELECT 1 FROM customer_management.customer_status_history
  WHERE customer_id = :customer_id AND correlation_id = :correlation_id
)
"""


def parameters(sample: SampleCustomer) -> list[dict]:
    return [
        string_param("customer_id", sample.customer_id),
        string_param("request_id", sample.customer_id.replace("CUS", "ONB", 1)),
        string_param("name", sample.name),
        string_param("status", sample.status),
        string_param("actor", SEED_ACTOR),
        string_param("age_days", str(sample.age_days)),
    ]


def execute(client, transaction_id: str, args, sql: str, params: list[dict]) -> None:
    client.execute_statement(
        resourceArn=args.resource_arn,
        secretArn=args.secret_arn,
        database=args.database,
        transactionId=transaction_id,
        sql=sql,
        parameters=params,
    )


def apply_seed(args) -> None:
    import boto3

    client = boto3.Session(profile_name=args.profile, region_name=args.region).client("rds-data")
    transaction = client.begin_transaction(
        resourceArn=args.resource_arn,
        secretArn=args.secret_arn,
        database=args.database,
    )["transactionId"]
    try:
        for index, sample in enumerate(SAMPLES, start=1):
            base = parameters(sample)
            execute(client, transaction, args, CUSTOMER_SQL, base)
            for provider in sample.providers:
                execute(
                    client,
                    transaction,
                    args,
                    PROVIDER_SQL,
                    [
                        string_param("customer_id", sample.customer_id),
                        string_param("provider", provider),
                        string_param("actor", SEED_ACTOR),
                    ],
                )
            slug = sample.name.removeprefix("Navigan Demo - ").lower().replace(" ", ".")
            execute(
                client,
                transaction,
                args,
                CONTACT_SQL,
                [
                    string_param("contact_id", f"CON-DEMO-{index:04d}"),
                    string_param("customer_id", sample.customer_id),
                    string_param("contact_name", f"{sample.name.removeprefix('Navigan Demo - ')} Platform Owner"),
                    string_param("email", f"platform.owner@{slug}.example"),
                ],
            )
            execute(
                client,
                transaction,
                args,
                HISTORY_SQL,
                [
                    string_param("customer_id", sample.customer_id),
                    string_param("status", sample.status),
                    string_param("actor", SEED_ACTOR),
                    string_param("correlation_id", f"navigan-demo-seed-{index:04d}"),
                ],
            )
        client.commit_transaction(
            resourceArn=args.resource_arn,
            secretArn=args.secret_arn,
            transactionId=transaction,
        )
    except Exception:
        client.rollback_transaction(
            resourceArn=args.resource_arn,
            secretArn=args.secret_arn,
            transactionId=transaction,
        )
        raise

    result = client.execute_statement(
        resourceArn=args.resource_arn,
        secretArn=args.secret_arn,
        database=args.database,
        sql="""
          SELECT status, count(*)::int AS customers
          FROM customer_management.customers
          WHERE customer_id LIKE 'CUS-DEMO-%'
          GROUP BY status ORDER BY status
        """,
        formatRecordsAs="JSON",
    )
    print("Sample customers are ready:")
    print(json.dumps(json.loads(result.get("formattedRecords", "[]")), indent=2))


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="navigan-sandbox")
    parser.add_argument("--region", default="ap-south-1")
    parser.add_argument("--resource-arn", required=True)
    parser.add_argument("--secret-arn", required=True)
    parser.add_argument("--database", default=ALLOWED_DATABASE)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the records. Without this flag the command performs no AWS calls.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    validate_samples()
    if args.database != ALLOWED_DATABASE:
        raise SystemExit(f"Refusing to seed {args.database!r}; only {ALLOWED_DATABASE!r} is permitted")
    if not args.apply:
        counts = {status: 0 for status in sorted(VALID_STATUSES)}
        for sample in SAMPLES:
            counts[sample.status] += 1
        print(f"Validated {len(SAMPLES)} deterministic sample customers for {args.database}")
        print(json.dumps(counts, indent=2))
        print("Dry run complete; no AWS calls were made. Add --apply to insert the records.")
        return
    apply_seed(args)


if __name__ == "__main__":
    main()
