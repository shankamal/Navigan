import { z } from "zod";

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
  createdAt: z.string(),
  updatedAt: z.string(),
});
export const clusterListSchema = z.object({
  items: z.array(clusterSchema),
  pagination: z.object({
    page: z.number(), pageSize: z.number(), totalElements: z.number(), totalPages: z.number(),
  }),
});
export const executionLogsSchema = z.object({
  status: z.string(),
  executionId: z.string().optional(),
  complete: z.boolean(),
  events: z.array(
    z.object({
      timestamp: z.number(),
      message: z.string(),
    }),
  ),
});
export interface ClusterInput {
  environmentId: string;
  environmentApprovedVersion: number;
  blueprintName: string;
  clusterName: string;
  description?: string;
}
export interface ClusterFilters {
  page?: number;
  pageSize?: number;
  status?: string;
  search?: string;
}
export type ExecutionLogs = z.infer<typeof executionLogsSchema>;
