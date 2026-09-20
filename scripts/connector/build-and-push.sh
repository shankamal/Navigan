#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
NAVIGAN_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
source "$NAVIGAN_ROOT/scripts/frontend/common.sh"
require_command docker

PLATFORM_STACK_NAME="${PLATFORM_STACK_NAME:-navigan-ashok-dev}"
REPOSITORY_URI="$(
  aws "${AWS_ARGS[@]}" cloudformation describe-stacks \
    --stack-name "$PLATFORM_STACK_NAME" \
    --query "Stacks[0].Outputs[?OutputKey=='ConnectorRepositoryUri'].OutputValue | [0]" \
    --output text
)"
[[ "$REPOSITORY_URI" == *.dkr.ecr.*.amazonaws.com/* ]]
REPOSITORY_NAME="${REPOSITORY_URI#*/}"
REGISTRY="${REPOSITORY_URI%%/*}"
SOURCE_REVISION="$(
  git -C "$NAVIGAN_ROOT" rev-parse --short HEAD 2>/dev/null ||
    printf 'worktree'
)"
IMAGE_TAG="${IMAGE_TAG:-tools-tunnel-${SOURCE_REVISION}-$(date -u +%Y%m%d%H%M%S)-$RANDOM}"

aws "${AWS_ARGS[@]}" ecr get-login-password |
  docker login --username AWS --password-stdin "$REGISTRY" >&2
docker buildx build --platform linux/amd64 --provenance=false --sbom=false \
  --load --pull --file "$NAVIGAN_ROOT/connector/Dockerfile" \
  --tag "$REPOSITORY_URI:$IMAGE_TAG" "$NAVIGAN_ROOT/connector" >&2
docker push "$REPOSITORY_URI:$IMAGE_TAG" >&2
DIGEST="$(
  aws "${AWS_ARGS[@]}" ecr describe-images \
    --repository-name "$REPOSITORY_NAME" \
    --image-ids "imageTag=$IMAGE_TAG" \
    --query 'imageDetails[0].imageDigest' --output text
)"
[[ "$DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]
printf '%s@%s\n' "$REPOSITORY_URI" "$DIGEST"
