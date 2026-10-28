# Selective releases: build once, deploy many

The DEV pilot now implements change planning, selective validation/builds, immutable
artifact publication, saved deployment plans, execution, authenticated verification,
and application rollback. PROD execution remains disabled. No live deployment was
performed while implementing these scripts. Docker/SAM builds and the first AWS DEV
release must be accepted on the connected runner before calling this operational.

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

## Start on the connected DEV machine

Prerequisites: Python 3.12, the project Python dependencies, AWS SAM CLI, Docker
Engine with buildx, git, and the existing authorized AWS profile. Linux/WSL Docker
must be usable from the same shell. A SAM/database release also needs a private
migration-owner connection to `navigan_dev` through `MIGRATION_DATABASE_URL`.
The frontend-only pilot does not require that connection.

```bash
python scripts/deploy-release-dev.py --init --bootstrap-registry \
  --profile navigan --region ap-south-1 --expected-account <account-id>
```

This verifies the existing DEV root/domain/database ownership and creates only an
isolated versioned S3 artifact bucket and immutable ECR repositories. It prints a
private `dev-config.json` and bucket name. Preserve that file locally; do not commit
configuration captures, tokens, connection strings or deployment journals.

First try the frontend alone, using the printed bucket/config path:

```bash
python scripts/build-release.py --profile navigan --region ap-south-1 \
  --expected-account <account-id> --artifact-bucket <printed-bucket> --initial frontend
python scripts/deploy-release-dev.py --profile navigan --prepare \
  --config <private-dev-config.json> --manifest <printed-release-manifest.json>
```

Review the printed selected/skipped stages and private summary. Execute its exact
saved plan, then open `http://localhost:3001` and sign in using DEV credentials:

```bash
python scripts/deploy-release-dev.py --profile navigan --execute <printed-release-plan.json>
python scripts/deploy-release-dev.py --profile navigan --verify <same-release-plan.json>
```

Execution requests a fresh DEV access token through a hidden prompt (or protected
`NAVIGAN_DEV_SMOKE_TOKEN`). Authenticated summary checks run before mutation and
through the candidate frontend proxy after deployment. The current port-3000
frontend is preserved. An unmanaged process on 3001 is never stopped. Later runs
replace only the recorded managed preview after testing an ephemeral candidate.

Use `--baseline-manifest <last-build-manifest.json>` for later builds. To adopt SAM
and schema stages after the frontend trial, add
`--enroll backend,infrastructure,database,image-worker`. Existing DEV collector
ownership must verify; its desired count, including zero, is retained.

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

## Persistent runner / GitHub Actions

For repeated runs, create a mode-700 runner directory, copy the private
`dev-config.json` into it, and use:

```bash
python scripts/run-dev-release.py --home <private-runner-home> --profile navigan --action build-prepare
python scripts/run-dev-release.py --home <same-home> --profile navigan --action execute --plan-id <printed-id>
```

The runner retains the last complete build manifest and reviewed plans. Other
actions are `verify` and `rollback`, using that same saved plan ID. A shared DEV
frontend is not provisioned by this pilot. Remote runners expose the local preview
only through an approved SSH tunnel.

`.github/workflows/dev-release.yml` invokes these same commands manually on a
persistent private runner labelled `navigan-dev-release`, in GitHub environment
`dev`. Configure `DEV_RELEASE_HOME`, `DEV_RELEASE_ROLE_ARN`, a fresh protected
`DEV_RELEASE_SMOKE_TOKEN`, and (for schema/SAM) `DEV_MIGRATION_DATABASE_URL` there.
The OIDC role must trust only this repository/environment and access only verified
DEV resources and the dedicated registry. No AWS keys belong in the workflow.
Runner/environment/OIDC setup has not been performed by this implementation.
Manual dispatch requires the workflow definition on the repository's default branch;
the local CLI works from this feature branch immediately.

`.github/workflows/dev-release-plan.yml` remains a read-only PR impact review.
Existing CI stays independent and credential-free. Source-agent rollout and PROD
promotion are separate follow-ups after DEV acceptance; PROD must consume the
accepted immutable manifest with its own runtime configuration, never rebuild it.
