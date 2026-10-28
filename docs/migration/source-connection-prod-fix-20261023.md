## Current requirement and PROD delivery trust — 23 October 2026

User clarified: an authorized customer should register an association with the same existing healthy physical source connector in the SAME Navigan instance, without another agent installation per customer. The prior source-scoped installation change prevents resource collisions but is NOT the required shared-connector association implementation. Do not present it as the final lifecycle solution or require retirement/reassignment of JPMC records. Keep customer-scoped permissions, explicit authorization of additional customer bindings, assessment/artifact isolation and association revocation. Source agent tokens must not be copied between customer records. DEV connectivity alone does not prove PROD connectivity; the agent's actual API endpoint/connector ID must be checked first.

User successfully executed the scoped API plan /mnt/b/Langchain_Ai/navigan-deploy-tmp/navigan-prod-migration-api-_efn9ga1/release-plan.json for code 064a72a058aa4a1d01006340ec69863505f188f1. MigrationFunction updated; MigrationIntegration unchanged dependency verified. Frontend remains :9; later UI changes are not deployed. Subsequent Install connector failed before SSM submission: CloudWatch correlation 052c7188-be32-45bd-a9d2-aed2ec8341f0 and e803245c-f2e1-4f56-947f-1fb06e161997 reported AccessDenied at source_connector_installation.py:309 (STS AssumeRole). This is not a database failure despite transaction-wrapper logging.

Live user diagnostic established identity-policy sts:AssumeRole evaluation allowed for PROD MigrationFunctionRole-kPeJA6r1VbOE with no missing context. NaviganSourceConnectorDeliveryRole trusted only DEV MigrationFunctionRole-zfZY0tTybea6. User then added exact PROD principal via Sid NaviganProductionSourceDelivery, preserving existing DEV statement and requiring sts:ExternalId matching SRC-*. Output confirmed update and verification. Private original trust backup: /mnt/b/Langchain_Ai/navigan-deploy-tmp/navigan-delivery-trust-v54qebuc/original-trust.json. No connector installation, customer reassignment or assessment cancellation was performed by that IAM update.

Next: read-only SSM inspection of source host i-08e28d9b2242cbd53 using /etc/kubernetes/admin.conf, namespace navigan-migration. Print only deployment identity/readiness and public NAVIGAN_API_BASE_URL/NAVIGAN_SOURCE_CONNECTOR_ID; never connector tokens, secrets or complete environment data. Compare with configured PROD connector API endpoint. Then implement the explicit shared-connector customer binding flow through APIs/connector assignment/report authorization. Generic AWS access failures also need clear client-safe errors. Do not blindly repeat Install connector simply to associate another customer. Original goal remains testing the DEV-validated migration/discovery/scope/artifact collection/export workflow end to end in PROD. Live functionality remains unverified.

---

# Source connection lifecycle correction — 23 October 2026

## Intended behavior

For an authorized customer, reuse an existing source registration across assessments. A fresh heartbeat proves the connector is live. A missing heartbeat allows installation/restoration for that registration using its own stable Kubernetes deployment, credentials, service account and RBAC names. A different customer's registration on the same test host must not be overwritten, reassigned or silently exposed.

Source registrations remain customer scoped. Sharing a physical Kubernetes lab is an administrator-authorized source connection, not permission to read another customer's Navigan records. No customer ownership, assessment status or target configuration is changed by this correction.

## Change and compatibility

The former fixed navigan-source-connector and navigan-migration-image-pull names caused replacement risk and the host-wide installation guard. New AWS SSM installations use navigan-source-<32-character source UUID> and matching suffixes. Namespace navigan-migration stays in place. No legacy resource is deleted or updated except reapplying the existing Namespace declaration. Active existing connectors are reused. Retrying a registration targets the same deterministic resources.

Same-customer physical source registration lookup is protected by the existing advisory lock, excludes revoked registrations, and prefers active, unexpired connectors with a recent heartbeat. Different customer IDs are never merged. API source enrollment revokes connector credentials only for the requested source ID. No connector agent image change is needed: the image, API origin, scoped connector ID/token and read-only Kubernetes permissions retain the same contract.

The frontend consumes the existing installationCheck API, handles registered versus verified state, reuses same-customer matches, refreshes registrations after creation and avoids reinstalling a live registration returned by backend reuse. API assessment creation reports duplicate customer/name conflicts clearly, including cancelled names.

## Release order

Use the existing WSL checkout without resetting or cleaning user files.

```bash
cd /mnt/b/Langchain_Ai/Navigan-migration-test
git pull --ff-only origin new_migration_approach_18oct26

TMPDIR=/mnt/b/Langchain_Ai/navigan-deploy-tmp \
/mnt/b/Langchain_Ai/navigan-deploy-venv/bin/python \
  scripts/deploy-migration-api-prod.py --profile navigan --prepare
```

Inspect the printed scoped plan and execute its NEW release-plan.json with the same script's --execute argument. Do not reuse October's already executed plan. This deploys only scoped migration API changes using the existing release guards and rollback records. No database migration or collector deployment is required.

After API deployment, the current PROD frontend (:9 at time of correction) can exercise Install connector for the Db Schenker pending source. The backend correction is compatible with it. Deploy the updated frontend separately using scripts/deploy-frontend-prod.py --profile navigan --prepare, then --execute of that newly printed plan. The frontend release script saves the actual currently running task as rollback; do not hardcode a future candidate number.

## Functional verification

1. Sign in afresh on navigan.click with the correct customer privileges.
2. Open the saved Db Schenker draft (or create an assessment with an unused customer/name).
3. Select its existing source registration. Save the draft. A saved registration alone is not a heartbeat.
4. If verification finds no recent heartbeat, Install connector (or Restore connector) through the API. Existing JPMC/DEV resources and historical assessments must remain unchanged.
5. Confirm the SSM command succeeds and a recent heartbeat arrives. Verify connection, then continue to discovery.
6. Repeat a new assessment for the same customer/source: source ID is reused, no extra connector installation when healthy.
7. For a different authorized customer/source registration, installation resources and credentials must be distinct; no cross-customer records appear.
8. Test duplicate assessment names: clear conflict feedback instead of INTERNAL_ERROR.
9. Continue the original DEV-tested sequence in PROD: discovery/assessment, scope, files/images collection and export. Validate actual artifact status and private S3 paths; deployment does not prove collection or target readiness.

If SSM delivery, IAM trust, image pulls or heartbeat calls fail after the host-wide block is removed, use the returned command/correlation ID and sanitized logs to resolve that actual failure. Do not bypass authorization or edit customer associations in SQL. The repository tests mock AWS/Kubernetes and are not live PROD proof.

## Local validation

78 backend tests and 44 frontend connection/discovery tests passed, as did frontend TypeScript and a local production build. The embedded installer was executed with mocked subprocess/network calls; generated YAML proves separate deployments, both secret types, service accounts, cluster roles/bindings and selectors across registrations and stable names on retries. Tenant source access and fresh-heartbeat protections remain tested.
