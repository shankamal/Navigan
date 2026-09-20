# Shared tools gateway

The gateway reuses the existing HTTPS load balancer. It creates an isolated Dev
hostname and SNI certificate, one small Dev Fargate task, target group,
host-and-path listener rule, log group, and narrowly scoped security-group
rules. It does not create a second load balancer or WAF. The existing
`navigan.click` certificate and default listener action are unchanged.
The image is digest-pinned in the existing `navigan/frontend` ECR repository;
no additional ECR repository is created.

The deployment is deliberately fail-closed:

- Keep `PlatformToolsGatewayEnabled` and `PlatformToolsTunnelEnabled` false
  until the gateway is healthy and a connector tunnel is reported connected.
- Use the Dev platform stack and `navigan_dev` database only.
- Do not source `scripts/frontend/config.env`; it contains Production frontend
  settings.

Required shell variables:

```bash
export AWS_PROFILE=navigan
export AWS_REGION=ap-south-1
export AWS_DEFAULT_REGION=ap-south-1
export FRONTEND_STACK_NAME='<existing Dev frontend stack>'
export PLATFORM_STACK_NAME=navigan-ashok-dev
export GATEWAY_HOSTNAME=dev.navigan.click
```

Build and deploy:

```bash
GATEWAY_IMAGE_URI="$(scripts/tools-gateway/build-and-push.sh)"
export GATEWAY_IMAGE_URI
scripts/tools-gateway/deploy.sh
```

After API migration/deployment and connector rollout, verify the tunnel row is
`CONNECTED` and unexpired before enabling the two platform feature flags.
