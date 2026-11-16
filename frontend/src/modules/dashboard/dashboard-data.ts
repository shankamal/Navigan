"use client";
import { useQueries, useQuery } from "@tanstack/react-query";
import { customersService } from "@/modules/customer-management/services/customers";
import { environments } from "@/modules/environment-management/services/environments";
import { clusters } from "@/modules/cluster-management/service";
import { migrations } from "@/modules/migration-management/service";
import type {
  Cluster,
  EksUpgradePlan,
} from "@/modules/cluster-management/model";
import { useAuth } from "@/shared/auth/auth-provider";
import { hasPermission } from "@/shared/auth/permissions";
import { useWorkspaceScope } from "@/shared/components/workspace-scope-context";

type PlatformComponentInventory = Awaited<
  ReturnType<typeof clusters.platformComponents>
>;

export async function allPages<T>(
  load: (
    page: number,
  ) => Promise<{ items: T[]; pagination: { totalPages: number } }>,
) {
  const first = await load(0);
  const items = [...first.items];
  for (let page = 1; page < first.pagination.totalPages; page++)
    items.push(...(await load(page)).items);
  return items;
}
export const openPlan = (p: EksUpgradePlan) =>
  !["SUCCEEDED", "CANCELLED", "REJECTED"].includes(p.status) ||
  (p.kind !== "UTILITY" &&
    p.status === "SUCCEEDED" &&
    p.execution.phase !== "IAC_SYNCHRONIZED");
export const activeMigration = (status: string) =>
  ![
    "DRAFT",
    "CANCELLED",
    "COMPLETED",
    "SUCCEEDED",
    "FAILED",
    "REJECTED",
  ].includes(status);
export function runtimeState(
  cluster: Cluster,
  inventory?: PlatformComponentInventory,
  now = Date.now(),
) {
  if (cluster.status === "STOPPED") return "Paused";
  const r = inventory?.runtimeInventory;
  if (
    !r ||
    !r.observedAt ||
    !r.expiresAt ||
    !Number.isFinite(Date.parse(r.expiresAt)) ||
    !Number.isFinite(Date.parse(r.observedAt)) ||
    Date.parse(r.expiresAt) <= now ||
    Date.parse(r.observedAt) > now ||
    now - Date.parse(r.observedAt) > 5 * 60_000 ||
    !["READY", "DEGRADED"].includes(r.status)
  )
    return "Unverified";
  if (r.metrics.nodeCount === 0) return "Paused";
  return r.status === "READY" ? "Ready" : "Degraded";
}
export function scheduledChanges(
  rows: { cluster: Cluster; plan: EksUpgradePlan }[],
  days: number,
  now = Date.now(),
) {
  const end = now + days * 86400000;
  return rows
    .flatMap(({ cluster, plan }) => {
      if (
        ["SUCCEEDED", "CANCELLED", "REJECTED", "FAILED"].includes(plan.status)
      )
        return [];
      const windows =
        plan.planSpec?.steps.flatMap((step, i) =>
          step.window ? [{ ...step.window, step: i + 1 }] : [],
        ) ?? [];
      const entries = windows.length
        ? windows
        : plan.scheduledFor
          ? [
              {
                scheduledFor: plan.scheduledFor,
                durationMinutes: undefined,
                step: undefined,
              },
            ]
          : [];
      return entries
        .filter(
          (w) =>
            Number.isFinite(Date.parse(w.scheduledFor)) &&
            Date.parse(w.scheduledFor) >= now &&
            Date.parse(w.scheduledFor) <= end,
        )
        .map((w) => ({ cluster, plan, ...w }));
    })
    .sort((a, b) => Date.parse(a.scheduledFor) - Date.parse(b.scheduledFor));
}
export function useDashboardData() {
  const { identity } = useAuth();
  const scope = useWorkspaceScope();
  const actor = [identity?.subject, identity?.authorizationRevision];
  const canCustomers = hasPermission(identity, "customer.view");
  const canEnvironments = hasPermission(identity, "environment.view");
  const canClusters = hasPermission(identity, "cluster.view");
  const canMigrations = hasPermission(identity, "migration.view");
  const defaults = {
    staleTime: 60_000,
    retry: false,
    refetchOnWindowFocus: false,
  };
  const customerQuery = useQuery({
    queryKey: ["dashboard", "customers", ...actor],
    queryFn: ({ signal }) =>
      allPages((page) =>
        customersService.list(
          { page, pageSize: 100, sort: "updatedAt,desc" },
          signal,
        ),
      ),
    enabled: canCustomers,
    ...defaults,
  });
  const environmentQuery = useQuery({
    queryKey: ["dashboard", "environments", ...actor],
    queryFn: ({ signal }) =>
      allPages((page) =>
        environments.list(
          { page, pageSize: 100, sort: "updatedAt,desc" },
          signal,
        ),
      ),
    enabled: canEnvironments,
    ...defaults,
  });
  const clusterQuery = useQuery({
    queryKey: ["dashboard", "clusters", ...actor],
    queryFn: ({ signal }) =>
      allPages((page) => clusters.list({ page, pageSize: 100 }, signal)),
    enabled: canClusters,
    ...defaults,
  });
  const migrationQuery = useQuery({
    queryKey: ["dashboard", "migrations", ...actor],
    queryFn: ({ signal }) => allPages((page) => migrations.list(signal, page)),
    enabled: canMigrations,
    ...defaults,
  });
  const match = (record: { customerId: string; environmentId?: string }) =>
    (scope.customerId === "all" || record.customerId === scope.customerId) &&
    (scope.environmentId === "all" ||
      record.environmentId === scope.environmentId);
  const cs =
    canCustomers &&
    customerQuery.data &&
    !customerQuery.error &&
    (scope.environmentId === "all" ||
      (environmentQuery.data && !environmentQuery.error))
      ? customerQuery.data.filter(
          (c) =>
            (scope.customerId === "all" || c.customerId === scope.customerId) &&
            (scope.environmentId === "all" ||
              environmentQuery.data?.some(
                (e) =>
                  e.environmentId === scope.environmentId &&
                  e.customerId === c.customerId,
              )),
        )
      : undefined;
  const es =
    canEnvironments && environmentQuery.data && !environmentQuery.error
      ? environmentQuery.data.filter(match)
      : undefined;
  const fleet =
    canClusters && clusterQuery.data && !clusterQuery.error
      ? clusterQuery.data.filter(match)
      : undefined;
  // Migration summaries have no environment association. Never present customer totals as environment-scoped counts.
  const ms =
    canMigrations &&
    scope.environmentId === "all" &&
    migrationQuery.data &&
    !migrationQuery.error
      ? migrationQuery.data.filter(
          (m) =>
            scope.customerId === "all" || m.customerId === scope.customerId,
        )
      : undefined;
  const planQueries = useQueries({
    queries: (fleet ?? []).map((c) => ({
      queryKey: ["eks-upgrade-plans", ...actor, c.clusterId],
      queryFn: () => clusters.upgradePlans(c.clusterId),
      ...defaults,
    })),
  });
  const inventoryClusters = (fleet ?? []).filter((c) => c.status === "ACTIVE");
  const inventoryQueries = useQueries({
    queries: inventoryClusters.map((c) => ({
      queryKey: ["dashboard", "inventory", ...actor, c.clusterId],
      queryFn: () => clusters.platformComponents(c.clusterId),
      ...defaults,
    })),
  });
  const planRows = (fleet ?? []).flatMap((cluster, i) =>
    (planQueries[i]?.data?.items ?? []).map((plan) => ({ cluster, plan })),
  );
  const inventories = new Map(
    inventoryClusters.map((c, i) => [
      c.clusterId,
      inventoryQueries[i]?.error ? undefined : inventoryQueries[i]?.data,
    ]),
  );
  const plansComplete =
    fleet !== undefined &&
    planQueries.every((q) => q.data !== undefined && !q.error);
  const inventoriesComplete =
    fleet !== undefined &&
    inventoryQueries.every((q) => q.data !== undefined && !q.error);
  const baseQueries = [
    customerQuery,
    environmentQuery,
    clusterQuery,
    migrationQuery,
  ];
  const enabled = [canCustomers, canEnvironments, canClusters, canMigrations];
  const queries = [
    ...baseQueries.filter((_, i) => enabled[i]),
    ...planQueries,
    ...inventoryQueries,
  ];
  return {
    customers: cs,
    environments: es,
    fleet,
    migrations: ms,
    planRows,
    inventories,
    plansComplete,
    inventoriesComplete,
    scope,
    identity,
    pending: queries.some((q) => q.isLoading),
    refreshing: queries.some((q) => q.isFetching),
    errors: queries.filter((q) => q.error).length,
    updatedAt:
      queries.length && queries.every((q) => q.dataUpdatedAt > 0 && !q.error)
        ? Math.min(...queries.map((q) => q.dataUpdatedAt))
        : 0,
    refresh: () =>
      Promise.all(queries.map((q) => q.refetch({ throwOnError: true }))),
  };
}
