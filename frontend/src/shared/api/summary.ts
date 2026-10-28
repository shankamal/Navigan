import { z } from "zod";
import { ApiError, apiClient, parseResponse } from "./client";

export const summarySchema = z.object({
  total: z.number().int().nonnegative(),
  byStatus: z.record(z.string(), z.number().int().nonnegative()),
  byProvider: z.record(z.string(), z.number().int().nonnegative()),
});

export type ResourceSummary = z.infer<typeof summarySchema>;

/** Keep existing capabilities usable until the summary routes are deployed. */
export async function resourceSummary(
  resource: "customers" | "environments" | "clusters",
  statuses: readonly string[],
  providers: readonly string[],
  legacyCount: (
    status?: string,
    provider?: string,
    signal?: AbortSignal,
  ) => Promise<number>,
  signal?: AbortSignal,
): Promise<ResourceSummary> {
  try {
    return parseResponse(
      summarySchema,
      (await apiClient.get(`/${resource}/summary`, { signal })).data,
    );
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 404) throw error;
  }

  const [total, statusCounts, providerCounts] = await Promise.all([
    legacyCount(undefined, undefined, signal),
    Promise.all(
      statuses.map((status) => legacyCount(status, undefined, signal)),
    ),
    Promise.all(
      providers.map((provider) => legacyCount(undefined, provider, signal)),
    ),
  ]);
  return {
    total,
    byStatus: Object.fromEntries(
      statuses.map((status, index) => [status, statusCounts[index]]),
    ),
    byProvider: Object.fromEntries(
      providers.map((provider, index) => [provider, providerCounts[index]]),
    ),
  };
}
