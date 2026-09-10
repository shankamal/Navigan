import { apiClient, parseResponse, writeHeaders } from "@/shared/api/client";
import { clusterListSchema, clusterSchema, type ClusterInput } from "./model";

const base = "/clusters";
export const clusters = {
  list: async () =>
    parseResponse(clusterListSchema, (await apiClient.get(base, { params: { page: 0, pageSize: 50 } })).data),
  get: async (id: string) =>
    parseResponse(clusterSchema, (await apiClient.get(base + "/" + id)).data),
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
