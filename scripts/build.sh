#!/usr/bin/env bash
# Build only required artifacts. Never deploy or create buckets/repositories.
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
release_python="${NAVIGAN_PYTHON:-$repo_dir/../navigan-deploy-venv/bin/python}"
if [[ ! -x "$release_python" ]]; then release_python=python3; fi
environment="${1:-dev}"
if [[ $# -gt 0 ]]; then shift; fi
exec "$release_python" "$repo_dir/scripts/simple-release.py" build --environment "$environment" "$@"
