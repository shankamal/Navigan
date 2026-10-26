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
summary is saved for diagnosis. Composite entries such as `ApiId,RouteId` are
split into their individual request properties. Preparation prints its compact
summary directly, and prints an execution-plan path only after successful
import-only verification. Failed preparation must not be followed by execution.

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

The materializer supports processed templates returned as JSON objects, JSON text
or CloudFormation YAML. YAML support uses a safe loader preserving intrinsic
functions; install `scripts/requirements-sam-reconciliation.txt` in the existing
deployment environment. Invalid or unsupported YAML stops without printing
private source lines. The completed DEV route import does not need repeating.

### Prepare application change sets

`scripts/prepare-sam-baseline-release.py` takes the private capture, one explicit
environment, expected root stack/account, profile and region. It freshly
materializes the baseline and verifies every template-owned IAM role, including
roles absent from the original Lambda/ECS-derived capture. It discovers the
existing deployment bucket from captured nested-template URLs and checks bucket
ownership/region before packaging with `sam package`. No source build is run.
Multiple referenced deployment buckets are supported. Selection prefers a SAM
managed bucket and otherwise uses stable ordering, accepting only a bucket that
passes authenticated account/region checks. An explicit `--artifact-bucket` may
select one of the captured buckets and retains the same checks.

The command uploads artifacts and creates unexecuted UPDATE change sets for the
root hierarchy and captured companion stacks (plus hosted frontend when present).
It retains prior stack parameters, tags and service role. Nested change sets are
inspected recursively. Only non-replacing modifications to the expected Lambda,
IAM, nested-stack and ECS service resources pass the mechanical review; additions,
deletions, replacements and other resource types are flagged for review. Empty
change sets are recorded as no-ops. Failed stages leave their private plan/logs
available; inspect them before retrying. No change set is executed or deleted.

Share only `release-summary.json`. The summary deliberately keeps
`deploymentReady: false`: passing its mechanical scope checks does not establish
semantic IAM correctness, workflow acceptance, or final reconciliation of the
public authored SAM templates. Review the proposed changes before executing Dev;
production preparation/execution remains a separate stage.

### Review finding: unnecessary snapshot and packaging changes

The first prepared development plans were blocked. Property-level evidence showed
many route/storage/runtime entries changed only in resource metadata, alongside
direct Lambda/IAM snapshot rewrites and conditional dependency changes. SAM CLI's
`ResourceMetadataNormalizer` adds `SamResourceId` during packaging; these metadata
changes are not evidence of new route behavior or key rotation.

Packaging now processes child templates first, restores their original resource
metadata before uploading them, and then packages the parent against those clean
child URLs. The normalizer rejects any packaging changes beyond Lambda code
locations and restored metadata. Existing metadata is retained exactly. Removing
metadata from the parent alone is insufficient because nested templates have
already been uploaded by ordinary recursive packaging.

Materialization also preserves verified same-stack Lambda role ARN expressions,
omits implicit Lambda defaults absent from the original template, and avoids
adding empty IAM policy arrays. This reduces unnecessary changes; it does not
prove all IAM/environment changes are semantically safe or eliminate all dynamic
replacement risks. The original blocked plans must remain unexecuted. Prepare
fresh plans only from the corrected code and review their actual results. The
replacement/resource-type guards have not been relaxed, and the maintained public
SAM templates still require reconciliation before normal source releases resume.

### Inspect already prepared plans without repeating packaging

Add `--review-directory <saved-release-directory>` to the release-preparer command
with the same capture, environment and explicit target/account/region options.
This mode reads saved plan IDs and current AWS change-set/template/resource data.
It does not require SAM CLI, choose a bucket, package, upload, create or execute
change sets. The mode checks target identity, availability, stable stacks and
unchanged parameter bindings, including nested change sets.

For unchanged definitions it can attach dependency evidence: local references
exist, reference targets have no replacement proposed, and relevant identity
properties (role name/path, function name, rule name/event bus) remain unchanged.
Unknown/external intrinsics and changed conditions/mappings are not inferred safe.
The summary preserves AWS's replacement classification. Evidence explains a
dependency warning; it does not override `reviewPassed`, approve conditional
replacements, validate every policy grant, or set `deploymentReady` to true.
The compact shareable output is `existing-plan-review-summary.json`; full local
AWS evidence stays under each stage's `review-evidence` directory.

Add `--verify-runtime` to that read-only command to compare the proposed templates
in AWS with live IAM role trust/inline/managed policies and boundaries, core Lambda
configuration and concurrency, and ECS service task revision/count. The verifier
also downloads each proposed S3 ZIP and checks its SHA-256 against the running
Lambda package and the recorded code lock. Thus a matching local filename is not
treated as evidence of matching code. Lambda updates in progress fail verification.
The report identifies mismatching fields without printing policy/environment
values; private code downloads remain in memory. The mode makes no AWS writes.

CodeBuild project references are checked against their project-name identity when
explaining event-rule dependencies. These checks provide review evidence; they do
not approve conditional replacements, validate every resource property, execute a
release, or finish reconciliation of the maintained source templates. Inspect
`runtime-binding-verification.json` and the printed summary before any execution.

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

### Execute a reviewed DEV baseline

`execute-sam-baseline-release.py` now accepts an existing release directory and
its original capture, with explicit `--environment dev`, `--expected-stack`,
`--expected-account`, `--region` and optional `--profile`. It creates no new
change sets or artifacts. It independently repeats the saved-plan scope and live
runtime checks immediately before executing the existing stages in order.

The execution gate accepts unchanged dependency definitions only when referenced
resource identities are stable. Conditional updates are limited to the reviewed
Lambda permission `SourceArn` and ECS task-definition `TaskRoleArn` cases.
CloudFormation may still replace those permissions or register a task revision;
no other resource identity changes, additions or removals are accepted. The
script stops on rollback/failure and records requested/completed stages in
`execution-record.json`. An existing execution record blocks duplicate runs;
inspect it and AWS stack status after interruption rather than deleting it and
retrying blindly.

After updates, all captured resource inventories are compared and IAM, Lambda
configuration/code hashes and ECS service bindings are checked again. Lambda
RevisionId is allowed to advance after CloudFormation updates; code hashes and
configuration remain mandatory. This executes the private deployed baseline; it
does not finish maintained source-template reconciliation, PROD adoption, or
application workflow validation. The existing preparer and review modes remain
non-executing.
