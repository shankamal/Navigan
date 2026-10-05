import { useQuery } from "@tanstack/react-query";

import { migrations } from "./service";

export const useSourceCatalogue = (
  migrationId: string,
) =>
  useQuery({
    queryKey: [
      "migrations",
      migrationId,
      "source-catalogue",
    ],
    queryFn: () =>
      migrations.sourceCatalogue(migrationId),
    enabled: Boolean(migrationId),
    retry: false,
    refetchInterval: (query) =>
      query.state.data?.catalogue ? false : 5_000,
  });
