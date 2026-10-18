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
