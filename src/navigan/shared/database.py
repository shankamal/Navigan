"""Short-lived TLS connections through RDS Proxy; one transaction per invocation."""

import json
import os
import time
from contextlib import contextmanager

_cache = {}


def connect(secret_env="DB_SECRET_ARN"):
    import psycopg
    from psycopg.rows import dict_row

    # Local integration tests only. Never allow a plaintext DSN override in Lambda.
    if os.getenv("DATABASE_URL") and not os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)
    import boto3

    arn = os.environ[secret_env]
    cached = _cache.get(arn)
    if not cached or cached[0] < time.monotonic():
        value = boto3.client("secretsmanager").get_secret_value(SecretId=arn)
        cached = (time.monotonic() + 60, json.loads(value["SecretString"]))
        _cache[arn] = cached
    secret = cached[1]
    try:
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
        )
    except psycopg.OperationalError:
        _cache.pop(arn, None)  # Fetch rotated credentials on next invocation; no ambiguous write retries.
        raise


@contextmanager
def transaction(secret_env="DB_SECRET_ARN"):
    with connect(secret_env) as connection:
        connection.execute("SET LOCAL statement_timeout = '8s'")
        connection.execute("SET LOCAL lock_timeout = '5s'")
        yield connection
