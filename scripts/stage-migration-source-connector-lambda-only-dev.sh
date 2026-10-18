#!/usr/bin/env bash
# Review-only DEV CloudFormation stage; reuses a completed Lambda package.
# Does not execute any change set or modify an active CloudFormation stack.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export AWS_PROFILE="${AWS_PROFILE:-navigan}"
export AWS_REGION="${AWS_REGION:-ap-south-1}"
export AWS_PAGER=''

ACCOUNT=905418045935
STACK=navigan-ashok-dev
BUCKET=aws-sam-cli-managed-default-samclisourcebucket-xj9yzigmdgri
REPOSITORY="${ACCOUNT}.dkr.ecr.ap-south-1.amazonaws.com/navigan/migration-source-connector"
ECR_NAME=navigan/migration-source-connector
TAG=dev-8aec3981a2e1-20261018130607
CODE_KEY=navigan-ashok-dev/migration-only/e62378a0e5f1/84a16c71921d98b59ee525f969030b27
EXPECTED_SOURCE_COMMIT=e62378a0e5f18cc18e604f49705b0c1dd8fb9b49

for tool in aws git python3; do
  command -v "$tool" >/dev/null || { echo "Missing $tool" >&2; exit 1; }
done

if [[ "$AWS_REGION" != ap-south-1 || "$(aws sts get-caller-identity --query Account --output text)" != "$ACCOUNT" ]]; then
  echo "Refusing unexpected AWS account or region." >&2
  exit 1
fi
if [[ "$(git -C "$ROOT" branch --show-current)" != new_migration_approach_18oct26 ]]; then
  echo "Wrong migration development branch." >&2
  exit 1
fi
REMOTE="$(git -C "$ROOT" ls-remote --exit-code origin refs/heads/new_migration_approach_18oct26 | awk '{print $1}')"
if [[ "$(git -C "$ROOT" rev-parse HEAD)" != "$REMOTE" ]]; then
  echo "Pull the latest migration DEV branch." >&2
  exit 1
fi

# No source-code change is allowed since the immutable Lambda artifact was built.
if [[ "$(git -C "$ROOT" rev-parse HEAD:src)" != "$(git -C "$ROOT" rev-parse "$EXPECTED_SOURCE_COMMIT:src")" ]]; then
  echo "Lambda source has changed since the staged artifact. Rebuild with review." >&2
  exit 1
fi

STATUS="$(aws cloudformation describe-stacks --stack-name "$STACK" --query 'Stacks[0].StackStatus' --output text)"
if [[ "$STATUS" != UPDATE_COMPLETE && "$STATUS" != UPDATE_ROLLBACK_COMPLETE ]]; then
  echo "DEV root stack not stable: $STATUS" >&2
  exit 1
fi

SIZE="$(aws s3api head-object --bucket "$BUCKET" --key "$CODE_KEY" --query ContentLength --output text)"
if [[ "$SIZE" != 27752246 ]]; then
  echo "Cannot verify uploaded 27.7 MB Lambda artifact." >&2
  exit 1
fi

DIGEST="$(aws ecr describe-images --repository-name "$ECR_NAME" --image-ids "imageTag=$TAG" --query 'imageDetails[0].imageDigest' --output text)"
if [[ ! "$DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "Immutable source connector digest is missing." >&2
  exit 1
fi

CHILD_STACK="$(aws cloudformation describe-stacks --stack-name "$STACK" \
  --query 'Stacks[0].Outputs[?OutputKey==`MigrationManagementStackId`].OutputValue | [0]' --output text)"
if [[ "$CHILD_STACK" != arn:aws:cloudformation:ap-south-1:905418045935:stack/* ]]; then
  echo "Cannot verify deployed migration nested stack." >&2
  exit 1
fi
API_ID="$(aws cloudformation describe-stacks --stack-name "$CHILD_STACK" \
  --query 'Stacks[0].Parameters[?ParameterKey==`ApiId`].ParameterValue | [0]' --output text)"
if [[ "$API_ID" == None || -z "$API_ID" ]]; then
  echo "Cannot resolve existing API ID." >&2
  exit 1
fi

EXISTING_ROUTE="$(aws apigatewayv2 get-routes --api-id "$API_ID" \
  --query 'Items[?RouteKey==`POST /api/v1/source-clusters/{sourceClusterId}/install`].RouteId | [0]' --output text)"
if [[ "$EXISTING_ROUTE" != None && -n "$EXISTING_ROUTE" ]]; then
  echo "Install API route already exists ($EXISTING_ROUTE). Stop to reconcile ownership." >&2
  exit 1
fi

TMP="$(mktemp -d /var/tmp/navigan-lambda-stage.XXXXXX)"
cleanup() { if [[ "$TMP" == /var/tmp/navigan-lambda-stage.* ]]; then rm -rf -- "$TMP"; fi; }
trap cleanup EXIT

aws cloudformation get-template --stack-name "$STACK" --template-stage Processed \
  --output json > "$TMP/root.json"
aws cloudformation get-template --stack-name "$CHILD_STACK" --template-stage Processed \
  --output json > "$TMP/child.json"

KEY="navigan-ashok-dev/migration-only/isolated-child-$(date -u +%Y%m%d%H%M%S)-$$.json"
URL="https://s3.ap-south-1.amazonaws.com/${BUCKET}/${KEY}"

python3 "$ROOT/scripts/scoped_migration_lambda_patch.py" \
  --root "$TMP/root.json" --child "$TMP/child.json" \
  --root-output "$TMP/root-updated.json" --child-output "$TMP/child-updated.json" \
  --template-url "$URL" --code-key "$CODE_KEY" --repository "$REPOSITORY" \
  --digest "$DIGEST" --api-id "$API_ID"

aws s3 cp "$TMP/child-updated.json" "s3://$BUCKET/$KEY" >/dev/null
aws cloudformation describe-stacks --stack-name "$STACK" --query 'Stacks[0].Parameters' \
  --output json > "$TMP/parameters.json"
python3 "$ROOT/scripts/source_connector_scoped_change.py" preserve \
  --existing "$TMP/parameters.json" --output "$TMP/preserved.json"

NAME="navigan-migration-lambda-only-$(date -u +%Y%m%d%H%M%S)-$$"
echo "Creating review-only change set; the deployed stack WILL NOT be updated."
ARN="$(aws cloudformation create-change-set --stack-name "$STACK" \
  --change-set-name "$NAME" --change-set-type UPDATE --include-nested-stacks \
  --template-body "file://$TMP/root-updated.json" \
  --parameters "file://$TMP/preserved.json" \
  --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND \
  --query Id --output text)"

if ! aws cloudformation wait change-set-create-complete --stack-name "$STACK" --change-set-name "$ARN"; then
  aws cloudformation describe-change-set --stack-name "$STACK" --change-set-name "$ARN" \
    --query '{Status:Status,Reason:StatusReason}' --output table
  exit 1
fi

aws cloudformation describe-change-set --stack-name "$STACK" --change-set-name "$ARN" \
  --output json > "$TMP/root-change.json"
python3 "$ROOT/scripts/source_connector_scoped_change.py" verify --changeset "$TMP/root-change.json"

CHILD_CHANGE="$(aws cloudformation describe-change-set --stack-name "$STACK" --change-set-name "$ARN" \
  --query "Changes[?ResourceChange.LogicalResourceId=='MigrationManagement'].ResourceChange.ChangeSetId | [0]" \
  --output text)"
if [[ "$CHILD_CHANGE" != arn:aws:cloudformation:ap-south-1:905418045935:changeSet/* ]]; then
  echo "Missing nested change set. Never execute without full review." >&2
  exit 1
fi
aws cloudformation describe-change-set --change-set-name "$CHILD_CHANGE" \
  --output json > "$TMP/child-change.json"
python3 "$ROOT/scripts/scoped_migration_lambda_patch.py" --verify-changeset "$TMP/child-change.json"

echo "Root changes:"
aws cloudformation describe-change-set --stack-name "$STACK" --change-set-name "$ARN" \
  --query 'Changes[].ResourceChange.[Action,LogicalResourceId,ResourceType,Replacement]' --output table
echo "Nested Migration changes:"
aws cloudformation describe-change-set --change-set-name "$CHILD_CHANGE" \
  --query 'Changes[].ResourceChange.[Action,LogicalResourceId,ResourceType,Replacement]' --output table
echo "CHANGE_SET_FOR_REVIEW=$ARN"
echo "Preview complete. Do NOT execute until explicitly reviewed."
