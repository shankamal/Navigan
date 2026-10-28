import type {
  Assessment,
  PlannedResource,
  RemediationDraft,
  SourceInventoryResource,
} from "./model";

export type PlanningRecommendation = {
  resource: PlannedResource;
  confidence: "HIGH" | "MEDIUM" | "REVIEW";
  reason: string;
  classification:
    "APPLICATION" | "SUPPORTING" | "PLATFORM_MANAGED" | "REQUIRES_REVIEW";
  safeToBulkAdd: boolean;
};

// Conservative recommendations: the source inventory is metadata-only and cannot
// establish application-to-application dependencies or prove target readiness.
export function recommendResource(
  resource: SourceInventoryResource & { name: string },
): PlanningRecommendation {
  const { kind, name } = resource;
  const platformManaged =
    (kind === "ConfigMap" && name === "kube-root-ca.crt") ||
    (kind === "ServiceAccount" && name === "default") ||
    (kind === "Secret" &&
      /^default-token-|^sh\.helm\.release\.v\d+\./.test(name)) ||
    (kind === "Service" && name === "kubernetes") ||
    (resource.namespace ?? "").startsWith("kube-");
  const workload = [
    "Deployment",
    "ReplicaSet",
    "StatefulSet",
    "DaemonSet",
    "Job",
    "CronJob",
    "Pod",
  ].includes(kind);
  const uncertain = [
    "StatefulSet",
    "PersistentVolumeClaim",
    "PersistentVolume",
    "StorageClass",
    "DaemonSet",
    "CustomResourceDefinition",
    "Node",
    "Job",
    "CronJob",
    "Pod",
    "ReplicaSet",
  ].includes(kind);
  const recreate = [
    "Secret",
    "ServiceAccount",
    "Role",
    "RoleBinding",
    "ClusterRole",
    "ClusterRoleBinding",
    "Ingress",
    "Service",
  ].includes(kind);
  const treatment: PlannedResource["treatment"] =
    platformManaged || uncertain ? "REVIEW" : recreate ? "RECREATE" : "MIGRATE";
  const classification: PlanningRecommendation["classification"] =
    platformManaged
      ? "PLATFORM_MANAGED"
      : uncertain
        ? "REQUIRES_REVIEW"
        : workload
          ? "APPLICATION"
          : "SUPPORTING";
  const reason = platformManaged
    ? "Kubernetes-managed or controller-generated resource; do not copy automatically. Confirm whether target recreates it."
    : uncertain
      ? "Requires explicit lifecycle, storage, ownership or target compatibility review"
      : recreate
        ? "Recreate or reconcile target-specific configuration securely on EKS"
        : workload
          ? "Workload candidate; validate runtime configuration, images and policies"
          : "Supporting resource candidate; include only when required by the selected application";
  return {
    resource: {
      apiVersion: resource.apiVersion,
      kind,
      namespace: resource.namespace ?? null,
      name,
      treatment,
      dependency: false,
    },
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
  for (const entry of Array.isArray(data.dependencyReferences)
    ? data.dependencyReferences
    : []) {
    if (!entry || typeof entry !== "object") continue;
    const item = entry as Record<string, unknown>;
    if (
      [
        "ConfigMap",
        "Secret",
        "ServiceAccount",
        "PersistentVolumeClaim",
      ].includes(String(item.kind)) &&
      typeof item.name === "string"
    ) {
      explicit.add(item.kind + ":" + item.name);
    }
  }
  // Legacy sanitized inventories only support serviceAccountName and do not
  // provide complete dependency evidence.
  const pod = (
    data.pod && typeof data.pod === "object" ? data.pod : {}
  ) as Record<string, unknown>;
  if (
    typeof pod.serviceAccountName === "string" &&
    pod.serviceAccountName !== "default"
  ) {
    explicit.add("ServiceAccount:" + pod.serviceAccountName);
  }
  // Test/older enriched inventories may contain direct reference objects.
  const visit = (node: unknown) => {
    if (!node || typeof node !== "object") return;
    if (Array.isArray(node)) {
      node.forEach(visit);
      return;
    }
    const value = node as Record<string, unknown>;
    for (const [field, child] of Object.entries(value)) {
      if (
        ["configMapRef", "configMapKeyRef", "configMap"].includes(field) &&
        child &&
        typeof child === "object" &&
        typeof (child as Record<string, unknown>).name === "string"
      )
        explicit.add("ConfigMap:" + (child as Record<string, unknown>).name);
      if (
        ["secretRef", "secretKeyRef"].includes(field) &&
        child &&
        typeof child === "object" &&
        typeof (child as Record<string, unknown>).name === "string"
      )
        explicit.add("Secret:" + (child as Record<string, unknown>).name);
      if (!["metadata", "annotations"].includes(field)) visit(child);
    }
  };
  visit(pod);
  const namespace = workload.namespace ?? null;
  return resources
    .filter(
      (r) =>
        (r.namespace ?? null) === namespace &&
        explicit.has(r.kind + ":" + r.name) &&
        recommendResource(r).classification !== "PLATFORM_MANAGED",
    )
    .map((r) => ({
      ...recommendResource(r),
      resource: { ...recommendResource(r).resource, dependency: true },
      confidence: "HIGH" as const,
      reason: "Explicit reference in source workload inventory",
    }));
}

/**
 * Explainable, evidence-conservative remediation intelligence.
 * Platform-specific capabilities are never considered verified solely from the platform name.
 * These proposals are reviewable planning suggestions, not infrastructure actions.
 */
export interface RemediationIntelligence {
  treatment: RemediationDraft["treatment"];
  confidence: "RULE_BASED" | "MANUAL_REVIEW";
  title: string;
  rationale: string;
  proposedActions: string[];
  verificationRequirements: string[];
  targetMapping: string;
  requiresHumanReview: true;
}
export function analyzeRemediationFinding(
  assessment: Assessment,
  findingIndex: number,
  targetPlatform = "KUBERNETES",
): RemediationIntelligence | null {
  const finding = assessment.findings[findingIndex];
  if (!finding) return null;
  const evidence = [finding.code, finding.message, finding.category]
    .join(" ")
    .toLowerCase();
  const platform = targetPlatform.trim() || "target platform";
  const rule = (
    title: string,
    treatment: RemediationDraft["treatment"],
    rationale: string,
    proposedActions: string[],
    verificationRequirements: string[],
  ): RemediationIntelligence => ({
    title,
    treatment,
    rationale,
    proposedActions,
    verificationRequirements,
    confidence: treatment === "REVIEW" ? "MANUAL_REVIEW" : "RULE_BASED",
    targetMapping: [
      ...proposedActions,
      "Evidence required: " + verificationRequirements.join("; "),
    ].join("\n"),
    requiresHumanReview: true,
  });
  // Order matters: explicit unknown-coverage and external dependencies must never be 'fixed'
  // by a broad config/identity/image pattern match.
  if (
    /not.collected|excluded|redacted|unknown|missing.evidence|unverified|not.verified|not.available|coverage|cannot.determine/.test(
      evidence,
    )
  )
    return rule(
      "Collect missing evidence",
      "REVIEW",
      "The assessment does not contain sufficient evidence to select or verify a target configuration.",
      [
        "Reassess the source using the approved connector or supply a reviewed artifact.",
        "Identify the affected owner and record the unresolved dependency.",
      ],
      ["Updated assessment evidence", "Approved target capability observation"],
    );
  if (
    /storage|volume|pvc|persistent|stateful|csi|storageclass|storage.class/.test(
      evidence,
    )
  )
    return rule(
      "Plan stateful data and storage mapping",
      "REVIEW",
      "Storage equivalence and data consistency cannot be established from workload metadata alone.",
      [
        "Identify the source volume, ownership, capacity and access mode.",
        "Choose backup/restore or replication with the application owner.",
        "Map to an observed compatible destination StorageClass on " +
          platform +
          "; do not assume it exists.",
      ],
      [
        "Authorized target storage/CSI observations",
        "Data restore or replication test",
        "Recovery and rollback criteria",
      ],
    );
  if (/secret|configmap|config.map|credential/.test(evidence))
    return rule(
      "Review configuration and secret dependencies",
      "REVIEW",
      "Contents may be intentionally excluded; a name reference cannot establish configuration compatibility.",
      [
        "Collect an approved dependency manifest without exposing secret values.",
        "Map configuration keys and secret delivery to approved target mechanisms.",
      ],
      [
        "Application owner sign-off",
        "Controlled target configuration validation",
      ],
    );
  if (
    /service.account|serviceaccount|workload.identity|identity|\biam\b/.test(
      evidence,
    )
  )
    return rule(
      "Map workload identity",
      "RECONFIGURE",
      "The source identity reference needs explicit destination authorization mapping.",
      [
        "Identify source ServiceAccount and required permissions.",
        "Design least-privilege workload identity for " +
          platform +
          " using the target's supported mechanism.",
      ],
      [
        "Approved destination identity mapping",
        "Authorization test",
        "Target identity capability evidence",
      ],
    );
  if (
    /image.digest|image.tag|mutable.image|not.pinned|immutable.digest|image is not pinned/.test(
      evidence,
    )
  )
    return rule(
      "Pin an approved container image",
      "RECONFIGURE",
      "Mutable image references undermine reproducibility and rollout integrity.",
      [
        "Resolve and approve the exact immutable image digest.",
        "Update the image reference to repository@sha256:<approved-digest> without changing the image content.",
      ],
      [
        "Image digest evidence",
        "Required security scan or signature",
        "Deployment test",
      ],
    );
  if (/ingress|route|dns|tls|certificate/.test(evidence))
    return rule(
      "Review ingress and traffic configuration",
      "RECONFIGURE",
      "Ingress and routing resources require destination-specific controller and network validation.",
      [
        "Compare ingress class, route rules, hostname, TLS references and controller annotations.",
        "Prepare a compatible routing configuration for " + platform + ".",
      ],
      [
        "Target ingress/controller inventory",
        "TLS and DNS validation",
        "End-to-end traffic test",
      ],
    );
  if (
    /network.policy|networkpolicy|\bcni\b|egress|firewall|connectivity/.test(
      evidence,
    )
  )
    return rule(
      "Validate network policy and connectivity",
      "RECONFIGURE",
      "Network enforcement and reachability are platform-dependent.",
      [
        "Map ingress/egress policies and service connectivity requirements.",
        "Validate the proposed policies against the target network implementation.",
      ],
      [
        "Observed target network capabilities",
        "Required connectivity and policy tests",
      ],
    );
  if (
    /deprecated|api.version|api_version|removed.api|unsupported.api/.test(
      evidence,
    )
  )
    return rule(
      "Replace unsupported API configuration",
      "REPLACE",
      "The source API may not be supported by the destination Kubernetes distribution/version.",
      [
        "Identify the source resource group/version and the destination-supported alternatives.",
        "Generate a reviewed replacement manifest preserving intended behavior.",
      ],
      [
        "Destination API discovery",
        "Schema validation",
        "Application compatibility test",
      ],
    );
  if (/cpu|memory|limit|request|resource.quota/.test(evidence))
    return rule(
      "Size workload resource requests and limits",
      "REVIEW",
      "No appropriate CPU/memory values can be inferred without utilization and target capacity evidence.",
      [
        "Collect approved resource usage and availability observations.",
        "Propose CPU and memory requests/limits and validate scheduling impact.",
      ],
      ["Source utilization baseline", "Target scheduling/capacity check"],
    );
  if (
    /affinity|toleration|topology|node.selector|scheduling|failure.domain/.test(
      evidence,
    )
  )
    return rule(
      "Map scheduling requirements",
      "REVIEW",
      "Node labels and failure domains must be mapped to actual target topology.",
      [
        "Inventory node selectors, affinity, tolerations and topology constraints.",
        "Map to observed destination node groups and failure domains.",
      ],
      [
        "Target node labels and topology evidence",
        "Scheduling simulation or deployment test",
      ],
    );
  return rule(
    "Investigate finding with application owner",
    "REVIEW",
    "Assessment evidence does not support an automatic treatment for this finding.",
    [
      "Review the raw assessment evidence and select an approved remediation.",
      "Document owner, target changes and decision rationale.",
    ],
    ["Owner approval", "Finding-specific validation evidence"],
  );
}
export function recommendFinding(
  assessment: Assessment,
  findingIndex: number,
): RemediationDraft | null {
  const recommendation = analyzeRemediationFinding(assessment, findingIndex);
  if (!recommendation) return null;
  return {
    findingIndex,
    treatment: recommendation.treatment,
    owner: "",
    targetMapping: recommendation.targetMapping,
    evidenceReference: "",
    status: "PLANNED",
  };
}
