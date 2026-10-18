#!/usr/bin/env bash
# Safe parameter-only DEV repair after a broad SAM deployment hits an
# unrelated API Gateway route ownership conflict. Does not redeploy code.
set -euo pipefail

if [[ "$#" -ne 2 || "${1:-}" != "--image-tag" || ! "${2:-}" =~ ^dev-[0-9a-f]{12}-[0-9]{14}$ ]]; then
  echo "Usage: AWS_PROFILE=navigan bash $0 --image-tag dev-<commit>-<timestamp>" >&2
  exit 2
fi

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export AWS_PROFILE="${AWS_PROFILE:-navigan}"
export AWS_REGION="${AWS_REGION:-ap-south-1}"
export AWS_PAGER=''
EXPECTED_ACCOUNT="905418045935"
DEV_STACK="navigan-ashok-dev"
ECR_REPOSITORY="navigan/migration-source-connector"
IMAGE_TAG="$2"

for program in aws python3 git; do
  command -v "$program" >/dev/null 2>&1 || {
    echo "Missing required command: $program" >&2
    exit 1
  }
done

if [[ "$AWS_REGION" != "ap-south-1" ]]; then
  echo "This operation is restricted to ap-south-1 DEV." >&2
  exit 1
fi
if [[ "$(git -C "$ROOT" branch --show-current)" != "new_migration_approach_18oct26" ]]; then
  echo "Switch to new_migration_approach_18oct26 first." >&2
  exit 1
fi
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
if [[ "$ACCOUNT" != "$EXPECTED_ACCOUNT" ]]; then
  echo "Wrong AWS account ($ACCOUNT); expected $EXPECTED_ACCOUNT." >&2
  exit 1
fi

TEMP_DIR="$(mktemp -d /var/tmp/navigan-migration-activation.XXXXXX)"
cleanup() {
  if [[ "$TEMP_DIR" == /var/tmp/navigan-migration-activation.* ]]; then
    rm -rf -- "$TEMP_DIR"
  fi
}
trap cleanup EXIT

STACK_STATUS="$(aws cloudformation describe-stacks \
  --stack-name "$DEV_STACK" \
  --query 'Stacks[0].StackStatus' --output text)"
if [[ "$STACK_STATUS" != "UPDATE_COMPLETE" && "$STACK_STATUS" != "UPDATE_ROLLBACK_COMPLETE" ]]; then
  echo "DEV stack is not stable: $STACK_STATUS" >&2
  exit 1
fi

REPOSITORY_URI="${EXPECTED_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPOSITORY}"
DIGEST="$(aws ecr describe-images \
  --repository-name "$ECR_REPOSITORY" \
  --image-ids "imageTag=$IMAGE_TAG" \
  --query 'imageDetails[0].imageDigest' --output text)"
if [[ ! "$DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "The existing ECR image digest is invalid: $DIGEST" >&2
  exit 1
fi

aws cloudformation describe-stacks \
  --stack-name "$DEV_STACK" \
  --query 'Stacks[0].Parameters' --output json > "$TEMP_DIR/parameters.json"
python3 "$ROOT/scripts/source_connector_scoped_change.py" prepare \
  --existing "$TEMP_DIR/parameters.json" \
  --output "$TEMP_DIR/new-parameters.json" \
  --repository "$REPOSITORY_URI" \
  --digest "$DIGEST"

CHANGE_SET_NAME="navigan-migration-only-$(date -u +%Y%m%d%H%M%S)-$$"
echo "Preparing DEV change set using the PREVIOUS deployed template."
echo "No source, Cluster Management, or other capability templates will be repackaged."
CHANGE_SET_ARN="$(aws cloudformation create-change-set \
  --stack-name "$DEV_STACK" \
  --change-set-name "$CHANGE_SET_NAME" \
  --change-set-type UPDATE \
  --use-previous-template \
  --parameters "file://$TEMP_DIR/new-parameters.json" \
  --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND \
  --query Id --output text)"

if ! aws cloudformation wait change-set-create-complete \
  --stack-name "$DEV_STACK" --change-set-name "$CHANGE_SET_ARN"; then
  aws cloudformation describe-change-set \
    --stack-name "$DEV_STACK" --change-set-name "$CHANGE_SET_ARN" \
    --query '{Status:Status,Reason:StatusReason}' --output table
  exit 1
fi

aws cloudformation describe-change-set \
  --stack-name "$DEV_STACK" --change-set-name "$CHANGE_SET_ARN" \
  --output json > "$TEMP_DIR/change-set.json"
python3 "$ROOT/scripts/source_connector_scoped_change.py" verify \
  --changeset "$TEMP_DIR/change-set.json"
aws cloudformation describe-change-set \
  --stack-name "$DEV_STACK" --change-set-name "$CHANGE_SET_ARN" \
  --query 'Changes[].ResourceChange.[Action,LogicalResourceId,ResourceType,Replacement]' \
  --output table

read -r -p 'Execute this MigrationManagement-only DEV change set? [y/N] ' CONFIRM
if [[ "$CONFIRM" != "y" && "$CONFIRM" != "Y" ]]; then
  aws cloudformation delete-change-set \
    --stack-name "$DEV_STACK" --change-set-name "$CHANGE_SET_ARN"
  echo "Change set not executed."
  exit 2
fi

aws cloudformation execute-change-set \
  --stack-name "$DEV_STACK" --change-set-name "$CHANGE_SET_ARN"
aws cloudformation wait stack-update-complete --stack-name "$DEV_STACK"

MIGRATION_STACK="$(aws cloudformation describe-stacks \
  --stack-name "$DEV_STACK" \
  --query 'Stacks[0].Outputs[?OutputKey==`MigrationManagementStackId`].OutputValue | [0]' \
  --output text)"
MIGRATION_FUNCTION="$(aws cloudformation describe-stack-resource \
  --stack-name "$MIGRATION_STACK" --logical-resource-id MigrationFunction \
  --query 'StackResourceDetail.PhysicalResourceId' --output text)"
aws lambda wait function-updated --function-name "$MIGRATION_FUNCTION"
CONFIGURED_REPOSITORY="$(aws lambda get-function-configuration \
  --function-name "$MIGRATION_FUNCTION" \
  --query 'Environment.Variables.MIGRATION_CONNECTOR_IMAGE_REPOSITORY' --output text)"
CONFIGURED_DIGEST="$(aws lambda get-function-configuration \
  --function-name "$MIGRATION_FUNCTION" \
  --query 'Environment.Variables.MIGRATION_CONNECTOR_IMAGE_DIGEST' --output text)"
if [[ "$CONFIGURED_REPOSITORY" != "$REPOSITORY_URI" || "$CONFIGURED_DIGEST" != "$DIGEST" ]]; then
  echo "Migration Lambda artifact configuration verification failed." >&2
  exit 1
fi

python3 "$ROOT/scripts/pin_source_connector_dev.py" \
  --config "$ROOT/samconfig.toml" \
  --repository "$REPOSITORY_URI" \
  --digest "$DIGEST"

echo "DEV MigrationManagement connector artifact configuration verified."
echo "Image: $REPOSITORY_URI@$DIGEST"
echo "Existing Cluster Management routes were not modified."
echo "Note: this changes PARAMETERS only; installer Lambda code was not redeployed."
