# DEV runtime reconciliation

`scripts/sync-dev-runtime.py` is a one-time reconciliation of the existing DEV
application with verified deployed PROD API artifacts. Ordinary subsequent
releases continue to use `bash scripts/build.sh dev` and
`bash scripts/deploy.sh dev`.

The reconciliation:

- Copies only differing live Lambda ZIPs into the configured existing versioned
  artifact bucket; it does not rebuild those packages.
- Retains DEV database, secret references, role/network settings and allowlists.
  It adds the missing StatusFunction tools URL using DEV's existing gateway
  binding, and enables the confirmed missing migration connector source-first
  flag. Unknown conflicting settings stop preparation.
- Adds the protected-system-node guard from the captured PROD runner to the
  captured DEV runner. The overlay retains DEV's base dependencies and every
  Terraform module file; it does not replace DEV's module with PROD's older one.
  Existing DEV node-group transformations are retained verbatim. Purpose defaults
  are added only when the old runner passes raw node groups. Protection is checked
  against the actual Terraform plan in both cases. Local patch validation runs
  before artifact staging, and known contract failures print their specific reason.
- Stages exact processed SAM templates with only scoped Lambda code/environment
  changes and the runner parameter change. Independent child previews and
  unchanged-sibling previews are never executed. The parent update is the only
  executed CloudFormation change set.
- Rejects resource additions, removals, primary replacements, unexpected
  dependencies and changed input baselines. Verifies API bindings, physical
  identities, IAM policies, exact code hashes and DEV configuration afterwards.

It does not deploy the frontend or collectors, run database SQL, change PROD,
start installer builds, provision clusters or edit existing customer GitOps
repositories. Matching collector source/dependency inventories do not require a
rebuild solely because their image digests differ.

Use existing private DEV/PROD bootstrap captures produced with
`audit-cluster-bootstrap-runtime.py --inspect-runner`. Both captures are checked
against current packages and the DEV runner identity. The configured artifact
bucket comes from `.navigan-release/dev.json`; no new bucket/repository is made.

```bash
python scripts/sync-dev-runtime.py --profile navigan \
  --dev-capture /path/to/private-dev-capture \
  --prod-capture /path/to/private-prod-capture --prepare
```

Preparation uploads artifacts/builds the narrow guard overlay and creates
unexecuted previews, then prints a private `release-plan.json` path. To execute
that exact plan:

```bash
python scripts/sync-dev-runtime.py --profile navigan --execute /path/to/release-plan.json
```

Alternatively, replace `--prepare` with `--apply` to prepare, scope-check and
execute in one invocation. Already requested execution is never blindly repeated.
If an update finishes but verification is interrupted, inspect CloudFormation
and use `--verify /path/to/release-plan.json`.

Private records retain original templates, Lambda configurations, original ZIPs,
the previous runner reference, exact proposed templates and the execution record.
CloudFormation rollback restores its previous managed template; where code was
previously changed outside CloudFormation, the original captured runtime ZIP is
also retained for a reviewed recovery. There is no automatic database rollback.
Do not share the private folder or presigned package URLs.

Successful runtime verification is not full DEV/PROD functional or IAM parity.
It does not compare every environment value, OS/native image dependency, database
object, external trust policy or customer GitOps repository. Afterwards verify
DEV sign-in, navigation, migration discovery/collection/export and a fresh cluster
bootstrap as applicable. An authenticated browser token is not requested by this
script. Existing customer clusters are not automatically upgraded by new defaults.
