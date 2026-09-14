import type { Identity, PlatformRole } from "./claims";

export type PlatformPermission =
  | "dashboard.platform.view"
  | "dashboard.operations.view"
  | "workqueue.own.view"
  | "notification.view"
  | "customer.view"
  | "customer.create"
  | "customer.edit"
  | "customer.submit"
  | "customer.review"
  | "customer.approve"
  | "customer.activate"
  | "customer.suspend"
  | "customer.deactivate"
  | "environment.view"
  | "environment.create"
  | "environment.edit"
  | "environment.submit"
  | "environment.review"
  | "environment.approve"
  | "environment.activate"
  | "environment.suspend"
  | "environment.deactivate"
  | "environment.revision.manage"
  | "cluster.view"
  | "cluster.create"
  | "cluster.edit"
  | "cluster.submit"
  | "cluster.review"
  | "cluster.approve"
  | "cluster.plan"
  | "cluster.apply"
  | "cluster.retry"
  | "cluster.cancel"
  | "cluster.decommission"
  | "cluster.logs.view"
  | "blueprint.view"
  | "remediation.review"
  | "operations.view"
  | "operations.logs.view"
  | "role.view"
  | "role.manage"
  | "privilege.view"
  | "assignment.manage"
  | "scope.manage"
  | "user.view"
  | "user.manage"
  | "platform.configure"
  | "access.audit.view";

const rolePermissions: Record<PlatformRole, readonly PlatformPermission[]> = {
  CLOUD_ENGINEER: [
    "dashboard.platform.view",
    "workqueue.own.view",
    "customer.view",
    "customer.create",
    "customer.edit",
    "customer.submit",
    "environment.view",
    "environment.create",
    "environment.edit",
    "environment.submit",
    "environment.revision.manage",
    "cluster.view",
    "cluster.create",
    "cluster.edit",
    "cluster.submit",
    "cluster.logs.view",
  ],
  PLATFORM_ARCHITECT: [
    "dashboard.platform.view",
    "dashboard.operations.view",
    "customer.view",
    "customer.review",
    "customer.approve",
    "customer.activate",
    "customer.suspend",
    "customer.deactivate",
    "environment.view",
    "environment.review",
    "environment.approve",
    "environment.activate",
    "environment.suspend",
    "environment.deactivate",
    "cluster.view",
    "cluster.review",
    "cluster.approve",
    "cluster.plan",
    "cluster.apply",
    "cluster.decommission",
    "cluster.logs.view",
    "blueprint.view",
    "remediation.review",
    "operations.view",
    "operations.logs.view",
  ],
  PLATFORM_ADMINISTRATOR: [
    "dashboard.platform.view",
    "dashboard.operations.view",
    "customer.view",
    "environment.view",
    "cluster.view",
    "cluster.apply",
    "cluster.decommission",
    "operations.view",
    "operations.logs.view",
    "user.view",
    "user.manage",
    "role.view",
    "role.manage",
    "privilege.view",
    "assignment.manage",
    "scope.manage",
    "platform.configure",
    "access.audit.view",
  ],
  SERVICE: [],
};

export function permissionsFor(
  identity: Identity | null,
): ReadonlySet<PlatformPermission> {
  if (identity?.privileges) {
    return new Set(identity.privileges as PlatformPermission[]);
  }
  const permissions = new Set<PlatformPermission>();
  for (const role of identity?.roles ?? []) {
    for (const permission of rolePermissions[role]) permissions.add(permission);
  }
  if (!identity?.canCreate) {
    permissions.delete("customer.create");
  }
  return permissions;
}

export function hasPermission(
  identity: Identity | null,
  permission: PlatformPermission,
): boolean {
  return permissionsFor(identity).has(permission);
}
