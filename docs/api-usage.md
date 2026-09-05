# Customer Management API

Base path `/api/v1`; JSON only. The SAM stage adds `/v1` before this path in its default invoke URL.
All routes require an API Gateway-validated JWT containing the configured API access scope.

| Method | Path (relative to `/api/v1`) | Role |
|---|---|---|
| POST | /customers | Cloud Engineer + customer_create entitlement |
| GET | /customers | Any supported role, scoped |
| GET | /customers/{customerId} | Any supported role, scoped |
| PUT | /customers/{customerId} | Cloud Engineer, DRAFT/REJECTED |
| GET | /customers/{customerId}/cloud-providers | Any supported role, scoped |
| PUT | /customers/{customerId}/cloud-providers | Cloud Engineer, DRAFT/REJECTED |
| POST | /customers/{customerId}/submit | Cloud Engineer |
| POST | /customers/{customerId}/resubmit | Cloud Engineer, REJECTED only |
| POST | /customers/{customerId}/review/start | Platform Architect |
| POST | /customers/{customerId}/approve | Platform Architect |
| POST | /customers/{customerId}/reject | Platform Architect; reason required |
| POST | /customers/{customerId}/activate | Platform Architect |
| POST | /customers/{customerId}/suspend | Platform Architect; reason required |
| POST | /customers/{customerId}/reactivate | Platform Architect |
| POST | /customers/{customerId}/deactivate | Platform Architect; reason required |
| GET | /customers/{customerId}/status-history | Any supported role, scoped |
| GET | /customers/{customerId}/reviews | Any supported role, scoped |
| GET | /customers/{customerId}/audit-log | Platform Architect, scoped |

Every existing-customer mutation requires `If-Match: <version>`. GET/create/update/action responses
include a version and ETag. Use `Idempotency-Key` on writes to safely retry the identical request,
including the original If-Match. To make a new logical request use a new key and latest version.

Example payload for POST /customers:

```json
{
  "name": "Example Corporation",
  "description": "Multi-cloud customer",
  "contacts": [{"type": "PRIMARY", "name": "Example Contact", "email": "contact@example.com"}],
  "cloudProviders": ["AWS", "AZURE", "OCI"]
}
```

A draft may omit contacts/providers. Submission requires both a PRIMARY contact and an active provider.
A PUT customer request replaces its editable master fields and contacts; it does not replace providers.
Use PUT `/customers/{customerId}/cloud-providers` with `{"cloudProviders":["AWS","OCI"]}` to replace the provider set.

Lifecycle requests accept `{}`, optional `comments`, and `reason` where applicable:

```json
{"reason":"Provider selection needs correction","comments":"Please confirm OCI requirements"}
```

No endpoint accepts status, IDs, version, actor/timestamp, cloud account or cluster fields in request bodies.
Unknown DTO fields are rejected, not silently ignored. Never submit credentials in any free-text field.

List query: `?page=0&pageSize=20&status=ACTIVE&cloudProvider=AWS&search=Example&sort=name,asc`.
Page size 1–100; default 20. Search matches literal case-insensitive substrings of customer ID/name.
Allowed sort fields: name, createdAt, updatedAt, status; direction asc/desc. Optional `createdBy` filter.
History/reviews/audit support page/pageSize and ascending stable order.

Business errors use `{"error":{"code":"...","message":"...","details":{},"correlationId":"..."}}`.
Out-of-scope customer IDs return 404. Unauthorized roles return 403. Invalid state returns 422.
Duplicate, stale version and idempotency conflicts return 409. Structural input errors return 400.
API Gateway can reject tokens/rate limits before Lambda and may use its own gateway error envelope.

Load [openapi.json](openapi.json) in a Swagger/OpenAPI 3.1 viewer for schemas and the full contract.
