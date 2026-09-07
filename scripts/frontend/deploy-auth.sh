#!/usr/bin/env bash
# Creates the token Lambda and invoke permission; never overwrites the existing user pool.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
require NEXT_PUBLIC_OIDC_CLIENT_ID
USER_POOL_ID="${COGNITO_USER_POOL_ID:-ap-south-1_GtWAW9Owz}"
aws "${AWS_ARGS[@]}" cloudformation deploy \
  --stack-name "${AUTH_STACK_NAME:-navigan-auth}" \
  --template-file "$NAVIGAN_ROOT/infrastructure/auth/template.yaml" \
  --capabilities CAPABILITY_IAM --no-fail-on-empty-changeset \
  --parameter-overrides "UserPoolId=$USER_POOL_ID" "AppClientId=$NEXT_PUBLIC_OIDC_CLIENT_ID" "ApiScope=${NAVIGAN_API_SCOPE:-navigan/api}"
aws "${AWS_ARGS[@]}" cloudformation describe-stacks --stack-name "${AUTH_STACK_NAME:-navigan-auth}" --query 'Stacks[0].Outputs' --output table
printf '\nAttach the output Lambda to the existing user pool as Pre token generation V2_0. See docs/custom-login.md before replacing an existing trigger.\n'
