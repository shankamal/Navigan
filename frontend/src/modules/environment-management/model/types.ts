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
  maxItems?: number;
  uniqueItems?: boolean;
  minimum?: number;
  maximum?: number;
  pattern?: string;
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
  pendingApprovedVersion: z.number().nullable().optional(),
  approvedStatus: z
    .enum(["ACTIVE", "SUSPENDED", "DEACTIVATED"])
    .nullable()
    .optional(),
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
export interface AwsDiscoveryInput {
  customerId: string;
  accountId: string;
  roleArn: string;
  externalId: string;
  regions: string[];
}
const discoveredRegionSchema = z.object({
  region: z.string(),
  availabilityZones: z.array(z.object({ name: z.string(), state: z.string() })),
  vpcs: z.array(
    z.object({
      vpcId: z.string(),
      name: z.string(),
      cidrBlock: z.string().nullable().optional(),
      isDefault: z.boolean(),
    }),
  ),
  subnets: z.array(
    z.object({
      subnetId: z.string(),
      name: z.string(),
      vpcId: z.string(),
      availabilityZone: z.string(),
      cidrBlock: z.string().nullable().optional(),
      availableIpAddressCount: z.number(),
      mapPublicIpOnLaunch: z.boolean(),
      routeTableId: z.string(),
      type: z.enum(["PRIVATE", "PUBLIC"]),
      egressTarget: z.string(),
    }),
  ),
  securityGroups: z.array(
    z.object({
      securityGroupId: z.string(),
      name: z.string(),
      description: z.string(),
      vpcId: z.string().nullable().optional(),
    }),
  ),
  vpcEndpoints: z.array(
    z.object({ vpcEndpointId: z.string(), serviceName: z.string() }),
  ),
  natGateways: z.array(
    z.object({
      natGatewayId: z.string(),
      vpcId: z.string(),
      subnetId: z.string(),
      state: z.string(),
    }),
  ),
  instanceTypes: z
    .array(
      z.object({
        instanceType: z.string(),
        vCpu: z.number(),
        memoryMiB: z.number(),
        architectures: z.array(z.string()),
        currentGeneration: z.boolean(),
        burstablePerformanceSupported: z.boolean(),
      }),
    )
    .optional(),
  kmsKeys: z.array(
    z.object({
      aliasName: z.string(),
      keyArn: z.string(),
      eligibility: z.enum(["READY", "WARNING", "BLOCKED"]).optional(),
      eligibilityReason: z.string().optional(),
    }),
  ),
  kubernetesVersions: z
    .array(
      z.object({
        version: z.string(),
        support: z.enum([
          "STANDARD_SUPPORT",
          "EXTENDED_SUPPORT",
          "UNSUPPORTED",
        ]),
        default: z.boolean(),
      }),
    )
    .optional(),
  eksClusters: z.array(z.object({ name: z.string() })),
  ecrRepositories: z.array(
    z.object({
      repositoryName: z.string(),
      repositoryArn: z.string(),
      imageTagMutability: z.string(),
    }),
  ),
  serviceQuotas: z.array(
    z.object({
      serviceCode: z.string(),
      quotaCode: z.string(),
      quotaName: z.string(),
      value: z.number(),
      adjustable: z.boolean(),
    }),
  ),
  ebsEncryptionByDefault: z.boolean(),
});
export const awsDiscoverySchema = z.object({
  cloudProvider: z.literal("AWS"),
  kubernetesDistribution: z.literal("EKS"),
  account: z.object({ accountId: z.string(), principalArn: z.string() }),
  roleArn: z.string(),
  regions: z.array(discoveredRegionSchema),
  iamRoles: z.array(
    z.object({
      roleName: z.string(),
      roleArn: z.string(),
      roleType: z.enum(["CLUSTER", "NODE", "OTHER"]).optional(),
      eligibility: z.enum(["READY", "WARNING", "BLOCKED"]).optional(),
      eligibilityReason: z.string().optional(),
    }),
  ),
  provisioningRoles: z.array(z.object({ roleName: z.string(), roleArn: z.string() })),
  provisioningSecrets: z.array(z.object({ name: z.string(), arn: z.string() })),
  counts: z.record(z.string(), z.number()),
  fetchedAt: z.string(),
});
export type AwsDiscovery = z.infer<typeof awsDiscoverySchema>;
export const blueprintFindingSchema = z.object({
  code: z.string(),
  field: z.string(),
  severity: z.enum(["BLOCKING", "WARNING"]),
  message: z.string(),
  recommendation: z.string(),
});
export const blueprintReadinessSchema = z.object({
  status: z.enum(["PASSED", "FAILED"]),
  score: z.number(),
  blockingCount: z.number().int().nonnegative(),
  warningCount: z.number().int().nonnegative(),
  findings: z.array(blueprintFindingSchema),
  advisor: z.object({
    mode: z.enum(["DETERMINISTIC", "BEDROCK"]),
    summary: z.string(),
    modelId: z.string().optional(),
  }),
});
export type BlueprintReadiness = z.infer<typeof blueprintReadinessSchema>;
export const bootstrapRemediationSchema = z.object({
  requestId: z.string(),
  customerId: z.string(),
  customerName: z.string().optional(),
  accountId: z.string(),
  region: z.string(),
  discoveryRoleArn: z.string(),
  missingResources: z.array(z.string()),
  requestedActions: z.array(z.string()),
  status: z.enum([
    "REQUESTED",
    "APPROVED",
    "REJECTED",
    "PLAN_RUNNING",
    "PLAN_READY",
    "APPLY_RUNNING",
    "COMPLETED",
    "FAILED",
  ]),
  confirmedBy: z.string(),
  confirmedAt: z.string(),
  requestedBy: z.string(),
  requestedAt: z.string(),
  decidedBy: z.string().nullable().optional(),
  decidedAt: z.string().nullable().optional(),
  decisionReason: z.string().nullable().optional(),
  version: z.number().int().positive(),
  correlationId: z.string(),
});
export type BootstrapRemediation = z.infer<typeof bootstrapRemediationSchema>;
export const bootstrapRemediationListSchema = z.object({
  items: z.array(bootstrapRemediationSchema),
  pagination: paginationSchema,
});
export interface BootstrapRemediationInput {
  customerId: string;
  accountId: string;
  region: string;
  discoveryRoleArn: string;
  missingResources: string[];
  requestedActions: string[];
  confirmed: true;
}
export interface BootstrapRemediationFilters {
  page: number;
  pageSize: number;
  status?: BootstrapRemediation["status"];
  customerId?: string;
  search?: string;
}
export interface BootstrapRemediationDecisionInput {
  version: number;
  reason?: string;
}
export interface Filters {
  page: number;
  pageSize: number;
  sort: string;
  search?: string;
  status?: string;
  approvedStatus?: string;
  cloudProvider?: string;
  customerId?: string;
  environmentType?: string;
  region?: string;
  createdBy?: string;
  createdFrom?: string;
  createdTo?: string;
}
export type Action =
  | "revise"
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
