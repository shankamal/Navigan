import { useQuery } from "@tanstack/react-query";
import { clusters } from "../service";
import type { ClusterFilters } from "../model";

export const useClusters = (filters: ClusterFilters) =>
  useQuery({
    queryKey: ["clusters", filters],
    queryFn: ({ signal }) => clusters.list(filters, signal),
    retry: false,
  });

export const useClusterCount = (status?: string, enabled = true) =>
  useQuery({
    queryKey: ["cluster-count", "summary"],
    queryFn: ({ signal }) => clusters.summary(signal),
    select: (summary) => status ? (summary.byStatus[status] ?? 0) : summary.total,
    retry: false,
    enabled,
  });

export const useCluster = (id: string) =>
  useQuery({
    queryKey: ["cluster", id],
    queryFn: () => clusters.get(id),
    enabled: !!id,
    retry: false,
  });
