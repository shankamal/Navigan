# Deployment: Aurora PostgreSQL and AWS Lambda

## 1. Database and network prerequisites

Provision an encrypted Aurora PostgreSQL-compatible cluster in private subnets (validate against your selected
supported Aurora major version; CI uses PostgreSQL 16). Enable automated backups/PITR, deletion protection,
performance monitoring and a recovery runbook. Section 2 creates the `navigan` database before migrations.

Provision RDS Proxy with TLS required, targeting that cluster. Configure both API and publisher login secrets
in the proxy's authentication configuration. Store each LOGIN's username/password in separate Secrets Manager
secrets, encrypted by a KMS key. The SAM stack takes these ARNs and the proxy endpoint as inputs.

Allow Lambda security groups -> proxy:5432 and proxy -> Aurora:5432. Keep Aurora inaccessible from the internet.
Provide Secrets Manager and EventBridge VPC endpoints or NAT connectivity for the private Lambdas. Restrict
endpoint policies and database security groups to the service roles/security groups.

## 2. Create the database, then apply migrations and roles

`migrate.py` creates schemas and tables **inside an existing database**. It cannot create the database
it connects to. Always use this order: connect to `postgres` -> create `navigan` -> connect to `navigan`
-> run migrations -> grant runtime roles. The database creator becomes its owner; use the designated
migration administrator for initial setup, or have the database administrator grant the migration owner
the required database/schema privileges.

### 2.1 Working directory and Python environment

Run from the cloned Navigan repository. If it is already installed, activate the existing environment:

```bash
cd /navigan/Navigan
git pull --ff-only origin main
source .venv/bin/activate
python --version
python -m pip --version
psql --version
```

Adjust the directory if your checkout is elsewhere. On a fresh installation, create the environment
with `python3.12 -m venv .venv`, activate it, then run `python -m pip install -e '.[dev]'`.
Python 3.12 is the repository's tested CI and Lambda runtime. The reported Python 3.14 traceback is
specifically a missing-database error; changing Python versions will not create the missing database.
Use `python -m pip` to install into the active interpreter. The `psql` PostgreSQL client must also be
installed on the setup host; pip does not install it.

### 2.2 Recovery when MIGRATION_DATABASE_URL is already configured

If you received `FATAL: database "navigan" does not exist`, run this block in the same shell where
`MIGRATION_DATABASE_URL` was set. It preserves your connection credentials, host, port and TLS options,
and changes only the bootstrap connection's database to `postgres`. Your configured login must be
permitted to create a database; otherwise have the database administrator perform creation first.

```bash
: "${MIGRATION_DATABASE_URL:?Set MIGRATION_DATABASE_URL before continuing}"
ADMIN_DATABASE_URL="$(python - <<'PYTHON'
import os
from psycopg.conninfo import make_conninfo
print(make_conninfo(os.environ["MIGRATION_DATABASE_URL"], dbname="postgres"))
PYTHON
)" && export ADMIN_DATABASE_URL &&
psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -v database_name=navigan \
  -f database/bootstrap/create_database.sql &&
psql "$MIGRATION_DATABASE_URL" -v ON_ERROR_STOP=1 -c 'SELECT current_database(), current_user;' &&
python scripts/migrate.py &&
psql "$MIGRATION_DATABASE_URL" -v ON_ERROR_STOP=1 -f database/bootstrap/roles.sql
```

The `&&` operators stop the sequence if any step fails. The connection check must report `navigan`.
Creation is safe to rerun: the bootstrap script skips an existing database. It does not delete data.
Do not run the creation script with `psql --single-transaction` or inside `BEGIN`/`COMMIT`.
Do not paste the connection variables into logs or support messages because they can contain passwords.

### 2.3 Fresh connection configuration

If no connection variables are configured yet, use the following setup before running section 2.2.
The prompts avoid putting a literal database password into shell history. Use the Aurora **writer DNS
endpoint** and an absolute path to the downloaded RDS CA bundle, so hostname verification can succeed.
Use a database administrator/migration login, not an application runtime login.

```bash
read -r -p 'Aurora writer DNS endpoint: ' PGHOST
read -r -p 'Database administrator/migration username: ' PGUSER
read -r -p 'Absolute RDS CA bundle path: ' PGSSLROOTCERT
read -r -s -p 'Database password: ' PGPASSWORD
printf '\n'
export PGHOST PGUSER PGSSLROOTCERT PGPASSWORD
export PGPORT=5432
export PGSSLMODE=verify-full
export MIGRATION_DATABASE_URL='dbname=navigan'
```

Both psql and psycopg use these standard PostgreSQL connection environment variables. Keyword connection
strings such as `dbname=navigan` are supported even though the environment variable is named `_URL`.
Download the official certificate bundle using the command in section 3 before setting PGSSLROOTCERT.
If using a self-managed PostgreSQL test server, configure its appropriate DNS endpoint and trusted CA.
Keep the currently working connection settings when applying the recovery block to an existing setup.

After setup, remove temporary password variables with `unset PGPASSWORD`. Use your managed credential
process or a permission-restricted PostgreSQL password file for repeated administrative operations.

### 2.4 Verify installation

```bash
psql "$MIGRATION_DATABASE_URL" -v ON_ERROR_STOP=1 -c '\dt customer_management.*'
psql "$MIGRATION_DATABASE_URL" -v ON_ERROR_STOP=1 \
  -c 'SELECT provider_code, provider_name FROM customer_management.cloud_providers ORDER BY display_order;'
psql "$MIGRATION_DATABASE_URL" -v ON_ERROR_STOP=1 \
  -c 'SELECT name, applied_at FROM platform.schema_migrations ORDER BY name;'
```

Expect the seven Customer Management tables, AWS/AZURE/GCP/OCI provider records, and migration
`001_customer_management.sql`. Run verification before clearing credentials, or authenticate again.

### 2.5 Troubleshooting setup failures

| Error | Resolution |
|---|---|
| `database "navigan" does not exist` | Create it through a connection to `postgres` using section 2.2; then rerun migrations. |
| `permission denied to create database` | Use a database administrator with CREATEDB permission; do not grant this to the Lambda login. |
| `CREATE DATABASE cannot run inside a transaction block` | Run the psql bootstrap script without `--single-transaction`. |
| Missing `MIGRATION_DATABASE_URL` | Export it in the same shell that runs `python scripts/migrate.py`. |
| `permission denied for database/schema` | Confirm the migration login owns the database or has the required grants. |
| `permission denied to create role` | Have the database administrator run `database/bootstrap/roles.sql` against `navigan`. |
| Certificate/hostname verification error | Use the database DNS endpoint matching its certificate and the correct trusted CA bundle. |
| `psql: command not found` | Install the PostgreSQL client package for your Amazon Linux release; Python dependencies do not supply psql. |

[PostgreSQL database creation documentation](https://www.postgresql.org/docs/current/manage-ag-createdb.html)
explains connecting to `postgres` first. [CREATE DATABASE requirements](https://www.postgresql.org/docs/current/sql-createdatabase.html)
cover privileges and the restriction on transaction blocks.

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

### 4.1 Prepare Docker on the Amazon Linux build host

If `sam build --use-container` reports:

```text
Error: Running AWS SAM projects locally requires a container runtime. Do you have Docker or Finch installed and running?
```

SAM cannot find or connect to a working container runtime. A Python virtual environment does not
install or start Docker. Check the operating system first:

```bash
cat /etc/os-release
uname -m
```

For **Amazon Linux 2023**, install Docker:

```bash
sudo yum install -y docker
```

For **Amazon Linux 2**, use its Docker package source instead:

```bash
sudo amazon-linux-extras install docker -y
```

Then start Docker, enable it after reboot, and verify that the daemon is accessible:

```bash
sudo systemctl enable --now docker
docker --version
docker info
```

The reported shell is running as `root`, so Docker group membership changes are unnecessary.
For a non-root `ec2-user` account, an administrator can run
`sudo usermod -aG docker ec2-user`; sign out and reconnect before running `docker info`.
Docker group membership grants root-level privileges; limit it to trusted build users.

Proceed only after `docker info` succeeds. Run the build from the Navigan repository root.
The template targets `python3.12` and `x86_64`; prefer an x86_64 build host. An ARM/Graviton host
needs working x86_64 emulation or a separate x86_64 builder. The container supplies the Python 3.12
build environment even if the active host virtual environment uses another Python version.

### 4.2 Validate, build and deploy

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

### 4.3 Troubleshoot container builds

| Symptom | Action |
|---|---|
| `docker: command not found` | Install Docker using section 4.1 for your Amazon Linux release. |
| `Cannot connect to the Docker daemon` | Run `sudo systemctl status docker --no-pager`, then `sudo systemctl start docker`. If startup fails, inspect `sudo journalctl -u docker -n 50 --no-pager`. |
| Permission denied on the Docker socket | Use the approved build account and the group setup in section 4.1; reconnect before retrying. Do not make the socket world-writable. |
| `docker info` succeeds but SAM still reports no runtime | Run both commands as the same user in the same shell. Check `docker context show` and `printenv DOCKER_HOST DOCKER_CONTEXT` for an unintended remote endpoint; remove stale overrides only if the local daemon is intended. Retry with `sam build --debug --use-container --template infrastructure/template.yaml`. |
| Build image download or dependency download fails | The build host needs outbound HTTPS and DNS access to the SAM build image registry (`public.ecr.aws`) and dependency sources such as PyPI, through your approved internet/NAT/proxy path. |
| `exec format error` | Verify the host architecture and x86_64 container support; use an x86_64 builder for the current template. |

Keep `--use-container` for the documented build so psycopg binary dependencies match Lambda's
Python 3.12/Linux/x86_64 environment. Removing it requires a compatible local Python 3.12 toolchain
and dependency build environment; a Python 3.14 virtual environment alone is not sufficient.
Building prepares artifacts; only the subsequent deploy step creates or updates AWS resources.

References: [AWS SAM Docker installation](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-docker.html)
and [AWS SAM container builds](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/using-sam-cli-build.html).

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

## Explicit API Gateway routes

The Customer Management Lambda has 18 explicitly configured method/path integrations in
`infrastructure/template.yaml`, matching `docs/openapi.json`. Every route has the EnterpriseJwt
authorizer and configured OAuth access scope, with payload format 2.0 and a 29-second integration timeout.
Unsupported paths/methods are rejected by API Gateway before reaching Lambda. Existing module RBAC and
customer scope checks still apply inside Lambda.

After deployment, the stack outputs `ApiId`, `ApiBaseUrl` and `ApiUrl` (Customer Management collection).
Use the gateway console or `aws apigatewayv2 get-routes --api-id <ApiId>` to inspect the deployed routes.
New modules should add explicit HttpApi events referencing the shared `Api` resource and retain authorizer
and scope configuration. The route-contract test prevents missing or extra Customer Management routes.

[AWS SAM HttpApi event reference](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/sam-property-function-httpapi.html)
