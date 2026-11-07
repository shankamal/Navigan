import { z } from "zod";

function versionTuple(version: string): number[] {
  return version.split(".").map((part) => Number(part) || 0);
}

function compareVersionsDescending(left: string, right: string): number {
  const a = versionTuple(left);
  const b = versionTuple(right);
  return (b[0] || 0) - (a[0] || 0) || (b[1] || 0) - (a[1] || 0);
}

export function supportedEksVersions(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return [
    ...new Set(
      value
        .map((item) => {
          if (typeof item === "string") return item;
          if (!item || typeof item !== "object" || Array.isArray(item))
            return "";
          const record = item as Record<string, unknown>;
          return typeof record.version === "string" &&
            ["STANDARD_SUPPORT", "EXTENDED_SUPPORT"].includes(
              String(record.support),
            )
            ? record.version
            : "";
        })
        .filter(Boolean),
    ),
  ].toSorted(compareVersionsDescending);
}

export type ClusterLifecycleAction =
  | "submit"
  | "review"
  | "approve"
  | "reject"
  | "plan"
  | "apply"
  | "stop"
  | "start"
  | "delete";

export function clusterLifecycleActions({
  status,
  canSubmit,
  canReview,
  canOperate,
  canDelete,
  certificationPassed,
}: {
  status: string;
  canSubmit: boolean;
  canReview: boolean;
  canOperate: boolean;
  canDelete: boolean;
  certificationPassed: boolean;
}): ClusterLifecycleAction[] {
  if (canSubmit && ["DRAFT", "REJECTED"].includes(status)) return ["submit"];
  if (canReview && status === "SUBMITTED") return ["review"];
  if (canReview && status === "UNDER_REVIEW") return ["approve", "reject"];
  if (canReview && status === "FAILED") return ["plan"];
  if (canReview && status === "PLAN_READY")
    return certificationPassed ? ["apply"] : ["plan"];
  if (canOperate && status === "ACTIVE")
    return canDelete ? ["stop", "delete"] : ["stop"];
  if (canOperate && status === "STOPPED")
    return canDelete ? ["start", "delete"] : ["start"];
  if (canDelete && status === "FAILED") return ["delete"];
  return [];
}

export function shouldShowClusterExecutionPanel({
  hasExecutionId,
  historicalExecution,
  status,
}: {
  hasExecutionId: boolean;
  historicalExecution: boolean;
  status: string;
}): boolean {
  return (
    hasExecutionId &&
    (!historicalExecution ||
      ["FAILED", "BOOTSTRAPPING", "BOOTSTRAP_FAILED"].includes(status))
  );
}

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
export const clusterRuntimeInventorySchema = z.object({
  clusterId: z.string(),
  customerId: z.string(),
  status: z.enum(["NOT_REPORTED", "READY", "DEGRADED", "STALE"]),
  connectorId: z.string().nullable(),
  sourceRevision: z.number().nullable(),
  observedAt: z.string().nullable(),
  expiresAt: z.string().nullable(),
  metrics: z.record(z.string(), z.number()),
  resources: z.array(
    z.object({
      kind: z.enum([
        "Node",
        "Deployment",
        "StatefulSet",
        "DaemonSet",
        "Pod",
        "Service",
      ]),
      namespace: z.string().nullable(),
      name: z.string(),
      status: z.string(),
      ready: z.number(),
      desired: z.number(),
      restarts: z.number(),
    }),
  ),
  warningEvents: z.array(
    z.object({
      namespace: z.string().nullable(),
      reason: z.string(),
      resourceKind: z.string().nullable(),
      resourceName: z.string().nullable(),
      message: z.string(),
      count: z.number(),
      lastObservedAt: z.string().nullable(),
    }),
  ),
});
export const platformComponentInventorySchema = z.object({
  clusterId: z.string(),
  customerId: z.string(),
  status: z.enum(["NOT_REPORTED", "READY", "DEGRADED"]),
  connectorId: z.string().nullable(),
  sourceRevision: z.number().nullable(),
  observedAt: z.string().nullable(),
  components: z.array(
    z.object({
      componentCode: z.string(),
      status: z.enum(["READY", "PROGRESSING", "DEGRADED", "MISSING"]),
      version: z.string().nullable(),
      syncStatus: z.string().nullable(),
      healthStatus: z.string().nullable(),
      observedAt: z.string().nullable(),
      sourceRevision: z.number().nullable(),
    }),
  ),
  runtimeInventory: clusterRuntimeInventorySchema,
});
const eksHealthIssueSchema = z.object({
  code: z.string().nullable().optional(),
  message: z.string().nullable().optional(),
  resourceIds: z.array(z.string()).default([]),
});
const eksVersionEvidenceSchema = z.object({
  version: z.string(),
  supportStatus: z.string(),
  releaseDate: z.string().nullable(),
  endOfStandardSupportDate: z.string().nullable(),
  endOfExtendedSupportDate: z.string().nullable(),
  defaultPlatformVersion: z.string().nullable().optional(),
  kubernetesPatchVersion: z.string().nullable().optional(),
});
const eksReadinessFindingSchema = z.object({
  code: z.string(),
  message: z.string(),
  insightId: z.string().nullable().optional(),
});
export const eksUpgradeReadinessSchema = z.object({
  clusterId: z.string(),
  customerId: z.string(),
  provider: z.literal("EKS"),
  region: z.string(),
  source: z.literal("AWS_EKS_API"),
  observedAt: z.string(),
  controlPlane: z.object({
    name: z.string(),
    arn: z.string().nullable().optional(),
    version: z.string(),
    platformVersion: z.string().nullable().optional(),
    status: z.string(),
    support: eksVersionEvidenceSchema.nullable().optional(),
  }),
  recommendedTarget: eksVersionEvidenceSchema.nullable(),
  nodeGroups: z.array(
    z.object({
      name: z.string(),
      version: z.string().nullable().optional(),
      releaseVersion: z.string().nullable().optional(),
      status: z.string(),
      amiType: z.string().nullable().optional(),
      capacityType: z.string().nullable().optional(),
      healthIssues: z.array(eksHealthIssueSchema),
    }),
  ),
  addons: z.array(
    z.object({
      name: z.string(),
      version: z.string().nullable().optional(),
      status: z.string(),
      serviceAccountRoleArn: z.string().nullable().optional(),
      healthIssues: z.array(eksHealthIssueSchema),
      targetVersion: z.string().nullable(),
    }),
  ),
  insights: z.array(
    z.object({
      id: z.string().nullable().optional(),
      name: z.string(),
      category: z.string().nullable().optional(),
      kubernetesVersion: z.string().nullable().optional(),
      status: z.string(),
      reason: z.string().nullable().optional(),
      description: z.string().nullable().optional(),
      recommendation: z.string().nullable().optional(),
      lastRefreshTime: z.string().nullable(),
      resources: z.array(
        z.object({
          arn: z.string().nullable().optional(),
          kubernetesResourceUri: z.string().nullable().optional(),
          status: z.string().nullable().optional(),
          reason: z.string().nullable().optional(),
        }),
      ),
    }),
  ),
  updates: z.array(
    z.object({
      id: z.string(),
      type: z.string().nullable().optional(),
      status: z.string(),
      createdAt: z.string().nullable(),
    }),
  ),
  readiness: z.object({
    status: z.enum(["READY", "WARNING", "BLOCKED"]),
    blockers: z.array(eksReadinessFindingSchema),
    warnings: z.array(eksReadinessFindingSchema),
    checks: z.object({
      controlPlaneActive: z.boolean(),
      nodeGroupsAligned: z.boolean(),
      addonsHealthy: z.boolean(),
      upgradeInsightsPassing: z.boolean(),
      noUpdateInProgress: z.boolean(),
    }),
  }),
});
export const utilityUpgradeOptionsSchema = z.object({
  utilityCode: z.string(),
  label: z.string(),
  chart: z.string().nullable(),
  currentVersion: z.string().nullable(),
  versions: z.array(z.string()),
  blockReason: z.string().nullable(),
  observedAt: z.string().nullable(),
  source: z.string().optional(),
  versionKind: z.string().optional(),
  compatibility: z.string().optional(),
});
export const eksUpgradePlanSchema = z
  .object({
    planId: z.string(),
    clusterId: z.string(),
    customerId: z.string(),
    provider: z.literal("EKS"),
    currentVersion: z.string(),
    targetVersion: z.string(),
    kind: z.enum(["CONTAINER", "UTILITY"]).default("CONTAINER"),
    utilityCode: z.string().optional(),
    managedGroup: z.string().optional(),
    utilityEvidence: z
      .object({
        label: z.string(),
        chart: z.string().nullable(),
        currentVersion: z.string().nullable(),
        versions: z.array(z.string()),
        observedAt: z.string().nullable(),
        source: z.string().optional(),
        compatibility: z.string().optional(),
      })
      .optional(),
    strategy: z.enum(["PROVIDER_MANAGED_ROLLING", "GITOPS_REVIEW"]),
    status: z.enum([
      "DRAFT",
      "SUBMITTED",
      "APPROVED",
      "SCHEDULED",
      "EXECUTING",
      "SUCCEEDED",
      "FAILED",
      "REJECTED",
      "CANCELLED",
    ]),
    scheduledFor: z.string().nullable().optional(),
    changeReason: z.string(),
    readinessEvidence: eksUpgradeReadinessSchema.optional(),
    execution: z.record(z.string(), z.unknown()),
    version: z.number(),
    submittedBy: z.string().nullable().optional(),
    submittedByName: z.string().nullable().optional(),
    createdByName: z.string().nullable().optional(),
    approvedByName: z.string().nullable().optional(),
    submittedAt: z.string().nullable().optional(),
    approvedBy: z.string().nullable().optional(),
    approvedAt: z.string().nullable().optional(),
    createdBy: z.string(),
    createdAt: z.string(),
    updatedBy: z.string(),
    updatedAt: z.string(),
  })
  .superRefine((plan, ctx) => {
    if (plan.kind === "UTILITY") {
      if (
        !plan.utilityEvidence ||
        !plan.utilityCode ||
        !plan.managedGroup ||
        plan.strategy !== "GITOPS_REVIEW"
      )
        ctx.addIssue({
          code: "custom",
          message:
            "Utility plans require chart evidence and GitOps review strategy.",
        });
    } else if (
      !plan.readinessEvidence ||
      plan.strategy !== "PROVIDER_MANAGED_ROLLING"
    )
      ctx.addIssue({
        code: "custom",
        message:
          "Container plans require EKS readiness evidence and provider rolling strategy.",
      });
  });
export const eksUpgradePlanListSchema = z.object({
  clusterId: z.string(),
  customerId: z.string(),
  items: z.array(eksUpgradePlanSchema),
});
export const clusterToolAccessSchema = z.object({
  clusterId: z.string(),
  customerId: z.string(),
  gateway: z.object({
    status: z.enum(["READY", "NOT_DEPLOYED"]),
    baseUrl: z.string().url().nullable(),
  }),
  tunnel: z.object({
    status: z.enum(["READY", "NOT_CONNECTED"]),
    connectorReady: z.boolean(),
  }),
  tools: z.array(
    z.object({
      code: z.enum([
        "HEADLAMP",
        "GRAFANA",
        "PROMETHEUS",
        "ARGOCD",
        "WEBKUBECTL",
      ]),
      label: z.string(),
      status: z.enum(["READY", "UNAVAILABLE"]),
      componentStatus: z.string(),
      interactive: z.boolean(),
      launchUrl: z.string().url().nullable(),
      disabledReason: z.string().nullable(),
    }),
  ),
});
export const clusterToolSessionSchema = z.object({
  sessionId: z.string(),
  exchangeToken: z.string(),
  exchangeExpiresAt: z.string(),
  expiresAt: z.string(),
  toolCode: z.enum([
    "HEADLAMP",
    "GRAFANA",
    "PROMETHEUS",
    "ARGOCD",
    "WEBKUBECTL",
  ]),
  exchangeUrl: z.string().url(),
  launchUrl: z.string().url(),
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
    page: z.number(),
    pageSize: z.number(),
    totalElements: z.number(),
    totalPages: z.number(),
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
export type EksUpgradeReadiness = z.infer<typeof eksUpgradeReadinessSchema>;
export type EksUpgradePlan = z.infer<typeof eksUpgradePlanSchema>;
export type ClusterToolAccess = z.infer<typeof clusterToolAccessSchema>;
export type ClusterToolSession = z.infer<typeof clusterToolSessionSchema>;
export type ClusterNodeGroupRequest = z.infer<
  typeof clusterNodeGroupRequestSchema
>;
