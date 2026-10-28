#!/usr/bin/env bash
# Capture-only until live ownership and the release baseline are reconciled.
set -euo pipefail
ENVIRONMENT="${1:-dev}"
if [[ $# -gt 0 ]]; then shift; fi
case "$ENVIRONMENT" in
  dev|prod|both) ;;
  *) echo "Usage: $0 dev|prod|both [reconcile-sam.py capture options]" >&2; exit 2 ;;
esac
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
echo "This entry point captures reconciliation evidence; it does not deploy SAM."
exec "${PYTHON:-python3}" "$SOURCE_DIR/scripts/reconcile-sam.py" --capture --environment "$ENVIRONMENT" "$@"
