#!/usr/bin/env bash
# Disposable test database only. No AWS credential/profile mounts.
set -euo pipefail
host_python="${NAVIGAN_PYTHON:-python3}"
if ! command -v "$host_python" >/dev/null 2>&1; then
  echo "Host Python 3 not found. Set NAVIGAN_PYTHON to an executable Python 3 interpreter." >&2
  exit 1
fi
task_id="navigan-test-$("$host_python" -c 'import uuid; print(uuid.uuid4().hex[:12])')"
task_network="${task_id}-network"
task_password="$("$host_python" -c 'import secrets; print(secrets.token_hex(16))')"
cleanup() {
  docker rm --force "$task_id" >/dev/null 2>&1 || true
  docker network rm "$task_network" >/dev/null 2>&1 || true
}
trap cleanup EXIT
docker network create "$task_network" >/dev/null
docker run --detach --name "$task_id" --network "$task_network" \
  --env "POSTGRES_PASSWORD=$task_password" --env POSTGRES_DB=navigan_test postgres:16 >/dev/null
# The image's temporary initialization server accepts Unix sockets only.
# Wait for TCP so migrations cannot race that server's shutdown/restart.
task_ready=false
for attempt in $(seq 1 120); do
  if docker exec "$task_id" pg_isready -h 127.0.0.1 -p 5432 -U postgres -d navigan_test >/dev/null 2>&1; then
    task_ready=true
    break
  fi
  sleep 1
done
if [[ "$task_ready" != true ]]; then
  echo "Temporary PostgreSQL did not become TCP-ready within 120 seconds." >&2
  docker logs --tail 80 "$task_id" >&2 || true
  exit 1
fi
echo "Temporary PostgreSQL is TCP-ready; starting backend checks."
docker run --rm --network "$task_network" \
  --mount "type=bind,src=$PWD,dst=/input,readonly" \
  --env "DATABASE_URL=postgresql://postgres:$task_password@$task_id:5432/navigan_test" \
  --env "MIGRATION_DATABASE_URL=postgresql://postgres:$task_password@$task_id:5432/navigan_test" \
  --env AWS_EC2_METADATA_DISABLED=true --env AWS_DEFAULT_REGION=ap-south-1 \
  python:3.12-slim /bin/sh -c '
    set -eu
    cp -a /input /tmp/source
    cd /tmp/source
    apt-get update -qq && apt-get install --yes --no-install-recommends git postgresql-client >/dev/null
    python -m pip install --disable-pip-version-check -e ".[dev]"
    psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -v database_name=navigan_bootstrap_test -f database/bootstrap/create_database.sql
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
