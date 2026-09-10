import { useQuery } from "@tanstack/react-query";
import { environments } from "../services/environments";
import type { Filters } from "../model/types";

export const useEnvironments = (filters: Filters) =>
  useQuery({
    queryKey: ["environments", filters],
    queryFn: () => environments.list(filters),
  });

export const useEnvironmentCount = (status?: string) =>
  useQuery({
    queryKey: ["environment-count", status || "ALL"],
    queryFn: async () =>
      (
        await environments.list({
          page: 0,
          pageSize: 1,
          sort: "createdAt,desc",
          status,
        })
      ).pagination.totalElements,
  });

export const useEnvironment = (id: string) =>
  useQuery({
    queryKey: ["environment", id],
    queryFn: () => environments.get(id),
    enabled: !!id,
  });
export const useMetadata = () =>
  useQuery({
    queryKey: ["environment-metadata"],
    queryFn: environments.metadata,
    staleTime: 300000,
  });
export const useConfigurationSchema = (distribution: string, version = "1.0") =>
  useQuery({
    queryKey: ["environment-schema", distribution, version],
    queryFn: () => environments.schema(distribution, version),
    enabled: !!distribution,
    staleTime: 300000,
  });
