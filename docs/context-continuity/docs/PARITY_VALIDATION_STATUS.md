# Parity validation status

The user confirmed successful deployment and verification of the development summary APIs, migration API correction, repository collector and image collector alignment. The targeted database role-permission repair was also committed and verified, with development permissions retained.

No further deployment is indicated for these completed fixes. Full functional parity is not yet accepted: authenticated development frontend and migration workflow validation, including collection and export, remain pending.

The user has now authorized SAM reconciliation while authenticated workflow validation remains pending. Template parameter wiring and a read-only ownership/baseline capture are implemented; live resource-ID reconciliation and reviewed change sets are still required. The legacy platform wrapper is capture-only during this work. See [SAM reconciliation](../../sam-reconciliation.md). No full SAM deployment has been performed.

The supplied live capture completed without read errors. Route identity preservation,
captured ZIP verification and an optional unexecuted import-only preparation stage
are implemented in `scripts/prepare-sam-route-ownership.py`. Existing route IDs and
environment-specific route absence are retained. Preparation checks all captured
owners and rechecks live ownership/settings before creating a change set. The new
stage has local regression coverage; live import preparation/execution, application
template overlays, permission ownership and baseline wiring remain pending.

The first live route preparation stopped before change-set creation because of
a fixed import-identifier assumption. Preparation now uses CloudFormation's
returned identifier names with route-specific validation and saves its private
template summary. Retry preparation using the existing capture; no import or
application deployment has been executed.

Saved DEV route plans can now be explicitly executed with target/account checks,
import-only validation and post-import route-identity/settings verification. A
private baseline materializer preserves processed resource IDs, deployed ZIPs,
fresh Lambda configuration, IAM role policies and ECS service task revisions.
Both paths have local regression coverage. The user has not yet supplied a
successful import execution or reviewed packaged application change set; full
SAM restoration and authenticated workflow acceptance remain incomplete.

The next preparation output identified CloudFormation's composite identifier
encoding: one comma-separated entry containing both route identifier properties.
The parser now splits that entry before constructing the import request, matching
AWS CDK's importer behavior. Regression coverage includes the exact live response.
Earlier attempts created no import plan and executed no imports. Reprepare before
attempting saved-plan execution; do not reuse the earlier missing-plan path.

The user confirmed DEV route import reached IMPORT_COMPLETE and verification
retained route identities/settings; production was unchanged. The baseline run
then failed in both environments with JSONDecodeError before AWS writes. The
materializer now accepts CloudFormation YAML as well as JSON and preserves
intrinsics with a safe loader. Retry only baseline generation after installing
its YAML dependency; do not repeat the completed route import.

The user confirmed both baselines generated without errors, retaining the
captured functions/services, with one unverified template-owned role per
environment. Materialization now reads those remaining roles directly. A release
preparer freshly materializes one explicitly selected environment, packages its
verified artifacts into the existing deployment bucket, and creates unexecuted
root/nested/companion UPDATE change sets. Recursive review flags non-modifications,
replacement risk and unexpected resource types. Local regression checks cover
nested scope, no-op handling and secret-parameter retention. No application change
set has yet been prepared or executed in AWS; public authored-template integration
and authenticated Dev/Prod workflow acceptance remain incomplete.

The first live application preparation stopped during deployment-bucket discovery,
before uploads or change-set creation. Discovery now accepts S3 HTTPS URLs with
version/signature query parameters, standard regional/dual-stack endpoints and
S3 URIs. It extracts only the bucket and never fetches or prints query values;
authenticated bucket owner/region verification remains required. Application
preparation needs retrying; the completed route import must not be repeated.

The next attempt stopped before uploads because different nested templates
referenced multiple deployment buckets. Discovery now accepts multiple candidates,
prefers the SAM managed bucket deterministically, and verifies account/region
before selecting a usable candidate. An explicit captured-bucket override is also
available. This changes discovery only; no application deployment has executed.

The user supplied successful preparation output for five development stages. All
were blocked by scope review, including four conditional replacements. No change
set executed. Subsequent property-level evidence showed route changes were
metadata-only, three conditional Lambda permissions depended on event-rule source
ARNs, and a worker task depended on its role ARN. Direct Lambda/IAM rewrites also
require review. AWS SAM CLI source confirms packaging adds resource metadata.

The preparation path now restores original metadata before uploading each nested
template, preserves verified local Lambda role references, avoids introducing
implicit Lambda defaults, and omits newly added empty IAM policy arrays. Regression
tests cover child metadata cleanup, unrelated-property rejection, reference
identity checks and default/nondefault configuration. Earlier plans remain blocked
and must not execute. Corrected live preparation and public authored-template
reconciliation remain pending; this is not a completed SAM restoration.

The user supplied the corrected five-stage development preparation. Metadata-only
route changes disappeared; four conditional replacements remained. A subsequent
local comparison confirmed every property on those four resources was identical
before/after, including the source-rule and worker-role ARN references. This alone
does not establish that their referenced identities remain unchanged.

A read-only existing-plan review mode now checks the saved AWS change sets,
original/proposed templates, current resource identities and parameter bindings.
It annotates unchanged definitions with dependency evidence when the referenced
resources retain their identity fields and have no replacement proposed. It does
not create new plans or uploads, relax the approval gates, execute changes, or
declare public authored-template reconciliation complete. Live results from this
mode and semantic policy/environment review remain pending.
