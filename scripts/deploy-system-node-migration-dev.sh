#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export AWS_PROFILE="${AWS_PROFILE:-navigan}"
export AWS_REGION="${AWS_REGION:-ap-south-1}"

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
REPOSITORY="navigan-terraform-runner"
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
IMAGE="${REGISTRY}/${REPOSITORY}"
TAG="system-migration-$(date -u +%Y%m%d%H%M%S)"

for command in aws docker sam python3; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "$command is required." >&2
    exit 1
  }
done

aws ecr describe-repositories \
  --repository-names "$REPOSITORY" \
  --region "$AWS_REGION" >/dev/null

aws ecr get-login-password --region "$AWS_REGION" |
  docker login --username AWS --password-stdin "$REGISTRY"

docker build \
  --file provisioning/runner/Dockerfile \
  --tag "${IMAGE}:${TAG}" \
  .

docker push "${IMAGE}:${TAG}"

DIGEST="$(
  aws ecr describe-images \
    --repository-name "$REPOSITORY" \
    --image-ids "imageTag=${TAG}" \
    --region "$AWS_REGION" \
    --query 'imageDetails[0].imageDigest' \
    --output text
)"

case "$DIGEST" in
  sha256:????????????????????????????????????????????????????????????????) ;;
  *)
    echo "The pushed image digest is invalid: $DIGEST" >&2
    exit 1
    ;;
esac

RUNNER_URI="${IMAGE}@${DIGEST}"
export NAVIGAN_DEV_RUNNER_URI="$RUNNER_URI"

python3 - <<'PYTHON'
import os
import pathlib
import re

path = pathlib.Path("samconfig.toml")
text = path.read_text(encoding="utf-8")
before_prod, marker, prod = text.partition("[prod.validate.parameters]")
if not marker:
    raise SystemExit("The production SAM profile boundary was not found.")

uri = os.environ["NAVIGAN_DEV_RUNNER_URI"]
pattern = r'TerraformRunnerImageUri=\\"[^"]+\\"'
updated, count = re.subn(
    pattern,
    'TerraformRunnerImageUri=\\"' + uri + '\\"',
    before_prod,
)
if count != 2:
    raise SystemExit(
        f"Expected to update the default and dev runner URIs, updated {count}."
    )

temporary = path.with_suffix(".toml.tmp")
temporary.write_text(updated + marker + prod, encoding="utf-8")
temporary.replace(path)
PYTHON

unset NAVIGAN_DEV_RUNNER_URI

echo "Pinned dev Terraform runner: $RUNNER_URI"
echo "Production SAM configuration was not changed."

sam validate \
  --config-env dev \
  --config-file "$ROOT/samconfig.toml"

sam build \
  --config-env dev \
  --config-file "$ROOT/samconfig.toml"

sam deploy \
  --config-env dev \
  --config-file "$ROOT/samconfig.toml" \
  --no-confirm-changeset

echo "Dev system-node migration backend deployed successfully."
