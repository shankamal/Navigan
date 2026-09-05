# Verification record

Verified on 2026-09-05.

[GitHub Actions run 33974749901](https://github.com/shankamal/Navigan/actions/runs/33974749901)
passed on implementation commit `36980bd5ae67f866c61eae0db09108fe374c2503`:
**133 tests passed, zero skipped**, including all 16 PostgreSQL 16 integration tests.
The migration applied successfully and its second execution was a successful no-op.
Generated OpenAPI matched the checked-in contract and CI lint passed.

Local verification:

- 117 unit, validation, contract, state-machine, RBAC and input-handling tests passed.
- OpenAPI 3.1 schema validated with openapi-spec-validator 0.7.2.
- AWS SAM/CloudFormation template validated with cfn-lint 1.39.1.
- Ruff lint/format and Python bytecode compilation passed.
- 16 PostgreSQL integration tests are included. Native PostgreSQL startup is unavailable in the
  authoring workspace because of process/user permissions. All 16 subsequently passed in GitHub Actions against PostgreSQL 16.

Integration coverage includes real Lambda-to-database CRUD and lifecycle flows, immutable history,
rejection/resubmission, cross-customer isolation, duplicate names, SQL runtime permissions,
atomic provider changes, dependency veto, provider activity, simultaneous writes, simultaneous
idempotent creates, retry deduplication, outbox records and partial event publication.

AWS deployment has not been executed. Aurora networking, proxy/TLS, IAM/OIDC configuration,
load/SLO, notification delivery and operational recovery require target-environment verification.
