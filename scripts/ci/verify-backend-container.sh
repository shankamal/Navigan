#!/usr/bin/env bash
# Disposable test database only. No AWS credential/profile mounts.
set -euo pipefail
task_id="navigan-test-$(python -c 'import uuid; print(uuid.uuid4().hex[:12])')"
task_network="${task_id}-network"
task_password="$(python -c 'import secrets; print(secrets.token_hex(16))')"
cleanup() {
  docker rm --force "$task_id" >/dev/null 2>&1 || true
  docker network rm "$task_network" >/dev/null 2>&1 || true
}
trap cleanup EXIT
docker network create "$task_network" >/dev/null
docker run --detach --name "$task_id" --network "$task_network" \
  --env "POSTGRES_PASSWORD=$task_password" --env POSTGRES_DB=navigan_test postgres:16 >/dev/null
for attempt in $(seq 1 60); do
  if docker exec "$task_id" pg_isready -U postgres -d navigan_test >/dev/null 2>&1; then break; fi
  sleep 1
done
docker exec "$task_id" pg_isready -U postgres -d navigan_test
docker run --rm --network "$task_network" \
  --mount "type=bind,src=$PWD,dst=/input,readonly" \
  --env "DATABASE_URL=postgresql://postgres:$task_password@$task_id:5432/navigan_test" \
  --env "MIGRATION_DATABASE_URL=postgresql://postgres:$task_password@$task_id:5432/navigan_test" \
  --env AWS_EC2_METADATA_DISABLED=true --env AWS_DEFAULT_REGION=ap-south-1 \
  python:3.12-slim /bin/sh -c '
    set -eu
    cp -a /input /tmp/source
    cd /tmp/source
    apt-get update -qq && apt-get install --yes --no-install-recommends postgresql-client >/dev/null
    python -m pip install --disable-pip-version-check -e ".[dev]"
    psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -v database_name=navigan_bootstrap_test -f database/bootstrap/create_database.sql
    python scripts/migrate.py
    python scripts/migrate.py
    python -m pytest -q
    python scripts/generate_openapi.py
    python scripts/generate_environment_openapi.py
    cmp docs/openapi.json /input/docs/openapi.json
    cmp docs/environment-openapi.json /input/docs/environment-openapi.json
    python -m ruff check src tests scripts --select E9,F63,F7,F82
  '
