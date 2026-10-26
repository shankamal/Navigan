# SAM reconciliation

The running platform has changes delivered through SAM, scoped CloudFormation
updates and direct runtime updates. Reconciliation must preserve the existing
resource identities and deployed code before normal releases resume.

## Source changes completed

- The parent forwards migration workspace bucket, KMS key and owner references.
- Backend and hosted frontend templates declare the migration feature flag.
- Migration GitHub App settings, optional key decryption and exact additional
  registry-role permissions are represented in the templates.
- Placeholder delivery-role defaults are removed; optional permissions are
  conditional. Enabled workspace mode requires complete storage bindings.
- Frontend deployment requires an explicit API origin and feature-flag value.
- SAM profiles no longer embed live target parameters. All deployment profiles
  default to creating an unexecuted change set; targets must be supplied explicitly.
- The old platform deployment wrapper is capture-only during reconciliation.
  It no longer builds and executes a full deployment as a side effect.

## Live capture

Run `scripts/reconcile-sam.py` with an explicit profile, region, expected account
and development/production stack names. `--environment both` captures both.
Supply the hosted frontend stack where one exists; a local development frontend
has no ECS stack to capture. `--capture-artifacts` also downloads checksum-verified
deployed Lambda ZIPs, deduplicated by content, without rebuilding branch source.

The capture reads original and processed templates, stack resources, route and
integration ownership, Lambda configuration, ECS task definitions and IAM policy
metadata. It references the existing workspace and collector companion stacks;
it does not create another collector, move buckets, modify external trust or run SQL.

Runtime parameters are resolved from the current migration API and companion
outputs, not from checked-in examples. Hosted frontend parameters retain its
current image, API origin and migration flag. These private files are inputs for
the subsequent reconciliation; they are not executable release plans.

Only `reconciliation-summary.json` should be shared for review. Full captures
and deployed packages remain in the private output directory. Presigned Lambda
download URLs and secret values are not written to the summary.

The capture uses the existing boto3 environment and standard library. Its route
contract is checked against source-template hashes before AWS reads. Developers
can regenerate the contract using `scripts/generate-sam-contract.py --write`
(requires PyYAML) when changing templates, then review both changes together.

## Remaining before deployment

### Route identity and adoption stage

`scripts/prepare-sam-route-ownership.py --capture-directory <private-capture>`
creates private route identity maps and verified per-function ZIP locks from the
saved capture. It preserves deployed logical IDs, omits routes absent from the
captured environment, and checks ownership across all captured stacks. It does
not build branch source or apply these maps to application templates yet.

Add `--prepare-import --profile <profile> --region <region>
--expected-account <account>` to prepare an **unexecuted** import-only change set
for routes without captured ownership. This stage rechecks live route settings
and CloudFormation ownership, discovers import identifiers from CloudFormation,
and aborts on conflicting ownership or unexpected operations. Routes are adopted
into a separate companion stack to preserve their physical IDs without changing
existing nested application stacks. Every route has retain policies.

Import preparation uses the identifier names returned by CloudFormation instead
of requiring a fixed pair. Values come from the revalidated API route. Unknown
or incomplete identifier sets still stop preparation; the private template
summary is saved for diagnosis.

Only `route-ownership-summary.json` is shareable. The private `import-plan.json`,
route templates and identity maps retain live identifiers. A failed or timed-out
preparation may leave an unexecuted change set or review stack: inspect the saved
plan before retrying. Preparation never executes, deletes or updates resources.

Use `--execute-dev-import <private-dev-import-plan.json>` with an explicit
`--expected-dev-stack`, profile, region and account to execute an already verified
development plan. The executor rechecks the exact change-set template, route
settings, import-only actions, retain policies and target stack; then verifies
completion and unchanged route identities/settings. It refuses production paths,
unverified plans and repeated execution requests. A failed or interrupted request
must be inspected in AWS using its saved plan before retrying.

### Private deployment baseline

`scripts/materialize-sam-baseline.py` uses the existing capture plus fresh read-only
checks to write packageable native CloudFormation templates for each environment.
The templates preserve deployed logical IDs, checksum-verified Lambda ZIPs, full
live Lambda environment/configuration and current role policies. Nested templates
use local paths for subsequent packaging. ECS services retain their current task
revision and desired count. Secret input parameters use `UsePreviousValue`.

This is a private reconciliation bridge for reviewing `sam package`/CloudFormation
change sets; it does not make the public authored templates the final source of
truth. It pins current ECS task revisions rather than promoting new images. It
does not adopt unmanaged Lambda permission statements. Unverified roles, route
ownership, other resource drift, packaged nested changes, and authenticated
behavior still require review. No packaging, uploads or deployment are performed.
Full runtime settings may contain sensitive values: share only the printed compact
summary, never the generated templates or locks. `deploymentReady` stays false.

1. Map authored route and permission resources to the actual deployed logical IDs.
   Existing unowned routes require an explicit adoption strategy; capture never
   imports, deletes or recreates them automatically.
2. Reconcile inline policies and external references without dropping working access.
3. Preserve the captured per-function code baseline, or explicitly select and test
   a source release. Current branch source can include behavior absent from live code.
4. Coordinate existing storage, repository collector, image collector and hosted
   frontend stacks as distinct release stages. Keep database migration/grant
   verification separate from SAM template execution.
5. Build and validate a development change set, reject removals/replacements
   outside the intended scope, then verify the deployed behavior before production.

`deploymentReady` remains false in every capture, even with no read errors.
Capture success does not establish that a full SAM deployment is safe or that
authenticated workflow validation has passed.
