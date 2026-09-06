# Navigan frontend

The frontend is a Next.js App Router application in `frontend/`. It uses React, strict TypeScript,
Tailwind CSS, TanStack Query (React Query), Axios, Zod, and `oidc-client-ts`.
Only Customer Management is implemented. Environment, Cluster, and Application Management have
explicit planned-module pages; they do not simulate provisioning or call unimplemented APIs.

## Run locally

Use Node.js 22 or newer and npm. From the repository root:

```bash
cd frontend
npm ci
cp .env.example .env.local
```

Set `NEXT_PUBLIC_OIDC_CLIENT_ID` to the **public Cognito app client ID** accepted by your gateway JWT
authorizer. This value was not supplied, so the application intentionally shows a configuration state
until it is set. Configure the remaining environment values below, then:

```bash
npm run dev
```

Open `http://localhost:3000`. The root redirects to `/customers`.
For a production Node.js deployment:

```bash
npm run build
npm start
```

Serve the application through HTTPS in production. Public environment variables are embedded at build
time; rebuild after changing the Cognito app client, issuer, scopes, or public application URL.
The Next.js server must be able to reach API Gateway over HTTPS. This is a server-rendered deployment,
not an S3-only static export: the same-origin API route requires a running Next.js server.
No AWS resources are provisioned by these commands.

## Configuration

| Variable | Purpose / default |
|---|---|
| `NAVIGAN_API_ORIGIN` | Server-only gateway host: `https://q0i8bcekw1.execute-api.ap-south-1.amazonaws.com`. |
| `NAVIGAN_API_BASE_PATH` | Server-only stage plus resource prefix: `/v1/api/v1`, matching the repository SAM template. |
| `NEXT_PUBLIC_OIDC_AUTHORITY` | `https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_GtWAW9Owz`. |
| `NEXT_PUBLIC_OIDC_CLIENT_ID` | Required Cognito public app client ID; no client secret. |
| `NEXT_PUBLIC_OIDC_SCOPE` | `openid profile email navigan/api`; the API access scope must match gateway configuration. |
| `NEXT_PUBLIC_APP_URL` | Browser application origin, e.g. `http://localhost:3000`; blank uses the current browser origin. |
| `NEXT_PUBLIC_COGNITO_DOMAIN` | Optional HTTPS Cognito managed-login domain for full provider logout. |
| `NEXT_PUBLIC_CORPORATE_LOGO_URL` | Optional path to an approved corporate logo under `public/`. |

The default upstream collection URL is
`https://q0i8bcekw1.execute-api.ap-south-1.amazonaws.com/v1/api/v1/customers`.
If the deployed API uses a different stage or custom-domain mapping, adjust only
`NAVIGAN_API_BASE_PATH` to match it. Do not append `/customers` to that variable.
`.env.local` is ignored by Git. No database connection strings, passwords or AWS credentials belong
in this frontend. The frontend talks only to the API.

## Cognito setup

1. Use a public app client without a client secret. Enable authorization code flow and PKCE-compatible
   browser sign-in. Configure a Cognito managed-login domain for the user pool.
2. Register the exact callback URL `http://localhost:3000/auth/callback` for local development and
   `https://YOUR_FRONTEND_HOST/auth/callback` for production. Register corresponding `/login` sign-out URLs.
3. Enable `openid`, `profile`, `email`, and the configured custom resource-server scope `navigan/api`
   on the app client. Update the scope environment setting if the gateway uses another scope.
4. Ensure the gateway audience accepts this app client ID and the issuer matches the user pool.
5. Provision access-token claims used by the existing Lambda authorization implementation:
   `roles`, `customer_ids`, `platform_scope`, and `customer_create`. Use administrator-controlled
   provisioning/token customization. Standard `cognito:groups` alone is not the `roles` claim expected
   by the backend. Supported roles are `CLOUD_ENGINEER`, `PLATFORM_ARCHITECT`, and `SERVICE`.
6. Set the frontend environment settings and restart/rebuild. Sign in as separately scoped engineer
   and architect users to exercise the maker/reviewer flow.

Sign-in uses `oidc-client-ts` authorization code flow with PKCE and OAuth state validation. The library
stores per-tab session state/tokens in `sessionStorage`; no access token is placed in localStorage,
URLs, logs or source code. Refresh tokens, when returned by Cognito, are used by the library for renewal.
A failed renewal or API 401 clears the local session and query cache. Access-token claims control UI
visibility only; the gateway and Lambda remain the security authority. Signed-in users cannot select
or override roles in the frontend. Identity changes clear cached customer data.

With `NEXT_PUBLIC_COGNITO_DOMAIN`, Sign out also redirects to the Cognito logout endpoint. Without it,
sign-out clears the local application session; the Cognito browser session may remain active.

## Feature-based structure

| Directory | Responsibility |
|---|---|
| `src/app/` | Thin Next.js route composition, root providers, global styles, error boundaries. |
| `src/app/(workspace)/` | Shared protected application shell and module routes. |
| `src/app/api/platform/[...path]/` | Same-origin server proxy to supported API routes. |
| `src/shared/auth/` | Cognito session lifecycle, identity parsing, provider and sign-in gate. |
| `src/shared/api/` | Axios authentication/error interceptors, typed error model, version headers, proxy allowlist. |
| `src/shared/components/` | Header/sidebar shell, shared controls, errors, loading, pagination and native dialogs. |
| `src/shared/config/` | Navigation registry for the four modules. |
| `src/modules/customer-management/model/` | Domain types, runtime schemas and frontend workflow affordances. |
| `src/modules/customer-management/services/` | Typed operations for all 18 APIs. |
| `src/modules/customer-management/hooks/` | React Query keys, reads, mutation invalidation and stable write keys. |
| `src/modules/customer-management/components/` | List, detail, forms, provider editor, workflow dialogs, history/review/audit views. |
| `src/modules/{environment,cluster,application}-management/` | Isolated placeholder entry points for future modules. |
| `tests/` | Contract, proxy, policy and component integration tests. |

Customer feature state lives inside its components/hooks. Shared components do not import customer
feature code. Next routes compose features rather than containing business logic. Add future module
models/services/hooks/components under their own module, extend the server proxy allowlist deliberately,
and keep using the same authenticated Axios client and application shell.

## Customer Management functionality

- Paginated listing; search by ID/name; status/provider filters; sorting and page-size selection.
- Summary counts use the API's scoped totals, not fabricated or current-page counts. Failed/unavailable
  metrics display an em dash, not zero.
- Draft creation with customer name, description, contacts and provider associations.
- Detail view with lifecycle metadata, contacts, cloud associations and version.
- Master-data/contact editing only in `DRAFT` or `REJECTED` for Cloud Engineers.
- A separate provider editor uses the dedicated GET/PUT cloud-provider endpoints.
- Submit/resubmit, start review, approve/reject, activate, suspend/reactivate, and deactivate dialogs.
- Mandatory reasons for rejection/suspension/deactivation; independent reviewer rules mirrored from
  the backend; deactivation is terminal in the currently implemented workflow.
- Paginated lifecycle history and reviews; audit log shown only for Platform Architects.
- Loading, empty, validation, permission, authentication, service-failure and stale-version states.

### Write correctness

Every write sends an `Idempotency-Key`; existing-customer mutations also send the current `If-Match`
version. The form/dialog captures the version being edited instead of silently rebasing unsaved input
onto a background response. A failed request retains its key for an identical manual retry while the
form/dialog remains mounted. Changing body/version or completing a successful write starts a new request.
Closing the page loses that in-memory retry context; after an ambiguous failure, retry in the same view
or inspect the latest record before starting a new request.

Mutation retries are never automatic. Success invalidates customer lists, counts, details and history.
A 409 preserves unsaved form values and requires the user to review the latest record. The master form
and cloud-provider editor save separately so two independent API transactions are not presented as
one atomic operation. Update payloads exclude provider associations and system-controlled fields.

### Same-origin API layer

Browser requests go to `/api/platform/customers/...`. The Next.js server forwards only allowlisted
Customer Management routes to the fixed configured HTTPS gateway host. It forwards the bearer token,
version and idempotency headers, with a generated correlation ID. It does not forward browser cookies
or arbitrary headers and does not follow upstream redirects. JSON request bodies are capped at 64 KiB.
Responses use `Cache-Control: no-store`; ETag/correlation/retry headers are preserved. Error logging
includes only status, error code and correlation ID—not tokens, request bodies, contacts or passwords.

This avoids requiring cross-origin browser access to the gateway. JWT verification and customer scoping
remain in the existing gateway/Lambda implementation; the proxy does not grant permissions itself.

## Brand implementation

Reviewed `docs/BrandCheck_ExternalAssets.pdf`, especially pages 9–12. The UI applies the document's
black application header, green-led palette, Open Sans typography, and functional-only red/amber states.
Open Sans is bundled via `@fontsource/open-sans`; no runtime Google Fonts request is required.
There are keyboard focus styles, a skip link, semantic forms/tables, visible text status labels,
keyboard-operated tabs, native modal focus behavior, responsive layouts and reduced-motion support.

The referenced live design-system site was not accessible here. The PDF itself does not include a
standalone approved logo asset or the complete design-system component library. Navigan uses a text
product name and supports inserting an approved logo without redrawing it. These implementation choices
are not a claim of formal brand clearance; follow the PDF's brand review process before external release.
The supplied provider catalog is AWS/AZURE/GCP/OCI. `OTHER` is optional in the specification and is not
seeded by the backend, so the UI does not offer it. Existing future provider codes returned by the API
are preserved and displayed.

## Verification

```bash
npm run typecheck
npm test
npm run format:check
npm run build
```

The frontend CI workflow runs these checks using the committed lockfile. Tests mock service boundaries
and use test-only customer fixtures; the shipped UI has no mock-data or demo-mode fallback.
No live customer mutation is performed by tests. A production build validates routes and bundling;
it does not prove the deployed gateway, Cognito configuration or brand approval.

Before production use, sign in through the configured Cognito client and exercise creation, provider
editing, submission, independent review, approval/activation, suspension/reactivation and deactivation
against a non-production customer. Verify 401/403 behavior, tenant isolation and stale-version recovery
with two sessions. Browser visual/accessibility review and authenticated live smoke testing remain
deployment validation steps.

## ECS Fargate hosting

For Docker image creation, ECR publishing, and a separate HTTPS ECS Fargate stack, follow
[the ECS deployment guide](frontend-ecs.md). It includes build-time Cognito configuration,
private subnet prerequisites, deployment scripts and digest-based rollback.
