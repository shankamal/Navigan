#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
NAVIGAN_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
source "$NAVIGAN_ROOT/scripts/frontend/common.sh"
require GATEWAY_IMAGE_URI FRONTEND_STACK_NAME GATEWAY_HOSTNAME
GATEWAY_STACK_NAME="${GATEWAY_STACK_NAME:-navigan-tools-gateway-dev}"
ECR_STACK_NAME="${TOOLS_GATEWAY_ECR_STACK_NAME:-navigan-frontend-ecr}"
REPOSITORY_ARN="$(stack_output "$ECR_STACK_NAME" RepositoryArn)"
stack_resource() {
  aws "${AWS_ARGS[@]}" cloudformation describe-stack-resource \
    --stack-name "$FRONTEND_STACK_NAME" --logical-resource-id "$1" \
    --query 'StackResourceDetail.PhysicalResourceId' --output text
}
stack_parameter() {
  aws "${AWS_ARGS[@]}" cloudformation describe-stacks \
    --stack-name "$FRONTEND_STACK_NAME" \
    --query "Stacks[0].Parameters[?ParameterKey=='$1'].ParameterValue | [0]" \
    --output text
}
CLUSTER_ARN="$(stack_resource Cluster)"
HTTPS_LISTENER_ARN="$(stack_resource HttpsListener)"
LOAD_BALANCER_SECURITY_GROUP_ID="$(stack_resource LoadBalancerSecurityGroup)"
LOAD_BALANCER_ARN="$(stack_resource LoadBalancer)"
VPC_ID="$(stack_parameter VpcId)"
PRIVATE_SUBNET_IDS="$(stack_parameter PrivateSubnetIds)"
HOSTED_ZONE_ID="$(stack_parameter HostedZoneId)"
FRONTEND_HOSTNAME="$(stack_parameter FrontendHostname)"
FRONTEND_CERTIFICATE_ARN="$(stack_parameter CertificateArn)"
if [[ "$GATEWAY_HOSTNAME" == "$FRONTEND_HOSTNAME" ]]; then
  EXISTING_CERTIFICATE_ARN="$FRONTEND_CERTIFICATE_ARN"
  CREATE_DNS_RECORD=false
else
  EXISTING_CERTIFICATE_ARN=
  CREATE_DNS_RECORD=true
fi
ENVIRONMENT_NAME="${ENVIRONMENT_NAME:-Dev}"
read -r LOAD_BALANCER_DNS_NAME LOAD_BALANCER_CANONICAL_ZONE_ID < <(
  aws "${AWS_ARGS[@]}" elbv2 describe-load-balancers \
    --load-balancer-arns "$LOAD_BALANCER_ARN" \
    --query 'LoadBalancers[0].[DNSName,CanonicalHostedZoneId]' --output text
)
USED_PRIORITIES="$(
  aws "${AWS_ARGS[@]}" elbv2 describe-rules \
    --listener-arn "$HTTPS_LISTENER_ARN" \
    --query 'Rules[?Priority!=`default`].Priority' --output text
)"
LISTENER_RULE_PRIORITY="${LISTENER_RULE_PRIORITY:-}"
if [[ -z "$LISTENER_RULE_PRIORITY" ]]; then
  for candidate in $(seq 20 99); do
    if [[ " $USED_PRIORITIES " != *" $candidate "* ]]; then
      LISTENER_RULE_PRIORITY="$candidate"
      break
    fi
  done
fi
require LISTENER_RULE_PRIORITY
PLATFORM_API_BASE_URL="$(
  aws "${AWS_ARGS[@]}" cloudformation describe-stacks \
    --stack-name "${PLATFORM_STACK_NAME:-navigan-ashok-dev}" \
    --query "Stacks[0].Outputs[?OutputKey=='ApiBaseUrl'].OutputValue | [0]" \
    --output text
)"
aws "${AWS_ARGS[@]}" cloudformation deploy \
  --stack-name "$GATEWAY_STACK_NAME" \
  --template-file "$NAVIGAN_ROOT/infrastructure/tools-gateway/service.yaml" \
  --capabilities CAPABILITY_IAM --no-fail-on-empty-changeset \
  --parameter-overrides \
    "ImageUri=$GATEWAY_IMAGE_URI" \
    "RepositoryArn=$REPOSITORY_ARN" \
    "VpcId=$VPC_ID" \
    "PrivateSubnetIds=$PRIVATE_SUBNET_IDS" \
    "ClusterArn=$CLUSTER_ARN" \
    "HttpsListenerArn=$HTTPS_LISTENER_ARN" \
    "LoadBalancerSecurityGroupId=$LOAD_BALANCER_SECURITY_GROUP_ID" \
    "PlatformApiBaseUrl=$PLATFORM_API_BASE_URL" \
    "GatewayHostname=$GATEWAY_HOSTNAME" \
    "ExistingCertificateArn=$EXISTING_CERTIFICATE_ARN" \
    "CreateDnsRecord=$CREATE_DNS_RECORD" \
    "EnvironmentName=$ENVIRONMENT_NAME" \
    "HostedZoneId=$HOSTED_ZONE_ID" \
    "LoadBalancerDnsName=$LOAD_BALANCER_DNS_NAME" \
    "LoadBalancerCanonicalHostedZoneId=$LOAD_BALANCER_CANONICAL_ZONE_ID" \
    "ListenerRulePriority=$LISTENER_RULE_PRIORITY"
aws "${AWS_ARGS[@]}" ecs wait services-stable \
  --cluster "$CLUSTER_ARN" \
  --services "$(stack_output "$GATEWAY_STACK_NAME" ServiceName)"
