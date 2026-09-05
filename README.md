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
infrastructure/            # AWS SAM deployment template
database/                 # See actualdatabase/ directory below
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
export MIGRATION_DATABASE_URL='postgresql://USER:PASSWORD@localhost:5432/navigan_test'
python scripts/migrate.py
export DATABASE_URL="$MIGRATION_DATABASE_URL"
pytest -q
python scripts/generate_openapi.py
```

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
