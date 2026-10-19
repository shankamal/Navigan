import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { migrations, sourceClusters } from "./service";

export const useSourceClusters = (customerId: string) =>
  useQuery({
    queryKey: ["source-clusters", customerId],
    queryFn: ({ signal }) => sourceClusters.list(customerId, signal),
    enabled: Boolean(customerId),
    retry: false,
  });

export const useMigrations = () =>
  useQuery({
    queryKey: ["migrations"],
    queryFn: ({ signal }) => migrations.list(signal),
    retry: false,
  });

export const useCancelMigration = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      migrationId,
      version,
    }: {
      migrationId: string;
      version: number;
    }) =>
      migrations.action(
        migrationId,
        "cancel",
        version,
        "Cancel and archive migration assessment",
      ),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ["migrations"],
      }),
  });
};

export const useDeleteMigrationAssessment = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ migrationId, version }: { migrationId: string; version: number }) =>
      migrations.action(migrationId, "cancel", version, "Delete migration assessment", true),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["migrations"] }),
  });
};

export const useMigration = (migrationId: string) =>
  useQuery({
    queryKey: ["migrations", migrationId],
    queryFn: ({ signal }) => migrations.get(migrationId, signal),
    enabled: Boolean(migrationId),
    retry: false,
  });

export const useSourceCatalogue = (migrationId: string) =>
  useQuery({
    queryKey: ["migrations", migrationId, "source-catalogue"],
    queryFn: ({ signal }) => migrations.sourceCatalogue(migrationId, signal),
    enabled: Boolean(migrationId),
    retry: false,
    refetchInterval: (query) => (query.state.data?.catalogue ? false : 5_000),
  });

export const useSourceInventory = (migrationId: string, enabled: boolean) =>
  useQuery({
    queryKey: ["migrations", migrationId, "source-inventory"],
    queryFn: ({ signal }) => migrations.sourceInventory(migrationId, signal),
    enabled: Boolean(migrationId) && enabled,
    retry: 2,
    refetchOnMount: "always",
    refetchOnWindowFocus: true,
  });

export const useMigrationAssessment = (migrationId: string, enabled: boolean) =>
  useQuery({
    queryKey: ["migrations", migrationId, "assessment"],
    queryFn: ({ signal }) => migrations.assessment(migrationId, signal),
    enabled: Boolean(migrationId) && enabled,
    retry: false,
    refetchInterval: (query) =>
      ["DISCOVERY_PENDING", "DISCOVERING", "ASSESSING"].includes(
        query.state.data?.status ?? "",
      ) || !query.state.data?.assessment
        ? 5_000
        : false,
  });

