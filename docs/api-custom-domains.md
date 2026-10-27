## 27 October 2026 — local DEV browser read checks passed

User screenshots show local DEV Customer, Environment, Cluster and Migration pages rendering data. Visible Network entries return HTTP 200 for identity/access reads, customer/environment/cluster lists and summaries, environment metadata and the migration list. These extend the previously verified same-token Customer/Environment/Cluster summary parity across the original and custom DEV API URLs. Detail views, writes, approvals, provisioning and full migration workflows are not established by these screenshots.

The local port conflict was identified as a Windows node.exe process belonging to the existing Navigan checkout, despite no identifiable WSL listener. A guarded Windows-side restart was supplied with the two API proxy variables set within PowerShell so the child Node process inherits them. Browser-facing requests remain at /api/platform; the server forwards upstream. No claim is made that screenshots alone reveal the upstream hostname. The intended DEV origin is https://api-dev.navigan.click and base path /api/v1.

Next: persist only those two values in the private local frontend/.env.local, preserving all other settings and avoiding duplicate assignments. Inspect any .env.development.local definitions or shell-level overrides before assuming the saved values take effect on an ordinary restart. Never commit the private environment file. Persistence has not yet been reported. Obtain a fresh two-environment domain audit including the deployed DEV domain before preparing PROD; the old pre-DEV audit cannot serve as the PROD baseline. PROD's existing endpoint/frontend and connector/tool/backend callbacks remain unchanged. Domain cleanup does not close SAM source/runtime/ownership parity. This checkpoint records screenshot and user-run evidence only; no new source/runtime code or tests are required.

## 27 October 2026 — DEV authenticated summary parity passed

The user reran the same-environment validator with a fresh DEV credential and supplied passed=true. Customer, Environment and Cluster summaries each returned HTTP 200 on the existing endpoint and custom domain with identical JSON. The prior attempt returned 401 on both endpoints; the retry establishes that a current accepted credential resolves that validation blocker. It does not establish the exact reason the earlier credential was rejected.

DEV domain resource/TLS/unauthenticated checks and these three authenticated summary reads are now verified through user-run output. No frontend switch, broader browser/workflow acceptance or PROD domain rollout is reported. The validator's private authenticated-verification.json contains the result. Tokens and response bodies remain private and are not included here.

Next: test the local DEV frontend with process-scoped NAVIGAN_API_ORIGIN=https://api-dev.navigan.click and NAVIGAN_API_BASE_PATH=/api/v1 while starting its existing dev server on port 3000. Stop only that existing local frontend process first. This changes the two server-side API proxy settings for this process; it does not edit environment files, rebuild an image, alter OIDC settings or deploy to AWS. Verify fresh login and Customer/Environment/Cluster navigation through the browser. Use the original execute-api origin and /v1/api/v1 path to restart that process for rollback. Persist the reviewed DEV configuration only after browser acceptance; then prepare PROD separately from a refreshed two-environment audit. SAM ownership/runtime/source parity remains a separate pending activity. No additional code change or test run is required for this evidence-only checkpoint.

## 27 October 2026 — DEV domain verification passed; authenticated comparison next

The user supplied the success marker from read-only verification after pulling the certificate verifier correction. DEV's custom domain passed certificate identity/validity, regional domain, empty existing-stage mapping, DNS alias, preserved existing API settings/default endpoint, HTTPS/TLS and unauthenticated protected-route checks. The frontend remains unchanged. This confirms domain verification, not authenticated workflow acceptance or SAM parity. PROD domain rollout remains pending.

Added scripts/validate-api-domain-parity.py for the next bounded check. It loads the existing private release plan and matching successful verification record, derives both URLs for that same environment/API, prompts once without echo, and uses GET only for Customer, Environment and Cluster summaries. Redirects are disabled. Both endpoints must return HTTP 200, valid summary objects and identical JSON data. All fields are compared; concurrent data changes can cause a mismatch that requires inspection. Tokens and response bodies are neither printed nor persisted. A private authenticated-verification.json stores only result metadata/statuses. This preliminary summary acceptance does not cover every authenticated workflow or browser behavior.

Validation: 107 domain tests passed, including 21 new checks for plan/verification/URL binding, same-token GET paths, redirect prevention, noninteractive prompt protection, malformed tokens, HTTP/connection/JSON/size/payload failures and private status-only evidence. No live authenticated request was performed from this workspace. Next: run the helper with the already verified DEV release plan and a current DEV token; require authenticated summary parity success before preparing a separate DEV frontend URL change. Do not repeat domain preparation/execution, change backend/connector/tool URLs, or start PROD rollout yet.

## 27 October 2026 — DEV domain created; certificate verification recovery

The user-run execution passed stack CREATE_COMPLETE, exact four-resource creation, unchanged API snapshots, regional domain availability, certificate attachment, root mapping and DNS alias checks, then stopped at the aggregate certificate metadata check. DNS/TLS/HTTP and authenticated acceptance remain unverified. This is a post-deployment verification failure; do not repeat preparation or execution.

The verifier incorrectly accepted only RSA_2048 even though AWS DescribeCertificate examples also use RSA-2048. The correction accepts those two exact RSA 2048 forms and directly describes the CloudFormation-owned certificate. Exact certificate identity/domain, ISSUED status and explicit timezone-aware validity dates remain required. Another certificate's validity and inventory-list presence cannot establish the owned certificate's validity. Failure messages now identify identity, status, algorithm or validity rather than an aggregate check. The supplied output does not reveal the actual certificate metadata, so the exact live mismatch is not yet confirmed.

Validation: 86 domain audit/release tests passed, covering both documented algorithm forms, inventory listing lag, wrong identity/domain/key/status, expired/future/missing/invalid validity dates, preserved API/mapping/DNS scope and read-only verification. Resume only with --verify and the existing saved release plan. No template change, AWS mutation, frontend switch or PROD rollout is part of this verifier correction. Require the verification success marker, then authenticated DEV parity before frontend/PROD work.

## Prepared-plan verification corrected

DEV preparation reached a saved, unexecuted companion change set after the freshness and public-delegation checks, then stopped because the verifier incorrectly expected ChangeSetType in DescribeChangeSet. AWS does not return that field. No deployment was executed.

The verifier now proves new-stack creation from the live independent REVIEW_IN_PROGRESS stack identity/status and the exact four Add actions. It retains parameter/template/availability checks and rejects imports, nested targets, existing stacks, modifications, removals and replacements. The response fixtures are validated against the actual botocore DescribeChangeSet and DescribeStacks schemas.

Validation: 71 domain audit/release tests passed; git diff --check passed. Reuse the saved release-plan.json with --execute after pulling the correction; do not repeat --prepare or create another stack. Execution still repeats all freshness/delegation/scope checks and journals before mutation. Runtime rollout, authenticated parity and frontend switching remain pending.

## DEV-first domain deployment prepared

The user-run read-only audit completed without read errors. Both existing HTTP APIs retain their v1 stages and enabled default endpoints. The two intended custom domains and target address/delegation records are absent, and no matching regional certificate candidates were found. Public DNS delegation was not established by that inventory; it must be verified before staging.

infrastructure/companion/api-domain.yaml defines exactly four resources for one explicitly selected environment: a new RSA-2048 DNS-validated ACM certificate, regional TLS 1.2 API domain, empty mapping to the existing API/stage, and Route 53 A alias. Existing certificate candidates, custom domains or address/delegation records stop this creation-only flow for separate reuse/ownership review. The application parent stacks, APIs/stages/routes/authorizers, frontend, backend and tools URLs are not updated.

scripts/deploy-api-domain.py --prepare --capture PRIVATE_AUDIT --environment dev stages an unexecuted CREATE change set after verifying the explicit account/region, fresh API snapshots for both environments, DNS/CAA state, absent target resources/stack, and public nameservers using HTTPS DNS resolvers. Permission and delegation failures block staging. Review the exact four Add entries before using --execute with the actual printed release-plan.json. The script rechecks the target, source template, parameters, change-set scope and freshness before execution; it writes an execution journal first and rejects duplicate execution requests.

Post-deployment verification checks companion resource ownership, regional certificate issuance, exact mapping and alias, unchanged settings for both existing APIs, preserved other-environment domain configuration, HTTPS/TLS and unauthenticated HTTP 401 at a known JWT-protected read route. It does not treat unauthenticated 401 as authenticated workflow acceptance. The frontend remains unchanged. DNS/TLS propagation can be checked again with --verify PLAN without executing another deployment. Inspect failed/interrupted stack creation before any retry; the helper never deletes/recreates a stack automatically.

Validation: 67 domain audit/release tests passed, including 43 new deployment checks for absent-resource and drift gates, public delegation, exact additions-only scope, journaled execution and DNS/certificate/mapping/TLS/HTTP verification. git diff --check passed. No certificate, custom domain, DNS record or change set was created from this development workspace.

Next: user stages DEV using the existing private audit and shares only the printed scope/result. After DEV creation, verify authenticated API parity before changing its frontend. Prepare PROD separately only after DEV acceptance, using a refreshed audit that includes the deployed DEV domain. Complete the resulting live ownership/runtime/SAM reconciliation afterward. Operational account/API/zone/stack identifiers and private capture/release paths remain outside this public record.

# Additive API custom domains

The user resumed the deferred API URL cleanup after the leadership demo. This
is separate from completing SAM source/runtime parity. The cluster bootstrap
configuration correction is verified, the existing-cluster GitOps URL repair
was pushed, and tool buttons were confirmed enabled. Actual tool launches were
not separately reported after that repair.

## Intended routing

| Environment | Custom API base | Existing stage | Mapping path |
| --- | --- | --- | --- |
| DEV | https://api-dev.navigan.click/api/v1 | v1 | empty |
| PROD | https://api.navigan.click/api/v1 | v1 | empty |

An empty root mapping selects the existing stage while preserving the application's
/api/v1 route prefix. Do not map api/v1 as a nonempty base path: mapping-path
stripping would change the route path sent to the existing API. Existing
execute-api URLs, stages, API IDs, routes, JWT authorizers and backend services
remain in place. No redirect or removal of the old endpoint is planned.

## Read-only first step

scripts/audit-api-domain-readiness.py requires an explicit AWS account, region and
distinct DEV/PROD API IDs. It inventories only existing HTTP APIs/stages/routes/
integrations/authorizers, the two target custom domains and their mappings,
matching public Route 53 zone/target records, parent CAA records and regional
ACM certificate metadata. All certificate key types are included; wildcard SANs
match a single hostname label. Existing domain/DNS mappings are reported for
review rather than overwritten. Errors do not trigger resource creation.

The script has no apply mode. Full observations and summary.json are saved in
a private directory with restrictive permissions. Share only summary.json.
Successful capture does not authorize deployment or establish live DNS
delegation, certificate compatibility, authenticated parity or zero downtime;
deploymentReady remains false. Public DNS delegation must be checked before
preparing a DNS change. No certificate keys, application credentials or tokens
are requested.

Validation: 24 focused tests passed for read-only calls, account/stage/endpoint
checks, API/record pagination, exact mapping inventory, certificate hostname and
validity handling, permission failures and private output. No live AWS audit or
resource changes were performed from the development workspace.

## Remaining delivery sequence

1. Review the user-run audit, DNS delegation, certificate candidates and conflicts.
2. Prepare scoped, additive CloudFormation ownership for only the new domains,
   mappings, DNS records and any required certificate validation resources.
   Reuse a suitable issued regional certificate when verified. Never overwrite
   existing records or import resources without reviewing actual ownership.
3. Deploy and validate DEV's new endpoint alongside its original endpoint.
   Confirm TLS, route behavior, Cognito JWT authorization and authenticated reads.
4. Update the DEV frontend API origin/base path in a separate controlled release
   and retain its previous configuration/task as rollback evidence. Determine
   whether DEV is currently local or hosted from live evidence first.
5. Repeat for PROD after DEV acceptance. Do not change connector, gateway or
   backend callback URLs merely to switch the frontend API target.
6. Capture the resulting live state for SAM reconciliation, include ownership of
   any new companion stacks, refresh/review the source contract, and complete
   no-op/identity/runtime and authenticated workflow acceptance. Custom-domain
   rollout alone does not complete SAM parity.

AWS references:
- https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-mappings.html
- https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-custom-domain-names.html
- https://docs.aws.amazon.com/acm/latest/APIReference/API_Filters.html

Live account/API/stack identifiers, certificates and capture paths remain private
operator inputs, outside this public runbook.
