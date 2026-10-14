import { apiClient, parseResponse, writeHeaders } from "@/shared/api/client";

import {
  assessmentResponseSchema,
  migrationListSchema,
  migrationSchema,
  sourceClusterListSchema,
  sourceClusterSchema,
  sourceCatalogueResponseSchema,
  sourceInventoryResponseSchema,
  sourceEnrollmentSchema,
  sourceInstallationSchema,
  type CreateMigrationInput,
  type CreateSourceClusterInput,
  type UpdateMigrationInput,
  type UpdateSourceClusterDeliveryInput,
} from "./model";

const base = "/migrations";

export interface SchedulingEvidenceResult {
  status: "PARTIAL" | "PENDING_EVIDENCE" | "REMEDIATION_REQUIRED";
  reason: string;
  candidateNodes?: number;
  observedNodes?: number;
  unverifiedNodes?: number;
  apiVersion: string;
  kind: string;
  namespace?: string | null;
  name: string;
}

export interface TargetCompatibilityResponse {
  migrationId: string;
  assessmentVersion: number | null;
  targetClusterId: string | null;
  coverageComplete: boolean;
  decision: { path: string; reason: string };
  schedulingEvidence?: {
    status: "PARTIAL" | "PENDING_EVIDENCE";
    reason: string;
    workloads: SchedulingEvidenceResult[];
  };
}

export interface TargetAssessmentRecord {
  targetClusterId: string;
  assessmentVersion: number;
  evidenceLevel: "CONNECTOR_RUNTIME_INVENTORY";
  createdAt: string;
  snapshot: {
    platform: string;
    clusterName: string;
    region?: string;
    sourceRevision?: string;
    resourceCount?: number;
    resourceKinds?: Record<string, number>;
    nodeCapacity?: { name?: string; allocatableCpu: string; allocatableMemory: string }[];
    nodeCapacityCoverage?: { observedNodes: number; nodesWithCapacity: number };
    capabilityEvidence?: Record<"kubernetesApi" | "compute" | "storage" | "networking" | "identity" | "dependencies", {
      status: "PARTIAL" | "NOT_VERIFIED";
      reason: string;
      observedNodeCount?: number;
      observedServiceCount?: number;
    }>;
    unclassifiedResourceCount?: number;
    inventoryExpiresAt?: string | null;
    kubernetesVersion?: string;
    clusterStatus?: string;
    observedAt: string;
    coverageComplete: false;
    unverified: string[];
  };
}
export interface TargetAssessmentResponse {
  migrationId: string;
  assessment: TargetAssessmentRecord | null;
}

export const migrations = {
  targetCompatibility: async (migrationId: string): Promise<TargetCompatibilityResponse> =>
    (await apiClient.get(`${base}/${migrationId}/target-compatibility`)).data,
  targetAssessment: async (migrationId: string): Promise<TargetAssessmentResponse> =>
    (await apiClient.get(`${base}/${migrationId}/target-assessment`)).data,
  analyzeTarget: async (migrationId: string): Promise<TargetAssessmentResponse> =>
    (await apiClient.post(`${base}/${migrationId}/target-assessment`, {}, { headers: writeHeaders({ key: crypto.randomUUID() }) })).data,

  list: async () =>
    parseResponse(
      migrationListSchema,
      (
        await apiClient.get(base, {
          params: { page: 0, pageSize: 100 },
        })
      ).data,
    ),

  get: async (migrationId: string) =>
    parseResponse(
      migrationSchema,
      (await apiClient.get(`${base}/${migrationId}`)).data,
    ),

  create: async (input: CreateMigrationInput) =>
    parseResponse(
      migrationSchema,
      (
        await apiClient.post(base, input, {
          headers: writeHeaders({
            key: crypto.randomUUID(),
          }),
        })
      ).data,
    ),

  discover: async (
    migrationId: string,
    version: number,
    connectorToken: string,
  ) =>
    parseResponse(
      migrationSchema,
      (
        await apiClient.post(
          `${base}/${migrationId}/discover`,
          {
            version,
            reason: "Begin read-only source discovery",
            connectorToken,
          },
          {
            headers: {
              "If-Match": String(version),
            },
          },
        )
      ).data,
    ),

  assess: async (migrationId: string, version: number) =>
    parseResponse(
      migrationSchema,
      (
        await apiClient.post(
          `${base}/${migrationId}/assess`,
          {
            version,
            reason: "Collect detailed inventory and assess feasibility",
          },
          {
            headers: writeHeaders({
              key: crypto.randomUUID(),
              version,
            }),
          },
        )
      ).data,
    ),

  assessment: async (migrationId: string) =>
    parseResponse(
      assessmentResponseSchema,
      (await apiClient.get(`${base}/${migrationId}/assessment`)).data,
    ),

  sourceCatalogue: async (migrationId: string) =>
    parseResponse(
      sourceCatalogueResponseSchema,
      (await apiClient.get(`${base}/${migrationId}/source-catalogue`)).data,
    ),

  sourceInventory: async (migrationId: string) =>
    parseResponse(
      sourceInventoryResponseSchema,
      (await apiClient.get(`${base}/${migrationId}/source-inventory`)).data,
    ),

  update: async (migrationId: string, input: UpdateMigrationInput) =>
    parseResponse(
      migrationSchema,
      (
        await apiClient.put(`${base}/${migrationId}`, input, {
          headers: writeHeaders({
            key: crypto.randomUUID(),
            version: input.version,
          }),
        })
      ).data,
    ),

  action: async (
    migrationId: string,
    action: "submit" | "review" | "approve" | "reject" | "cancel",
    version: number,
    reason: string,
  ) =>
    parseResponse(
      migrationSchema,
      (
        await apiClient.post(
          `${base}/${migrationId}/${action}`,
          { version, reason },
          {
            headers: writeHeaders({
              key: crypto.randomUUID(),
              version,
            }),
          },
        )
      ).data,
    ),
};

const sourceClustersBase = "/source-clusters";

export const sourceClusters = {
  list: async (customerId: string) =>
    parseResponse(
      sourceClusterListSchema,
      (
        await apiClient.get(sourceClustersBase, {
          params: { customerId },
        })
      ).data,
    ),

  create: async (input: CreateSourceClusterInput) =>
    parseResponse(
      sourceClusterSchema,
      (
        await apiClient.post(sourceClustersBase, input, {
          headers: writeHeaders({ key: crypto.randomUUID() }),
        })
      ).data,
    ),

  updateDelivery: async (
    sourceClusterId: string,
    input: UpdateSourceClusterDeliveryInput,
  ) =>
    parseResponse(
      sourceClusterSchema,
      (
        await apiClient.put(`${sourceClustersBase}/${sourceClusterId}`, input, {
          headers: writeHeaders({
            key: crypto.randomUUID(),
            version: input.version,
          }),
        })
      ).data,
    ),

  enroll: async (sourceClusterId: string, version: number) =>
    parseResponse(
      sourceEnrollmentSchema,
      (
        await apiClient.post(
          `${sourceClustersBase}/${sourceClusterId}/enrollments`,
          {
            version,
            reason: "Connect source cluster for read-only assessment",
          },
          {
            headers: {
              "If-Match": String(version),
            },
          },
        )
      ).data,
    ),

  install: async (sourceClusterId: string, version: number) =>
    parseResponse(
      sourceInstallationSchema,
      (
        await apiClient.post(
          `${sourceClustersBase}/${sourceClusterId}/install`,
          {
            version,
            reason: "Install read-only source assessment connector",
          },
          {
            headers: writeHeaders({
              key: crypto.randomUUID(),
              version,
            }),
          },
        )
      ).data,
    ),
};
