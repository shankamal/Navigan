#!/usr/bin/env bash
# Source from entry-point scripts only. No AWS calls are made by this file.
set -euo pipefail
FRONTEND_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
NAVIGAN_ROOT="$(cd -- "$FRONTEND_SCRIPT_DIR/../.." && pwd)"
require() {
  local name
  for name in "$@"; do
    if [[ -z "${!name:-}" || "${!name}" == *REPLACE* ]]; then
      printf 'Set %s to your actual deployment value.\n' "$name" >&2
      exit 1
    fi
  done
}
require_command() {
  command -v "$1" >/dev/null || { printf 'Required command missing: %s\n' "$1" >&2; exit 1; }
}
require_command aws
require AWS_REGION
AWS_ARGS=(--region "$AWS_REGION")
if [[ -n "${AWS_PROFILE:-}" ]]; then AWS_ARGS+=(--profile "$AWS_PROFILE"); fi
export AWS_PAGER=''
stack_output() {
  aws "${AWS_ARGS[@]}" cloudformation describe-stacks --stack-name "$1" \
    --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue | [0]" --output text
}
validate_public_config() {
  require NEXT_PUBLIC_OIDC_AUTHORITY NEXT_PUBLIC_OIDC_CLIENT_ID NEXT_PUBLIC_APP_URL
  if [[ ! "$NEXT_PUBLIC_APP_URL" =~ ^https://[a-zA-Z0-9.-]+$ || "$NEXT_PUBLIC_APP_URL" == *example.com* ]]; then
    printf 'NEXT_PUBLIC_APP_URL must be your production HTTPS origin without a path or trailing slash.\n' >&2
    exit 1
  fi
  if [[ ! "$NEXT_PUBLIC_OIDC_AUTHORITY" =~ ^https:// ]]; then
    printf 'NEXT_PUBLIC_OIDC_AUTHORITY must use HTTPS.\n' >&2; exit 1
  fi
}
