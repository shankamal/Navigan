"""Short-lived TLS connections through RDS Proxy; one transaction per invocation."""

import json
import os
import time
from contextlib import contextmanager
from .diagnostics import phase

_cache = {}


def connect(secret_env="DB_SECRET_ARN"):
    with phase("database_driver_import"):
        import psycopg
        from psycopg.rows import dict_row

    class DiagnosticCursor(psycopg.Cursor):
        def execute(self, query, params=None, **kwargs):
            with phase("database_query"):
                return super().execute(query, params, **kwargs)

    # Local integration tests only. Never allow a plaintext DSN override in Lambda.
    if os.getenv("DATABASE_URL") and not os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row, cursor_factory=DiagnosticCursor)
    with phase("aws_sdk_import"):
        import boto3
        from botocore.config import Config

    arn = os.environ[secret_env]
    cached = _cache.get(arn)
    if not cached or cached[0] < time.monotonic():
        with phase("secrets_client", secretVariable=secret_env):
            client = boto3.client("secretsmanager", config=Config(
                connect_timeout=3, read_timeout=3,
                retries={"mode": "standard", "total_max_attempts": 1}))
        with phase("secret_fetch", secretVariable=secret_env):
            value = client.get_secret_value(SecretId=arn)
        with phase("secret_decode"):
            cached = (time.monotonic() + 60, json.loads(value["SecretString"]))
        _cache[arn] = cached
    secret = cached[1]
    try:
        with phase("database_connect"):
            return psycopg.connect(
                host=os.environ["DB_PROXY_HOST"],
                port=int(os.getenv("DB_PORT", "5432")),
                dbname=os.environ["DB_NAME"],
                user=secret["username"],
                password=secret["password"],
                sslmode="verify-full",
                sslrootcert=os.environ["DB_CA_BUNDLE"],
                connect_timeout=5,
                row_factory=dict_row,
                cursor_factory=DiagnosticCursor,
            )
    except psycopg.OperationalError:
        _cache.pop(arn, None)  # Fetch rotated credentials on next invocation; no ambiguous write retries.
        raise


@contextmanager
def transaction(secret_env="DB_SECRET_ARN"):
    connection = connect(secret_env)
    with phase("database_transaction"):
        with connection:
            connection.execute("SET LOCAL statement_timeout = '8s'")
            connection.execute("SET LOCAL lock_timeout = '5s'")
            yield connection
