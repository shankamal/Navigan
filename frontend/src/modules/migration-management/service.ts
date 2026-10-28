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

export interface ResourceCompatibilityEvaluation {
  resource: {
    apiVersion: string;
    kind: string;
    namespace: string | null;
    name: string;
  };
  status:
    "INCOMPATIBLE" | "REMEDIATION_REQUIRED" | "PENDING_EVIDENCE" | "COMPATIBLE";
  sourceStatus?: string;
  targetStatus?: string;
  checks: {
    capability: string;
    status: string;
    reason: string;
    nextAction: string;
  }[];
}

export interface DiscoveryCoverageReport {
  source: {
    inventoryResourceCount: number;
    selectedWorkloadCount: number;
    matchedSelectedWorkloads: number;
    freshness: "CURRENT" | "STALE" | "UNKNOWN";
    discoveryAccepted: boolean;
    dependencyEvidence: {
      relationshipCount: number;
      unresolvedCount: number;
      workloadCoverage: {
        selectedWorkloads: number;
        withReferenceEvidence: number;
        withoutReferenceEvidence: number;
        complete: boolean;
      };
    };
    capabilities: Record<string, { status: string; reason: string }>;
  };
  target: {
    inventoryResourceCount: number | null;
    freshness: "CURRENT" | "STALE" | "UNKNOWN";
    discoveryAccepted: boolean;
    capabilities: Record<string, { status: string; reason: string }>;
  };
  note: string;
}

export interface WorkloadAssessmentReport {
  status: "ASSESSMENT_ONLY";
  executionReady: false;
  workloadCount: number;
  targetClusterId: string | null;
  workloads: {
    source: {
      apiVersion: string;
      kind: string;
      namespace: string | null;
      name: string;
    };
    plannedTreatment: string;
    compatibilityStatus: string;
    dependencyEvidenceStatus: string;
    observedDependencies: {
      kind: string;
      namespace: string | null;
      name: string;
    }[];
    unresolvedDependencies: {
      kind: string;
      namespace: string | null;
      name: string;
    }[];
    checks: {
      capability: string;
      status: string;
      reason: string;
      nextAction: string;
    }[];
  }[];
  limitations: string[];
}

export interface TargetCompatibilityResponse {
  workloadAssessmentReport?: WorkloadAssessmentReport;
  discoveryCoverage?: DiscoveryCoverageReport;
  resourceEvaluations?: ResourceCompatibilityEvaluation[];
  migrationId: string;
  assessmentVersion: number | null;
  targetClusterId: string | null;
  coverageComplete: boolean;
  decision: { path: string; reason: string };
  apiEvidence?: {
    status: "PARTIAL" | "PENDING_EVIDENCE";
    reason: string;
    resources: {
      apiVersion?: string | null;
      kind: string;
      namespace?: string | null;
      name: string;
      status: "PARTIAL" | "PENDING_EVIDENCE";
      reason: string;
    }[];
  };
  storageEvidence?: {
    status: "PARTIAL" | "PENDING_EVIDENCE";
    reason: string;
    claims: {
      apiVersion: string;
      kind: string;
      namespace?: string | null;
      name: string;
      sourceStorageClass?: string | null;
      sourceAccessModes?: string[];
      requestedStorage?: string | null;
      volumeMode?: string | null;
      targetProvisioner?: string | null;
      targetVolumeBindingMode?: string | null;
      csiDriverObserved?: boolean;
      status: "PARTIAL" | "PENDING_EVIDENCE";
      reason: string;
    }[];
  };
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
    collectionGaps?: Record<string, "MISSING" | "PARTIAL">;
    collectionLimitations?: Record<string, string>;
    resourceKinds?: Record<string, number>;
    discoveredApiVersions?: string[];
    storageDiscovery?: {
      StorageClass?:
        "AVAILABLE" | "PERMISSION_DENIED" | "UNAVAILABLE" | "NOT_REPORTED";
      CSIDriver?:
        "AVAILABLE" | "PERMISSION_DENIED" | "UNAVAILABLE" | "NOT_REPORTED";
    };
    storageClasses?: string[];
    storageClassDetails?: {
      name: string;
      provisioner?: string | null;
      volumeBindingMode?: string | null;
      reclaimPolicy?: string | null;
    }[];
    csiDrivers?: string[];
    nodeCapacity?: {
      name?: string;
      allocatableCpu: string;
      allocatableMemory: string;
    }[];
    nodeCapacityCoverage?: { observedNodes: number; nodesWithCapacity: number };
    capabilityEvidence?: Record<
      | "kubernetesApi"
      | "compute"
      | "storage"
      | "networking"
      | "identity"
      | "dependencies",
      {
        status: "PARTIAL" | "NOT_VERIFIED";
        reason: string;
        observedApiVersions?: string[];
        observedStorageClassCount?: number;
        observedCSIDriverCount?: number;
        observedNodeCount?: number;
        observedServiceCount?: number;
      }
    >;
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
  prepareArtifactUpload: async (
    migrationId: string,
    input: {
      kind:
        "MANIFEST_YAML" | "HELM_CHART" | "HELM_VALUES" | "VALIDATION_REPORT";
      filename: string;
      sha256: string;
      sizeBytes: number;
      contentType: string;
    },
  ): Promise<{
    method: "PUT";
    url: string;
    key: string;
    requiredHeaders: Record<string, string>;
    status: string;
  }> =>
    (
      await apiClient.post(
        `${base}/${migrationId}/artifacts/upload-intent`,
        input,
        { headers: writeHeaders({ key: crypto.randomUUID() }) },
      )
    ).data,
  targetCompatibility: async (
    migrationId: string,
  ): Promise<TargetCompatibilityResponse> =>
    (await apiClient.get(`${base}/${migrationId}/target-compatibility`)).data,
  targetAssessment: async (
    migrationId: string,
  ): Promise<TargetAssessmentResponse> =>
    (await apiClient.get(`${base}/${migrationId}/target-assessment`)).data,
  analyzeTarget: async (
    migrationId: string,
  ): Promise<TargetAssessmentResponse> =>
    (
      await apiClient.post(
        `${base}/${migrationId}/target-assessment`,
        {},
        { headers: writeHeaders({ key: crypto.randomUUID() }) },
      )
    ).data,

  list: async (signal?: AbortSignal) =>
    parseResponse(
      migrationListSchema,
      (
        await apiClient.get(base, {
          params: { page: 0, pageSize: 100 },
          signal,
        })
      ).data,
    ),

  get: async (migrationId: string, signal?: AbortSignal) =>
    parseResponse(
      migrationSchema,
      (await apiClient.get(`${base}/${migrationId}`, { signal })).data,
    ),

  create: async (input: CreateMigrationInput, idempotencyKey?: string) =>
    parseResponse(
      migrationSchema,
      (
        await apiClient.post(base, input, {
          headers: writeHeaders({
            key: idempotencyKey ?? crypto.randomUUID(),
          }),
        })
      ).data,
    ),

  discover: async (
    migrationId: string,
    version: number,
    connectorToken?: string,
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

  assessment: async (migrationId: string, signal?: AbortSignal) =>
    parseResponse(
      assessmentResponseSchema,
      (await apiClient.get(`${base}/${migrationId}/assessment`, { signal }))
        .data,
    ),

  sourceCatalogue: async (migrationId: string, signal?: AbortSignal) =>
    parseResponse(
      sourceCatalogueResponseSchema,
      (
        await apiClient.get(`${base}/${migrationId}/source-catalogue`, {
          signal,
        })
      ).data,
    ),

  sourceInventory: async (migrationId: string, signal?: AbortSignal) =>
    parseResponse(
      sourceInventoryResponseSchema,
      (
        await apiClient.get(`${base}/${migrationId}/source-inventory`, {
          signal,
        })
      ).data,
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
    deleteAssessment = false,
  ) =>
    parseResponse(
      migrationSchema,
      (
        await apiClient.post(
          `${base}/${migrationId}/${action}`,
          {
            version,
            reason,
            ...(deleteAssessment ? { deleteAssessment: true } : {}),
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

const sourceClustersBase = "/source-clusters";

export const sourceClusters = {
  get: async (sourceClusterId: string, installationCheck = false) =>
    parseResponse(
      sourceClusterSchema,
      (
        await apiClient.get(`${sourceClustersBase}/${sourceClusterId}`, {
          params: installationCheck ? { installationCheck: "true" } : undefined,
        })
      ).data,
    ),
  list: async (customerId: string, signal?: AbortSignal) =>
    parseResponse(
      sourceClusterListSchema,
      (
        await apiClient.get(sourceClustersBase, {
          params: { customerId },
          signal,
        })
      ).data,
    ),

  create: async (input: CreateSourceClusterInput, idempotencyKey?: string) =>
    parseResponse(
      sourceClusterSchema,
      (
        await apiClient.post(sourceClustersBase, input, {
          headers: writeHeaders({ key: idempotencyKey ?? crypto.randomUUID() }),
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

  install: async (
    sourceClusterId: string,
    version: number,
    recoveryMigrationId?: string,
  ) =>
    parseResponse(
      sourceInstallationSchema,
      (
        await apiClient.post(
          `${sourceClustersBase}/${sourceClusterId}/install`,
          {
            version,
            reason: "Install read-only source assessment connector",
            ...(recoveryMigrationId ? { recoveryMigrationId } : {}),
          },
          {
            headers: writeHeaders({
              // Reusing this key on remount/retry returns the original SSM
              // command instead of launching another installation.
              key: recoveryMigrationId
                ? `source-connector-recover:${sourceClusterId}:v${version}:${recoveryMigrationId}`
                : `source-connector-install:${sourceClusterId}:v${version}`,
              version,
            }),
          },
        )
      ).data,
    ),
};
