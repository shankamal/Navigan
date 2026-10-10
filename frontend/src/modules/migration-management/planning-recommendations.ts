import type { Assessment, PlannedResource, RemediationDraft, SourceInventoryResource } from "./model";

export type PlanningRecommendation = {
  resource: PlannedResource;
  confidence: "HIGH" | "MEDIUM" | "REVIEW";
  reason: string;
};

// Conservative recommendations: the source inventory is metadata-only and cannot
// establish application-to-application dependencies or prove target readiness.
export function recommendResource(resource: SourceInventoryResource & { name: string }): PlanningRecommendation {
  const kind = resource.kind;
  const uncertain = ["StatefulSet", "PersistentVolumeClaim", "PersistentVolume", "StorageClass", "DaemonSet", "CustomResourceDefinition", "Node"].includes(kind);
  const recreate = ["Secret", "ServiceAccount", "Role", "RoleBinding", "ClusterRole", "ClusterRoleBinding", "Ingress", "Service"].includes(kind);
  const treatment: PlannedResource["treatment"] =
    uncertain ? "REVIEW" : recreate ? "RECREATE" : ["Job", "CronJob"].includes(kind) ? "REVIEW" : "MIGRATE";
  const reason = uncertain
    ? "Requires explicit target, data, or platform compatibility review"
    : recreate
      ? "Recreate or reconcile target-specific configuration and credentials on EKS"
      : treatment === "REVIEW"
        ? "Confirm whether historical or scheduled work must run on the destination"
        : "Standard Kubernetes resource candidate; validate images, policies and configuration";
  return {
    resource: {
      apiVersion: resource.apiVersion,
      kind,
      namespace: resource.namespace ?? null,
      name: resource.name,
      treatment,
      dependency: false,
    },
    confidence: uncertain || treatment === "REVIEW" ? "REVIEW" : "MEDIUM",
    reason,
  };
}

// Only direct, same-namespace ConfigMap, Secret and ServiceAccount references
// are treated as evidence. Unknown relationships are deliberately not guessed.
export function recommendDependencies(
  workload: SourceInventoryResource & { name: string },
  resources: (SourceInventoryResource & { name: string })[],
): PlanningRecommendation[] {
  const data = workload as Record<string, unknown>;
  const pod = (data.pod && typeof data.pod === "object" ? data.pod : {}) as Record<string, unknown>;
  const explicit = new Set<string>();
  const visit = (node: unknown, key?: string) => {
    if (!node || typeof node !== "object") return;
    if (Array.isArray(node)) { for (const item of node) visit(item); return; }
    for (const [field, value] of Object.entries(node as Record<string, unknown>)) {
      if (["configMapRef", "configMapKeyRef", "configMap"].includes(field) && value && typeof value === "object") {
        const name = (value as Record<string, unknown>).name;
        if (typeof name === "string") explicit.add("ConfigMap:" + name);
      }
      if (["secretRef", "secretKeyRef", "secret", "imagePullSecrets"].includes(field)) {
        if (Array.isArray(value)) value.forEach((item) => visit({secret: item}));
        else if (value && typeof value === "object") {
          const name = (value as Record<string, unknown>).name;
          if (typeof name === "string") explicit.add("Secret:" + name);
        }
      }
      if (field === "serviceAccountName" && typeof value === "string") explicit.add("ServiceAccount:" + value);
      if (field !== "metadata" && field !== "annotations") visit(value, field);
    }
  };
  visit(pod);
  const namespace = workload.namespace ?? null;
  return resources.filter((r) =>
    (r.namespace ?? null) === namespace && explicit.has(r.kind + ":" + r.name)
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
