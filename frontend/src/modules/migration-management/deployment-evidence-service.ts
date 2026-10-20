import { apiClient, writeHeaders } from "@/shared/api/client";
export interface DeploymentSourcesConfiguration {
  inventoryOnly?: boolean;
  repositories: { repository: string; revision: string; directory: string }[];
  registries: string[];
  confirmations?: {
    apiVersion: string;
    kind: string;
    namespace: string;
    name: string;
    repository: string;
    commit: string;
    filePath: string;
  }[];
}
export interface DeploymentSourceSettings {
  sourceClusterId: string;
  version: number;
  configuration: DeploymentSourcesConfiguration;
  githubOrganizations: string[];
  registryAdapters: string[];
  authentication?: Record<
    string,
    {
      mode: string;
      status: string;
      secretConfigured?: boolean;
      verifiedAt?: string;
      message?: string;
      roleArn?: string;
      provider?: string;
      externalId?: string;
      accountId?: string;
      region?: string;
    }
  >;
  readyForDiscovery?: boolean;
  registryPrincipalArn?: string;
}
export interface RegistryImageEvidence {
  image: string;
  status: string;
  registryDigest?: string | null;
  architectures?: string[];
  reason?: string;
}
export interface DeploymentWorkloadEvidence {
  workload: {
    apiVersion: string;
    kind: string;
    namespace: string | null;
    name: string;
  };
  dependencies?: {
    kind: string;
    name: string;
    namespace: string | null;
    status: string;
    reason: string;
    sourceCandidates: {
      repository?: string;
      commit?: string;
      filePath?: string;
      format?: string;
    }[];
  }[];
  helmEvidence?: { status: string; reason: string } | null;
  applicationVersion: string | null;
  artifactFormat: string;
  deliveryTool: string;
  deliveryEvidenceBasis?: string;
  evidenceStatus?: string;
  registryVerified?: boolean;
  clusterSnapshot?: {
    format: string;
    status: string;
    inventoryDigest: string | null;
    observedAt: string | null;
    resource?: Record<string, unknown>;
    resourceIdentity?: {
      apiVersion: string;
      kind: string;
      namespace: string | null;
      name: string;
    };
    deployable: false;
  };
  helmChart: string | null;
  helmRelease: string | null;
  mappingStatus: string;
  runtimeStatus: string;
  candidates: {
    repository: string;
    commit: string;
    filePath: string;
    format: string;
    match: string;
  }[];
  containers: {
    name: string;
    containerType: string;
    configuredImage: string;
    runningImageIDs: string[];
    observedDigests: string[];
    runningImages: string[];
    runningPodCount: number;
    multipleRunningVersions: boolean;
    digestComparison: string;
    registryEvidence: RegistryImageEvidence | null;
  }[];
  gaps: string[];
}
export interface RecoveryRequest {
  operation: "START" | "POLL" | "DOWNLOAD";
  jobId?: string;
  artifactKind?: "IMAGE" | "HELM_RELEASE";
  apiVersion?: string;
  kind?: string;
  namespace?: string | null;
  name?: string;
  containerName?: string;
  containerType?: string;
  digest?: string;
}
export interface RecoveryJob {
  jobId: string;
  kind: "IMAGE" | "HELM_RELEASE";
  workload: DeploymentWorkloadEvidence["workload"];
  containerName?: string;
  inventoryDigest?: string;
  status: string;
  message: string;
  digest?: string;
  sha256?: string;
  sizeBytes?: number;
  platform?: string;
}
export interface DeploymentEvidence {
  namespaces?: { name: string; workloadCount: number }[];
  analysisCurrent?: boolean;
  recoveries?: RecoveryJob[];
  recoveryStorageConfigured?: boolean;
  coverage?: {
    status: string;
    workloadCount: number;
    namespaceCount: number;
    repositoryMappedCount: number;
    runtimeObservedCount: number;
    registryVerifiedWorkloadCount: number;
    inventorySnapshotCount: number;
    scope: string;
    limitations: string[];
  };
  migrationId: string;
  sourceClusterId: string;
  inventoryDigest: string | null;
  observedAt: string | null;
  analyzedAt: string | null;
  configuration: DeploymentSourcesConfiguration;
  configurationCurrent: boolean;
  repositories: {
    repository: string;
    commit?: string;
    status: string;
    gaps: string[];
    artifacts: {
      filePath: string;
      format: string;
      resource?: {
        apiVersion: string;
        kind: string;
        namespace?: string | null;
        name: string;
      };
      usesHelm?: boolean;
      usesKubectl?: boolean;
      referencedPaths?: string[];
      dynamicReferences?: boolean;
    }[];
  }[];
  images: RegistryImageEvidence[];
  workloads: DeploymentWorkloadEvidence[];
  limitations: string[];
}
const headers = (version: number) => ({
  headers: writeHeaders({ key: crypto.randomUUID(), version }),
});
export const deploymentDiscovery = {
  recover: async (
    id: string,
    version: number,
    recovery: RecoveryRequest,
  ): Promise<{ job: RecoveryJob; downloadUrl?: string }> =>
    (
      await apiClient.post(
        `/migrations/${id}/deployment-evidence`,
        { version, recovery },
        headers(version),
      )
    ).data,
  settings: async (
    id: string,
    signal?: AbortSignal,
  ): Promise<DeploymentSourceSettings> =>
    (
      await apiClient.get(`/source-clusters/${id}/deployment-sources`, {
        signal,
      })
    ).data,
  saveSettings: async (
    id: string,
    version: number,
    configuration: DeploymentSourcesConfiguration,
    credentials: {
      key: string;
      mode: string;
      username?: string;
      token?: string;
      roleArn?: string;
      provider?: string;
    }[] = [],
    verify = false,
  ): Promise<DeploymentSourceSettings> =>
    (
      await apiClient.put(
        `/source-clusters/${id}/deployment-sources`,
        { version, configuration, credentials, verify },
        headers(version),
      )
    ).data,
  evidence: async (
    id: string,
    signal?: AbortSignal,
  ): Promise<DeploymentEvidence> =>
    (await apiClient.get(`/migrations/${id}/deployment-evidence`, { signal }))
      .data,
  analyze: async (
    id: string,
    version: number,
    continueAnalysis = false,
  ): Promise<DeploymentEvidence> =>
    (
      await apiClient.post(
        `/migrations/${id}/deployment-evidence`,
        { version, ...(continueAnalysis ? { continueAnalysis: true } : {}) },
        headers(version),
      )
    ).data,
  refresh: async (id: string, version: number) =>
    (
      await apiClient.post(
        `/migrations/${id}/deployment-evidence`,
        { version, refreshCluster: true },
        headers(version),
      )
    ).data,
};
