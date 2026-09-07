import { z } from "zod";
import {
  paginationSchema,
  statusSchema,
} from "@/modules/customer-management/model/types";
export type JsonValue =
  string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };
export interface ConfigurationSchema {
  type: "object" | "array" | "string" | "number" | "integer" | "boolean";
  title?: string;
  properties?: Record<string, ConfigurationSchema>;
  items?: ConfigurationSchema;
  required?: string[];
  enum?: string[];
  const?: string;
  additionalProperties?: boolean;
  minItems?: number;
}
export const distributions = {
  AWS: "EKS",
  AZURE: "AKS",
  GCP: "GKE",
  OCI: "OKE",
} as const;
export type Provider = keyof typeof distributions;
export type Distribution = (typeof distributions)[Provider];
export const summarySchema = z.object({
  environmentId: z.string(),
  customerId: z.string(),
  customerName: z.string(),
  cloudProvider: z.enum(["AWS", "AZURE", "GCP", "OCI"]),
  kubernetesDistribution: z.enum(["EKS", "AKS", "GKE", "OKE"]),
  environmentName: z.string(),
  environmentType: z.string(),
  status: statusSchema,
  version: z.number().int().positive(),
  approvedVersion: z.number().nullable().optional(),
  createdAt: z.string(),
  updatedAt: z.string().nullable().optional(),
});
export const environmentSchema = summarySchema.extend({
  description: z.string(),
  configurationSchemaVersion: z.string(),
  configuration: z.record(z.string(), z.json()),
  createdBy: z.string(),
  workflow: z.record(
    z.string(),
    z.object({
      by: z.string(),
      at: z.string(),
      reason: z.string().nullable().optional(),
      comments: z.string().nullable().optional(),
      reasonCode: z.string().nullable().optional(),
    }),
  ),
});
export type Environment = z.infer<typeof environmentSchema>;
export type EnvironmentSummary = z.infer<typeof summarySchema>;
export const listSchema = z.object({
  items: z.array(summarySchema),
  pagination: paginationSchema,
});
export const metadataSchema = z.object({
  environmentTypes: z.array(z.string()),
  distributions: z.array(
    z.object({
      cloudProvider: z.enum(["AWS", "AZURE", "GCP", "OCI"]),
      kubernetesDistribution: z.enum(["EKS", "AKS", "GKE", "OKE"]),
      schemaVersions: z.array(z.string()),
    }),
  ),
});
export interface EnvironmentInput {
  customerId: string;
  cloudProvider: Provider;
  kubernetesDistribution: Distribution;
  environmentName: string;
  environmentType: string;
  description: string;
  configurationSchemaVersion: string;
  configuration: Record<string, JsonValue>;
}
export interface Filters {
  page: number;
  pageSize: number;
  sort: string;
  search?: string;
  status?: string;
  cloudProvider?: string;
  customerId?: string;
  environmentType?: string;
  region?: string;
  createdBy?: string;
  createdFrom?: string;
  createdTo?: string;
}
export type Action =
  | "submit"
  | "resubmit"
  | "review"
  | "approve"
  | "reject"
  | "activate"
  | "suspend"
  | "reactivate"
  | "deactivate";
export interface ActionInput {
  version: number;
  reason?: string;
  reasonCode?: string;
  comments?: string;
}
export type HistoryKind =
  "status-history" | "versions" | "reviews" | "audit-log";
export const recordSchema = z.object({
  environmentId: z.string(),
  version: z.number().optional(),
  createdAt: z.string().optional(),
  createdBy: z.string().optional(),
  changeReason: z.string().nullable().optional(),
  previousStatus: z.string().nullable().optional(),
  newStatus: z.string().optional(),
  changedBy: z.string().optional(),
  changedAt: z.string().optional(),
  reason: z.string().nullable().optional(),
  comments: z.string().nullable().optional(),
  reviewStatus: z.string().optional(),
  reviewerId: z.string().optional(),
  reviewedAt: z.string().optional(),
  environmentVersion: z.number().optional(),
  action: z.string().optional(),
  performedBy: z.string().optional(),
  performedAt: z.string().optional(),
  oldValue: z.json().optional(),
  newValue: z.json().optional(),
});
export const recordsSchema = z.object({
  items: z.array(recordSchema),
  pagination: paginationSchema,
});
