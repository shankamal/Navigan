import { useQuery } from "@tanstack/react-query";

import { migrations, sourceClusters } from "./service";

export const useSourceClusters = (customerId: string) =>
  useQuery({
    queryKey: ["source-clusters", customerId],
    queryFn: () => sourceClusters.list(customerId),
    enabled: Boolean(customerId),
    retry: false,
  });

export const useMigrations = () =>
  useQuery({
    queryKey: ["migrations"],
    queryFn: () => migrations.list(),
    retry: false,
  });

export const useMigration = (migrationId: string) =>
  useQuery({
    queryKey: ["migrations", migrationId],
    queryFn: () => migrations.get(migrationId),
    enabled: Boolean(migrationId),
    retry: false,
  });

export const useSourceCatalogue = (migrationId: string) =>
  useQuery({
    queryKey: ["migrations", migrationId, "source-catalogue"],
    queryFn: () => migrations.sourceCatalogue(migrationId),
    enabled: Boolean(migrationId),
    retry: false,
    refetchInterval: (query) => (query.state.data?.catalogue ? false : 5_000),
  });

export const useMigrationAssessment = (migrationId: string, enabled: boolean) =>
  useQuery({
    queryKey: ["migrations", migrationId, "assessment"],
    queryFn: () => migrations.assessment(migrationId),
    enabled: Boolean(migrationId) && enabled,
    retry: false,
    refetchInterval: (query) => (query.state.data?.assessment ? false : 5_000),
  });
