# DEV: automatic migration source connector prerequisites

This procedure resolves `SOURCE_CONNECTOR_ARTIFACT_UNAVAILABLE` for a
self-managed Kubernetes source registered with AWS Systems Manager. It is a
**one-time platform release operation**, not something a migration user must
perform while registering a source cluster.

## Platform operator: publish and configure the artifact

From the Navigan WSL repository on `new_migration_approach_18oct26`:

```bash
git pull --ff-only origin new_migration_approach_18oct26
AWS_PROFILE=navigan AWS_REGION=ap-south-1 \
  bash scripts/deploy-migration-source-connector-dev.sh --deploy-dev
```

The guarded release script:

1. Refuses any account other than `905418045935`, any region other than
   `ap-south-1`, and any branch other than `new_migration_approach_18oct26`.
2. Creates or reuses the private ECR repository
   `navigan/migration-source-connector`.
3. Builds `migration_connector/Dockerfile` from committed sources, publishes a
   Linux/amd64 image and resolves its immutable `sha256` digest.
4. Pins the repository, digest and existing approved delivery role into a
   temporary copy of the default/DEV SAM profiles (never the production profile).
5. Validates, builds, presents a CloudFormation change set for approval and
   deploys the **DEV** backend stack `navigan-ashok-dev` only.
6. Reads the deployed migration Lambda environment to verify both artifact
   settings before reporting success. After success, updates the local
   `samconfig.toml` default/DEV values so subsequent local deployments preserve
   the pin. Review that file and commit its DEV-only release pin when appropriate.

No production stack, ECS service, application database or source Kubernetes
cluster is changed by this release script.

### Resume after a temporary SAM/PyPI download timeout

If the connector image was successfully pushed but SAM stopped at
`PythonPipBuilder:ResolveDependencies` due to a network read timeout, reuse the
existing immutable image tag from that run:

```bash
AWS_PROFILE=navigan AWS_REGION=ap-south-1 \
  bash scripts/deploy-migration-source-connector-dev.sh \
  --resume-dev dev-<12-character-commit>-<UTC-timestamp>
```

This skips Docker publishing, queries ECR for the existing digest and retries
the DEV build with increased pip download timeout and retry settings passed
into the SAM build container. It still presents the CloudFormation change set
for approval and verifies the deployed Lambda environment.

### DEV repair when the full stack encounters an existing API route conflict

On 18 October, the full DEV SAM release rolled back because Cluster Management
attempted to create an API Gateway route that already exists:
`POST /api/v1/clusters/{clusterId}/connector/upgrade`. Do **not** remove the
working route or repeat the full SAM release against this conflicted stack.

For the already published connector image, run the separate guarded,
**parameter-only** activation instead:

```bash
git pull --ff-only origin new_migration_approach_18oct26
AWS_PROFILE=navigan AWS_REGION=ap-south-1 \
  bash scripts/activate-migration-source-connector-dev.sh \
  --image-tag dev-8aec3981a2e1-20261018130607
```

This command uses CloudFormation's **existing deployed root template**, keeps
all non-image parameters unchanged, and will execute only if its change set
contains exactly one non-replacing modification to `MigrationManagement`.
It asks for confirmation before execution. If the deployed template lacks the
connector image parameters, the script stops without deploying. It checks the
Migration Lambda's final repository/digest environment values and then pins
the verified DEV parameters in the local SAM configuration.

**Important limitation:** this repair configures the published connector image;
it does **not** deploy changed Lambda installer code or resolve the pre-existing
API route ownership conflict. The latter requires a separately planned,
reviewed root-stack reconciliation before a full backend release. Thus the
automatic source installation is not yet proven end to end; verify connector
enrollment and first inventory before declaring it ready.

### Deployed root template predates the connector image parameters

The attempted previous-template activation correctly stopped on 18 October
because `navigan-ashok-dev` does not have the two connector-image parameters.
The deployed `MigrationManagement` resource is a nested stack referencing an
older S3 template, and the conflicting `UpgradeConnectorRoute` is **not** a
resource owned by the currently deployed Cluster Management nested stack.

To avoid reintroducing that route conflict, stage a **migration-only preview**
from the existing processed CloudFormation root template:

```bash
git pull --ff-only origin new_migration_approach_18oct26
AWS_PROFILE=navigan AWS_REGION=ap-south-1 \
  bash scripts/stage-migration-source-connector-dev.sh \
  --image-tag dev-8aec3981a2e1-20261018130607
```

This script builds the currently committed Migration Management Lambda only,
uploads its package into the existing SAM artifacts bucket, fetches the
**deployed processed root template**, and changes only its MigrationManagement
child template URL and three child parameters. It preserves every existing root
parameter value and all other capability resource definitions. It creates a
nested CloudFormation change set, verifies that the root would only modify
MigrationManagement, and prints changes inside the nested module.

**It does not execute the change set.** The operator must review and share the
root and nested change-set details before any execution is approved, including
checking for newly created API Gateway routes and unexpected resource changes.
Publishing SAM package objects and creating a change set can incur minimal
storage/API costs, but do not change the running application infrastructure.

## Source cluster: private image-pull permission

For the P0 self-managed AWS kubeadm lab, the EC2/SSM **control-plane instance
role** must be allowed to request an ECR authorization token. The installer now
uses that permission to create a Kubernetes `imagePullSecret` before deploying
the read-only connector. The token stays on the source instance and inside the
Kubernetes Secret; it is not sent through the SSM command parameters or
exposed in Navigan's UI.

The lab Terraform module grants scoped image-pull permissions when its local
`terraform.tfvars` contains:

```hcl
migration_connector_repository_arn = "arn:aws:ecr:ap-south-1:905418045935:repository/navigan/migration-source-connector"
```

Review the Terraform plan before applying any lab IAM change. Do not re-create
the cluster just to set the permission. For other self-managed clusters, use
an equivalent approved method for registry authentication.

ECR-issued Docker passwords are time limited. This enables initial connection
in DEV; production hardening still requires automated credential rotation or
a node credential provider, particularly when new nodes need to pull the image
later. Do not treat initial connectivity as proof that private registry
credentials will remain usable indefinitely.

## User: resume the existing assessment

After the platform prerequisites are complete:

1. Reopen the existing migration draft; do **not** cancel it or register the
   source a second time.
2. Select **Retry source connection** if the last attempt failed. Navigan
   sends the SSM install command automatically.
3. The source is genuinely ready only after the installed connector submits
   its first inventory; an SSM command ID alone is not a successful connection.

If installation fails after the SSM command is issued, inspect its command ID
in AWS Systems Manager Run Command for the source account. Streaming those
sanitized logs in Navigan is a separate read-only API enhancement and is not
implemented by this release.

### Safe follow-up after the full nested change-set preview (18 October)

The full nested MigrationManagement preview created by
`stage-migration-source-connector-dev.sh` proposed dozens of API Gateway route
replacements, IAM permission replacements, and new S3/KMS infrastructure.
**Do not execute** that change set. In particular, do not replace existing
migration API routes to activate the source connector.

A narrower, review-only script reuses the successfully uploaded 27.7 MB
Lambda package and patches the **deployed processed** MigrationManagement
child template rather than swapping in the full current SAM template:

```bash
git pull --ff-only origin new_migration_approach_18oct26
AWS_PROFILE=navigan AWS_REGION=ap-south-1 bash scripts/stage-migration-source-connector-lambda-only-dev.sh
```

The script must produce a root change set that modifies only
`MigrationManagement` and a nested change set limited to:

- `MigrationFunction`: in-place code and connector environment update
- `MigrationConnectorFunction`: in-place code update
- `MigrationFunctionRole`: in-place scoped `sts:AssumeRole` permission
- `InstallSourceClusterConnectorRoute`: add one new route, only when absent

It checks the existing API for the install route and fails safely if it already
exists. It does **not** execute a change set, build a container, provision an
artifact bucket/KMS key, or modify other capability templates. If the preview
includes any other resources or replacements, stop and reconcile before any
deployment.
