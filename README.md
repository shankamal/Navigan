# Navigan

A modular Container Management Platform implemented in Python for AWS Lambda and Aurora PostgreSQL.
The first module is **Customer Management**, based on the supplied Customer Management Specification v2.0.

## Repository layout

```text
src/navigan/
  modules/
    customer_management/   # Lambda controller, DTOs, workflow, service, SQL repository
  shared/                  # Verified identity, errors, database connections, outbox worker
src/requirements.txt       # Lambda package dependencies
samconfig.toml             # SAM build/deploy defaults; guided environment configuration
infrastructure/template.yaml  # Parent stack orchestration
infrastructure/shared/     # Shared API Gateway and EventBridge stack
infrastructure/modules/customer-management/  # Separate Customer Management CFN stack
database/migrations/      # Forward-only PostgreSQL DDL and provider master seed
database/bootstrap/       # Least-privilege database group roles
scripts/                   # Migration runner and OpenAPI generation
tests/                    # Unit and PostgreSQL integration/API/concurrency tests
docs/                     # API contract, architecture, deployment and decisions
.github/workflows/         # PostgreSQL-backed continuous integration
```

New modules belong under `src/navigan/modules/<module_name>/`, with a separate database schema,
Lambda handler and API Gateway route. Shared utilities have no dependency on a business module.

## Implemented capabilities

- All 15 MVP endpoints, plus explicit resubmission, audit log and review-history endpoints (18 total).
- Create/get/list/update customers and replace a normalized set of cloud providers.
- Full onboarding and operational state machine, independent maker/reviewer checks, soft deactivation.
- Verified JWT roles, explicit platform administration scope, customer-scoped reads and writes.
- Submission validation, duplicate prevention, filtering, sorting and pagination.
- Required `If-Match` for existing-customer mutations; transactional idempotency for all writes.
- Append-only audit, status history and review cycles; atomic provider-set updates.
- Transactional outbox, scheduled EventBridge publisher and SQS notification handoff.
- Aurora-compatible schema, migrations, indexes and least-privilege runtime roles.

No cloud account IDs, regions, environments, cluster configuration or cloud credentials are accepted.
Customer contact information is stored only in the contacts table, never in event or audit snapshots.

## Quick start

Python 3.12 and a disposable PostgreSQL 16 database are required for the full suite.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
export ADMIN_DATABASE_URL='postgresql://USER:PASSWORD@localhost:5432/postgres'
psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -v database_name=navigan_test -f database/bootstrap/create_database.sql
export MIGRATION_DATABASE_URL='postgresql://USER:PASSWORD@localhost:5432/navigan_test'
python scripts/migrate.py
export DATABASE_URL="$MIGRATION_DATABASE_URL"
pytest -q
python scripts/generate_openapi.py
```

**Create the database before running migrations.** For Aurora installation and recovery from
`database "navigan" does not exist`, follow [deployment guide section 2](docs/deployment.md#2-create-the-database-then-apply-migrations-and-roles).
The connection strings above are local examples; replace USER/PASSWORD with your test login.

`pytest -q` without `DATABASE_URL` runs unit tests and explicitly skips database tests.
The GitHub Actions workflow starts PostgreSQL and runs both suites. Never point tests at production.
Use a separate migration-owner login for migrations; the Lambda runtime must use the restricted roles.

## Documentation

- [OpenAPI 3.1 contract](docs/openapi.json)
- [API usage and endpoint inventory](docs/api-usage.md)
- [Architecture and future module integration](docs/architecture.md)
- [Implementation policies and specification traceability](docs/implementation-decisions.md)
- [Aurora and Lambda deployment](docs/deployment.md)
- [Verification record](docs/verification.md)

The infrastructure template references an existing Aurora PostgreSQL cluster/RDS Proxy, VPC,
OIDC provider, Secrets Manager secrets and a certificate layer. It does not deploy an Aurora cluster
or create cloud accounts automatically. Notification delivery is a separate consumer integration;
the module publishes review/decision events to an encrypted SQS queue.

## Modular infrastructure deployment

Customer Management runs in its own nested CloudFormation stack, alongside the shared platform stack.
The parent template coordinates their parameters and dependencies. From the repository root:

```bash
sam build --config-file "$PWD/samconfig.toml"
sam deploy --guided --config-file "$PWD/samconfig.toml"
```

The first deployment collects your AWS region, identity, database and network settings. Later deployments
can omit `--guided` after saving those values. Docker is required for the configured container build.
See the [deployment guide](docs/deployment.md#modular-stacks-and-samconfigtoml) for stack ownership,
parameter definitions, adding modules and migration from an already deployed monolithic stack.

## Frontend

The modular Next.js frontend is in `frontend/`. Customer Management includes the directory, details,
create/edit forms, provider management and approval workflow. Environment, Cluster and Application
Management have isolated placeholders. See [frontend setup and architecture](docs/frontend.md) for
Cognito configuration, API integration, startup commands and validation.

## Environment Management

Provider-aware EKS, AKS, GKE and OCI/OKE infrastructure baselines, governed approval
and immutable versions are implemented. See [deployment and module guide](docs/environment-management.md)
and [Environment OpenAPI](docs/environment-openapi.json).
