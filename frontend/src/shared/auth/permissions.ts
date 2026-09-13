import type { Identity, PlatformRole } from "./claims";

export type PlatformPermission =
  | "dashboard.read"
  | "customer.read"
  | "customer.create"
  | "environment.read"
  | "environment.request.create"
  | "cluster.read"
  | "cluster.request.create"
  | "request.review"
  | "request.approve"
  | "blueprint.manage"
  | "remediation.review"
  | "tenant.manage"
  | "user.manage"
  | "platform.configure"
  | "audit.read";

const rolePermissions: Record<PlatformRole, readonly PlatformPermission[]> = {
  CLOUD_ENGINEER: [
    "dashboard.read",
    "customer.read",
    "customer.create",
    "environment.read",
    "environment.request.create",
    "cluster.read",
    "cluster.request.create",
  ],
  PLATFORM_ARCHITECT: [
    "dashboard.read",
    "customer.read",
    "environment.read",
    "cluster.read",
    "request.review",
    "request.approve",
    "blueprint.manage",
    "remediation.review",
    "audit.read",
  ],
  PLATFORM_ADMINISTRATOR: [
    "dashboard.read",
    "customer.read",
    "environment.read",
    "cluster.read",
    "tenant.manage",
    "user.manage",
    "platform.configure",
    "audit.read",
  ],
  SERVICE: [],
};

export function permissionsFor(
  identity: Identity | null,
): ReadonlySet<PlatformPermission> {
  const permissions = new Set<PlatformPermission>();
  for (const role of identity?.roles ?? []) {
    for (const permission of rolePermissions[role]) permissions.add(permission);
  }
  if (!identity?.canCreate) permissions.delete("customer.create");
  return permissions;
}

export function hasPermission(
  identity: Identity | null,
  permission: PlatformPermission,
): boolean {
  return permissionsFor(identity).has(permission);
}
