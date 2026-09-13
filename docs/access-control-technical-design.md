# Dynamic Access Control Technical Design

## Status

| Area | Status |
|---|---|
| Business and navigation baseline | Approved |
| Authorization decisions | Approved with secure defaults |
| Database design | Draft for technical review |
| Authorization API design | Draft for technical review |
| Identity integration design | Draft for technical review |
| Implementation | Not started |

## Approved authorization decisions

| Decision | Approved baseline |
|---|---|
| Direct user privilege assignments | Supported through explicit grants and denials |
| Initial scope granularity | SELF, CUSTOMER and PLATFORM implemented first |
| Resource-specific scope | Data model reserved; enforcement deferred |
| Maker and approver access | Separation enforced for the same request |
| Cluster apply authorization | Separate from request approval |
| Delegated administration | Administrators cannot grant privileges or scope beyond their effective authority |

## Target architecture

Cognito remains responsible for authentication. Navigan becomes the source of truth for authorization.

```text
Cognito authentication
        |
        v
Verified user subject
        |
        v
Navigan authorization service
  - user status
  - role assignments
  - privilege grants and denials
  - customer/platform scopes
  - assignment validity
  - authorization revision
        |
        +----> Effective access response for the UI
        |
        +----> Server-side decision for every API action
```

Role names must never control business behaviour. Services authorize privilege codes against the requested resource and workflow state.

## Database ownership

Create a dedicated `access_management` schema. Customer, environment and cluster schemas continue to own their business data.

### users

| Column | Type | Rules |
|---|---|---|
| user_id | varchar(100) | Primary key; stable Cognito subject |
| username | varchar(255) | Unique normalized login/display identifier |
| display_name | varchar(255) | Required |
| email | varchar(320) | Optional; normalized where present |
| status | varchar(30) | INVITED, ACTIVE, DISABLED or DEACTIVATED |
| authorization_revision | bigint | Incremented after access-affecting changes |
| created_by | varchar(100) | Required |
| created_at | timestamptz | Required |
| updated_by | varchar(100) | Optional |
| updated_at | timestamptz | Optional |

The platform must not use an email address as the immutable user identifier.

### roles

| Column | Type | Rules |
|---|---|---|
| role_id | varchar(50) | Primary key |
| role_code | varchar(100) | Unique stable code |
| role_name | varchar(255) | User-facing name |
| description | text | Optional |
| role_type | varchar(30) | SYSTEM_TEMPLATE or CUSTOM |
| status | varchar(30) | ACTIVE or RETIRED |
| version | bigint | Optimistic locking |
| created_by / created_at | audit fields | Required |
| updated_by / updated_at | audit fields | Optional |

System templates may be edited by creating a new version. Existing assignments retain an auditable relationship to the role.

### privileges

| Column | Type | Rules |
|---|---|---|
| privilege_id | varchar(50) | Primary key |
| privilege_code | varchar(150) | Unique immutable application contract |
| module_code | varchar(50) | DASHBOARD, CUSTOMER, ENVIRONMENT, CLUSTER, OPERATIONS, ACCESS or PLATFORM |
| name | varchar(255) | User-facing name |
| description | text | Required |
| risk_level | varchar(20) | LOW, MEDIUM, HIGH or CRITICAL |
| scope_types | text array | Allowed scope types |
| active | boolean | Inactive privileges cannot be newly assigned |

Privilege codes are application contracts. Administrators may assign them but cannot invent executable privileges through the UI. New privilege codes require an application release and migration.

### role_privileges

| Column | Type | Rules |
|---|---|---|
| role_id | varchar(50) | Foreign key to roles |
| privilege_id | varchar(50) | Foreign key to privileges |
| effect | varchar(10) | ALLOW or DENY |
| created_by / created_at | audit fields | Required |

Primary key: `role_id, privilege_id`.

### user_role_assignments

| Column | Type | Rules |
|---|---|---|
| assignment_id | varchar(50) | Primary key |
| user_id | varchar(100) | Foreign key to users |
| role_id | varchar(50) | Foreign key to roles |
| valid_from | timestamptz | Required |
| valid_until | timestamptz | Optional |
| status | varchar(20) | ACTIVE or REVOKED |
| reason | text | Required for privileged assignments and revocation |
| created_by / created_at | audit fields | Required |
| revoked_by / revoked_at | audit fields | Optional |

An active duplicate assignment for the same user and role must be prevented.

### user_privilege_assignments

| Column | Type | Rules |
|---|---|---|
| assignment_id | varchar(50) | Primary key |
| user_id | varchar(100) | Foreign key to users |
| privilege_id | varchar(50) | Foreign key to privileges |
| effect | varchar(10) | ALLOW or DENY |
| valid_from / valid_until | timestamps | Time-bound access |
| status | varchar(20) | ACTIVE or REVOKED |
| reason | text | Required |
| created_by / created_at | audit fields | Required |

An effective direct DENY overrides role and direct ALLOW assignments.

### access_scopes

| Column | Type | Rules |
|---|---|---|
| scope_id | varchar(50) | Primary key |
| scope_type | varchar(20) | SELF, CUSTOMER, PLATFORM or RESOURCE |
| customer_id | varchar(50) | Required for CUSTOMER and RESOURCE |
| resource_type | varchar(30) | Reserved for ENVIRONMENT or CLUSTER |
| resource_id | varchar(50) | Reserved for resource scope |
| created_at | timestamptz | Required |

Database checks must enforce valid column combinations for each scope type.

### assignment_scopes

| Column | Type | Rules |
|---|---|---|
| assignment_type | varchar(30) | USER_ROLE or USER_PRIVILEGE |
| assignment_id | varchar(50) | Assignment identifier |
| scope_id | varchar(50) | Foreign key to access_scopes |

An assignment without a valid scope is rejected. Platform scope is never inferred from a role name.

### access_audit_log

| Column | Type | Rules |
|---|---|---|
| audit_id | bigint identity | Primary key |
| action | varchar(100) | Assignment or administration action |
| target_type | varchar(50) | USER, ROLE, PRIVILEGE, ASSIGNMENT or SCOPE |
| target_id | varchar(100) | Required |
| performed_by | varchar(100) | Required |
| performed_at | timestamptz | Required |
| reason | text | Required for sensitive changes |
| correlation_id | varchar(100) | Required |
| old_value / new_value | jsonb | Redacted safe snapshots |

The audit table must be append-only through trigger and database privileges.

## Effective authorization algorithm

For every request:

1. Accept only the verified token subject from API Gateway.
2. Load the active Navigan user.
3. Reject disabled or deactivated users.
4. Load active, non-expired role and direct privilege assignments.
5. Expand role privileges.
6. Apply direct privilege assignments.
7. Apply DENY precedence.
8. Resolve assignment scopes.
9. Verify that the requested customer owns the environment or cluster.
10. Verify resource workflow state and separation-of-duty rules.
11. Allow or return a generic HTTP 403 response.
12. Record sensitive authorization and administration decisions.

The effective privilege formula is:

```text
(role allows + direct allows)
  - role denies
  - direct denies
= effective privileges within effective scopes
```

## Customer hierarchy enforcement

Authorization must resolve ownership server-side:

```text
cluster.customer_id = environment.customer_id
cluster.environment_id = environment.environment_id
environment.customer_id = requested customer_id
```

The client must not be trusted to supply a valid relationship. Database foreign keys and service validation should both protect the hierarchy.

## Separation of duties

Privileges define eligibility, but request-level rules define independence.

The following actors cannot approve the same request:

- Original creator
- Current revision creator
- Current submitter
- A user acting through a service identity

This rule applies even when the user possesses both create and approve privileges through multiple assignments.

An emergency override should not be included in the initial release. If introduced later, it requires a dedicated critical privilege, mandatory reason, second authorization and enhanced audit.

## Cluster approval and apply

Cluster configuration approval and infrastructure application are distinct controls:

```text
Create and submit
    -> Review
    -> Configuration approval
    -> Plan generation
    -> Plan review or validation
    -> Apply authorization
    -> Infrastructure apply
```

`cluster.approve` does not imply `cluster.apply`. An organization may assign both privileges to one role, but the request-level maker/approver restriction still applies.

## Identity and token contract

### Cognito token

Keep the access token small and stable:

| Claim | Purpose |
|---|---|
| sub | Immutable user identity |
| scope | API access scope |
| iss, aud/client_id, exp | Standard token validation |
| authz_revision | Optional cache invalidation hint |

Roles, privileges and customer lists should no longer be the long-term authorization source in Cognito groups or token claims.

### Effective access endpoint

The frontend loads effective access after authentication:

```text
GET /api/v1/access/me
```

Response:

```json
{
  "user": {
    "userId": "subject-id",
    "displayName": "Example User"
  },
  "authorizationRevision": 12,
  "privileges": [
    "dashboard.platform.view",
    "customer.view",
    "environment.create"
  ],
  "scopes": [
    {
      "type": "CUSTOMER",
      "customerIds": ["CUS-example"]
    }
  ],
  "menuCapabilities": {
    "hasPlatformScope": false,
    "canReviewRequests": false,
    "canManageAccess": false
  }
}
```

The frontend uses this response for navigation and action visibility. APIs independently evaluate authorization and must never trust privileges sent back by the browser.

## Authorization APIs

### Current user

| Method | Endpoint | Purpose |
|---|---|---|
| GET | /api/v1/access/me | Return current effective access |

### Users

| Method | Endpoint | Privilege |
|---|---|---|
| GET | /api/v1/access/users | user.view |
| POST | /api/v1/access/users | user.manage |
| GET | /api/v1/access/users/{userId} | user.view |
| PUT | /api/v1/access/users/{userId} | user.manage |
| POST | /api/v1/access/users/{userId}/disable | user.manage |
| POST | /api/v1/access/users/{userId}/reactivate | user.manage |
| GET | /api/v1/access/users/{userId}/effective-access | user.view and assignment.manage |

### Roles and privileges

| Method | Endpoint | Privilege |
|---|---|---|
| GET | /api/v1/access/roles | role.view |
| POST | /api/v1/access/roles | role.manage |
| GET | /api/v1/access/roles/{roleId} | role.view |
| PUT | /api/v1/access/roles/{roleId} | role.manage |
| POST | /api/v1/access/roles/{roleId}/retire | role.manage |
| GET | /api/v1/access/privileges | privilege.view |
| PUT | /api/v1/access/roles/{roleId}/privileges | role.manage |

### Assignments and scopes

| Method | Endpoint | Privilege |
|---|---|---|
| GET | /api/v1/access/users/{userId}/assignments | assignment.manage |
| POST | /api/v1/access/users/{userId}/role-assignments | assignment.manage |
| POST | /api/v1/access/users/{userId}/privilege-assignments | assignment.manage |
| POST | /api/v1/access/assignments/{assignmentId}/revoke | assignment.manage |
| PUT | /api/v1/access/assignments/{assignmentId}/scopes | scope.manage |
| GET | /api/v1/access/audit | access.audit.view |

All writes require optimistic locking or an equivalent version, idempotency where relevant, a reason for sensitive changes and immutable audit records.

## Delegated administration controls

Before changing another user's access, the service verifies:

1. The administrator possesses `assignment.manage`.
2. The administrator possesses every privilege being granted.
3. The administrator's scope includes every scope being granted.
4. The target assignment does not bypass a direct DENY.
5. The administrator is not modifying their own critical access.
6. The assignment does not create a prohibited maker-approver combination where policy forbids it.

Initial release policy: self-assignment, self-elevation and self-reactivation are prohibited.

## Caching and revocation

- Cache effective access by `user_id` and `authorization_revision`.
- Increment the revision after every role, privilege, scope, status or assignment change affecting the user.
- Use a short cache lifetime as a safety fallback.
- Disabled users must be checked independently of a cached allow decision.
- Administration writes should invalidate affected cache entries immediately.

The initial implementation may use an in-process Lambda cache only as an optimization. Correctness must not depend on cache availability.

## Bootstrap administration

The first Platform Administrator must be established through a controlled deployment bootstrap:

1. Identify the immutable Cognito subject.
2. Insert or activate the Navigan user.
3. Assign the administrator template and PLATFORM scope.
4. Record the deployment identity, reason and timestamp.
5. Disable repeated bootstrap execution after successful establishment.

Bootstrap must not create a permanent unauthenticated administration endpoint.

## Migration strategy

| Stage | Activity |
|---|---|
| 1 | Create access-management schema and seed privilege catalogue |
| 2 | Seed editable starter-role templates |
| 3 | Register existing Cognito users and translate current group assignments |
| 4 | Add `/access/me` and backend privilege evaluation alongside existing role checks |
| 5 | Compare old and new authorization decisions in non-enforcing audit mode |
| 6 | Switch frontend menu and actions to effective privileges |
| 7 | Switch backend endpoints to privilege enforcement |
| 8 | Remove authorization dependence on static Cognito role groups |
| 9 | Build Access Management UI |
| 10 | Remove legacy role and customer claims after acceptance |

The migration must be additive until new authorization decisions are verified. Existing users must not lose access without a comparison report and approved cutover.

## Required tests

- Privilege allow and deny precedence
- Multiple-role privilege union
- Expired and revoked assignments
- Customer-scope isolation
- Environment and cluster ownership validation
- Platform-scope access
- Maker-approver separation
- Cluster approve versus apply separation
- Disabled-user rejection
- Administrator anti-escalation
- Self-assignment rejection
- Authorization revision and cache invalidation
- Sidebar visibility from `/access/me`
- Direct URL and API access when menu is hidden
- Cross-tenant negative tests for every business module

## Next implementation deliverables

1. Migration `007_access_management.sql`
2. Access-management repository and authorization evaluator
3. `/api/v1/access/me`
4. Seeded privilege catalogue and starter roles
5. Compatibility adapter for existing Cognito assignments
6. Authorization decision tests

No frontend sidebar conversion should begin until `/access/me` and backend privilege evaluation are available.
