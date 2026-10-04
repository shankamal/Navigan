# Access Control and Navigation Baseline

## Status

| Item | Status |
|---|---|
| Priority 0: separate environment baseline from cluster configuration | Approved for implementation |
| Priority 0: cluster start, stop and governed deletion | Approved for implementation |
| Priority 0: governed resource fulfilment and end-to-end cluster readiness | Approved for implementation |
| Requirements baseline | Approved |
| Privilege catalogue | Draft for approval |
| Scope model | Draft for approval |
| Starter role templates | Draft for approval |
| Clustered sidebar | Draft for approval |
| Application implementation | Not started |
| Dashboard development | On hold |

## Priority 0: environment and cluster responsibility separation

This change takes precedence over the remaining dashboard and access-management
UI work.

| Phase | Requirement | Target ownership | Status |
|---|---|---|---|
| P0.1 | Remove cluster blueprints from Environment creation and revision | Environment retains customer, account, region, network, security, IAM, encryption, connectivity and baseline tags | Implemented locally |
| P0.2 | Move cluster name, Kubernetes version and API endpoint access | Cluster request | Implemented locally |
| P0.3 | Move node groups, instance types, capacity type, scaling and storage | Cluster request | Implemented locally |
| P0.4 | Move provisioning role, external-ID secret and cluster tags | Cluster request, validated against the selected active Environment | Implemented locally |
| P0.5 | Preserve the approved Environment version as the immutable infrastructure baseline used by planning and apply | Cluster request reference | Implemented locally |
| P0.6 | Add Stop and Start lifecycle actions | Cluster Operations; Stop scales managed worker groups to zero while the EKS control plane remains active | Implemented locally; backend integration test pending |
| P0.7 | Add governed Delete action | Cluster Operations; explicit confirmation, authorization, audit history and asynchronous Terraform destroy | Implemented locally; backend integration test pending |
| P0.8 | Identify and remove the obsolete test cluster | AWS Dev account only, after exact cluster identity and state ownership are verified | Awaiting target verification |

### Safety and lifecycle rules

1. Environment approval must not approve Kubernetes versions, endpoint modes,
   worker sizing or cluster credentials.
2. Cluster configuration is versioned and independently reviewed before plan
   and apply.
3. Stop means scaling managed worker capacity to zero. It does not stop or
   remove the managed EKS control plane.
4. Start restores the last approved node-group minimum and desired capacities.
5. Delete is asynchronous and must use the cluster's recorded Terraform state;
   it must not directly delete an unverified AWS cluster.
6. Production lifecycle actions remain unavailable until they have passed Dev
   validation and explicit promotion approval.

## Priority 0: governed resource fulfilment and cluster readiness

This workflow is the prerequisite path between AWS discovery and an approvable
Environment baseline.

| Phase | Requirement | Status |
|---|---|---|
| RF.1 | Let the requester use an eligible discovered resource or request a dedicated managed resource | In progress |
| RF.2 | Capture validated user-specified names without accepting executable code or IAM policy documents | In progress |
| RF.3 | Persist requested specifications in the remediation request, history and architect review | In progress |
| RF.4 | Generate immutable, versioned Terraform input and a downloadable administrator package | Planned |
| RF.5 | Require independent plan approval before customer-account changes | Existing foundation; extension planned |
| RF.6 | Monitor execution, rerun discovery and verify every created resource is eligible | Planned |
| RF.7 | Attach only verified resources to the Environment revision | Planned |
| RF.8 | Permit Environment submission only when its complete baseline is verified | Planned |
| RF.9 | Provision the Cluster from the active Environment baseline and independently approved cluster specification | In progress |
| RF.10 | Mark a cluster ACTIVE only after control-plane, node-group and Kubernetes node readiness checks pass | Planned |

End-to-end state flow:

`DISCOVERED → RESOURCE_REQUESTED → PLAN_READY → APPROVED → EXECUTING → REDISCOVERING → BASELINE_VERIFIED → ENVIRONMENT_ACTIVE → CLUSTER_PLANNED → CLUSTER_APPLYING → HEALTH_VERIFYING → ACTIVE`

Failed verification must result in `REMEDIATION_REQUIRED` or `FAILED`; it must
never result in an incorrectly ACTIVE environment or cluster.

## Design principles

1. A customer is a unique tenant and the authoritative parent for its environments and clusters.
2. A customer can own multiple environments and submit any number of versioned environment requests.
3. An active environment can own multiple cluster requests and provisioned clusters.
4. Every cluster must be linked to both its customer and its environment.
5. Cross-customer access must be denied in the frontend, API, service and database access layers.
6. Roles are editable collections of privileges, not hard-coded application behaviour.
7. Users may receive privileges from multiple roles and optional direct assignments.
8. Menu visibility is calculated from effective privileges and scope.
9. Hiding a menu is a usability feature; backend authorization remains mandatory.
10. Request creation and request approval should remain separated unless an explicitly approved policy allows both.

## Authorization model

An authorization decision is based on:

```text
User
  + active role assignments
  + role privileges
  + direct privilege grants or denials
  + platform or customer scope
  + resource ownership and workflow state
  = effective authorization
```

### Assignment types

| Assignment | Purpose |
|---|---|
| User to role | Assign a reusable privilege collection |
| Role to privilege | Define what a role can do |
| User to privilege | Controlled exception without creating a new role |
| User or role to customer scope | Restrict access to selected customers |
| User or role to platform scope | Permit access across all customers |
| Temporary assignment | Time-bound elevated or project access |

Direct denial should override an allow. Disabled, expired or revoked assignments must not contribute to effective access.

## Scope model

| Scope | Meaning | Typical use |
|---|---|---|
| SELF | Records created by or assigned to the user | Engineer request queues |
| CUSTOMER | One or more explicitly assigned customers | Customer delivery teams |
| PLATFORM | All customers within the Navigan platform | Central architecture and administration |
| RESOURCE | A specific environment or cluster | Exceptional delegated support |

Scope must follow the hierarchy:

```text
Customer
└── Environment
    └── Cluster
```

Access to an environment or cluster must not be granted through an unrelated customer. A resource-scoped assignment must still retain its owning customer boundary.

## Privilege catalogue

### Dashboard and work management

| Privilege | Description |
|---|---|
| dashboard.platform.view | View the platform overview within assigned scope |
| dashboard.operations.view | View operational metrics and activity |
| workqueue.own.view | View the user's drafts, rejected items and assigned work |
| notification.view | View personal platform notifications |

### Customer management

| Privilege | Description |
|---|---|
| customer.view | List and view customer records within scope |
| customer.create | Create a customer onboarding draft |
| customer.edit | Edit customer data when workflow state permits |
| customer.provider.manage | Change customer cloud-provider associations |
| customer.submit | Submit or resubmit customer requests |
| customer.review | Start and perform customer review |
| customer.approve | Approve or reject reviewed customer requests |
| customer.activate | Activate an approved customer |
| customer.suspend | Suspend or reactivate a customer |
| customer.deactivate | Deactivate a customer |
| customer.history.view | View customer lifecycle history |
| customer.audit.view | View detailed customer audit records |

### Environment management

| Privilege | Description |
|---|---|
| environment.view | List and view environments within scope |
| environment.create | Create an environment request for an eligible customer |
| environment.edit | Edit a draft, revision or rejected environment request |
| environment.discover | Run approved read-only cloud discovery |
| environment.submit | Submit or resubmit an environment request |
| environment.review | Start and perform environment review |
| environment.approve | Approve or reject an environment request |
| environment.activate | Activate an approved environment revision |
| environment.suspend | Suspend or reactivate an environment |
| environment.deactivate | Deactivate an environment |
| environment.revision.manage | Create and maintain environment revisions |
| environment.history.view | View environment lifecycle and revision history |
| environment.audit.view | View detailed environment audit records |

### Cluster management

| Privilege | Description |
|---|---|
| cluster.view | List and view cluster requests and provisioned clusters |
| cluster.create | Create a cluster request under an eligible active environment |
| cluster.edit | Edit a draft or rejected cluster request |
| cluster.submit | Submit or resubmit a cluster request |
| cluster.review | Start and perform cluster review |
| cluster.approve | Approve or reject a cluster request |
| cluster.plan | Generate and inspect an infrastructure plan |
| cluster.apply | Authorize or execute an approved infrastructure apply |
| cluster.retry | Retry a failed cluster operation |
| cluster.cancel | Cancel an eligible cluster operation |
| cluster.decommission | Request or execute controlled cluster removal |
| cluster.logs.view | View cluster execution logs |
| cluster.history.view | View cluster lifecycle history |
| cluster.audit.view | View detailed cluster audit records |

### Blueprint and remediation management

| Privilege | Description |
|---|---|
| blueprint.view | View approved cluster blueprints |
| blueprint.create | Create a blueprint draft |
| blueprint.edit | Edit blueprint drafts and revisions |
| blueprint.submit | Submit a blueprint for review |
| blueprint.review | Review a submitted blueprint |
| blueprint.approve | Approve, reject or activate a blueprint |
| remediation.view | View bootstrap and infrastructure remediation requests |
| remediation.request | Submit a remediation request |
| remediation.review | Review and approve or reject remediation |
| remediation.execute | Execute an approved remediation |

### Operations and governance

| Privilege | Description |
|---|---|
| operations.view | View platform provisioning activity |
| operations.logs.view | View platform-wide execution logs |
| operations.retry | Retry eligible failed operations |
| operations.cancel | Cancel eligible operations |
| event.view | View platform events |
| audit.platform.view | View platform-wide audit information |
| compliance.view | View compliance and policy findings |

### Access and platform administration

| Privilege | Description |
|---|---|
| user.view | View users |
| user.manage | Create, update, disable or reactivate users |
| role.view | View roles and their privileges |
| role.manage | Create, update or retire roles |
| privilege.view | View the privilege catalogue |
| assignment.manage | Manage user-role and direct privilege assignments |
| scope.manage | Manage platform, customer and resource scopes |
| serviceaccount.manage | Manage service identities |
| access.audit.view | View access-assignment history |
| provider.configure | Manage supported cloud providers |
| environmenttype.configure | Manage environment types |
| workflow.configure | Manage workflow policies |
| notification.configure | Manage notification policies |
| platform.configure | Manage platform-level configuration |

## Starter role templates

These are editable initial templates. Application logic must not depend on their names.

### Cloud Engineer template

- Platform dashboard and own work queue
- Customer, environment and cluster view access within assigned scope
- Create, edit, submit and resubmit customer requests
- Create, edit, discover, revise and submit environment requests
- Create, edit and submit cluster requests
- View logs and history for owned or assigned resources
- Request remediation
- No approval privileges by default

### Platform Architect template

- Platform and operations dashboards within assigned scope
- Customer, environment, cluster and blueprint view access
- Review and approve customer requests
- Review and approve environment requests and revisions
- Review and approve cluster requests
- Review and approve blueprints and remediation requests
- View lifecycle history and audit information
- No create or submit privileges by default

### Platform Administrator template

- Platform and operations dashboards
- Platform-wide directory and operational visibility
- User, role, privilege, assignment and scope administration
- Platform configuration and access audit
- Operational retry and cancellation privileges where approved
- No maker or reviewer privileges by default

Administrator access does not automatically imply request creation or approval. Those privileges can be assigned separately when organizational policy permits.

## Clustered sidebar

Menu items are displayed only when at least one associated privilege is effective. Empty menu groups are hidden.

### Overview

| Menu item | Required privilege |
|---|---|
| Platform Dashboard | dashboard.platform.view |
| Operations Dashboard | dashboard.operations.view |
| My Work | workqueue.own.view |
| Notifications | notification.view |

### Customer Management

| Menu item | Required privilege |
|---|---|
| Customer Directory | customer.view |
| Create Customer | customer.create |
| My Customer Requests | customer.submit or workqueue.own.view |
| Customer Reviews | customer.review |
| Customer Approvals | customer.approve |
| Active Customers | customer.view |

### Environment Management

| Menu item | Required privilege |
|---|---|
| Environment Directory | environment.view |
| Create Environment | environment.create |
| My Environment Requests | environment.submit or workqueue.own.view |
| Environment Reviews | environment.review |
| Environment Approvals | environment.approve |
| Active Environments | environment.view |
| Environment Revisions | environment.revision.manage |
| Bootstrap Approvals | remediation.review |

### Cluster Management

| Menu item | Required privilege |
|---|---|
| Cluster Directory | cluster.view |
| New Cluster Request | cluster.create |
| My Cluster Requests | cluster.submit or workqueue.own.view |
| Cluster Reviews | cluster.review |
| Cluster Approvals | cluster.approve |
| Provisioned Clusters | cluster.view |
| Failed Clusters | cluster.view and operations.view |
| Cluster Operations | cluster.plan, cluster.apply, cluster.retry or cluster.cancel |

### Platform Operations

| Menu item | Required privilege |
|---|---|
| Provisioning Activity | operations.view |
| Execution Logs | operations.logs.view |
| Failed Operations | operations.view |
| Remediation Requests | remediation.view |
| Infrastructure Events | event.view |

### Governance and Audit

| Menu item | Required privilege |
|---|---|
| Approval Queue | Any customer, environment, cluster, blueprint or remediation review privilege |
| Request History | Relevant history privilege |
| Audit Logs | Relevant audit privilege |
| Compliance Findings | compliance.view |

### Access Management

| Menu item | Required privilege |
|---|---|
| Users | user.view |
| Roles | role.view |
| Privileges | privilege.view |
| User Assignments | assignment.manage |
| Customer Access | scope.manage |
| Service Accounts | serviceaccount.manage |
| Access Audit | access.audit.view |

### Platform Configuration

| Menu item | Required privilege |
|---|---|
| Cloud Providers | provider.configure |
| Environment Types | environmenttype.configure |
| Cluster Blueprints | blueprint.view, blueprint.create or blueprint.edit |
| Workflow Policies | workflow.configure |
| Notifications | notification.configure |
| System Settings | platform.configure |

## Contextual navigation

The global sidebar must not list individual customers, environments or clusters.

### Customer workspace

- Overview
- Environments
- Clusters
- Requests
- Cloud providers
- Contacts
- Access assignments
- History and audit

### Environment workspace

- Overview
- Configuration
- Revisions
- Cluster requests
- Active clusters
- Infrastructure
- Execution logs
- Approval history
- Audit

### Cluster workspace

- Overview
- Approved configuration
- Infrastructure plan
- Provisioning progress
- Nodes and outputs
- Execution logs
- Lifecycle history
- Audit

Each contextual tab must also have a privilege requirement. Tabs without effective access are hidden.

## Core capability program: platform engineering and secure cluster access

Status: architecture inspected and implementation plan prepared on 14 September
2026. Implementation has not started.

### Current architecture findings

| Area | Current behaviour | Required evolution |
|---|---|---|
| Navigation | Sidebar renders multiple privilege-filtered routes inside Customer, Environment and Cluster groups | Give Cloud Engineers one top-level entry for each management module and move permitted tasks into module pages |
| Identity | Cognito group membership is converted into role, customer-scope and platform-scope token claims | Add `PLATFORM_ENGINEER`; keep claims as a migration input while database assignments become authoritative |
| Authorization | Database-backed privileges, ALLOW/DENY effects and SELF/CUSTOMER/PLATFORM/RESOURCE scopes exist, with a legacy claim adapter | Route every API through the central evaluator and remove scattered `principal.require(role)` checks |
| Query scoping | Customer, Environment and Cluster repositories reuse a common customer-scope SQL clause | Make scope predicates consume effective database scopes and verify Environment/Cluster ownership centrally |
| User administration | Schema supports users, roles, assignments and scopes; only `/access/me` is implemented | Add managed user, role and scope APIs and forms before removing the legacy adapter |
| Cluster lifecycle | Versioned requests, state transitions, idempotency keys, Terraform execution and audit history exist | Add a centralized capability resolver and explicit operation records/locking |
| EKS access | Terraform creates EKS with `API_AND_CONFIG_MAP`; no external human OIDC association or RBAC reconciliation exists | Add external OIDC association, EKS access controls and Kubernetes RBAC reconciliation |
| WebKubectl | No complete user-scoped browser terminal contract was identified | Design a short-lived, server-brokered session before exposing this action |

Amazon EKS external OIDC user authentication is distinct from the EKS workload
OIDC issuer used by service accounts. IAM authentication must remain enabled for
nodes and platform automation. The implementation will associate the platform
identity provider for human Kubernetes API authentication and bind stable group
claims to least-privilege Kubernetes RBAC.

### Target role and scope model

Role names remain editable templates; authorization decisions use privileges and
scopes rather than role-name conditionals.

| Role template | Required scope | Intended access |
|---|---|---|
| PLATFORM_ENGINEER | PLATFORM | Global infrastructure visibility and approved platform-wide Environment, Cluster and operations management |
| CLOUD_ENGINEER | One or more CUSTOMER scopes, optionally SELF | Only explicitly assigned customers and their owned Environments and Clusters |
| PLATFORM_ARCHITECT | CUSTOMER or PLATFORM as assigned | Independent review, approval and governance |
| PLATFORM_ADMINISTRATOR | PLATFORM | Identity, role, privilege, scope and platform configuration administration |

Security invariants:

1. `PLATFORM_ENGINEER` assignments must include an active PLATFORM scope.
2. `CLOUD_ENGINEER` must not receive implicit platform scope from UI state,
   request parameters or mutable user attributes.
3. Every Environment and Cluster authorization resolves its owning customer
   before permitting access.
4. Explicit DENY overrides every role-derived ALLOW.
5. Server-side privilege and scope checks are mandatory even when a menu or
   action is hidden.

### Cloud Engineer sidebar target

The simplified presentation applies to Cloud Engineers. Existing routes remain
available as module-local pages and actions when authorized.

| Top-level item | Landing route | Module-local capabilities |
|---|---|---|
| Customer Management | `/customers` | Directory, details, create/edit and owned requests |
| Environment Management | `/environments` | Directory, create/edit, discovery, revisions and owned requests |
| Cluster Management | `/clusters` | Directory, new request, request progress and permitted lifecycle actions |

Review, approval, operations and access-administration navigation remains
privilege-driven for Platform Architects, Platform Engineers and Platform
Administrators. The frontend should consume a backend navigation profile or
effective capabilities rather than infer global access from a role label.

### Status-aware cluster action contract

Add `allowedActions` to Cluster list/detail responses. Each entry should include
an action code, availability, disabled reason, confirmation requirement and
current operation identifier where applicable.

| Cluster state | Candidate actions before privilege filtering |
|---|---|
| READY or RUNNING | DASHBOARD, WEB_KUBECTL, MANAGE |
| ACTIVE | DASHBOARD, WEB_KUBECTL, MANAGE |
| FAILED | MANAGE, EDIT, RETRY_PROVISIONING, DELETE |
| REQUESTED or PENDING | VIEW_DETAILS, EDIT_REQUEST, CANCEL_REQUEST |
| DRAFT, SUBMITTED or UNDER_REVIEW | VIEW_DETAILS plus workflow-valid edit/cancel actions |
| PROVISIONING or APPLYING | VIEW_PROGRESS, VIEW_LOGS, CANCEL_PROVISIONING when supported |
| UPDATING, STARTING or STOPPING | VIEW_PROGRESS, VIEW_LOGS, MANAGE when safe |
| DELETING | VIEW_PROGRESS |
| STOPPED | START, MANAGE, EDIT, DELETE |
| UNKNOWN or disconnected | VIEW_DETAILS, REFRESH_STATUS, TROUBLESHOOT |

The backend resolver combines lifecycle state, effective privileges, customer
scope, active operation state, provider capabilities and integration readiness.
The UI three-dot menu renders this contract without duplicating authorization
rules. Destructive operations require confirmation, idempotency and audit
events. Concurrent provisioning, retry, update and deletion operations must be
rejected server-side.

### Incremental implementation plan

| Phase | Workstream | Deliverable | Status |
|---|---|---|---|
| PE.1 | Data model | Migration adds the `PLATFORM_ENGINEER` system role, grants, required-scope validation and cluster identity-integration/operation metadata | Platform Engineer role on hold; operation metadata remains planned |
| PE.2 | Authorization | Extend token parsing and the legacy adapter, but make database effective access authoritative for migrated users | Planned |
| PE.3 | Authorization | Replace Customer, Environment, Cluster and remediation role checks with privilege plus scope policies | Planned |
| PE.4 | Query security | Centralize customer ownership predicates and enforce child-resource ownership on every read and mutation | Planned |
| PE.5 | Access administration | Add user, role, assignment, scope and effective-access APIs with immutable audit events | Planned |
| PE.6 | Frontend navigation | Implement the three-item Cloud Engineer sidebar while preserving routes and permission guards | Implemented locally; UI validation pending |
| PE.7 | Frontend access | Add Platform Engineer handling, route denial states and user-management forms | Platform Engineer role on hold |
| PE.8 | Cluster capabilities | Add a centralized backend action resolver and `allowedActions` API contract | Implemented locally; backend deployment pending |
| PE.9 | Cluster UI | Add accessible three-dot menus, disabled reasons, confirmations, progress, errors and empty/loading states | Initial list action menu implemented locally; UI validation pending |
| PE.10 | Operation safety | Add active-operation locking, retry/cancel rules, structured logs and action audit events | Planned |
| PE.11 | OIDC configuration | Store validated issuer, audience, stable username/group claims, prefixes and required claims without storing tokens | Planned |
| PE.12 | New-cluster provisioning | Associate the external EKS OIDC identity provider and wait for ACTIVE status idempotently | Planned |
| PE.13 | Kubernetes RBAC | Generate and apply versioned least-privilege Role/ClusterRole and binding templates | Planned |
| PE.14 | Identity verification | Verify OIDC authentication and authorized/denied Kubernetes API operations before marking integration READY | Planned |
| PE.15 | Existing clusters | Add discovery and reconciliation that preserves unrelated RBAC and reports recreation requirements | Planned |
| PE.16 | WebKubectl | Implement a short-lived, user-specific, scope-checked session broker with expiry, revocation and audit logging | Planned |
| PE.17 | Migration | Backfill assignments/scopes, compare legacy and dynamic decisions, then remove unsafe legacy fallbacks | Planned |
| PE.18 | Validation | Run unit, integration, Terraform, security and Dev end-to-end tests before Production promotion | Planned |

### Data and API additions

Proposed persistent additions:

- Seeded `PLATFORM_ENGINEER` role and privilege assignments.
- Constraint or service policy requiring PLATFORM scope for Platform Engineer.
- Cluster identity-integration status, provider configuration fingerprint,
  reconciliation version, last verification and failure details.
- Cluster operation record with type, status, idempotency key, execution ID,
  initiator, timestamps and sanitized error metadata.
- WebKubectl session metadata only; credentials and tokens must not be stored.

Proposed contracts:

- Extend `GET /api/v1/access/me` with a server-selected navigation profile.
- Add managed access-administration endpoints described in the technical design.
- Extend Cluster list/detail records with `allowedActions` and active operation.
- Add endpoints for retry, cancellation, refresh/reconcile identity integration
  and WebKubectl session creation.
- Keep state-changing endpoints idempotent and version protected.

### OIDC, RBAC and WebKubectl security decisions

1. Use the immutable identity-provider subject as the Kubernetes username claim,
   or another explicitly verified immutable claim.
2. Use stable identity-provider group identifiers with a Navigan-specific
   prefix; do not authorize mutable display names.
3. Do not grant `cluster-admin` by default. Create a reviewed Navigan Platform
   Engineer ClusterRole with only required operations.
4. Use namespace or constrained cluster roles for customer Cloud Engineers.
5. Keep IAM/EKS access required for nodes and automation; external OIDC is an
   additional human authentication path.
6. Never return administrative kubeconfigs, service-account tokens or customer
   provisioning credentials to the browser.
7. WebKubectl sessions are short-lived, user-bound, cluster-bound,
   customer-scope checked and fully audited.
8. Reconciliation is additive and idempotent. Unrelated existing RBAC objects
   are preserved.

### Infrastructure assumptions and limitations

- The central identity provider must expose a publicly reachable OIDC discovery
  endpoint and suitable ID-token claims for EKS.
- A dedicated Kubernetes audience/client ID may be required; the existing web
  application client should not automatically be reused.
- Private-only EKS endpoints require the reconciliation and WebKubectl runtime
  to execute inside connected customer networking.
- EKS keeps IAM authentication enabled because worker nodes and platform
  automation require it.
- Provider-specific identity integration for AKS, GKE, OKE and non-managed
  Kubernetes requires separate adapters; this phase implements EKS first.
- Cancel support depends on the underlying provider operation. Unsupported
  cancellation is returned as a disabled action with a reason.

### Required validation matrix

| Test area | Required coverage |
|---|---|
| Role and scope | Platform Engineer global access; Cloud Engineer assigned-customer access; explicit cross-customer denial |
| Navigation | Simplified Cloud Engineer sidebar; privilege-aware navigation for other roles; direct-route denial |
| API authorization | Unauthorized reads and actions rejected server-side; forged customer IDs and role claims fail closed |
| Cluster capabilities | Every supported lifecycle state, privilege combination, active-operation conflict and disabled reason |
| Operations | Idempotent retries, duplicate prevention, cancellation support and failure recovery |
| Audit | Capability-sensitive actions, destructive confirmations, identity reconciliation and WebKubectl sessions |
| OIDC | Issuer, audience, claims, prefixes, required claims, TLS/discovery and provider-state validation |
| Kubernetes RBAC | Deterministic manifest generation, least privilege, customer isolation and stable group mapping |
| Reconciliation | First apply, no-op repeat, drift repair, preservation of unrelated RBAC and partial failure |
| WebKubectl | Scope enforcement, short expiry, revocation, no kubeconfig exposure and session audit |
| Regression | Existing Customer, Environment, Cluster request, approval, provisioning and lifecycle workflows |

### Delivery gates

1. Approve the Platform Engineer privilege template and Kubernetes permission
   boundary.
2. Confirm the identity provider issuer, dedicated audience/client ID and stable
   group claim.
3. Confirm private-cluster network reachability for reconciliation and
   WebKubectl.
4. Implement and validate database/authorization changes before navigation or
   action-menu rollout.
5. Validate OIDC and RBAC on a disposable Dev cluster before reconciling an
   existing cluster.
6. Promote to Production only after authorization comparison, rollback and
   credential-exposure reviews pass.

## Implementation boundary for the next phase

The next technical phase should replace current static role checks with a central effective-authorization contract. Before coding begins, the following decisions require approval:

1. Whether direct user privilege grants and denials are allowed in the first release.
2. Whether resource-level scope is required initially or deferred after customer scope.
3. Whether the same person may receive both maker and approver privileges.
4. Whether cluster apply is a separate approval after cluster configuration approval.
5. Whether Platform Administrators may grant privileges equal to or greater than their own.
