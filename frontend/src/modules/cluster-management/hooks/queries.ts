import { useQuery } from "@tanstack/react-query";
import { clusters } from "../service";
import type { ClusterFilters } from "../model";

export const useClusters = (filters: ClusterFilters) =>
  useQuery({
    queryKey: ["clusters", filters],
    queryFn: () => clusters.list(filters),
    retry: false,
  });

export const useClusterCount = (status?: string) =>
  useQuery({
    queryKey: ["cluster-count", status || "ALL"],
    queryFn: async () =>
      (await clusters.list({ page: 0, pageSize: 1, status })).pagination
        .totalElements,
    retry: false,
  });

export const useCluster = (id: string) =>
  useQuery({
    queryKey: ["cluster", id],
    queryFn: () => clusters.get(id),
    enabled: !!id,
    retry: false,
  });
