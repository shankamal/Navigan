import { z } from "zod";

export const clusterActionSchema = z.object({
  code: z.string(),
  label: z.string(),
  enabled: z.boolean(),
  disabledReason: z.string().nullable().optional(),
  destructive: z.boolean(),
  confirmation: z.string().nullable().optional(),
});

export const clusterSchema = z.object({
  clusterId: z.string(),
  customerId: z.string(),
  customerName: z.string().optional(),
  environmentId: z.string(),
  environmentName: z.string().optional(),
  environmentApprovedVersion: z.number(),
  platform: z.literal("EKS"),
  clusterName: z.string(),
  description: z.string().nullable().optional(),
  configuration: z.record(z.string(), z.unknown()).optional(),
  provisioningRoleArn: z.string().optional(),
  externalIdSecretArn: z.string().optional(),
  terraformModuleVersion: z.string().optional(),
  terraformStateKey: z.string().optional(),
  status: z.string(),
  version: z.number(),
  planSha256: z.string().nullable().optional(),
  providerExecutionId: z.string().nullable().optional(),
  outputs: z.record(z.string(), z.unknown()).optional(),
  workflow: z.record(z.string(), z.unknown()).optional(),
  allowedActions: z.array(clusterActionSchema).default([]),
  createdAt: z.string(),
  updatedAt: z.string(),
});
export const kubernetesAccessAssignmentSchema = z.object({
  assignmentId: z.string(),
  subjectType: z.enum(["USER", "GROUP"]),
  subjectId: z.string(),
  profileCode: z.string(),
  profileName: z.string(),
  scopeType: z.enum(["NAMESPACE", "CLUSTER"]),
  namespace: z.string().nullable().optional(),
  status: z.enum(["PENDING", "ACTIVE", "REVOKED", "EXPIRED"]),
  validFrom: z.string().optional(),
  validUntil: z.string().nullable().optional(),
});
export const kubernetesAccessProfileSchema = z.object({
  profileCode: z.string(),
  profileName: z.string(),
  description: z.string(),
  scopeType: z.enum(["NAMESPACE", "CLUSTER"]),
});
export const kubernetesAccessSchema = z.object({
  clusterId: z.string(),
  customerId: z.string(),
  assignments: z.array(kubernetesAccessAssignmentSchema),
  profiles: z.array(kubernetesAccessProfileSchema),
});
export const identitySubjectSchema = z.object({
  type: z.enum(["USER", "GROUP"]),
  id: z.string(),
  displayName: z.string(),
  email: z.string().nullable().optional(),
  username: z.string().nullable().optional(),
  description: z.string().nullable().optional(),
  aliases: z.array(z.string()).default([]),
  enabled: z.boolean().optional(),
  status: z.string().nullable().optional(),
});
export const identitySubjectsSchema = z.object({
  clusterId: z.string(),
  customerId: z.string(),
  users: z.array(identitySubjectSchema),
  groups: z.array(identitySubjectSchema),
  truncated: z.boolean(),
});
export const clusterNamespaceInventorySchema = z.object({
  clusterId: z.string(),
  customerId: z.string(),
  status: z.enum(["NOT_CONFIGURED", "SYNCING", "READY", "STALE", "FAILED"]),
  source: z.literal("IN_CLUSTER_CONNECTOR"),
  connectorId: z.string().nullable(),
  observedAt: z.string().nullable(),
  expiresAt: z.string().nullable(),
  failureCode: z.string().nullable(),
  namespaces: z.array(
    z.object({
      namespace: z.string(),
      isSystem: z.boolean(),
      observedAt: z.string(),
    }),
  ),
});
export const connectorInstallationSchema = z.object({
  connectorId: z.string(),
  clusterId: z.string(),
  customerId: z.string(),
  status: z.enum(["REQUESTED", "RUNNING"]),
  executionId: z.string(),
});
export const clusterNodeGroupRequestSchema = z.object({
  requestId: z.string(),
  clusterId: z.string(),
  customerId: z.string(),
  nodeGroup: z.object({
    name: z.string(),
    purpose: z.literal("APPLICATION"),
    instanceTypes: z.array(z.string()),
    capacityType: z.enum(["ON_DEMAND", "SPOT"]),
    minSize: z.number(),
    desiredSize: z.number(),
    maxSize: z.number(),
    diskSizeGiB: z.number(),
  }),
  reason: z.string(),
  status: z.string(),
  version: z.number(),
  planSha256: z.string().nullable().optional(),
  providerExecutionId: z.string().nullable().optional(),
  workflow: z.record(z.string(), z.unknown()).default({}),
  createdBy: z.string(),
  createdAt: z.string(),
  updatedBy: z.string(),
  updatedAt: z.string(),
});
export const clusterNodeGroupRequestsSchema = z.object({
  clusterId: z.string(),
  customerId: z.string(),
  items: z.array(clusterNodeGroupRequestSchema),
});
export const clusterListSchema = z.object({
  items: z.array(clusterSchema),
  pagination: z.object({
    page: z.number(), pageSize: z.number(), totalElements: z.number(), totalPages: z.number(),
  }),
});
export const executionLogsSchema = z.object({
  status: z.string(),
  requestStatus: z.string().optional(),
  operation: z.string().nullable().optional(),
  executionId: z.string().optional(),
  errorCode: z.string().nullable().optional(),
  complete: z.boolean(),
  events: z.array(
    z.object({
      timestamp: z.number(),
      message: z.string(),
    }),
  ),
});
export const clusterAuditLogSchema = z.object({
  clusterId: z.string(),
  customerId: z.string(),
  items: z.array(
    z.object({
      auditId: z.number(),
      clusterId: z.string(),
      action: z.string(),
      performedBy: z.string(),
      correlationId: z.string(),
      oldValue: z.record(z.string(), z.unknown()).nullable().optional(),
      newValue: z.record(z.string(), z.unknown()).nullable().optional(),
      occurredAt: z.string(),
    }),
  ),
});
export interface ClusterNodeGroupInput {
  name: string;
  purpose: "SYSTEM" | "APPLICATION";
  instanceTypes: string[];
  capacityType: "ON_DEMAND" | "SPOT";
  minSize: number;
  desiredSize: number;
  maxSize: number;
  diskSizeGiB: number;
  managementMode?: "MANAGED" | "ADOPTED";
}

export interface ClusterInput {
  environmentId: string;
  environmentApprovedVersion: number;
  blueprintName: string;
  clusterName: string;
  kubernetesVersion: string;
  endpointAccess: "PRIVATE" | "PUBLIC_AND_PRIVATE";
  nodeGroups: ClusterNodeGroupInput[];
  provisioningRoleArn: string;
  externalIdSecretArn: string;
  tags?: Record<string, string>;
  description?: string;
  githubOrganization: string;
}
export interface ClusterFilters {
  page?: number;
  pageSize?: number;
  status?: string;
  search?: string;
}
export type ExecutionLogs = z.infer<typeof executionLogsSchema>;
export type Cluster = z.infer<typeof clusterSchema>;
export type ClusterAction = z.infer<typeof clusterActionSchema>;
export type KubernetesAccess = z.infer<typeof kubernetesAccessSchema>;
export type IdentitySubject = z.infer<typeof identitySubjectSchema>;
export type ClusterNamespaceInventory = z.infer<
  typeof clusterNamespaceInventorySchema
>;
export type ConnectorInstallation = z.infer<typeof connectorInstallationSchema>;
export type ClusterNodeGroupRequest = z.infer<
  typeof clusterNodeGroupRequestSchema
>;
