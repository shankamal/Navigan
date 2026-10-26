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
