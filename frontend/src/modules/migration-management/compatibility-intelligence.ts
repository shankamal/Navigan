import type { TargetCapabilitySnapshot } from "./target-capabilities";
import { inspectTargetCapabilitySnapshot } from "./target-capabilities";
import type {
  StorageClaimEvidence,
  ProposedStorageMapping,
} from "./storage-validation";
import { evaluateStorageCompatibility } from "./storage-validation";

export type CompatibilityStatus =
  "COMPATIBLE" | "INCOMPATIBLE" | "REVIEW_REQUIRED" | "UNKNOWN";
export interface CompatibilityResult {
  id: string;
  resource: string;
  capability: string;
  status: CompatibilityStatus;
  reason: string;
  nextAction: string;
  evidence: "OBSERVED" | "MISSING" | "UNVERIFIED";
}
export interface SourceRequirement {
  kind: string;
  name: string;
  namespace: string | null;
  serviceAccountName?: string | null;
  ingressClassName?: string | null;
}
/** No provider defaults, class names, or inferred capabilities are treated as evidence. */
export function evaluateTargetCompatibility(args: {
  platform: string;
  targetId: string;
  snapshot: TargetCapabilitySnapshot | null;
  requirements: SourceRequirement[];
  claims: StorageClaimEvidence[];
  mappings: ProposedStorageMapping[];
  now?: number;
}): {
  evidenceStatus: ReturnType<typeof inspectTargetCapabilitySnapshot>["status"];
  findings: CompatibilityResult[];
} {
  const inspected = inspectTargetCapabilitySnapshot(
    args.snapshot,
    args.platform,
    args.targetId,
    args.now,
  );
  const findings: CompatibilityResult[] = [];
  for (const req of args.requirements) {
    const resource = [req.namespace ?? "cluster", req.name].join("/");
    if (req.serviceAccountName && req.serviceAccountName !== "default") {
      findings.push({
        id: `identity:${resource}`,
        resource,
        capability: "Workload identity",
        status: "REVIEW_REQUIRED",
        reason:
          "Source ServiceAccount is identified, but target identity mapping and authorization are not verified.",
        nextAction:
          "Record target identity mapping and validate least-privilege permissions using authorized evidence.",
        evidence: "UNVERIFIED",
      });
    }
    if (req.ingressClassName) {
      findings.push({
        id: `ingress:${resource}`,
        resource,
        capability: "Ingress controller",
        status: "UNKNOWN",
        reason:
          "Source ingress class is known, but observed target ingress/controller support was not provided.",
        nextAction:
          "Collect read-only target ingress/controller capabilities and compare routing/TLS requirements.",
        evidence: "MISSING",
      });
    }
  }
  for (const finding of evaluateStorageCompatibility(
    args.claims,
    args.mappings,
    inspected.evidence,
  )) {
    const incompatible =
      finding.type === "CAPACITY_TOO_SMALL" ||
      finding.type === "ACCESS_MODE_UNSUPPORTED";
    findings.push({
      id: `storage:${finding.claim}:${finding.type}`,
      resource: finding.claim,
      capability: "Persistent storage",
      status: incompatible
        ? "INCOMPATIBLE"
        : finding.type === "CLASS_UNVERIFIED"
          ? "UNKNOWN"
          : "REVIEW_REQUIRED",
      reason: finding.detail,
      nextAction: incompatible
        ? "Revise the target mapping and revalidate against verified evidence."
        : "Obtain fresh, target-bound storage capabilities and validate the proposed mapping.",
      evidence: incompatible ? "OBSERVED" : "UNVERIFIED",
    });
  }
  if (inspected.status !== "CURRENT") {
    findings.unshift({
      id: "target-evidence",
      resource: args.targetId || "Unknown destination",
      capability: "Target discovery",
      status: "UNKNOWN",
      reason: `Target capability evidence is ${inspected.status.toLowerCase()}; no compatibility approval can be inferred.`,
      nextAction:
        "Collect an authorized read-only, fresh snapshot bound to the selected target.",
      evidence: "MISSING",
    });
  }
  return { evidenceStatus: inspected.status, findings };
}
