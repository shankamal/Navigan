import type { Assessment, PlannedResource, RemediationDraft, SourceInventoryResource } from "./model";

export type PlanningRecommendation = {
  resource: PlannedResource;
  confidence: "HIGH" | "MEDIUM" | "REVIEW";
  reason: string;
  classification: "APPLICATION" | "SUPPORTING" | "PLATFORM_MANAGED" | "REQUIRES_REVIEW";
  safeToBulkAdd: boolean;
};

// Conservative recommendations: the source inventory is metadata-only and cannot
// establish application-to-application dependencies or prove target readiness.
export function recommendResource(resource: SourceInventoryResource & { name: string }): PlanningRecommendation {
  const { kind, name } = resource;
  const platformManaged = (kind === "ConfigMap" && name === "kube-root-ca.crt")
    || (kind === "ServiceAccount" && name === "default")
    || (kind === "Secret" && /^default-token-|^sh\.helm\.release\.v\d+\./.test(name))
    || (kind === "Service" && name === "kubernetes")
    || (resource.namespace ?? "").startsWith("kube-");
  const workload = ["Deployment", "ReplicaSet", "StatefulSet", "DaemonSet", "Job", "CronJob", "Pod"].includes(kind);
  const uncertain = ["StatefulSet", "PersistentVolumeClaim", "PersistentVolume", "StorageClass", "DaemonSet", "CustomResourceDefinition", "Node", "Job", "CronJob", "Pod", "ReplicaSet"].includes(kind);
  const recreate = ["Secret", "ServiceAccount", "Role", "RoleBinding", "ClusterRole", "ClusterRoleBinding", "Ingress", "Service"].includes(kind);
  const treatment: PlannedResource["treatment"] = platformManaged || uncertain ? "REVIEW" : recreate ? "RECREATE" : "MIGRATE";
  const classification: PlanningRecommendation["classification"] = platformManaged
    ? "PLATFORM_MANAGED" : uncertain ? "REQUIRES_REVIEW" : workload ? "APPLICATION" : "SUPPORTING";
  const reason = platformManaged
    ? "Kubernetes-managed or controller-generated resource; do not copy automatically. Confirm whether target recreates it."
    : uncertain ? "Requires explicit lifecycle, storage, ownership or target compatibility review"
    : recreate ? "Recreate or reconcile target-specific configuration securely on EKS"
    : workload ? "Workload candidate; validate runtime configuration, images and policies"
    : "Supporting resource candidate; include only when required by the selected application";
  return {
    resource: { apiVersion: resource.apiVersion, kind, namespace: resource.namespace ?? null, name, treatment, dependency: false },
    confidence: platformManaged || uncertain ? "REVIEW" : "MEDIUM",
    reason,
    classification,
    safeToBulkAdd: classification === "APPLICATION" && treatment === "MIGRATE",
  };
}

// Only direct, same-namespace ConfigMap, Secret and ServiceAccount references
// are treated as evidence. Unknown relationships are deliberately not guessed.
export function recommendDependencies(
  workload: SourceInventoryResource & { name: string },
  resources: (SourceInventoryResource & { name: string })[],
): PlanningRecommendation[] {
  const data = workload as Record<string, unknown>;
  const explicit = new Set<string>();
  // Connector v2: allowlisted kind/name references without secret contents.
  for (const entry of Array.isArray(data.dependencyReferences) ? data.dependencyReferences : []) {
    if (!entry || typeof entry !== "object") continue;
    const item = entry as Record<string, unknown>;
    if (["ConfigMap", "Secret", "ServiceAccount", "PersistentVolumeClaim"].includes(String(item.kind)) && typeof item.name === "string") {
      explicit.add(item.kind + ":" + item.name);
    }
  }
  // Legacy sanitized inventories only support serviceAccountName and do not
  // provide complete dependency evidence.
  const pod = (data.pod && typeof data.pod === "object" ? data.pod : {}) as Record<string, unknown>;
  if (typeof pod.serviceAccountName === "string" && pod.serviceAccountName !== "default") {
    explicit.add("ServiceAccount:" + pod.serviceAccountName);
  }
  // Test/older enriched inventories may contain direct reference objects.
  const visit = (node: unknown) => {
    if (!node || typeof node !== "object") return;
    if (Array.isArray(node)) { node.forEach(visit); return; }
    const value = node as Record<string, unknown>;
    for (const [field, child] of Object.entries(value)) {
      if (["configMapRef", "configMapKeyRef", "configMap"].includes(field) && child && typeof child === "object" && typeof (child as Record<string, unknown>).name === "string")
        explicit.add("ConfigMap:" + (child as Record<string, unknown>).name);
      if (["secretRef", "secretKeyRef"].includes(field) && child && typeof child === "object" && typeof (child as Record<string, unknown>).name === "string")
        explicit.add("Secret:" + (child as Record<string, unknown>).name);
      if (!["metadata", "annotations"].includes(field)) visit(child);
    }
  };
  visit(pod);
  const namespace = workload.namespace ?? null;
  return resources.filter((r) =>
    (r.namespace ?? null) === namespace && explicit.has(r.kind + ":" + r.name) && recommendResource(r).classification !== "PLATFORM_MANAGED"
  ).map((r) => ({
    ...recommendResource(r),
    resource: { ...recommendResource(r).resource, dependency: true },
    confidence: "HIGH" as const,
    reason: "Explicit reference in source workload inventory",
  }));
}

export function recommendFinding(
  assessment: Assessment,
  findingIndex: number,
): RemediationDraft | null {
  const finding = assessment.findings[findingIndex];
  if (!finding) return null;
  const evidence = [finding.category, finding.code, finding.message].join(" ").toLowerCase();
  const treatment: RemediationDraft["treatment"] =
    /storage|volume|pvc|persistent/.test(evidence) ? "REVIEW" :
    /ingress|controller|cni|network|identity|iam|service.account/.test(evidence) ? "RECONFIGURE" :
    /deprecated|api.version|unsupported/.test(evidence) ? "REPLACE" : "REVIEW";
  const mapping = /storage|volume|pvc|persistent/.test(evidence)
    ? "Confirm destination EKS StorageClass/CSI driver and data backup, restore or replication plan."
    : /ingress|controller/.test(evidence)
    ? "Validate the chosen EKS ingress controller, ingress class, DNS, TLS and annotations."
    : /identity|iam|service.account/.test(evidence)
    ? "Validate least-privilege target service account and approved EKS workload identity."
    : /network|cni/.test(evidence)
    ? "Validate target EKS CNI, policies, routing and required connectivity."
    : /deprecated|api.version|unsupported/.test(evidence)
    ? "Select and validate an API version or equivalent resource supported by the target cluster."
    : "Review the assessment finding and determine an approved EKS mapping with the application owner.";
  return {
    findingIndex, treatment, owner: "", targetMapping: mapping,
    evidenceReference: "", status: "PLANNED",
  };
}
