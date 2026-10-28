#!/usr/bin/env bash
# Publish the immutable migration source connector and pin it to DEV only.
# Intentionally never deploys production or changes the source Kubernetes cluster.
set -euo pipefail

case "${1:-}" in
  --deploy-dev)
    if [[ "$#" -ne 1 ]]; then
      echo "Usage: AWS_PROFILE=navigan $0 --deploy-dev" >&2
      exit 2
    fi
    ;;
  --resume-dev)
    if [[ "$#" -ne 2 || ! "${2:-}" =~ ^dev-[0-9a-f]{12}-[0-9]{14}$ ]]; then
      echo "Usage: AWS_PROFILE=navigan $0 --resume-dev dev-<commit>-<UTC timestamp>" >&2
      exit 2
    fi
    ;;
  *)
    echo "Usage: AWS_PROFILE=navigan $0 --deploy-dev | --resume-dev <existing-image-tag>" >&2
    exit 2
    ;;
esac

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export AWS_PROFILE="${AWS_PROFILE:-navigan}"
export AWS_REGION="${AWS_REGION:-ap-south-1}"
export AWS_PAGER=''
EXPECTED_ACCOUNT="905418045935"
EXPECTED_REGION="ap-south-1"
DEV_STACK="navigan-ashok-dev"
REPOSITORY_NAME="navigan/migration-source-connector"

for program in git tar python3 aws docker sam; do
  command -v "$program" >/dev/null 2>&1 || {
    echo "Missing required command: $program" >&2
    exit 1
  }
done

if [[ "${AWS_REGION}" != "$EXPECTED_REGION" ]]; then
  echo "Refusing to deploy: this script is restricted to DEV in $EXPECTED_REGION." >&2
  exit 1
fi
if [[ "$(git -C "$ROOT" branch --show-current)" != "new_migration_approach_18oct26" ]]; then
  echo "Switch to new_migration_approach_18oct26 before deploying." >&2
  exit 1
fi

ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
if [[ "$ACCOUNT" != "$EXPECTED_ACCOUNT" ]]; then
  echo "Refusing to deploy to AWS account $ACCOUNT (expected $EXPECTED_ACCOUNT)." >&2
  exit 1
fi
aws cloudformation describe-stacks --stack-name "$DEV_STACK" \
  --query 'Stacks[0].StackId' --output text >/dev/null

RELEASE_DIR="$(mktemp -d /var/tmp/navigan-migration-source-dev.XXXXXX)"
cleanup() {
  if [[ "$RELEASE_DIR" == /var/tmp/navigan-migration-source-dev.* ]]; then
    rm -rf -- "$RELEASE_DIR"
  fi
}
trap cleanup EXIT

# Use committed contents, not the user's generated next-env file or other local edits.
git -C "$ROOT" archive HEAD -- infrastructure src migration_connector samconfig.toml |
  tar -x -C "$RELEASE_DIR"

CONFIG_STACK="$(python3 - "$RELEASE_DIR/samconfig.toml" <<'PY'
import sys
import tomllib
with open(sys.argv[1], 'rb') as handle:
    print(tomllib.load(handle)['dev']['deploy']['parameters']['stack_name'])
PY
)"
if [[ "$CONFIG_STACK" != "$DEV_STACK" ]]; then
  echo "Refusing unexpected DEV stack: $CONFIG_STACK" >&2
  exit 1
fi

echo "AWS account: $ACCOUNT | Region: $AWS_REGION | Stack: $DEV_STACK"
echo "Source commit: $(git -C "$ROOT" rev-parse --short=12 HEAD)"

REPOSITORY_URI=""
if REPOSITORY_URI="$(aws ecr describe-repositories \
  --repository-names "$REPOSITORY_NAME" \
  --query 'repositories[0].repositoryUri' --output text 2>"$RELEASE_DIR/ecr-lookup-error")"; then
  :
elif [[ "$1" == "--deploy-dev" ]] && grep -q 'RepositoryNotFoundException' "$RELEASE_DIR/ecr-lookup-error"; then
  echo "Creating private ECR repository $REPOSITORY_NAME"
  REPOSITORY_URI="$(aws ecr create-repository \
    --repository-name "$REPOSITORY_NAME" \
    --image-tag-mutability IMMUTABLE \
    --encryption-configuration encryptionType=AES256 \
    --query 'repository.repositoryUri' --output text)"
else
  echo "Could not inspect ECR repository; refusing to create it blindly." >&2
  exit 1
fi

EXPECTED_URI="${EXPECTED_ACCOUNT}.dkr.ecr.${EXPECTED_REGION}.amazonaws.com/${REPOSITORY_NAME}"
if [[ "$REPOSITORY_URI" != "$EXPECTED_URI" ]]; then
  echo "Unexpected ECR repository: $REPOSITORY_URI" >&2
  exit 1
fi

if [[ "$1" == "--resume-dev" ]]; then
  TAG="$2"
  echo "Reusing previously published DEV connector $TAG (no image rebuild or push)."
else
  REGISTRY="${REPOSITORY_URI%%/*}"
  TAG="dev-$(git -C "$ROOT" rev-parse --short=12 HEAD)-$(date -u +%Y%m%d%H%M%S)"
  aws ecr get-login-password |
    docker login --username AWS --password-stdin "$REGISTRY" >/dev/null

  echo "Building and publishing immutable source connector $TAG"
  docker buildx build \
    --progress=plain \
    --platform linux/amd64 \
    --provenance=false \
    --sbom=false \
    --pull \
    --push \
    --file "$RELEASE_DIR/migration_connector/Dockerfile" \
    --tag "$REPOSITORY_URI:$TAG" \
    "$RELEASE_DIR"
fi

DIGEST="$(aws ecr describe-images \
  --repository-name "$REPOSITORY_NAME" \
  --image-ids "imageTag=$TAG" \
  --query 'imageDetails[0].imageDigest' --output text)"
if [[ ! "$DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "ECR did not return a valid image digest: $DIGEST" >&2
  exit 1
fi

python3 "$ROOT/scripts/pin_source_connector_dev.py" \
  --config "$RELEASE_DIR/samconfig.toml" \
  --repository "$REPOSITORY_URI" \
  --digest "$DIGEST"

cd "$RELEASE_DIR"
echo "Validating DEV application and building backend packages"
sam validate --config-env dev --config-file "$RELEASE_DIR/samconfig.toml"
# Python dependencies are fetched inside the SAM build container. Give PyPI
# downloads sufficient time on WSL/office networks without silently switching
# away from the Lambda-compatible container build environment.
python3 - "$RELEASE_DIR/build-env.json" <<'PY'
import json
import pathlib
import sys
pathlib.Path(sys.argv[1]).write_text(json.dumps({"Parameters": {
    "PIP_DEFAULT_TIMEOUT": "180",
    "PIP_RETRIES": "10",
    "PIP_DISABLE_PIP_VERSION_CHECK": "1",
}}), encoding="utf-8")
PY
sam build --use-container --config-env dev --config-file "$RELEASE_DIR/samconfig.toml" \
  --container-env-var-file "$RELEASE_DIR/build-env.json"

echo "Review the CloudFormation changeset carefully; only DEV is authorized."
sam deploy --config-env dev --config-file "$RELEASE_DIR/samconfig.toml" \
  --confirm-changeset

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
  echo "DEV Lambda connector configuration verification failed." >&2
  exit 1
fi

# Preserve the verified release pin for subsequent SAM deployments from this
# working copy. Only default/DEV parameters change; production stays intact.
python3 "$ROOT/scripts/pin_source_connector_dev.py" \
  --config "$ROOT/samconfig.toml" \
  --repository "$REPOSITORY_URI" \
  --digest "$DIGEST"

echo "DEV migration source connector artifact configured successfully."
echo "Image: $REPOSITORY_URI@$DIGEST"
echo "The source cluster must have private ECR image-pull access before installation can succeed."
echo "Your local samconfig.toml now pins this DEV digest; review/commit it before a later release."
echo "Reopen the existing migration draft and retry source connection."
