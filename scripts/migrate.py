"""Forward-only checksummed migrations; run with a separate migration-owner login."""

import hashlib
import os
from pathlib import Path
import psycopg


def migrate(connection, directory):
    with connection.transaction():
        connection.execute("SELECT pg_advisory_xact_lock(7093314001)")
        connection.execute("CREATE SCHEMA IF NOT EXISTS platform")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS platform.schema_migrations "
            "(name text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        for path in sorted(Path(directory).glob("*.sql")):
            content = path.read_text()
            checksum = hashlib.sha256(content.encode()).hexdigest()
            previous = connection.execute(
                "SELECT checksum FROM platform.schema_migrations WHERE name=%s", [path.name]
            ).fetchone()
            if previous:
                if previous[0] != checksum:
                    raise RuntimeError(f"Applied migration was modified: {path.name}")
                continue
            connection.execute(content)
            connection.execute(
                "INSERT INTO platform.schema_migrations(name,checksum) VALUES (%s,%s)", [path.name, checksum]
            )
            print(f"Applied {path.name}")


if __name__ == "__main__":
    with psycopg.connect(os.environ["MIGRATION_DATABASE_URL"]) as connection:
        migrate(connection, Path(__file__).resolve().parents[1] / "database/migrations")
