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
