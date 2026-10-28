"""Checksummed SQL bundles and DEV-only, transactional migration execution."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from release_common import DEV_DATABASE, canonical, deterministic_zip, require, sha, unzip


def bundle(source):
    files = {}
    for path in sorted((Path(source) / "database/migrations").glob("*.sql")):
        require(re.fullmatch(r"[0-9]+_[A-Za-z0-9_-]+\.sql", path.name), "Unexpected SQL migration filename.")
        files["database/migrations/" + path.name] = path.read_text().encode()
    require(files, "No database migrations were found.")
    index = {name: sha(data) for name, data in files.items()}
    files["migration-index.json"] = canonical({"format": 1, "checksums": index})
    return deterministic_zip(files)


def migrations(content):
    files = unzip(content, maximum=20 * 1024 * 1024)
    index = json.loads(files.pop("migration-index.json"))
    require(index.get("format") == 1 and isinstance(index.get("checksums"), dict), "Invalid migration bundle.")
    require(set(files) == set(index["checksums"]), "Migration bundle inventory differs.")
    result = {}
    for path, data in files.items():
        require(re.fullmatch(r"database/migrations/[0-9]+_[A-Za-z0-9_-]+\.sql", path)
                and sha(data) == index["checksums"][path], "Migration checksum differs from the bundle.")
        result[Path(path).name] = data.decode()
    return result


def inventory(connection, scripts):
    actual = connection.execute("SELECT current_database()").fetchone()[0]
    require(actual == DEV_DATABASE, "Migration connection is not the DEV database.")
    exists = connection.execute("SELECT to_regclass('platform.schema_migrations')").fetchone()[0]
    applied = dict(connection.execute("SELECT name, checksum FROM platform.schema_migrations").fetchall()) if exists else {}
    require(set(applied) <= set(scripts), "Applied migrations are absent from this release; downgrade/removal rejected.")
    for name, checksum in applied.items():
        require(checksum == hashlib.sha256(scripts[name].encode()).hexdigest(), "An applied migration checksum changed.")
    return sorted(set(scripts) - set(applied))


def inspect(dsn, content):
    import psycopg
    scripts = migrations(content)
    with psycopg.connect(dsn) as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        return inventory(connection, scripts)


def apply(dsn, content, expected_pending):
    import psycopg
    scripts = migrations(content)
    with psycopg.connect(dsn) as connection:
        # Same lock and checksum history as the existing migration runner.
        connection.execute("SELECT pg_advisory_xact_lock(7093314001)")
        pending = inventory(connection, scripts)
        require(pending == expected_pending, "Migration history changed after preparation.")
        if not pending:
            return []
        connection.execute("CREATE SCHEMA IF NOT EXISTS platform")
        connection.execute("CREATE TABLE IF NOT EXISTS platform.schema_migrations "
                           "(name text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())")
        for name in pending:
            connection.execute(scripts[name])
            connection.execute("INSERT INTO platform.schema_migrations(name,checksum) VALUES (%s,%s)",
                               [name, hashlib.sha256(scripts[name].encode()).hexdigest()])
    return pending
