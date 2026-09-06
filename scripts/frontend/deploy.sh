#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
validate_public_config
require IMAGE_URI VPC_ID PUBLIC_SUBNET_IDS PRIVATE_SUBNET_IDS CERTIFICATE_ARN
[[ "$IMAGE_URI" =~ @sha256:[0-9a-f]{64}$ ]] || { printf 'IMAGE_URI must reference an immutable sha256 digest from build-and-push.sh.\n' >&2; exit 1; }
MIN_TASKS="${MIN_TASKS:-2}"
MAX_TASKS="${MAX_TASKS:-4}"
[[ "$MIN_TASKS" =~ ^[0-9]+$ && "$MAX_TASKS" =~ ^[0-9]+$ ]] || { printf 'Task counts must be integers.\n' >&2; exit 1; }
(( MIN_TASKS >= 1 && MAX_TASKS >= MIN_TASKS && MAX_TASKS <= 20 )) || { printf 'Require 1 <= MIN_TASKS <= MAX_TASKS <= 20.\n' >&2; exit 1; }
FRONTEND_STACK_NAME="${FRONTEND_STACK_NAME:-navigan-frontend}"
ECR_STACK_NAME="${ECR_STACK_NAME:-navigan-frontend-ecr}"
REPOSITORY_URI="$(stack_output "$ECR_STACK_NAME" RepositoryUri)"
[[ "${IMAGE_URI%@*}" == "$REPOSITORY_URI" ]] || { printf 'IMAGE_URI must belong to the configured ECR stack.\n' >&2; exit 1; }
REPOSITORY_ARN="$(stack_output "$ECR_STACK_NAME" RepositoryArn)"
FRONTEND_HOST="${NEXT_PUBLIC_APP_URL#https://}"
aws "${AWS_ARGS[@]}" cloudformation deploy \
  --stack-name "$FRONTEND_STACK_NAME" --template-file "$NAVIGAN_ROOT/infrastructure/frontend/service.yaml" \
  --capabilities CAPABILITY_IAM --no-fail-on-empty-changeset \
  --parameter-overrides \
    "ImageUri=$IMAGE_URI" "RepositoryArn=$REPOSITORY_ARN" \
    "VpcId=$VPC_ID" "PublicSubnetIds=$PUBLIC_SUBNET_IDS" "PrivateSubnetIds=$PRIVATE_SUBNET_IDS" \
    "CertificateArn=$CERTIFICATE_ARN" "FrontendHostname=$FRONTEND_HOST" \
    "HostedZoneId=${HOSTED_ZONE_ID:-}" "AllowedIngressCidr=${ALLOWED_INGRESS_CIDR:-0.0.0.0/0}" \
    "MinTasks=${MIN_TASKS:-2}" "MaxTasks=${MAX_TASKS:-4}" \
    "ApiOrigin=${NAVIGAN_API_ORIGIN:-https://q0i8bcekw1.execute-api.ap-south-1.amazonaws.com}" \
    "ApiBasePath=${NAVIGAN_API_BASE_PATH:-/v1/api/v1}"
CLUSTER="$(stack_output "$FRONTEND_STACK_NAME" ClusterName)"
SERVICE="$(stack_output "$FRONTEND_STACK_NAME" ServiceName)"
aws "${AWS_ARGS[@]}" ecs wait services-stable --cluster "$CLUSTER" --services "$SERVICE"
# Circuit-breaker rollback can leave a stable service running the previous image. Check it explicitly.
TASK_DEFINITION="$(aws "${AWS_ARGS[@]}" ecs describe-services --cluster "$CLUSTER" --services "$SERVICE" --query 'services[0].taskDefinition' --output text)"
DEPLOYED_IMAGE="$(aws "${AWS_ARGS[@]}" ecs describe-task-definition --task-definition "$TASK_DEFINITION" --query 'taskDefinition.containerDefinitions[?name==`frontend`].image | [0]' --output text)"
[[ "$DEPLOYED_IMAGE" == "$IMAGE_URI" ]] || { printf 'Service is stable but is not running the requested image (possible rollback).\n' >&2; exit 1; }
aws "${AWS_ARGS[@]}" cloudformation describe-stacks --stack-name "$FRONTEND_STACK_NAME" --query 'Stacks[0].Outputs' --output table
printf '\nOpen %s/login. Configure the public SRP app client and V2 token trigger as documented in docs/custom-login.md.\n' "$NEXT_PUBLIC_APP_URL"
