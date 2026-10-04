# Navigan Portable Delivery Baseline

Baseline name: **NPD-1 — Portable API-First Dev-to-Prod**

Status: Deferred for implementation

Recorded: 11 September 2026

## Objective

Make Navigan portable, API-first and suitable for a controlled promotion from
local development to AWS production without rebuilding release artifacts.

## Non-negotiable constraints

1. Maintain at least two isolated environments:
   - Development: runs locally on a developer laptop.
   - Production: runs in AWS ECS Fargate.
2. The local workflow is:
   - Develop locally.
   - build and deploy the complete local development environment;
   - test locally;
   - promote the tested release to production.
3. Frontend, backend and asynchronous middleware must be independently
   packageable as portable containers.
4. All external business interactions must enter through versioned APIs.
   The Navigan frontend, customer-provided UIs, ServiceNow and automation
   clients must use the same API contracts and authorization rules.
5. Production APIs must be exposed through Amazon API Gateway. Backend
   services must not be directly exposed publicly.
6. Production must promote the exact immutable container image digests tested
   in the development pipeline. Production deployment must not rebuild them.
7. Configuration and secrets must remain external to container images and be
   isolated by environment.
8. Database migrations must be versioned, forward-only and executed as an
   explicit deployment stage.
9. Releases must support health verification, controlled rollout and rollback.
10. The architecture must preserve Navigan's Customer, Environment and Cluster
    module boundaries.

## Target package set

- `navigan-frontend`: Next.js portal and server-side API proxy.
- `navigan-api`: portable HTTP API containing independently organized business
  modules.
- `navigan-worker`: outbox and asynchronous workflow processing.
- `navigan-terraform-runner`: isolated infrastructure execution image.

## Target runtime

### Local development

Docker Compose runs:

- frontend;
- API;
- worker;
- PostgreSQL;
- supporting local emulators or explicitly configured development AWS services.

### AWS production

- Frontend: private ECS Fargate tasks behind an HTTPS Application Load Balancer.
- API: private ECS Fargate service reached through API Gateway and private
  integration.
- Worker: ECS service or scheduled/event-driven ECS tasks.
- Database: Aurora PostgreSQL through RDS Proxy.
- Identity: Cognito or an approved enterprise OIDC provider.
- Images: immutable ECR digest references.

## CI/CD decision

### Pull request validation

- formatting, linting and type checks;
- backend and frontend unit tests;
- PostgreSQL integration tests;
- OpenAPI contract validation;
- container builds;
- dependency, secret and container vulnerability scans;
- Docker Compose smoke test.

### Development release

- build each image once;
- assign a release identifier and source commit;
- publish immutable images;
- deploy the local/testable development package;
- run API, authentication and workflow acceptance tests;
- record test evidence and image digests.

### Production promotion

- require an explicit production approval;
- promote the already-tested image digests without rebuilding;
- apply approved database migrations;
- perform a rolling or canary Fargate deployment;
- run health and API smoke tests;
- automatically roll back when release health gates fail.

## Required implementation work

1. Separate Lambda/API Gateway event handling from core business services.
2. Add a portable HTTP adapter for the backend.
3. Add backend and worker Dockerfiles.
4. Add a complete Docker Compose development environment.
5. Replace WSL-only operational commands with cross-platform deployment tools.
6. Add Fargate infrastructure for the API and worker.
7. Add API Gateway private integration to the Fargate API.
8. Establish a complete versioned OpenAPI contract.
9. Add machine-to-machine OAuth scopes for ServiceNow and automation clients.
10. Add GitHub Actions validation, packaging, development deployment and
    production-promotion workflows.

## Resume instruction

Use this request:

> Resume **NPD-1 — Portable API-First Dev-to-Prod** from
> `docs/portable-delivery-baseline.md`. Review the current repository state
> first, then continue from the first incomplete implementation item. Do not
> deploy or commit without my explicit approval.

