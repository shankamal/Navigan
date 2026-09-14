"""Database-backed privilege evaluation with an explicit legacy migration adapter."""

from dataclasses import dataclass

from .errors import ApiError


LEGACY_ROLE_PRIVILEGES = {
    "CLOUD_ENGINEER": frozenset(
        {
            "dashboard.platform.view",
            "workqueue.own.view",
            "notification.view",
            "customer.view",
            "customer.create",
            "customer.edit",
            "customer.provider.manage",
            "customer.submit",
            "customer.history.view",
            "environment.view",
            "environment.create",
            "environment.edit",
            "environment.discover",
            "environment.submit",
            "environment.revision.manage",
            "environment.history.view",
            "cluster.view",
            "cluster.create",
            "cluster.edit",
            "cluster.submit",
            "cluster.logs.view",
            "cluster.history.view",
            "blueprint.view",
            "remediation.view",
            "remediation.request",
        }
    ),
    "PLATFORM_ARCHITECT": frozenset(
        {
            "dashboard.platform.view",
            "dashboard.operations.view",
            "notification.view",
            "customer.view",
            "customer.review",
            "customer.approve",
            "customer.activate",
            "customer.suspend",
            "customer.deactivate",
            "customer.history.view",
            "customer.audit.view",
            "environment.view",
            "environment.review",
            "environment.approve",
            "environment.activate",
            "environment.suspend",
            "environment.deactivate",
            "environment.history.view",
            "environment.audit.view",
            "cluster.view",
            "cluster.review",
            "cluster.approve",
            "cluster.plan",
            "cluster.logs.view",
            "cluster.history.view",
            "cluster.audit.view",
            "blueprint.view",
            "blueprint.review",
            "blueprint.approve",
            "remediation.view",
            "remediation.review",
            "operations.view",
            "operations.logs.view",
            "compliance.view",
        }
    ),
    "PLATFORM_ADMINISTRATOR": frozenset(
        {
            "dashboard.platform.view",
            "dashboard.operations.view",
            "customer.view",
            "environment.view",
            "cluster.view",
            "blueprint.view",
            "remediation.view",
            "operations.view",
            "operations.logs.view",
            "operations.retry",
            "operations.cancel",
            "event.view",
            "audit.platform.view",
            "compliance.view",
            "user.view",
            "user.manage",
            "role.view",
            "role.manage",
            "privilege.view",
            "assignment.manage",
            "scope.manage",
            "serviceaccount.manage",
            "access.audit.view",
            "provider.configure",
            "environmenttype.configure",
            "workflow.configure",
            "notification.configure",
            "platform.configure",
        }
    ),
}


@dataclass(frozen=True)
class Scope:
    scope_type: str
    customer_id: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None


@dataclass(frozen=True)
class EffectiveAccess:
    user_id: str
    display_name: str
    authorization_revision: int
    privileges: frozenset[str]
    scopes: tuple[Scope, ...]
    source: str = "DYNAMIC"

    def has(self, privilege: str) -> bool:
        return privilege in self.privileges

    def require(self, privilege: str):
        if not self.has(privilege):
            raise ApiError(403, "FORBIDDEN", "This operation is not permitted.")

    def can_access_customer(self, customer_id: str, owner_id: str | None = None) -> bool:
        return any(
            scope.scope_type == "PLATFORM"
            or (scope.scope_type == "CUSTOMER" and scope.customer_id == customer_id)
            or (scope.scope_type == "SELF" and owner_id == self.user_id)
            for scope in self.scopes
        )

    def require_customer(self, customer_id: str, owner_id: str | None = None):
        if not self.can_access_customer(customer_id, owner_id):
            raise ApiError(403, "FORBIDDEN", "This operation is outside your access scope.")


class AccessRepository:
    def __init__(self, db):
        self.db = db

    def user(self, user_id):
        return self.db.execute(
            "SELECT user_id,display_name,status,authorization_revision "
            "FROM access_management.users WHERE user_id=%s",
            [user_id],
        ).fetchone()

    def privilege_effects(self, user_id):
        return self.db.execute(
            """
            SELECT p.privilege_code,rp.effect
            FROM access_management.user_role_assignments ura
            JOIN access_management.roles r ON r.role_id=ura.role_id
            JOIN access_management.role_privileges rp ON rp.role_id=r.role_id
            JOIN access_management.privileges p ON p.privilege_id=rp.privilege_id
            WHERE ura.user_id=%s AND ura.status='ACTIVE' AND r.status='ACTIVE' AND p.active
              AND ura.valid_from<=now() AND (ura.valid_until IS NULL OR ura.valid_until>now())
            UNION ALL
            SELECT p.privilege_code,upa.effect
            FROM access_management.user_privilege_assignments upa
            JOIN access_management.privileges p ON p.privilege_id=upa.privilege_id
            WHERE upa.user_id=%s AND upa.status='ACTIVE' AND p.active
              AND upa.valid_from<=now() AND (upa.valid_until IS NULL OR upa.valid_until>now())
            """,
            [user_id, user_id],
        ).fetchall()

    def scopes(self, user_id):
        return self.db.execute(
            """
            SELECT DISTINCT s.scope_type,s.customer_id,s.resource_type,s.resource_id
            FROM access_management.user_role_assignments ura
            JOIN access_management.user_role_scopes urs ON urs.assignment_id=ura.assignment_id
            JOIN access_management.access_scopes s ON s.scope_id=urs.scope_id
            WHERE ura.user_id=%s AND ura.status='ACTIVE'
              AND ura.valid_from<=now() AND (ura.valid_until IS NULL OR ura.valid_until>now())
            UNION
            SELECT DISTINCT s.scope_type,s.customer_id,s.resource_type,s.resource_id
            FROM access_management.user_privilege_assignments upa
            JOIN access_management.user_privilege_scopes ups ON ups.assignment_id=upa.assignment_id
            JOIN access_management.access_scopes s ON s.scope_id=ups.scope_id
            WHERE upa.user_id=%s AND upa.status='ACTIVE'
              AND upa.valid_from<=now() AND (upa.valid_until IS NULL OR upa.valid_until>now())
            """,
            [user_id, user_id],
        ).fetchall()


class AccessEvaluator:
    def __init__(self, repository):
        self.repository = repository

    def evaluate(self, principal):
        user = self.repository.user(principal.user_id)
        if not user:
            return legacy_access(principal)
        if user["status"] != "ACTIVE":
            raise ApiError(403, "USER_DISABLED", "This user is not active.")
        effects = self.repository.privilege_effects(principal.user_id)
        allowed = {row["privilege_code"] for row in effects if row["effect"] == "ALLOW"}
        denied = {row["privilege_code"] for row in effects if row["effect"] == "DENY"}
        scopes = tuple(Scope(**row) for row in self.repository.scopes(principal.user_id))
        return EffectiveAccess(
            user_id=principal.user_id,
            display_name=user["display_name"],
            authorization_revision=int(user["authorization_revision"]),
            privileges=frozenset(allowed - denied),
            scopes=scopes,
        )


def legacy_access(principal):
    """Temporary additive migration path; remove after assignments are backfilled."""
    privileges = set()
    for role in principal.roles:
        privileges.update(LEGACY_ROLE_PRIVILEGES.get(role, ()))
    scopes = [Scope("CUSTOMER", customer_id=item) for item in principal.customer_ids]
    if principal.platform_scope:
        scopes.append(Scope("PLATFORM"))
    if principal.can_create:
        scopes.append(Scope("SELF"))
    return EffectiveAccess(
        user_id=principal.user_id,
        display_name=principal.user_id,
        authorization_revision=0,
        privileges=frozenset(privileges),
        scopes=tuple(scopes),
        source="LEGACY_CLAIMS",
    )
