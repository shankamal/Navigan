import { z } from "zod";

export const namespaceCatalogueSchema = z.object({
  name: z.string(),
  resourceCounts: z.record(z.string(), z.number().int().nonnegative()),
});

export const sourceCatalogueSchema = z.object({
  catalogueVersion: z.number().int().positive(),
  migrationVersion: z.number().int().positive(),
  schemaVersion: z.number().int().positive(),
  observedAt: z.string(),
  sourceKubernetesVersion: z.string(),
  inventoryDigest: z.string().regex(/^[a-f0-9]{64}$/),
  nodeCount: z.number().int().nonnegative(),
  architectures: z.array(z.string()),
  namespaces: z.array(namespaceCatalogueSchema),
  createdAt: z.string(),
});

export const sourceCatalogueResponseSchema = z.object({
  migrationId: z.string(),
  version: z.number().int().positive(),
  status: z.string(),
  catalogue: sourceCatalogueSchema.nullable(),
});

export const sourceInventoryResourceSchema = z
  .object({
    apiVersion: z.string(),
    kind: z.string(),
    namespace: z.string().nullable().optional(),
    name: z.string().nullable().optional(),
    annotationKeys: z.array(z.string()).optional(),
    labelKeys: z.array(z.string()).optional(),
  })
  .passthrough();

export const sourceInventorySchema = z.object({
  inventoryVersion: z.number().int().positive(),
  migrationVersion: z.number().int().positive(),
  schemaVersion: z.number().int().positive(),
  observedAt: z.string(),
  sourceKubernetesVersion: z.string(),
  inventoryDigest: z.string().regex(/^[a-f0-9]{64}$/),
  resourceCount: z.number().int().positive(),
  resources: z.array(sourceInventoryResourceSchema),
  sensitiveDataIncluded: z.literal(false),
  createdAt: z.string(),
});

export const sourceInventoryResponseSchema = z.object({
  migrationId: z.string(),
  version: z.number().int().positive(),
  status: z.string(),
  inventory: sourceInventorySchema.nullable(),
});

export const assessmentFindingSchema = z.object({
  code: z.string(),
  severity: z.enum(["INFO", "WARNING", "BLOCKER"]),
  category: z.string(),
  disposition: z.enum([
    "SEAMLESS",
    "AUTOMATED_CHANGE",
    "MANUAL_CHANGE",
    "BLOCKER",
  ]),
  namespace: z.string().optional(),
  resourceKind: z.string().optional(),
  resourceName: z.string().optional(),
  message: z.string(),
  remediation: z.string().optional(),
  ruleId: z.string().optional(),
  affectedWorkloadCount: z.number().int().nonnegative().optional(),
  evidenceCount: z.number().int().nonnegative().optional(),
  evidenceReferences: z.array(z.string()).optional(),
  targetTreatment: z.string().optional(),
  owner: z.string().optional(),
  remediationStatus: z.string().optional(),
  dependencies: z.array(z.string()).optional(),
  resolutionSteps: z.array(z.string()).optional(),
  validationSteps: z.array(z.string()).optional(),
  automationLevel: z.string().optional(),
  ownerTeam: z.string().optional(),
});

export const assessmentSchema = z.object({
  assessmentVersion: z.number().int().positive(),
  migrationVersion: z.number().int().positive(),
  reportSchemaVersion: z.number().int().positive(),
  sourceKubernetesVersion: z.string(),
  observedAt: z.string(),
  inventoryDigest: z.string().regex(/^[a-f0-9]{64}$/),
  compatibilityScore: z.number().int().min(0).max(100),
  containsBlockers: z.boolean(),
  inventorySummary: z.object({
    resourceCount: z.number().int().nonnegative(),
    resourceKinds: z
      .record(z.string(), z.number().int().nonnegative())
      .default({}),
    classification: z.object({
      SEAMLESS: z.number().int().nonnegative(),
      AUTOMATED_CHANGE: z.number().int().nonnegative(),
      MANUAL_CHANGE: z.number().int().nonnegative(),
      BLOCKER: z.number().int().nonnegative(),
    }),
    target: z.object({
      clusterId: z.string().nullable().optional(),
      clusterName: z.string().nullable().optional(),
      status: z.string(),
      nodeCount: z.number().int().nullable().optional(),
      readyNodeCount: z.number().int().nullable().optional(),
      podCount: z.number().int().nullable().optional(),
      readyPodCount: z.number().int().nullable().optional(),
      containerRestartCount: z.number().int().nullable().optional(),
      warningEventCount: z.number().int().nullable().optional(),
    }),
  }),
  findings: z.array(assessmentFindingSchema),
  governance: z
    .object({
      checkpoint: z.string().optional(),
      reviewerName: z.string().optional(),
      reviewerRole: z.string().optional(),
      dueDate: z.string().optional(),
      policyChecks: z.record(z.string(), z.string()).optional(),
      approvalConditions: z.array(z.string()).optional(),
    })
    .optional(),
  auditMetadata: z
    .object({
      reportId: z.string().optional(),
      reportVersion: z.string().optional(),
      generatedBy: z.string().optional(),
    })
    .optional(),
  dependencySummary: z
    .object({
      total: z.number().int().nonnegative().optional(),
      external: z.number().int().nonnegative().optional(),
      unresolved: z.number().int().nonnegative().optional(),
    })
    .optional(),
  createdBy: z.string(),
  createdAt: z.string(),
});

export const assessmentResponseSchema = z.object({
  migrationId: z.string(),
  version: z.number().int().positive(),
  status: z.string(),
  assessment: assessmentSchema.nullable(),
});

export const discoveryConnectorSchema = z
  .object({
    connectorId: z.string(),
    status: z.string(),
    expiresAt: z.string().optional(),
  })
  .passthrough();

export const sourceClusterSchema = z
  .object({
    sourceClusterId: z.string().regex(/^SRC-[a-f0-9]{32}$/),
    customerId: z.string(),
    customerName: z.string().optional(),
    name: z.string(),
    distribution: z.string().nullable().optional(),
    locationType: z.enum(["CLOUD", "ON_PREMISES", "OTHER"]),
    cloudProvider: z.enum(["AWS", "AZURE", "GCP", "OCI", "OTHER"]).nullable(),
    region: z.string().nullable().optional(),
    registrationMethod: z.enum([
      "LOCAL_KUBECONFIG",
      "GITOPS",
      "PROVIDER_AUTOMATION",
    ]),
    deliveryMethod: z
      .enum(["MANUAL_HELM", "AWS_SSM", "GITOPS"])
      .default("MANUAL_HELM"),
    deliveryConfiguration: z.record(z.string(), z.unknown()).default({}),
    status: z.enum(["PENDING_ENROLLMENT", "CONNECTED", "STALE", "REVOKED"]),
    version: z.number().int().positive(),
    lastConnectedAt: z.string().nullable().optional(),
  })
  .passthrough();

export const sourceClusterListSchema = z.object({
  items: z.array(sourceClusterSchema),
});

export const sourceEnrollmentSchema = z.object({
  enrollmentId: z.string().regex(/^SCE-[a-f0-9]{32}$/),
  sourceClusterId: z.string().regex(/^SRC-[a-f0-9]{32}$/),
  status: z.literal("ISSUED"),
  expiresAt: z.string(),
  enrollmentToken: z.string().min(43),
});

export const sourceInstallationSchema = z.object({
  sourceClusterId: z.string().regex(/^SRC-[a-f0-9]{32}$/),
  enrollmentId: z.string().regex(/^SCE-[a-f0-9]{32}$/),
  commandId: z.string().uuid(),
  managedInstanceId: z.string(),
  status: z.literal("INSTALLATION_STARTED"),
});

export const migrationSchema = z
  .object({
    migrationId: z.string(),
    customerId: z.string(),
    name: z.string(),
    status: z.string(),
    version: z.number().int().positive(),
    sourceConfiguration: z.record(z.string(), z.unknown()),
    targetConfiguration: z.record(z.string(), z.unknown()),
    migrationScope: z.record(z.string(), z.unknown()),
    planningDraft: z.record(z.string(), z.unknown()).optional(),
    discoveryConnector: discoveryConnectorSchema.optional(),
    assessmentConnector: discoveryConnectorSchema.optional(),
  })
  .passthrough();

export const migrationSummarySchema = z
  .object({
    migrationId: z.string(),
    customerId: z.string(),
    customerName: z.string(),
    name: z.string(),
    sourcePlatform: z.string(),
    targetPlatform: z.string(),
    executionMode: z.literal("ASSESSMENT_ONLY"),
    status: z.string(),
    version: z.number().int().positive(),
    createdBy: z.string(),
    createdAt: z.string(),
    updatedAt: z.string(),
  })
  .passthrough();

export const migrationListSchema = z.object({
  items: z.array(migrationSummarySchema),
  pagination: z.object({
    page: z.number().int().nonnegative(),
    pageSize: z.number().int().positive(),
    totalElements: z.number().int().nonnegative(),
    totalPages: z.number().int().nonnegative(),
  }),
});

export type Migration = z.infer<typeof migrationSchema>;
export type MigrationSummary = z.infer<typeof migrationSummarySchema>;
export type SourceClusterRegistration = z.infer<typeof sourceClusterSchema>;
export type SourceEnrollment = z.infer<typeof sourceEnrollmentSchema>;
export type SourceInstallation = z.infer<typeof sourceInstallationSchema>;
export type Assessment = z.infer<typeof assessmentSchema>;
export type SourceInventory = z.infer<typeof sourceInventorySchema>;
export type SourceInventoryResource = z.infer<
  typeof sourceInventoryResourceSchema
>;
export type AssessmentResponse = z.infer<typeof assessmentResponseSchema>;
export type SourceCatalogueResponse = z.infer<
  typeof sourceCatalogueResponseSchema
>;

export interface CreateMigrationInput {
  customerId: string;
  name: string;
  source: {
    platform: "SELF_MANAGED_KUBERNETES";
    sourceClusterId?: string;
    accessMode: "READ_ONLY_CONNECTOR";
  };
  target: {
    platform: "EKS";
    targetType: "EXISTING_CLUSTER";
    environmentId: string;
    environmentApprovedVersion: number;
    endpointAccess: "PRIVATE";
  };
  scope: {
    namespaces: string[];
    excludeNamespaces: string[];
    includeClusterScopedResources: false;
    includePersistentData: false;
  };
}

export interface CreateSourceClusterInput {
  customerId: string;
  name: string;
  distribution?: string;
  registrationMethod: "LOCAL_KUBECONFIG" | "GITOPS" | "PROVIDER_AUTOMATION";
  location: {
    type: "CLOUD" | "ON_PREMISES" | "OTHER";
    cloudProvider?: "AWS" | "AZURE" | "GCP" | "OCI" | "OTHER";
    region?: string;
  };
  delivery: SourceConnectorDeliveryInput;
}

export interface SourceConnectorDeliveryInput {
  method: "MANUAL_HELM" | "AWS_SSM" | "GITOPS";
  awsSsm?: {
    accountId: string;
    region: string;
    managedInstanceId: string;
    roleArn?: string;
    kubeconfigPath: string;
  };
}

export interface UpdateSourceClusterDeliveryInput {
  version: number;
  delivery: SourceConnectorDeliveryInput;
  reason: string;
}

export interface UpdateMigrationInput {
  version: number;
  planningDraft?: MigrationPlanningDraft;
  source?: {
    platform: "SELF_MANAGED_KUBERNETES";
    sourceClusterId?: string;
    clusterName?: string;
    accessMode: "READ_ONLY_CONNECTOR";
  };
  target?: {
    platform: "EKS";
    targetType: "EXISTING_CLUSTER";
    environmentId: string;
    environmentApprovedVersion: number;
    clusterId?: string;
    clusterName?: string;
    endpointAccess: "PRIVATE";
  };
  scope?: {
    namespaces: string[];
    excludeNamespaces: string[];
    includeClusterScopedResources: false;
    includePersistentData: false;
  };
  changeReason: string;
}

export interface PlannedResource {
  apiVersion: string;
  kind: string;
  namespace: string | null;
  name: string;
  treatment: "MIGRATE" | "RECREATE" | "REPLACE" | "RETIRE" | "REVIEW";
  dependency: boolean;
}

export interface RemediationDraft {
  findingIndex: number;
  treatment: "RECONFIGURE" | "RECREATE" | "REPLACE" | "RETIRE" | "REVIEW";
  owner: string;
  targetMapping: string;
  evidenceReference: string;
  status: "PLANNED" | "IN_PROGRESS" | "EVIDENCE_ATTACHED";
}

export interface MigrationPlanningDraft {
  schemaVersion: 1;
  mode: "SELECTED_WORKLOADS" | "FULL_CLUSTER";
  assessmentVersion: number;
  inventoryDigest: string;
  resources: PlannedResource[];
  remediations: RemediationDraft[];
  dataStrategy:
    "UNDECIDED" | "BACKUP_RESTORE" | "REPLICATION" | "NO_PERSISTENT_DATA";
  notes: string;
}
