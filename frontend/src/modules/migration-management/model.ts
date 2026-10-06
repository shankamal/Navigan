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
    resourceKinds: z.record(
      z.string(),
      z.number().int().nonnegative(),
    ).default({}),
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
    }),
  }),
  findings: z.array(assessmentFindingSchema),
  createdBy: z.string(),
  createdAt: z.string(),
});

export const assessmentResponseSchema = z.object({
  migrationId: z.string(),
  version: z.number().int().positive(),
  status: z.string(),
  assessment: assessmentSchema.nullable(),
});

export const discoveryConnectorSchema = z.object({
  connectorId: z.string(),
  status: z.string(),
  expiresAt: z.string().optional(),
}).passthrough();

export const migrationSchema = z.object({
  migrationId: z.string(),
  customerId: z.string(),
  name: z.string(),
  status: z.string(),
  version: z.number().int().positive(),
  sourceConfiguration: z.record(z.string(), z.unknown()),
  targetConfiguration: z.record(z.string(), z.unknown()),
  migrationScope: z.record(z.string(), z.unknown()),
  discoveryConnector: discoveryConnectorSchema.optional(),
  assessmentConnector: discoveryConnectorSchema.optional(),
}).passthrough();

export type Migration = z.infer<typeof migrationSchema>;
export type Assessment = z.infer<typeof assessmentSchema>;
export type AssessmentResponse = z.infer<
  typeof assessmentResponseSchema
>;
export type SourceCatalogueResponse = z.infer<
  typeof sourceCatalogueResponseSchema
>;

export interface CreateMigrationInput {
  customerId: string;
  name: string;
  source: {
    platform: "SELF_MANAGED_KUBERNETES";
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

export interface UpdateMigrationInput {
  version: number;
  source: {
    platform: "SELF_MANAGED_KUBERNETES";
    clusterName?: string;
    accessMode: "READ_ONLY_CONNECTOR";
  };
  target: {
    platform: "EKS";
    targetType: "EXISTING_CLUSTER";
    environmentId: string;
    environmentApprovedVersion: number;
    clusterId: string;
    clusterName: string;
    endpointAccess: "PRIVATE";
  };
  scope: {
    namespaces: string[];
    excludeNamespaces: string[];
    includeClusterScopedResources: false;
    includePersistentData: false;
  };
  changeReason: string;
}
