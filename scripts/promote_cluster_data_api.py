#!/usr/bin/env python3
"""Promote current cluster ownership data between databases through RDS Data API.

The transfer intentionally excludes connector credentials, live inventories,
tool sessions, tunnels, webkubectl sessions, and reconciliation executions.
Those records are reset in the target and must be re-established there.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import boto3


COPY_TABLES = (
    ("cluster_management", "github_app_connections", "customer"),
    ("cluster_management", "clusters", "cluster"),
    ("cluster_management", "cluster_versions", "cluster"),
    ("cluster_management", "cluster_identity_integrations", "cluster"),
    ("cluster_management", "cluster_node_group_requests", "cluster"),
    ("cluster_management", "cluster_system_repositories", "cluster"),
    ("access_management", "kubernetes_access_assignments", "cluster"),
)

RUNTIME_TABLES = (
    ("cluster_management", "cluster_tool_sessions"),
    ("cluster_management", "cluster_tool_tunnels"),
    ("cluster_management", "webkubectl_sessions"),
    ("cluster_management", "cluster_access_reconciliations"),
    ("cluster_management", "cluster_runtime_inventories"),
    ("cluster_management", "cluster_platform_components"),
    ("cluster_management", "cluster_platform_component_inventories"),
    ("cluster_management", "cluster_namespaces"),
    ("cluster_management", "cluster_namespace_inventories"),
    ("cluster_management", "cluster_connectors"),
)

IMMUTABLE_TABLES = {("cluster_management", "cluster_versions")}


def execute(client, args, database, sql, parameters=None, transaction_id=None):
    request = {
        "resourceArn": args.resource_arn,
        "secretArn": args.secret_arn,
        "database": database,
        "sql": sql,
    }
    if parameters:
        request["parameters"] = parameters
    if transaction_id:
        request["transactionId"] = transaction_id
    return client.execute_statement(**request)


def text_parameter(name: str, value: str) -> dict:
    return {"name": name, "value": {"stringValue": value}}


def quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def table_name(schema: str, table: str) -> str:
    return f"{quote(schema)}.{quote(table)}"


def json_rows(client, args, database, schema, table, where, tx=None):
    qualified = table_name(schema, table)
    result = execute(
        client,
        args,
        database,
        "SELECT COALESCE(jsonb_agg(to_jsonb(source_rows)), '[]'::jsonb)::text "
        f"FROM (SELECT * FROM {qualified} WHERE {where}) source_rows",
        transaction_id=tx,
    )
    payload = result["records"][0][0]["stringValue"]
    if len(payload.encode("utf-8")) > 900_000:
        raise RuntimeError(f"{schema}.{table} export exceeds the safe Data API response size")
    return json.loads(payload)


def table_metadata(client, args, database, schema, table, tx):
    columns_result = execute(
        client,
        args,
        database,
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema=:schema AND table_name=:table "
        "ORDER BY ordinal_position",
        [
            text_parameter("schema", schema),
            text_parameter("table", table),
        ],
        tx,
    )
    columns = [record[0]["stringValue"] for record in columns_result.get("records", [])]
    pk_result = execute(
        client,
        args,
        database,
        "SELECT key_column.column_name "
        "FROM information_schema.table_constraints constraint_definition "
        "JOIN information_schema.key_column_usage key_column "
        "ON key_column.constraint_schema=constraint_definition.constraint_schema "
        "AND key_column.constraint_name=constraint_definition.constraint_name "
        "WHERE constraint_definition.table_schema=:schema "
        "AND constraint_definition.table_name=:table "
        "AND constraint_definition.constraint_type='PRIMARY KEY' "
        "ORDER BY key_column.ordinal_position",
        [
            text_parameter("schema", schema),
            text_parameter("table", table),
        ],
        tx,
    )
    primary_key = [record[0]["stringValue"] for record in pk_result.get("records", [])]
    if not columns or not primary_key:
        raise RuntimeError(f"Missing table metadata for {schema}.{table}")
    return columns, primary_key


def upsert_rows(client, args, schema, table, rows, tx):
    if not rows:
        return
    columns, primary_key = table_metadata(
        client, args, args.target_database, schema, table, tx
    )
    qualified = table_name(schema, table)
    column_list = ",".join(quote(column) for column in columns)
    conflict = ",".join(quote(column) for column in primary_key)
    if (schema, table) in IMMUTABLE_TABLES:
        resolution = "DO NOTHING"
    else:
        updates = ",".join(
            f"{quote(column)}=EXCLUDED.{quote(column)}"
            for column in columns
            if column not in primary_key
        )
        resolution = f"DO UPDATE SET {updates}"
    sql = (
        f"INSERT INTO {qualified} ({column_list}) "
        f"SELECT {column_list} FROM jsonb_populate_recordset("
        f"NULL::{qualified},CAST(:payload AS jsonb)) "
        f"ON CONFLICT ({conflict}) {resolution}"
    )
    execute(
        client,
        args,
        args.target_database,
        sql,
        [text_parameter("payload", json.dumps(rows, separators=(",", ":")))],
        tx,
    )


def cluster_where(cluster_ids):
    values = ",".join("'" + value.replace("'", "''") + "'" for value in cluster_ids)
    return f"cluster_id IN ({values})"


def customer_where(customer_ids):
    values = ",".join("'" + value.replace("'", "''") + "'" for value in customer_ids)
    return f"customer_id IN ({values})"


def begin(client, args, database):
    return client.begin_transaction(
        resourceArn=args.resource_arn,
        secretArn=args.secret_arn,
        database=database,
    )["transactionId"]


def rollback(client, args, database, transaction_id):
    client.rollback_transaction(
        resourceArn=args.resource_arn,
        secretArn=args.secret_arn,
        transactionId=transaction_id,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--resource-arn", required=True)
    parser.add_argument("--secret-arn", required=True)
    parser.add_argument("--source-database", required=True)
    parser.add_argument("--target-database", required=True)
    parser.add_argument("--confirm-transfer")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-dir", default=".promotion-backups")
    args = parser.parse_args()

    expected_confirmation = f"{args.source_database}->{args.target_database}"
    if not args.source_database.endswith("_dev"):
        raise SystemExit("Safety stop: source database must end with '_dev'")
    if args.target_database.endswith("_dev") or args.target_database == args.source_database:
        raise SystemExit("Safety stop: target must be a different non-Dev database")
    if args.apply and args.confirm_transfer != expected_confirmation:
        raise SystemExit(
            f"Safety stop: --confirm-transfer must equal {expected_confirmation!r}"
        )

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    client = session.client("rds-data")
    source_tx = begin(client, args, args.source_database)
    target_tx = None
    try:
        execute(
            client,
            args,
            args.source_database,
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY",
            transaction_id=source_tx,
        )
        clusters = json_rows(
            client,
            args,
            args.source_database,
            "cluster_management",
            "clusters",
            "TRUE",
            source_tx,
        )
        cluster_ids = [row["cluster_id"] for row in clusters]
        customer_ids = sorted({row["customer_id"] for row in clusters})
        if not cluster_ids:
            raise RuntimeError("Source contains no clusters")

        copied = {}
        for schema, table, scope in COPY_TABLES:
            if (schema, table) == ("cluster_management", "clusters"):
                rows = clusters
            else:
                where = (
                    customer_where(customer_ids)
                    if scope == "customer"
                    else cluster_where(cluster_ids)
                )
                rows = json_rows(
                    client,
                    args,
                    args.source_database,
                    schema,
                    table,
                    where,
                    source_tx,
                )
            copied[f"{schema}.{table}"] = rows

        prerequisite_result = execute(
            client,
            args,
            args.target_database,
            "SELECT source.cluster_id "
            "FROM jsonb_to_recordset(CAST(:payload AS jsonb)) AS source("
            "cluster_id text,customer_id text,environment_id text,"
            "environment_approved_version bigint) "
            "LEFT JOIN customer_management.customers customer "
            "ON customer.customer_id=source.customer_id "
            "LEFT JOIN environment_management.environment_versions environment_version "
            "ON environment_version.environment_id=source.environment_id "
            "AND environment_version.version=source.environment_approved_version "
            "WHERE customer.customer_id IS NULL "
            "OR environment_version.environment_id IS NULL",
            [
                text_parameter(
                    "payload", json.dumps(clusters, separators=(",", ":"))
                )
            ],
        )
        missing_prerequisites = [
            record[0]["stringValue"]
            for record in prerequisite_result.get("records", [])
        ]
        if missing_prerequisites:
            raise RuntimeError(
                "Target is missing customer/environment prerequisites for clusters: "
                + ", ".join(missing_prerequisites)
            )

        print(
            json.dumps(
                {
                    "source": args.source_database,
                    "target": args.target_database,
                    "clusters": [
                        {
                            "cluster_id": row["cluster_id"],
                            "cluster_name": row["cluster_name"],
                            "status": row["status"],
                        }
                        for row in clusters
                    ],
                    "copy_counts": {name: len(rows) for name, rows in copied.items()},
                    "runtime_action": "reset in target; not copied from Dev",
                    "mode": "apply" if args.apply else "dry-run",
                },
                indent=2,
            )
        )
        if not args.apply:
            rollback(client, args, args.source_database, source_tx)
            return 0

        target_tx = begin(client, args, args.target_database)
        connected = execute(
            client,
            args,
            args.target_database,
            "SELECT current_database()",
            transaction_id=target_tx,
        )["records"][0][0]["stringValue"]
        if connected != args.target_database:
            raise RuntimeError(
                f"Connected to {connected!r}; expected {args.target_database!r}"
            )
        execute(
            client,
            args,
            args.target_database,
            "SELECT pg_advisory_xact_lock(7093314002)",
            transaction_id=target_tx,
        )

        backup = {"database": args.target_database, "tables": {}}
        for schema, table, _scope in COPY_TABLES:
            where = (
                customer_where(customer_ids)
                if (schema, table) == ("cluster_management", "github_app_connections")
                else cluster_where(cluster_ids)
            )
            backup["tables"][f"{schema}.{table}"] = json_rows(
                client,
                args,
                args.target_database,
                schema,
                table,
                where,
                target_tx,
            )
        for schema, table in RUNTIME_TABLES:
            backup["tables"][f"{schema}.{table}"] = json_rows(
                client,
                args,
                args.target_database,
                schema,
                table,
                cluster_where(cluster_ids),
                target_tx,
            )
        backup_path = Path(args.backup_dir)
        backup_path.mkdir(parents=True, exist_ok=True)
        timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output = backup_path / f"{args.target_database}-before-{timestamp}.json"
        output.write_text(json.dumps(backup, indent=2), encoding="utf-8")
        print(f"Saved target backup to {output}")

        for schema, table in RUNTIME_TABLES:
            execute(
                client,
                args,
                args.target_database,
                f"DELETE FROM {table_name(schema, table)} "
                f"WHERE {cluster_where(cluster_ids)}",
                transaction_id=target_tx,
            )

        for schema, table, _scope in COPY_TABLES:
            upsert_rows(client, args, schema, table, copied[f"{schema}.{table}"], target_tx)

        client.commit_transaction(
            resourceArn=args.resource_arn,
            secretArn=args.secret_arn,
            transactionId=target_tx,
        )
        target_tx = None
        rollback(client, args, args.source_database, source_tx)
        source_tx = None
        print(
            f"Ownership data promoted successfully: "
            f"{args.source_database} -> {args.target_database}"
        )
        print("Target runtime was reset; re-enrol active clusters in Production.")
        return 0
    except Exception:
        if target_tx:
            rollback(client, args, args.target_database, target_tx)
        if source_tx:
            rollback(client, args, args.source_database, source_tx)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
