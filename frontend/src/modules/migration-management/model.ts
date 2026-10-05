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
}).passthrough();

export type Migration = z.infer<typeof migrationSchema>;
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
