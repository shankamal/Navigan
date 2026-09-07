import { useQuery } from "@tanstack/react-query";
import { environments } from "../services/environments";
import type { Filters } from "../model/types";
export const useEnvironments = (filters: Filters) =>
  useQuery({
    queryKey: ["environments", filters],
    queryFn: () => environments.list(filters),
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
