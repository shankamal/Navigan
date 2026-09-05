# Deployment: Aurora PostgreSQL and AWS Lambda

## 1. Database and network prerequisites

Provision an encrypted Aurora PostgreSQL-compatible cluster in private subnets (validate against your selected
supported Aurora major version; CI uses PostgreSQL 16). Enable automated backups/PITR, deletion protection,
performance monitoring and a recovery runbook. Create a `navigan` database with an administrative login.

Provision RDS Proxy with TLS required, targeting that cluster. Configure both API and publisher login secrets
in the proxy's authentication configuration. Store each LOGIN's username/password in separate Secrets Manager
secrets, encrypted by a KMS key. The SAM stack takes these ARNs and the proxy endpoint as inputs.

Allow Lambda security groups -> proxy:5432 and proxy -> Aurora:5432. Keep Aurora inaccessible from the internet.
Provide Secrets Manager and EventBridge VPC endpoints or NAT connectivity for the private Lambdas. Restrict
endpoint policies and database security groups to the service roles/security groups.

## 2. Apply SQL migrations and roles

From an authorized network location, set `ADMIN_DATABASE_URL` to an administrator connection to the existing
`postgres` database. Use the migration-owner login for `MIGRATION_DATABASE_URL`, not the Lambda credentials:

```bash
pip install -e '.[dev]'
export MIGRATION_DATABASE_URL='postgresql://MIGRATION_USER:PASSWORD@CLUSTER_WRITER:5432/navigan?sslmode=verify-full&sslrootcert=/path/global-bundle.pem'
psql "$ADMIN_DATABASE_URL" -v database_name=navigan -f database/bootstrap/create_database.sql
python scripts/migrate.py
psql "$MIGRATION_DATABASE_URL" -v ON_ERROR_STOP=1 -f database/bootstrap/roles.sql
```

The runner serializes migrations with an advisory lock, applies them transactionally, records SHA-256 checksums,
and refuses edited previously-applied migrations. Add new numbered files for upgrades. DDL and initial provider
master data are in `001_customer_management.sql`. The script is compatible with Aurora PostgreSQL and requires
no superuser-only extensions. Bootstrap roles require an administrator permitted to create/grant roles.

Create separate LOGIN users using your secure administrator process and grant:

```sql
GRANT navigan_api TO your_api_login;
GRANT navigan_events TO your_event_publisher_login;
```

Do not grant schema ownership, CREATE, elevated role membership, BYPASSRLS or broad table privileges to runtime
users. The migration owner retains administrative rights. No application passwords are included in repository SQL.
The API login's restricted UPDATE(active) privilege on the provider master allows PostgreSQL FOR SHARE locks;
the application has no route to change provider master data.

Migrations are forward-only. For recovery, use Aurora PITR/snapshot restore to a new cluster, validate and switch
the proxy target under your recovery procedure; do not DROP production schemas as a rollback technique.

## 3. Certificate layer

Download the official RDS CA bundle using your approved build process and package it into a Lambda layer:

```bash
mkdir -p ca-layer/certs
curl --fail --location https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem -o ca-layer/certs/global-bundle.pem
(cd ca-layer && zip -r ../rds-ca.zip certs)
aws lambda publish-layer-version --layer-name navigan-rds-ca --zip-file fileb://rds-ca.zip --compatible-runtimes python3.12
```

Pass the resulting LayerVersionArn to `RdsCaLayerArn`. The code uses `sslmode=verify-full` and
`/opt/certs/global-bundle.pem`. Keep the CA bundle updated through a reviewed dependency process.

## 4. Identity configuration and SAM deploy

Configure your OIDC provider with issuer/audience, an API access scope (default `navigan/api`) and administrator-
controlled role/customer claims documented in architecture.md. Never allow users to edit platform_scope,
customer_create, roles or customer_ids in self-service profiles.

```bash
sam validate --lint --template infrastructure/template.yaml
sam build --use-container --template infrastructure/template.yaml
sam deploy --guided
```

Use container build to package psycopg binary dependencies for Lambda Linux/x86_64. Supply all parameters:
issuer, audience, scope, database name, proxy host, API secret ARN, publisher secret ARN, secrets KMS ARN,
private subnet IDs, Lambda security group IDs and CA layer ARN. Review IAM changes in the change set.

The stack deploys an HTTP API, Customer Management Lambda, outbox Lambda, EventBridge bus, notification
queues/rule, logs and baseline alarms. Aurora, RDS Proxy, identity provider, networking and certificate layer
are external prerequisites so future modules share the established platform foundation.

The default endpoint includes the stage `/v1` followed by `/api/v1/customers`. For a custom domain, map the
stage according to your API naming standard. CORS is not enabled by default; configure explicit allowed
frontend origins when a UI is introduced. Do not create a Function URL. Do not grant users direct Lambda invocation.

## 5. Smoke test and operations

1. Use a Cloud Engineer access token with customer_create entitlement to create a draft.
2. Read its ETag/version, set providers/PRIMARY contact and submit using If-Match.
3. Use an independent, correctly scoped Platform Architect token to start review, approve and activate.
4. Verify status/review history, audit records, EventBridge outbox drain and notification queue messages.
5. Verify unrelated customer access returns 404, unauthorized actions return 403, stale writes return 409.
6. Verify secret rotation, TLS certificate verification, proxy capacity, alarms and backup/restore in staging.
7. Connect the enterprise notification consumer and alarm notification destinations before production rollout.

Logs contain correlation/request IDs and result/latency, without request bodies, contacts or database exception
text. API metrics use CloudWatch Embedded Metric Format. `customers_active_total` counts successful activation/reactivation operations; it is not a current-active-customer gauge. Event publisher metrics report pending count/age and
publish failures. Configure alert destinations and thresholds for the actual SLO/traffic. Secrets cache lasts at
most 60 seconds and is invalidated on connection failure; never retry ambiguous committed writes without the
same Idempotency-Key.

At-rest retention must cover customer contacts AND idempotency response records. Keep database access tightly
restricted and define lawful retention/erasure separately. Do not add arbitrary secrets to free-text fields.
