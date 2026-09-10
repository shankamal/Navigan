#!/usr/bin/env python3
"""Apply Navigan PostgreSQL migrations through the Aurora RDS Data API.

This runner exists for administrative workstations that cannot connect directly
to the private Aurora endpoint. It preserves the repository migration contract:
ordered files, one transaction, an advisory lock, and SHA-256 checksums.
"""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path

import boto3


DOLLAR_TAG = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")


def split_postgresql_script(source: str) -> list[str]:
    """Split SQL on top-level semicolons while preserving PostgreSQL dollar blocks."""
    statements: list[str] = []
    current: list[str] = []
    index = 0
    single_quote = False
    double_quote = False
    line_comment = False
    block_comment_depth = 0
    dollar_tag: str | None = None

    while index < len(source):
        if line_comment:
            char = source[index]
            current.append(char)
            index += 1
            if char == "\n":
                line_comment = False
            continue

        if block_comment_depth:
            if source.startswith("/*", index):
                current.append("/*")
                block_comment_depth += 1
                index += 2
            elif source.startswith("*/", index):
                current.append("*/")
                block_comment_depth -= 1
                index += 2
            else:
                current.append(source[index])
                index += 1
            continue

        if dollar_tag:
            if source.startswith(dollar_tag, index):
                current.append(dollar_tag)
                index += len(dollar_tag)
                dollar_tag = None
            else:
                current.append(source[index])
                index += 1
            continue

        char = source[index]

        if single_quote:
            current.append(char)
            index += 1
            if char == "'":
                if index < len(source) and source[index] == "'":
                    current.append("'")
                    index += 1
                else:
                    single_quote = False
            continue

        if double_quote:
            current.append(char)
            index += 1
            if char == '"':
                if index < len(source) and source[index] == '"':
                    current.append('"')
                    index += 1
                else:
                    double_quote = False
            continue

        if source.startswith("--", index):
            current.append("--")
            line_comment = True
            index += 2
            continue
        if source.startswith("/*", index):
            current.append("/*")
            block_comment_depth = 1
            index += 2
            continue
        if char == "'":
            current.append(char)
            single_quote = True
            index += 1
            continue
        if char == '"':
            current.append(char)
            double_quote = True
            index += 1
            continue
        if char == "$":
            match = DOLLAR_TAG.match(source, index)
            if match:
                dollar_tag = match.group(0)
                current.append(dollar_tag)
                index = match.end()
                continue
        if char == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            index += 1
            continue

        current.append(char)
        index += 1

    if single_quote or double_quote or block_comment_depth or dollar_tag:
        raise ValueError("Unterminated quote, comment, or dollar-quoted block in SQL")
    final = "".join(current).strip()
    if final:
        statements.append(final)
    return statements


def execute(client, args, transaction_id: str, sql: str, parameters=None):
    request = {
        "resourceArn": args.resource_arn,
        "secretArn": args.secret_arn,
        "database": args.database,
        "transactionId": transaction_id,
        "sql": sql,
        "continueAfterTimeout": True,
    }
    if parameters:
        request["parameters"] = parameters
    return client.execute_statement(**request)


def string_parameter(name: str, value: str) -> dict:
    return {"name": name, "value": {"stringValue": value}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--resource-arn", required=True)
    parser.add_argument("--secret-arn", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--migrations-dir", default="database/migrations")
    parser.add_argument("--roles-file", default="database/bootstrap/roles.sql")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # Refuse production-like targets. This utility is intentionally dev-only.
    if not args.database.endswith("_dev"):
        raise SystemExit("Safety stop: --database must end with '_dev'")

    migrations_dir = Path(args.migrations_dir).resolve()
    roles_file = Path(args.roles_file).resolve()
    migration_files = sorted(migrations_dir.glob("*.sql"))
    if not migration_files:
        raise SystemExit(f"No migrations found in {migrations_dir}")
    if not roles_file.is_file():
        raise SystemExit(f"Roles file not found: {roles_file}")

    if args.dry_run:
        for path in migration_files:
            content = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(content.encode()).hexdigest()
            statements = split_postgresql_script(content)
            print(f"Validated {path.name}: {len(statements)} statements, sha256={checksum}")
        role_statements = split_postgresql_script(roles_file.read_text(encoding="utf-8"))
        print(f"Validated {roles_file.name}: {len(role_statements)} statements")
        print(f"Dry run complete for {args.database}; no AWS calls were made")
        return 0

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    client = session.client("rds-data")
    transaction_id: str | None = None

    try:
        started = client.begin_transaction(
            resourceArn=args.resource_arn,
            secretArn=args.secret_arn,
            database=args.database,
        )
        transaction_id = started["transactionId"]

        identity = execute(client, args, transaction_id, "SELECT current_database()")
        connected_database = identity["records"][0][0]["stringValue"]
        if connected_database != args.database:
            raise RuntimeError(
                f"Safety stop: connected to {connected_database!r}, expected {args.database!r}"
            )

        execute(client, args, transaction_id, "SELECT pg_advisory_xact_lock(7093314001)")
        execute(client, args, transaction_id, "CREATE SCHEMA IF NOT EXISTS platform")
        execute(
            client,
            args,
            transaction_id,
            "CREATE TABLE IF NOT EXISTS platform.schema_migrations "
            "(name text PRIMARY KEY, checksum text NOT NULL, "
            "applied_at timestamptz NOT NULL DEFAULT now())",
        )

        for path in migration_files:
            content = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(content.encode()).hexdigest()
            existing = execute(
                client,
                args,
                transaction_id,
                "SELECT checksum FROM platform.schema_migrations WHERE name=:name",
                [string_parameter("name", path.name)],
            )
            if existing.get("records"):
                previous = existing["records"][0][0]["stringValue"]
                if previous != checksum:
                    raise RuntimeError(f"Applied migration was modified: {path.name}")
                print(f"Skipped {path.name} (already applied)")
                continue

            statements = split_postgresql_script(content)
            print(f"Applying {path.name} ({len(statements)} statements)")
            for number, statement in enumerate(statements, start=1):
                try:
                    execute(client, args, transaction_id, statement)
                except Exception as error:
                    raise RuntimeError(
                        f"{path.name} statement {number}/{len(statements)} failed"
                    ) from error
            execute(
                client,
                args,
                transaction_id,
                "INSERT INTO platform.schema_migrations(name, checksum) "
                "VALUES (:name, :checksum)",
                [
                    string_parameter("name", path.name),
                    string_parameter("checksum", checksum),
                ],
            )
            print(f"Applied {path.name}")

        role_statements = split_postgresql_script(roles_file.read_text(encoding="utf-8"))
        print(f"Applying runtime grants ({len(role_statements)} statements)")
        for number, statement in enumerate(role_statements, start=1):
            try:
                execute(client, args, transaction_id, statement)
            except Exception as error:
                raise RuntimeError(
                    f"roles.sql statement {number}/{len(role_statements)} failed"
                ) from error

        client.commit_transaction(
            resourceArn=args.resource_arn,
            secretArn=args.secret_arn,
            transactionId=transaction_id,
        )
        transaction_id = None
        print(f"Migration committed successfully to {args.database}")
        return 0
    except Exception:
        if transaction_id:
            client.rollback_transaction(
                resourceArn=args.resource_arn,
                secretArn=args.secret_arn,
                transactionId=transaction_id,
            )
            print("Migration failed; transaction rolled back")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
