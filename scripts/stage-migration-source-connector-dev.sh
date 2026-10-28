#!/usr/bin/env bash
# Stage a DEV migration-only nested CloudFormation change set for REVIEW.
# This script deliberately NEVER executes the change set or updates an active stack.
set -euo pipefail

if [[ "$#" -ne 2 || "${1:-}" != "--image-tag" || ! "${2:-}" =~ ^dev-[0-9a-f]{12}-[0-9]{14}$ ]]; then
  echo "Usage: AWS_PROFILE=navigan bash $0 --image-tag dev-<commit>-<timestamp>" >&2
  exit 2
fi

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export AWS_PROFILE="${AWS_PROFILE:-navigan}"
export AWS_REGION="${AWS_REGION:-ap-south-1}"
export AWS_PAGER=''
ACCOUNT="905418045935"
DEV_STACK="navigan-ashok-dev"
ECR_REPO="navigan/migration-source-connector"
DELIVERY_ROLE="arn:aws:iam::905418045935:role/NaviganSourceConnectorDeliveryRole"
BUCKET="aws-sam-cli-managed-default-samclisourcebucket-xj9yzigmdgri"
IMAGE_TAG="$2"

for executable in aws sam docker git tar python3; do
  command -v "$executable" >/dev/null || { echo "Missing $executable" >&2; exit 1; }
done
if [[ "$AWS_REGION" != "ap-south-1" || "$(aws sts get-caller-identity --query Account --output text)" != "$ACCOUNT" ]]; then
  echo "Refusing non-DEV AWS account or region." >&2
  exit 1
fi
if [[ "$(git -C "$ROOT" branch --show-current)" != "new_migration_approach_18oct26" ]]; then
  echo "Wrong git branch for DEV release." >&2
  exit 1
fi
REMOTE_HEAD="$(git -C "$ROOT" ls-remote --exit-code origin refs/heads/new_migration_approach_18oct26 | awk '{print $1}')"
if [[ ! "$REMOTE_HEAD" =~ ^[0-9a-f]{40}$ || "$(git -C "$ROOT" rev-parse HEAD)" != "$REMOTE_HEAD" ]]; then
  echo "Pull the latest approved DEV branch before preparing the release." >&2
  exit 1
fi

STACK_STATUS="$(aws cloudformation describe-stacks --stack-name "$DEV_STACK" --query 'Stacks[0].StackStatus' --output text)"
if [[ "$STACK_STATUS" != "UPDATE_COMPLETE" && "$STACK_STATUS" != "UPDATE_ROLLBACK_COMPLETE" ]]; then
  echo "DEV stack is not stable: $STACK_STATUS" >&2
  exit 1
fi

REPOSITORY="${ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}"
DIGEST="$(aws ecr describe-images --repository-name "$ECR_REPO" --image-ids "imageTag=$IMAGE_TAG" --query 'imageDetails[0].imageDigest' --output text)"
if [[ ! "$DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "Unable to verify immutable ECR image digest." >&2
  exit 1
fi
ROLE_ARN="$(aws iam get-role --role-name NaviganSourceConnectorDeliveryRole --query Role.Arn --output text)"
if [[ "$ROLE_ARN" != "$DELIVERY_ROLE" ]]; then
  echo "The explicitly approved delivery role is unavailable." >&2
  exit 1
fi

TEMP_DIR="$(mktemp -d /var/tmp/navigan-migration-stage.XXXXXX)"
cleanup() {
  if [[ "$TEMP_DIR" == /var/tmp/navigan-migration-stage.* ]]; then
    rm -rf -- "$TEMP_DIR"
  fi
}
trap cleanup EXIT

COMMIT="$(git -C "$ROOT" rev-parse --short=12 HEAD)"
git -C "$ROOT" archive HEAD -- infrastructure/modules/migration-management src |
  tar -x -C "$TEMP_DIR"

echo "Building only the migration-management Lambda package from $COMMIT."
python3 - "$TEMP_DIR/build-env.json" <<'PY'
import json
import pathlib
import sys
pathlib.Path(sys.argv[1]).write_text(json.dumps({"Parameters": {
    "PIP_DEFAULT_TIMEOUT": "180", "PIP_RETRIES": "10",
    "PIP_DISABLE_PIP_VERSION_CHECK": "1"
}}), encoding="utf-8")
PY
(
  cd "$TEMP_DIR"
  sam build --use-container --template-file infrastructure/modules/migration-management/template.yaml \
    --container-env-var-file "$TEMP_DIR/build-env.json"
)

sam package --template-file "$TEMP_DIR/.aws-sam/build/template.yaml" \
  --s3-bucket "$BUCKET" --s3-prefix "$DEV_STACK/migration-only/$COMMIT" \
  --output-template-file "$TEMP_DIR/migration-packaged.yaml"

# Packaging requires the new child template to declare the three parameters.
for parameter in MigrationConnectorImageRepository MigrationConnectorImageDigest SourceConnectorDeliveryRoleArn; do
  if ! grep -q "$parameter" "$TEMP_DIR/migration-packaged.yaml"; then
    echo "Packaged migration template lacks $parameter" >&2
    exit 1
  fi
done

OBJECT_KEY="$DEV_STACK/migration-only/$COMMIT/migration-template-$(date -u +%Y%m%d%H%M%S)-$$.yaml"
aws s3 cp "$TEMP_DIR/migration-packaged.yaml" "s3://$BUCKET/$OBJECT_KEY" >/dev/null
CHILD_URL="https://s3.${AWS_REGION}.amazonaws.com/${BUCKET}/${OBJECT_KEY}"

aws cloudformation get-template --stack-name "$DEV_STACK" --template-stage Processed \
  --output json > "$TEMP_DIR/deployed-root.json"
python3 "$ROOT/scripts/patch_migration_nested_template.py" \
  --response "$TEMP_DIR/deployed-root.json" \
  --output "$TEMP_DIR/migration-only-root.json" \
  --new-url "$CHILD_URL" --repository "$REPOSITORY" \
  --digest "$DIGEST" --delivery-role "$DELIVERY_ROLE"

aws cloudformation describe-stacks --stack-name "$DEV_STACK" \
  --query 'Stacks[0].Parameters' --output json > "$TEMP_DIR/current-parameters.json"
python3 "$ROOT/scripts/source_connector_scoped_change.py" preserve \
  --existing "$TEMP_DIR/current-parameters.json" \
  --output "$TEMP_DIR/preserved-parameters.json"

CHANGE_SET_NAME="navigan-migration-stage-$(date -u +%Y%m%d%H%M%S)-$$"
echo "Creating a root DEV change set for REVIEW ONLY; nothing will be executed."
CHANGE_SET_ARN="$(aws cloudformation create-change-set \
  --stack-name "$DEV_STACK" --change-set-name "$CHANGE_SET_NAME" \
  --change-set-type UPDATE --include-nested-stacks \
  --template-body "file://$TEMP_DIR/migration-only-root.json" \
  --parameters "file://$TEMP_DIR/preserved-parameters.json" \
  --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND \
  --query Id --output text)"

if ! aws cloudformation wait change-set-create-complete \
  --stack-name "$DEV_STACK" --change-set-name "$CHANGE_SET_ARN"; then
  aws cloudformation describe-change-set --stack-name "$DEV_STACK" \
    --change-set-name "$CHANGE_SET_ARN" --query '{Status:Status,Reason:StatusReason}' --output table
  exit 1
fi

aws cloudformation describe-change-set --stack-name "$DEV_STACK" \
  --change-set-name "$CHANGE_SET_ARN" --output json > "$TEMP_DIR/root-changes.json"
python3 "$ROOT/scripts/source_connector_scoped_change.py" verify \
  --changeset "$TEMP_DIR/root-changes.json"

CHILD_CHANGE_SET="$(aws cloudformation describe-change-set --stack-name "$DEV_STACK" \
  --change-set-name "$CHANGE_SET_ARN" \
  --query "Changes[?ResourceChange.LogicalResourceId=='MigrationManagement'].ResourceChange.ChangeSetId | [0]" \
  --output text)"
if [[ "$CHILD_CHANGE_SET" != arn:aws:cloudformation:ap-south-1:905418045935:changeSet/* ]]; then
  echo "Cannot inspect nested migration change set. Do not execute." >&2
  exit 1
fi

echo "Root change set (must contain ONLY MigrationManagement):"
aws cloudformation describe-change-set --stack-name "$DEV_STACK" \
  --change-set-name "$CHANGE_SET_ARN" \
  --query 'Changes[].ResourceChange.[Action,LogicalResourceId,ResourceType,Replacement]' --output table

echo "Nested MigrationManagement changes (review every resource):"
aws cloudformation describe-change-set --change-set-name "$CHILD_CHANGE_SET" \
  --query 'Changes[].ResourceChange.[Action,LogicalResourceId,ResourceType,Replacement]' --output table

echo "CHANGE_SET_FOR_REVIEW=$CHANGE_SET_ARN"
echo "CHILD_CHANGE_SET_FOR_REVIEW=$CHILD_CHANGE_SET"
echo "PREVIEW ONLY. The running DEV stack is unchanged. Do NOT execute before review."
