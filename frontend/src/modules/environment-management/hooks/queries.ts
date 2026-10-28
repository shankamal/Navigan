import { useQuery } from "@tanstack/react-query";
import { environments } from "../services/environments";
import type { BootstrapRemediationFilters, Filters } from "../model/types";

export const useEnvironments = (filters: Filters) =>
  useQuery({
    queryKey: ["environments", filters],
    queryFn: ({ signal }) => environments.list(filters, signal),
  });

export const useEnvironmentSummary = (enabled = true) =>
  useQuery({
    queryKey: ["environment-count", "summary"],
    queryFn: ({ signal }) => environments.summary(signal),
    enabled,
  });

export const useEnvironmentCount = (status?: string, enabled = true) => {
  return useQuery({
    queryKey: ["environment-count", "summary"],
    queryFn: ({ signal }) => environments.summary(signal),
    select: (summary) =>
      status ? (summary.byStatus[status] ?? 0) : summary.total,
    enabled,
  });
};

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
export const useBootstrapRemediations = (
  filters: BootstrapRemediationFilters,
) =>
  useQuery({
    queryKey: ["bootstrap-remediations", filters],
    queryFn: () => environments.listBootstrapRemediations(filters),
  });
export const useBootstrapRemediation = (requestId: string) =>
  useQuery({
    queryKey: ["bootstrap-remediation", requestId],
    queryFn: () => environments.getBootstrapRemediation(requestId),
    enabled: Boolean(requestId),
  });
export const useConfigurationSchema = (
  distribution: string,
  version = "1.0",
  enabled = true,
) =>
  useQuery({
    queryKey: ["environment-schema", distribution, version],
    queryFn: () => environments.schema(distribution, version),
    enabled: enabled && !!distribution,
    staleTime: 300000,
  });
