# Access Control and Navigation Baseline

## Status

| Item | Status |
|---|---|
| Requirements baseline | Approved |
| Privilege catalogue | Draft for approval |
| Scope model | Draft for approval |
| Starter role templates | Draft for approval |
| Clustered sidebar | Draft for approval |
| Application implementation | Not started |
| Dashboard development | On hold |

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

## Implementation boundary for the next phase

The next technical phase should replace current static role checks with a central effective-authorization contract. Before coding begins, the following decisions require approval:

1. Whether direct user privilege grants and denials are allowed in the first release.
2. Whether resource-level scope is required initially or deferred after customer scope.
3. Whether the same person may receive both maker and approver privileges.
4. Whether cluster apply is a separate approval after cluster configuration approval.
5. Whether Platform Administrators may grant privileges equal to or greater than their own.
