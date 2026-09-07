# Host the Navigan frontend on ECS Fargate

> **Authentication update:** Navigan now uses a custom SRP login form. Follow [custom login setup](custom-login.md) for the public app client, token trigger and group permissions.
This deployment is independent of the backend SAM parent and its Customer Management stack.
It creates two CloudFormation stacks: a retained ECR repository, and the frontend ECS/ALB service.
The existing API Gateway, Cognito user pool, Aurora and RDS Proxy remain external dependencies.

## Files

| File | Purpose |
|---|---|
| `frontend/Dockerfile` | Multi-stage Node.js 22 build; minimal Next.js standalone runtime; non-root user. |
| `frontend/.dockerignore` | Excludes local environment files, dependencies, build output and tests. |
| `frontend/src/app/healthz/route.ts` | Unauthenticated liveness endpoint for ALB/container health checks. |
| `infrastructure/frontend/ecr.yaml` | ECR repository with immutable tags, encryption and scan-on-push. |
| `infrastructure/frontend/service.yaml` | HTTPS ALB, private Fargate service, roles, logs and CPU autoscaling. |
| `scripts/frontend/build-and-push.sh` | Deploy ECR stack, build linux/amd64 image, push and return digest URI. |
| `scripts/frontend/deploy.sh` | Deploy service stack with the digest, wait for stability and verify requested image. |
| `scripts/frontend/config.env.example` | Non-secret configuration to copy and customize. |

## Prerequisites

- Bash 4.2+, Git, AWS CLI v2, Docker with Buildx, and a running Docker daemon on the build host.
  Node/npm run inside Docker; they are not required on that host. Use an x86_64 builder, or configure
  Buildx emulation if building on ARM. The generated task definition runs Linux/x86_64.
- AWS credentials through an AWS CLI profile, SSO, or the build EC2 instance's IAM role. No static
  access keys are embedded in scripts or images.
- An existing VPC, at least two public ALB subnets in different AZs, and private task subnets.
  Public subnets need a route to an internet gateway. Private tasks have **no public IP** and need
  outbound HTTPS via NAT to pull images and reach CloudWatch Logs and the public API Gateway endpoint.
  VPC endpoints for ECR API/DKR, S3 and Logs can replace those particular NAT paths, but you must still
  provide connectivity to the configured public API endpoint. VPC DNS resolution must work.
- A production frontend hostname, such as your own `navigan.company.com`, and an **issued ACM
  certificate in the ECS/ALB region** that covers it. The service requires HTTPS for secure browser authentication.
- A configured Cognito public SRP app client without a secret, a V2 token trigger and assigned user groups;
  follow [custom login setup](custom-login.md).
- Optional Route 53 public hosted-zone ID for automatic DNS alias creation. Otherwise create the
  DNS alias/CNAME to the ALB DNS output yourself before using the frontend hostname.

The deployer needs CloudFormation and resource-management permissions for ECR, ECS, EC2 security
groups, ELBv2, CloudWatch Logs/alarms, Application Auto Scaling, IAM roles and `iam:PassRole`.
First deployment may also need `iam:CreateServiceLinkedRole` for ECS and Application Auto Scaling.
Route 53 permissions are required only when creating the DNS alias. ECR build/push permissions are
required on the selected repository. The container task role itself has **no AWS API permissions**;
application requests use the user's JWT. The execution role only pulls from the selected ECR repository
and writes to the service's log group, plus the required registry authorization-token operation.

## 1. Configure

From the repository root:

```bash
git pull --ff-only origin main
cp scripts/frontend/config.env.example scripts/frontend/config.env
```

Edit `config.env` with your actual client ID, HTTPS application origin, subnets, VPC and certificate ARN.
Set the public app client ID for SRP sign-in and attach the token trigger described in `docs/custom-login.md`.
Set `HOSTED_ZONE_ID` if the stack should create the DNS alias. Set `AWS_PROFILE` only when using a named
profile; otherwise the standard credential chain applies. Then load the file:

```bash
source scripts/frontend/config.env
aws sts get-caller-identity --region "$AWS_REGION"
```

When using a named profile, AWS CLI reads the exported `AWS_PROFILE`. The config file is ignored by Git.
Source only your own trusted configuration file: it is shell code. It must not contain database passwords,
JWT tokens or cloud access keys.

## 2. Build and push

```bash
IMAGE_URI="$(bash scripts/frontend/build-and-push.sh)" && export IMAGE_URI
```

The script first creates/updates `navigan-frontend-ecr`, then logs Docker into ECR using a password pipe.
It builds from `frontend/`, tags the image with Git revision/time/random suffix, pushes it, and resolves
its SHA-256 digest. Progress is on stderr; stdout contains only the deployable immutable image URI.
Stop if the build command fails. The deploy script also refuses an empty or non-digest image URI.

The default ECR repository is `navigan/frontend`. If an unmanaged repository already has that name,
choose another `ECR_REPOSITORY_NAME` or import the existing repository into CloudFormation first.
Tags are immutable: provide a unique `IMAGE_TAG` override for each build if overriding the default.
Builds include the working tree; commit/review changes before release and record the returned digest.
ECR scanning runs after push; review scan results under your release process.

**Build-time vs runtime configuration:** `NEXT_PUBLIC_*` settings are compiled into browser assets.
Changing the app URL, Cognito client or user pool requires a new image. Setting these only on the
ECS task will not change the existing image. `NAVIGAN_API_ORIGIN` and `NAVIGAN_API_BASE_PATH` are server-only
runtime variables, injected by CloudFormation, so changing them only needs a service-stack update.
Use the same public config when building and deploying a release.

## 3. Deploy to ECS

```bash
bash scripts/frontend/deploy.sh
```

The script deploys `navigan-frontend`, waits for a stable service, and confirms the active task definition
uses the requested digest. If deployment fails, it exits nonzero instead of reporting completion.
CloudFormation and the ECS deployment circuit breaker roll back failed updates. Inspect stack events
and ECS service events when failures occur. The script prints the frontend URL, ALB DNS name, cluster,
service, task definition, log group and image URI after success.

Defaults are two tasks (each 0.5 vCPU / 1 GiB), scaling up to four at 60% average CPU, with deployment
capacity of up to twice the desired count. Ensure the account has capacity/quota for that overlap.
`MIN_TASKS` and `MAX_TASKS` are configurable from 1 to 20, with max >= min. Updating the stack reapplies
the configured desired minimum; autoscaling can subsequently adjust it.

Only the ALB accepts browser traffic on 443; port 80 redirects to HTTPS. Tasks accept port 3000 only
from the ALB security group. `ALLOWED_INGRESS_CIDR` can restrict browser access to a corporate CIDR.
Liveness probes use `/healthz`, which deliberately does not depend on a user's login or API availability.
The API proxy remains server-side, so browser-to-API Gateway CORS changes are unnecessary.

If DNS is not managed by this stack, point the production hostname to the printed ALB DNS output.
An ACM certificate for your hostname does not validate the raw `*.elb.amazonaws.com` hostname;
use the configured custom hostname for login and HTTPS testing.

## 4. Verify and operate

```bash
curl --fail --show-error "${NEXT_PUBLIC_APP_URL}/healthz"
```

Expect `{"status":"ok"}`. Open the frontend hostname and complete Cognito sign-in. Test customer listing
and the engineer/independent-architect workflow on a test customer. Health checks prove process liveness,
not Cognito configuration, API permissions or authorization correctness.

Logs have 30-day retention. A CloudWatch unhealthy-target alarm is created; connect its notification
actions to your operational SNS integration. Container Insights is enabled. Add application-specific
monitoring, ALB access-log storage and WAF policies according to your environment's requirements.
No database secrets or AWS credentials are required by the frontend container.

### Update or roll back

For changes: rebuild and push, export the new digest URI, then rerun `deploy.sh`.
For rollback: set `IMAGE_URI` to a previously verified digest from the **same repository** and run
`deploy.sh` again, using that release's public app settings. ECR images are not automatically expired;
retain release digests needed for rollback. The ECR repository and logs are retained if their stacks
are deleted. Resource deletion/retirement is a separate action, not part of these scripts.

### Troubleshooting

| Symptom | Check |
|---|---|
| Cannot connect to Docker | Install/start Docker as documented in `docs/deployment.md`; verify `docker info`. |
| Build fails before compilation | Supply the actual public Cognito client ID, issuer and production HTTPS origin. |
| ECR tag already exists | Choose a new tag; immutable tags cannot be overwritten. |
| Task cannot pull image / initialize logs | Private subnet NAT or VPC endpoints, outbound HTTPS, execution role, ECR region/repository. |
| ALB targets unhealthy | Container logs, port 3000, `/healthz`, ALB-to-task SG rule and available memory. |
| TLS or sign-in error | Issued ACM cert, DNS, public app client without a secret, enabled SRP flow and token trigger; see `docs/custom-login.md`. |
| Sign-in succeeded but API requests fail | JWT scopes/custom claims and runtime gateway stage/base path; see `docs/frontend.md`. |
| CFN rollback / stable old image | Inspect CloudFormation/ECS events; fix the cause and deploy a new release. |

The CI workflow validates both templates and builds/runs the Docker image with non-production public
settings. It does not push to ECR or deploy AWS resources. Real deployment requires your account values.

References: [Next.js standalone output](https://nextjs.org/docs/pages/api-reference/config/next-config-js/output),
[AWS Fargate networking](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-task-networking.html),
and [CloudFormation ECS service](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-ecs-service.html).

## Customer routes return ROUTE_NOT_FOUND

The browser URL `/api/platform/customers` is the Next.js proxy route. With the repository defaults,
it forwards to `https://q0i8bcekw1.execute-api.ap-south-1.amazonaws.com/v1/api/v1/customers`.
The first `/v1` is the API Gateway stage; `/api/v1/customers` is the resource route.

The Customer Management handler now removes the named stage from the incoming HTTP API
`rawPath` before route matching, idempotency lookup and business metrics. It also accepts
already-unprefixed paths and the `$default` stage.

Deploy this Python handler fix through the existing backend SAM stack. Before deploying, review
your local SAM environment's saved parameters: `JwtIssuer`, `JwtAudience`, `JwtScope` and the
database/network settings must match your current deployment. Do not overwrite them with old
example values from the repository. Use the same SAM environment and stack as your existing backend.

```bash
git pull --ff-only origin main
sam build --config-file "$PWD/samconfig.toml"
sam deploy --guided --config-file "$PWD/samconfig.toml"
```

The guided deployment lets you confirm the existing stack and current parameters before applying
the change. This update includes the Customer Management Lambda; it is not an auth-stack update.
No frontend image rebuild is needed when the upstream settings are already correct.

Keep `NAVIGAN_API_BASE_PATH=/v1/api/v1` for the existing named `v1` stage. If your deployed gateway
uses `$default`, its base path would instead be `/api/v1`. Check the actual stage before changing it.
A plain API Gateway `{"message":"Not Found"}` response can indicate an upstream stage/route mismatch;
a structured `ROUTE_NOT_FOUND` response indicates the request reached the backend router.
