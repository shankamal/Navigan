#!/usr/bin/env bash
# stdout is the immutable image URI; progress goes to stderr for IMAGE_URI=$(...) usage.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
require_command docker
validate_public_config
docker info >/dev/null
docker buildx version >/dev/null
ECR_STACK_NAME="${ECR_STACK_NAME:-navigan-frontend-ecr}"
ECR_REPOSITORY_NAME="${ECR_REPOSITORY_NAME:-navigan/frontend}"
aws "${AWS_ARGS[@]}" sts get-caller-identity --query Account --output text >&2
aws "${AWS_ARGS[@]}" cloudformation deploy \
  --stack-name "$ECR_STACK_NAME" --template-file "$NAVIGAN_ROOT/infrastructure/frontend/ecr.yaml" \
  --parameter-overrides "RepositoryName=$ECR_REPOSITORY_NAME" --no-fail-on-empty-changeset >&2
REPOSITORY_URI="$(stack_output "$ECR_STACK_NAME" RepositoryUri)"
[[ "$REPOSITORY_URI" != None && -n "$REPOSITORY_URI" ]] || { printf 'ECR stack output missing.\n' >&2; exit 1; }
REGISTRY="${REPOSITORY_URI%%/*}"
IMAGE_TAG="${IMAGE_TAG:-$(git -C "$NAVIGAN_ROOT" rev-parse --short HEAD)-$(date -u +%Y%m%d%H%M%S)-$RANDOM}"
[[ "$IMAGE_TAG" =~ ^[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,127}$ ]] || { printf 'Invalid IMAGE_TAG.\n' >&2; exit 1; }
aws "${AWS_ARGS[@]}" ecr get-login-password | docker login --username AWS --password-stdin "$REGISTRY" >&2
BUILD_ARGS=()
for name in NEXT_PUBLIC_OIDC_AUTHORITY NEXT_PUBLIC_OIDC_CLIENT_ID NEXT_PUBLIC_APP_URL NEXT_PUBLIC_OIDC_SCOPE NEXT_PUBLIC_COGNITO_DOMAIN NEXT_PUBLIC_CORPORATE_LOGO_URL; do
  if [[ -v "$name" ]]; then BUILD_ARGS+=(--build-arg "$name=${!name}"); fi
done
docker buildx build --platform linux/amd64 --load --pull \
  --file "$NAVIGAN_ROOT/frontend/Dockerfile" --tag "$REPOSITORY_URI:$IMAGE_TAG" \
  "${BUILD_ARGS[@]}" "$NAVIGAN_ROOT/frontend" >&2
docker push "$REPOSITORY_URI:$IMAGE_TAG" >&2
DIGEST="$(aws "${AWS_ARGS[@]}" ecr describe-images --repository-name "$ECR_REPOSITORY_NAME" \
  --image-ids "imageTag=$IMAGE_TAG" --query 'imageDetails[0].imageDigest' --output text)"
[[ "$DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]] || { printf 'Could not resolve pushed image digest.\n' >&2; exit 1; }
printf '%s@%s\n' "$REPOSITORY_URI" "$DIGEST"
