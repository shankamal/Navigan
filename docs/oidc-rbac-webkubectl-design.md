# Cluster Identity, RBAC, WebKubectl and Dashboard Design

## Decision summary

- Implement EKS first behind provider-neutral service contracts.
- Keep `PLATFORM_ENGINEER` on hold. Use existing dynamic privileges and scopes.
- Cognito authenticates users; Navigan remains the authorization source of truth.
- Use a dedicated Kubernetes OIDC audience/client, not the browser application's client.
- Use stable subject and group identifiers. Never authorize display names.
- Keep EKS IAM access enabled for automation and recovery.
- Manage Kubernetes access through reviewed profiles and assignments, not arbitrary YAML.
- WebKubectl must use short-lived, user-bound sessions; no kubeconfig or shared token reaches the browser.
- All reconciliation must be idempotent, additive, auditable, and preserve unrelated RBAC.

## Current architecture

| Area | Existing foundation | Gap |
|---|---|---|
| Authentication | Cognito JWT authentication and token enrichment | Dedicated Kubernetes OIDC client and claims contract |
| Authorization | Database-backed privileges, ALLOW/DENY, customer/platform/resource scopes | Kubernetes access profiles and effective cluster-access projection |
| Cluster API | Customer-scoped repository, backend action capabilities, lifecycle audit | Identity state, reconciliation operations and access APIs |
| Provisioning | Terraform EKS module with `API_AND_CONFIG_MAP`; asynchronous runner | OIDC association, access entries, RBAC application and validation |
| Frontend | Privilege-aware navigation and cluster action menu | Access Management, Dashboard and WebKubectl pages |
| Networking | Private Lambda and private EKS endpoint baseline | A runtime with network reachability to each private Kubernetes API |

## Target flow

```text
User signs in with Cognito
        |
        v
Navigan resolves privileges and customer/resource scope
        |
        +--> Cluster Dashboard read session
        |
        +--> WebKubectl session request
        |
        v
Cluster Access Broker validates user + cluster + action
        |
        v
Short-lived, user-bound Kubernetes credential
        |
        v
Private Kubernetes API
        |
        v
Kubernetes RBAC generated from approved Navigan access assignments
```

## Data model

Add migration `010_cluster_identity_access.sql`.

### `cluster_management.cluster_identity_integrations`

- One record per cluster.
- Stores provider, status, issuer, audience, username claim, groups claim, prefixes,
  configuration fingerprint, desired revision, applied revision, last verified time,
  sanitized failure code, and optimistic-lock version.
- Statuses: `NOT_CONFIGURED`, `PENDING`, `RECONCILING`, `READY`,
  `DRIFTED`, `FAILED`, `UNSUPPORTED`.
- No client secret, token, kubeconfig, certificate private key, or raw provider response.

### `access_management.kubernetes_access_profiles`

- Reviewed profile catalogue such as Viewer, Namespace Operator,
  Application Administrator and Cluster Operator.
- Stores stable code, provider-neutral permissions, scope type, version and status.
- Platform Administrator manages profiles; customer administrators assign only profiles
  and scopes they are authorized to grant.

### `access_management.kubernetes_access_assignments`

- Binds a Navigan user or managed identity group to a profile and customer/cluster/namespace scope.
- Supports validity windows, approval state, revocation and mandatory reason.
- A DENY or missing matching scope must fail closed.

### `cluster_management.cluster_access_reconciliations`

- Append-oriented operation record with idempotency key, desired revision,
  execution ID, status, initiator, timestamps and sanitized result.
- Prevents concurrent reconciliation for the same cluster.

### `cluster_management.webkubectl_sessions`

- Metadata only: session ID, user, customer, cluster, requested namespace,
  effective profile, issued/expiry/revocation timestamps and status.
- Credentials and terminal content are not stored in this table.

## Privileges

Seed application-defined privileges:

- `cluster.identity.view`
- `cluster.identity.reconcile`
- `cluster.access.view`
- `cluster.access.manage`
- `cluster.dashboard.view`
- `cluster.webkubectl.open`
- `cluster.webkubectl.audit`

Privileges use the existing CUSTOMER, PLATFORM and RESOURCE scopes. No behavior is
authorized from a role name.

## Backend APIs

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/v1/clusters/{id}/identity` | Identity integration and verification state |
| POST | `/api/v1/clusters/{id}/identity/reconcile` | Start idempotent reconciliation |
| GET | `/api/v1/clusters/{id}/access` | Effective profiles and assignments |
| POST | `/api/v1/clusters/{id}/access/assignments` | Create governed assignment |
| POST | `/api/v1/clusters/{id}/access/assignments/{assignmentId}/revoke` | Revoke assignment |
| GET | `/api/v1/clusters/{id}/dashboard` | Sanitized Kubernetes inventory and health |
| POST | `/api/v1/clusters/{id}/webkubectl/sessions` | Create a short-lived scoped session |
| POST | `/api/v1/clusters/{id}/webkubectl/sessions/{sessionId}/revoke` | Revoke a session |

Every endpoint independently validates privilege, customer/resource scope, cluster
ownership and current integration state.

## EKS integration

### New clusters

1. Provision EKS with IAM authentication retained.
2. Associate the approved external OIDC identity provider.
3. Wait for provider state to become active.
4. Create required EKS access entries for Navigan automation and recovery.
5. Generate deterministic RBAC manifests from approved profiles and assignments.
6. Apply manifests through the private cluster-access runtime.
7. Validate an allowed and denied operation.
8. Mark identity integration `READY`.
9. Enable Dashboard and WebKubectl capabilities.

Cluster infrastructure may be `ACTIVE` while identity integration is still
`PENDING` or `FAILED`; the UI must show both states clearly.

### Existing clusters

1. Discover current EKS authentication mode and identity providers.
2. Compare the desired provider fingerprint with actual configuration.
3. Report incompatible immutable fields before changing anything.
4. Add or repair only Navigan-owned objects.
5. Preserve unrelated identity providers, access entries and RBAC objects.
6. Verify effective access before marking `READY`.

## Kubernetes RBAC

- Use versioned Navigan-owned `ClusterRole` and `Role` templates.
- Prefer namespace-scoped `RoleBinding` for Cloud Engineer access.
- Reserve cluster-wide bindings for explicitly approved operational profiles.
- Do not grant `cluster-admin` by default.
- Label every managed object with owner, customer, cluster, profile and revision.
- Server-side generation must be deterministic and reject unsafe wildcard escalation.
- Never allow the UI to submit executable RBAC YAML in the first release.

## WebKubectl

- Run a dedicated broker/gateway in connected private networking.
- Authorize each session against current Navigan access and cluster state.
- Issue a short-lived, audience-bound, user-specific credential.
- Restrict namespace and command capabilities through Kubernetes RBAC.
- Use secure WebSocket transport, idle timeout, maximum lifetime and immediate revocation.
- Audit session creation, closure, target cluster, namespace and privileged API actions.
- Never expose administrator kubeconfig files, provisioning role credentials, client
  secrets or shared service-account tokens.

## Kubernetes dashboard

First release:

- Cluster health, Kubernetes version and identity-integration state
- Node and node-group health/capacity
- Namespaces and workload health
- Deployments, StatefulSets, DaemonSets, Pods and restart counts
- CPU/memory requests and utilization where metrics are available
- Recent warning events
- RBAC/access summary
- Current and recent Navigan operations

The backend returns provider-neutral view models so later adapters can support other
Kubernetes distributions and non-Kubernetes container platforms without rewriting the UI.

## Frontend

- Keep existing sidebar behavior unchanged initially.
- Enable Dashboard and WebKubectl cluster actions only from backend capabilities.
- Add an Access tab on cluster details and a platform Access Management area.
- Show loading, empty, permission-denied, integration-required, drift and failure states.
- Show disabled actions with a precise backend-provided reason.

## Delivery phases

| Phase | Scope | Exit gate |
|---|---|---|
| 1 | Migration, privileges, identity state and read APIs | Authorization and isolation tests pass |
| 2 | OIDC configuration and reconciliation for one disposable Dev EKS cluster | Allowed/denied identity tests pass |
| 3 | Managed Kubernetes RBAC profiles and assignments | Idempotency and cross-customer denial pass |
| 4 | Existing-cluster reconciliation | No-op repeat and unrelated-RBAC preservation pass |
| 5 | Read-only Kubernetes Dashboard | Private connectivity and scope tests pass |
| 6 | WebKubectl broker | Short-lived session, revocation and credential-exposure review pass |
| 7 | Production promotion | Dev acceptance, rollback plan and security review approved |

## Required decisions before implementation

1. Confirm the central OIDC issuer and a dedicated Kubernetes audience/client ID.
2. Confirm the immutable username claim and stable group claim.
3. Confirm how the broker reaches private EKS endpoints in every customer VPC.
4. Approve the first RBAC profiles and their exact Kubernetes permissions.
5. Decide whether initial assignments target Cognito groups, individual users, or both.

## Immediate next implementation slice

After the decisions above, implement Phase 1 only:

- migration `010_cluster_identity_access.sql`;
- identity/access repository and service;
- identity state in cluster detail and backend capabilities;
- read-only identity/access endpoints;
- unit and cross-customer authorization tests.

No cluster configuration, RBAC mutation, WebKubectl session, Dev deployment or
Production deployment belongs in Phase 1.
