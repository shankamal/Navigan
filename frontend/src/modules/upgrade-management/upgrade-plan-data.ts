"use client";

import { useQueries, useQuery } from "@tanstack/react-query";
import { clusters } from "@/modules/cluster-management/service";
import { useAuth } from "@/shared/auth/auth-provider";

export function useUpgradePlans() {
  const { identity } = useAuth();
  const actor = [identity?.subject, identity?.authorizationRevision];
  const fleet = useQuery({
    queryKey: ["upgrade-plan-fleet", ...actor],
    queryFn: async () => {
      const first = await clusters.list({ page: 0, pageSize: 100 });
      const items = [...first.items];
      for (let page = 1; page < first.pagination.totalPages; page++) {
        const next = await clusters.list({ page, pageSize: 100 });
        items.push(...next.items);
      }
      return items;
    },
    staleTime: 10_000,
  });
  const items = fleet.data ?? [];
  const queries = useQueries({
    queries: items.map((cluster) => ({
      queryKey: ["eks-upgrade-plans", ...actor, cluster.clusterId],
      queryFn: () => clusters.upgradePlans(cluster.clusterId),
      staleTime: 0,
      retry: false,
    })),
  });
  return {
    identity,
    rows: items.flatMap((cluster, index) =>
      (queries[index]?.data?.items ?? []).map((plan) => ({
        clusterName: cluster.clusterName,
        environment: cluster.environmentName ?? "Environment",
        plan,
      })),
    ),
    pending: fleet.isPending || queries.some((query) => query.isPending),
    errors: [
      ...(fleet.error ? [fleet.error.message] : []),
      ...queries.flatMap((query, index) =>
        query.error
          ? [items[index].clusterName + ": " + query.error.message]
          : [],
      ),
    ],
    refresh: () => {
      void fleet.refetch();
      for (const query of queries) void query.refetch();
    },
  };
}
