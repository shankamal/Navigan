# Selective releases: build once, deploy many

The DEV pilot now implements change planning, selective validation/builds, immutable
artifact publication, saved deployment plans, execution, authenticated verification,
and application rollback. PROD execution remains disabled. No live deployment was
performed while implementing these scripts. Docker/SAM builds and the first AWS DEV
release must be accepted on the connected runner before calling this operational.


## Normal use: two commands

Use the existing ECR repositories and S3 artifact bucket. No new registry stack,
bucket or repository is required. Configure the names once in a private local file:

```bash
mkdir -p .navigan-release
cp scripts/release-config.example.json .navigan-release/dev.json
```

Edit `dev.json` with the existing account, profile, versioned private artifact bucket
and component repository URIs. The example starts with the frontend-only DEV trial.
For an initial complete core build, use `initialComponents` containing `frontend`,
`backend`, `infrastructure`, `database`, `image-worker`, and provide the existing
frontend/image-worker repository URIs. Subsequent builds select stages from changes.
The local configuration/state directory is ignored by git. Do not add credentials.

Then the routine commands are just:

```bash
bash scripts/build.sh dev
bash scripts/deploy.sh dev
```

Build validates/tests the selected components, builds once, pushes only those
artifacts into the existing storage, and saves its manifest. Deploy consumes that
manifest, prepares/verifies the DEV target and change set, deploys, and performs
authenticated checks. It does not rebuild. Existing resources are never created
or reconfigured by the build wrapper. The bucket must already be private and
versioned; no special release tags are required. ECR settings stay unchanged and
images deploy by exact digest, including when an existing repository uses mutable tags.

Python is used internally; the operator entry points are Bash. They select the
existing sibling `navigan-deploy-venv` automatically; `NAVIGAN_PYTHON` can override it.
For database/SAM stages provide the existing DEV migration connection through
`MIGRATION_DATABASE_URL`. Deployment asks for a fresh DEV token in a hidden prompt.
After an interrupted deployment, use `bash scripts/deploy.sh dev --verify` or
`--rollback`. No new build is performed during recovery. An unfinished deployment
is not silently replaced by another attempt. PROD execution remains disabled.

The detailed commands below are implementation/reference material. The optional
isolated-registry bootstrap is not part of the normal flow and should not be run
when reusing existing resources.

## Build and deployment decisions

Build compares the committed revision with the previous complete build manifest.
Only changed input/dependency families build; unchanged artifacts retain their exact
references. Deploy separately compares the candidate manifest with DEV's last
successful deployment record. A failed deployment never replaces that record.
Configuration-only changes deploy retained artifacts without rebuilding.

| Change | Build | Deployment |
|---|---|---|
| Frontend source/dependencies | Frontend image | DEV preview only |
| Frontend tests only | No artifact | Checks only |
| Python source | Lambda ZIP and image-worker image | SAM references and existing DEV collector |
| Python dependencies | Lambda ZIP | SAM references |
| Infrastructure only | Template bundle, reusing Lambda ZIP | Reviewed SAM hierarchy |
| Lambda runtime/build contract | Backend and template bundle | Reviewed SAM hierarchy |
| New SQL migration | Checksummed SQL bundle | Pending DEV migrations only |
| Existing migration edits/removals | Blocked for review | No automatic execution |
| Documentation | None | No application stage |
| API contracts | Producer/consumer verification | No automatic application rebuild |
| Unknown path | Blocked for classification | None |

The first SAM adoption includes backend, infrastructure and database artifacts so
that schema history can be verified. Later backend changes repackage template
references without building the Lambda ZIP twice. `--enroll` explicitly adds an
unmanaged component to an existing build manifest.

The builder also supports connector, runner and tools-gateway images. Their
customer-agent/shared-service deployment bindings are not enabled in this DEV
pilot; selecting them for deployment stops with a clear scope error. Publishing
an image does not upgrade existing customer clusters or source agents.

## Immutable artifacts and portable frontend

`navigan-release-manifest-v1` records committed source revision, component input
hashes, recipe hashes/dependencies and artifact checksums. Images use ECR digests;
packages and templates use exact S3 object versions. Content-addressed storage
reuses the same version for identical bytes. Per-recipe locks prevent concurrent
duplicate builds; deployment has its own target lock. A cached artifact is verified
before reuse. Promotion/execution invokes no build commands.

The frontend image has no environment build arguments. A dynamic, no-store
`/api/runtime-config` endpoint exposes an exact public allowlist; authentication
loads it before mounting the application. Private upstream settings stay server
side. `NAVIGAN_PUBLIC_*` is preferred; existing `NEXT_PUBLIC_*` values are accepted
through dynamic runtime lookups. Missing API configuration cannot fall back to PROD.
The image builder starts the same image with DEV and PROD fixture settings and
requires both to pass. These fixtures do not contact or deploy PROD.

Legacy frontend build/deploy entry points refuse portable source before AWS writes
because their task templates do not supply its runtime identity settings. Saved
legacy execution plans still work for their existing images. The new DEV executor
does not modify the running PROD frontend or its CloudFormation drift.

## Prerequisites

Python 3.12 with the project dependencies, AWS SAM CLI, Docker Engine/buildx, git,
and the existing authorized AWS profile are required. Use the same Linux/WSL shell
for both commands. Actual AWS/Docker/SAM acceptance is still pending on the connected
DEV machine; offline tests alone do not establish a live successful deployment.

## Failure handling

Execution is journaled before mutations and cannot be blindly repeated. A command
interrupted after a successful AWS update can finish using `--verify` and a fresh
token. Inspect the private plan/journal when a stage fails. Restore the captured
working application state using `--rollback <same-plan>`; Lambda rollback uses the
actual prior deployed ZIPs/configuration, not a potentially stale source template.
Rollback does not rebuild, remove infrastructure, or reverse SQL. Migrations remain
forward-only; changes must be backward compatible with the previous application.

The executor fixes DEV API/database/stack bindings, prepares nested SAM change sets,
blocks deletion/replacement outside proven unchanged references, and checks physical
resource identities after execution. Unexpected or destructive infrastructure work
requires a separately reviewed change. The last-successful S3 pointer updates
conditionally only after all selected stages and authenticated checks pass.

## GitHub Actions (optional after the local DEV trial)

The manual `.github/workflows/dev-release.yml` calls the same Bash commands on a
persistent private runner labelled `navigan-dev-release`, in GitHub environment
`dev`. Configure `DEV_RELEASE_CONFIG` with the absolute private config path and
`DEV_RELEASE_ROLE_ARN` with the existing DEV-scoped OIDC role. Set the config's
`profile` to null there to use the assumed role, rather than a local named profile.
Authenticated checks need a fresh protected `DEV_RELEASE_SMOKE_TOKEN`; SAM/schema
stages need the protected `DEV_MIGRATION_DATABASE_URL`. Do not log either value.
Build and deploy runs must use the same persistent private configuration/state.

No runner, OIDC role, bucket or repository is created by these commands/workflows.
GitHub runner/environment setup has not been performed here. Manual dispatch needs
the workflow definition on the default branch; the local Bash commands work from
this feature branch. Remote preview access is through an approved SSH tunnel to
localhost:3001; this pilot does not provision a hosted DEV frontend.

The PR planner workflow remains read-only and runs offline release tests. Existing
CI stays independent. Customer-agent rollout and PROD promotion remain separate
follow-ups after DEV acceptance; future PROD promotion must reuse accepted artifacts.
