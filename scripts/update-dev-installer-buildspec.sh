#!/usr/bin/env bash
set -euo pipefail

ROOT="$(
  cd "$(dirname "${BASH_SOURCE[0]}")/.."
  pwd
)"
AWS_REGION="${AWS_REGION:-ap-south-1}"
EXPECTED_ACCOUNT_ID="${NAVIGAN_EXPECTED_AWS_ACCOUNT_ID:-905418045935}"
PROJECT_NAME="${NAVIGAN_INSTALLER_PROJECT_NAME:-NaviganClusterInstaller}"
BUILDSPEC="$ROOT/infrastructure/bootstrap/aws-customer-v1.2.0/connector-installer-buildspec.yml"

for command in aws jq; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "Required command is unavailable: $command" >&2
    exit 1
  }
done

ACCOUNT_ID="$(
  aws sts get-caller-identity \
    --region "$AWS_REGION" \
    --query Account \
    --output text
)"
if [[ "$ACCOUNT_ID" != "$EXPECTED_ACCOUNT_ID" ]]; then
  echo "AWS account check failed." >&2
  echo "Expected: $EXPECTED_ACCOUNT_ID" >&2
  echo "Current:  $ACCOUNT_ID" >&2
  exit 1
fi

[[ -s "$BUILDSPEC" ]] || {
  echo "Buildspec is unavailable: $BUILDSPEC" >&2
  exit 1
}

WORK_DIR="$(mktemp -d /tmp/navigan-installer-buildspec.XXXXXX)"
cleanup() {
  rm -rf -- "$WORK_DIR"
}
trap cleanup EXIT

aws codebuild batch-get-projects \
  --names "$PROJECT_NAME" \
  --region "$AWS_REGION" \
  --query 'projects[0].source' \
  --output json >"$WORK_DIR/source.json"

jq --rawfile buildspec "$BUILDSPEC" \
  '.buildspec = $buildspec' \
  "$WORK_DIR/source.json" >"$WORK_DIR/source-updated.json"

aws codebuild update-project \
  --name "$PROJECT_NAME" \
  --region "$AWS_REGION" \
  --source "file://$WORK_DIR/source-updated.json" \
  --query 'project.{Name:name}' \
  --output json

echo "Buildspec SHA-256: $(sha256sum "$BUILDSPEC" | cut -d' ' -f1)"
echo "Updated Dev connector installer buildspec: $PROJECT_NAME"
