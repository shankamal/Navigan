import { apiClient, parseResponse, writeHeaders } from "@/shared/api/client";
import {
  clusterListSchema,
  clusterSchema,
  executionLogsSchema,
  type ClusterFilters,
  type ClusterInput,
} from "./model";

const base = "/clusters";
export const clusters = {
  list: async (filters: ClusterFilters = {}) =>
    parseResponse(
      clusterListSchema,
      (
        await apiClient.get(base, {
          params: { page: 0, pageSize: 20, ...filters },
        })
      ).data,
    ),
  get: async (id: string) =>
    parseResponse(clusterSchema, (await apiClient.get(base + "/" + id)).data),
  executionLogs: async (id: string) =>
    parseResponse(
      executionLogsSchema,
      (await apiClient.get(base + "/" + id + "/execution-logs")).data,
    ),
  create: async (input: ClusterInput) =>
    parseResponse(clusterSchema, (
      await apiClient.post(base, input, { headers: writeHeaders({ key: crypto.randomUUID() }) })
    ).data),
  action: async (
    id: string,
    action: "submit" | "review" | "approve" | "reject" | "plan" | "apply",
    version: number,
    comments = "",
  ) =>
    parseResponse(clusterSchema, (
      await apiClient.post(
        base + "/" + id + "/" + action,
        { version, comments, ...(action === "reject" ? { reason: comments } : {}) },
        { headers: writeHeaders({ key: crypto.randomUUID(), version }) },
      )
    ).data),
};
