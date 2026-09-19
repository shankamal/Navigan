import { apiClient, parseResponse, writeHeaders } from "@/shared/api/client";
import {
  clusterListSchema,
  clusterSchema,
  executionLogsSchema,
  clusterAuditLogSchema,
  kubernetesAccessAssignmentSchema,
  kubernetesAccessSchema,
  identitySubjectsSchema,
  clusterNamespaceInventorySchema,
  connectorInstallationSchema,
  clusterNodeGroupRequestSchema,
  clusterNodeGroupRequestsSchema,
  type ClusterFilters,
  type ClusterInput,
  type ClusterNodeGroupInput,
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
  nodeGroupExecutionLogs: async (id: string, requestId: string) =>
    parseResponse(
      executionLogsSchema,
      (
        await apiClient.get(
          `${base}/${id}/node-groups/${requestId}/execution-logs`,
        )
      ).data,
    ),
  auditLog: async (id: string) =>
    parseResponse(
      clusterAuditLogSchema,
      (await apiClient.get(`${base}/${id}/audit-log`)).data,
    ),
  access: async (id: string) =>
    parseResponse(
      kubernetesAccessSchema,
      (await apiClient.get(base + "/" + id + "/access")).data,
    ),
  accessSubjects: async (id: string) =>
    parseResponse(
      identitySubjectsSchema,
      (await apiClient.get(base + "/" + id + "/access/subjects")).data,
    ),
  accessNamespaces: async (id: string) =>
    parseResponse(
      clusterNamespaceInventorySchema,
      (await apiClient.get(base + "/" + id + "/access/namespaces")).data,
    ),
  installConnector: async (id: string, version: number, reason: string) =>
    parseResponse(
      connectorInstallationSchema,
      (
        await apiClient.post(
          base + "/" + id + "/connector/install",
          { version, reason },
          {
            headers: writeHeaders({
              version,
              key: crypto.randomUUID(),
            }),
          },
        )
      ).data,
    ),
  nodeGroupRequests: async (id: string) =>
    parseResponse(
      clusterNodeGroupRequestsSchema,
      (await apiClient.get(base + "/" + id + "/node-groups")).data,
    ),
  createNodeGroupRequest: async (
    id: string,
    nodeGroup: {
      name: string;
      purpose: "APPLICATION";
      instanceTypes: string[];
      capacityType: "ON_DEMAND" | "SPOT";
      minSize: number;
      desiredSize: number;
      maxSize: number;
      diskSizeGiB: number;
    },
    reason: string,
  ) =>
    parseResponse(
      clusterNodeGroupRequestSchema,
      (
        await apiClient.post(
          base + "/" + id + "/node-groups",
          { nodeGroup, reason },
          { headers: writeHeaders({ key: crypto.randomUUID() }) },
        )
      ).data,
    ),
  nodeGroupAction: async (
    id: string,
    requestId: string,
    action: "submit" | "approve" | "reject" | "apply" | "retry",
    version: number,
    comments = "",
  ) =>
    parseResponse(
      clusterNodeGroupRequestSchema,
      (
        await apiClient.post(
          `${base}/${id}/node-groups/${requestId}/${action}`,
          {
            version,
            comments,
            ...(["reject"].includes(action) ? { reason: comments } : {}),
          },
          { headers: writeHeaders({ key: crypto.randomUUID(), version }) },
        )
      ).data,
    ),
  assignAccess: async (
    id: string,
    input: {
      subjectType: "USER" | "GROUP";
      subjectId: string;
      profileCode: string;
      namespace?: string;
      reason: string;
    },
  ) =>
    parseResponse(
      kubernetesAccessAssignmentSchema,
      (
        await apiClient.post(base + "/" + id + "/access/assignments", input, {
          headers: writeHeaders({ key: crypto.randomUUID() }),
        })
      ).data,
    ),
  revokeAccess: async (id: string, assignmentId: string, reason: string) =>
    parseResponse(
      kubernetesAccessAssignmentSchema,
      (
        await apiClient.post(
          base + "/" + id + "/access/assignments/" + assignmentId + "/revoke",
          { reason },
          { headers: writeHeaders({ key: crypto.randomUUID() }) },
        )
      ).data,
    ),
  create: async (input: ClusterInput) =>
    parseResponse(clusterSchema, (
      await apiClient.post(base, input, { headers: writeHeaders({ key: crypto.randomUUID() }) })
    ).data),
  beginGitHubAuthorization: async (id: string, version: number) =>
    (
      await apiClient.post(
        `${base}/${id}/github/authorize`,
        { version },
        { headers: writeHeaders({ key: crypto.randomUUID(), version }) },
      )
    ).data as {
      authorizationUrl: string;
      state: string;
      expiresInSeconds: number;
      organization: string;
      repositoryName: string;
    },
  completeGitHubAuthorization: async (
    id: string,
    version: number,
    state: string,
    installationId: number,
  ) =>
    (
      await apiClient.post(
        `${base}/${id}/github/complete`,
        { version, state, installationId },
        { headers: writeHeaders({ key: crypto.randomUUID(), version }) },
      )
    ).data,
  migrateSystemNodeGroup: async (
    id: string,
    version: number,
    legacyNodeGroupName: string,
    targetNodeGroup: ClusterNodeGroupInput,
    reason: string,
  ) =>
    parseResponse(
      clusterSchema,
      (
        await apiClient.post(
          `${base}/${id}/migrate-system-node-group`,
          { version, legacyNodeGroupName, targetNodeGroup, reason },
          { headers: writeHeaders({ key: crypto.randomUUID(), version }) },
        )
      ).data,
    ),
  action: async (
    id: string,
    action:
      | "submit"
      | "review"
      | "approve"
      | "reject"
      | "plan"
      | "apply"
      | "stop"
      | "start"
      | "delete",
    version: number,
    comments = "",
  ) =>
    parseResponse(clusterSchema, (
      await apiClient.post(
        base + "/" + id + "/" + action,
        {
          version,
          comments,
          ...(["reject", "delete"].includes(action) ? { reason: comments } : {}),
        },
        { headers: writeHeaders({ key: crypto.randomUUID(), version }) },
      )
    ).data),
};
