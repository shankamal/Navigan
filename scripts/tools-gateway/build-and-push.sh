#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
NAVIGAN_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
source "$NAVIGAN_ROOT/scripts/frontend/common.sh"
require_command docker
ECR_STACK_NAME="${TOOLS_GATEWAY_ECR_STACK_NAME:-navigan-frontend-ecr}"
REPOSITORY_URI="$(stack_output "$ECR_STACK_NAME" RepositoryUri)"
REPOSITORY_NAME="${REPOSITORY_URI#*/}"
REGISTRY="${REPOSITORY_URI%%/*}"
SOURCE_REVISION="$(
  git -C "$NAVIGAN_ROOT" rev-parse --short HEAD 2>/dev/null ||
    printf 'worktree'
)"
IMAGE_TAG="${IMAGE_TAG:-tools-gateway-${SOURCE_REVISION}-$(date -u +%Y%m%d%H%M%S)-$RANDOM}"
aws "${AWS_ARGS[@]}" ecr get-login-password |
  docker login --username AWS --password-stdin "$REGISTRY" >&2
docker buildx build --platform linux/amd64 --provenance=false --sbom=false \
  --load --pull --file "$NAVIGAN_ROOT/tools-gateway/Dockerfile" \
  --tag "$REPOSITORY_URI:$IMAGE_TAG" "$NAVIGAN_ROOT/tools-gateway" >&2
docker push "$REPOSITORY_URI:$IMAGE_TAG" >&2
DIGEST="$(aws "${AWS_ARGS[@]}" ecr describe-images \
  --repository-name "$REPOSITORY_NAME" --image-ids "imageTag=$IMAGE_TAG" \
  --query 'imageDetails[0].imageDigest' --output text)"
[[ "$DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]
printf '%s@%s\n' "$REPOSITORY_URI" "$DIGEST"
