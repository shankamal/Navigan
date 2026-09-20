#!/usr/bin/env bash
set -euo pipefail

ENVIRONMENT="${1:-dev}"
case "$ENVIRONMENT" in
  dev) ;;
  prod)
    if [[ "${NAVIGAN_CONFIRM_PRODUCTION_DEPLOY:-}" != "YES" ]]; then
      echo "Production deployment is blocked."
      echo "Set NAVIGAN_CONFIRM_PRODUCTION_DEPLOY=YES only after Dev validation and approval."
      exit 2
    fi
    ;;
  *)
    echo "Usage: $0 dev|prod"
    exit 2
    ;;
esac

SOURCE_DIR="$(
  cd "$(dirname "${BASH_SOURCE[0]}")/.."
  pwd
)"
AWS_REGION="${AWS_REGION:-ap-south-1}"
EXPECTED_ACCOUNT_ID="${NAVIGAN_EXPECTED_AWS_ACCOUNT_ID:-905418045935}"

for command in aws rsync sam; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Required command is unavailable: $command"
    exit 1
  fi
done

ACCOUNT_ID="$(
  aws sts get-caller-identity \
    --region "$AWS_REGION" \
    --query Account \
    --output text
)"
if [[ "$ACCOUNT_ID" != "$EXPECTED_ACCOUNT_ID" ]]; then
  echo "AWS account check failed."
  echo "Expected: $EXPECTED_ACCOUNT_ID"
  echo "Current:  $ACCOUNT_ID"
  exit 1
fi

DEPLOY_DIR="$(mktemp -d "/var/tmp/navigan-${ENVIRONMENT}-deploy.XXXXXX")"
cleanup() {
  rm -rf -- "$DEPLOY_DIR"
}
trap cleanup EXIT

rsync -a "$SOURCE_DIR/infrastructure/" "$DEPLOY_DIR/infrastructure/"
rsync -a "$SOURCE_DIR/src/" "$DEPLOY_DIR/src/"
cp "$SOURCE_DIR/samconfig.toml" "$DEPLOY_DIR/samconfig.toml"

cd "$DEPLOY_DIR"

echo "Validating Navigan ${ENVIRONMENT} template in $DEPLOY_DIR"
sam validate \
  --lint \
  --config-env "$ENVIRONMENT" \
  --config-file "$DEPLOY_DIR/samconfig.toml"

echo "Building Navigan ${ENVIRONMENT} artifacts"
sam build \
  --config-env "$ENVIRONMENT" \
  --config-file "$DEPLOY_DIR/samconfig.toml"

echo "Deploying Navigan ${ENVIRONMENT}; review the CloudFormation change set carefully."
sam deploy \
  --config-env "$ENVIRONMENT" \
  --config-file "$DEPLOY_DIR/samconfig.toml" \
  --confirm-changeset

