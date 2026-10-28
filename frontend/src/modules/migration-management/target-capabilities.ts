import type { TargetAssessmentRecord } from "./service";
/** Read-only, provider-neutral capability snapshot contract.
 * An adapter must supply actual target observations; platform defaults are never verified evidence. */
import type { StorageTargetEvidence } from "./storage-validation";

export interface TargetCapabilitySnapshot {
  schemaVersion: 1;
  platform: string;
  targetId: string;
  observedAt: string;
  source: "READ_ONLY_ADAPTER";
  storageClasses: {
    name: string;
    provisioner: string;
    accessModes: string[];
    verified: boolean;
  }[];
}
export type CapabilityEvidenceStatus =
  "UNAVAILABLE" | "INVALID" | "STALE" | "CURRENT";
export interface TargetCapabilityAdapter {
  platform: string;
  discover(targetId: string): Promise<TargetCapabilitySnapshot>;
}
export function inspectTargetCapabilitySnapshot(
  snapshot: TargetCapabilitySnapshot | null,
  expectedPlatform: string,
  expectedTargetId: string,
  now = Date.now(),
  maxAgeMs = 60 * 60 * 1000,
): {
  status: CapabilityEvidenceStatus;
  evidence: StorageTargetEvidence | null;
} {
  if (!snapshot) return { status: "UNAVAILABLE", evidence: null };
  const observed = Date.parse(snapshot.observedAt);
  if (
    snapshot.schemaVersion !== 1 ||
    snapshot.source !== "READ_ONLY_ADAPTER" ||
    snapshot.platform !== expectedPlatform ||
    snapshot.targetId !== expectedTargetId ||
    !Array.isArray(snapshot.storageClasses) ||
    snapshot.storageClasses.some(
      (c) =>
        !c ||
        typeof c.name !== "string" ||
        typeof c.provisioner !== "string" ||
        !Array.isArray(c.accessModes) ||
        !c.accessModes.every((mode) => typeof mode === "string") ||
        typeof c.verified !== "boolean",
    ) ||
    !Number.isFinite(observed) ||
    observed > now + 300000
  )
    return { status: "INVALID", evidence: null };
  if (now - observed > maxAgeMs) return { status: "STALE", evidence: null };
  return {
    status: "CURRENT",
    evidence: {
      platform: snapshot.platform,
      storageClasses: snapshot.storageClasses,
    },
  };
}

/**
 * Bridge the persisted connector observation to the local evaluator contract.
 * Observed StorageClass names/provisioners do NOT establish supported access
 * modes or PVC compatibility; they intentionally remain unverified.
 */
export function targetCapabilityFromAssessment(
  assessment: TargetAssessmentRecord | null,
  targetPlatform: string,
  targetId: string,
  assessmentVersion: number,
  now = Date.now(),
): TargetCapabilitySnapshot | null {
  if (
    !assessment ||
    assessment.targetClusterId !== targetId ||
    assessment.assessmentVersion !== assessmentVersion ||
    assessment.evidenceLevel !== "CONNECTOR_RUNTIME_INVENTORY"
  )
    return null;
  const snapshot = assessment.snapshot;
  const observedAt = Date.parse(snapshot.observedAt);
  const expiresAt = snapshot.inventoryExpiresAt
    ? Date.parse(snapshot.inventoryExpiresAt)
    : observedAt + 60 * 60 * 1000;
  if (
    !Number.isFinite(observedAt) ||
    !Number.isFinite(expiresAt) ||
    observedAt > now + 300000 ||
    expiresAt <= now ||
    now - observedAt > 60 * 60 * 1000 ||
    snapshot.platform.toUpperCase() !== targetPlatform
  )
    return null;
  const classes =
    snapshot.storageDiscovery?.StorageClass === "AVAILABLE"
      ? (snapshot.storageClassDetails ?? [])
      : [];
  return {
    schemaVersion: 1,
    platform: targetPlatform,
    targetId,
    observedAt: snapshot.observedAt,
    source: "READ_ONLY_ADAPTER",
    storageClasses: classes
      .filter(
        (item) =>
          typeof item.name === "string" && typeof item.provisioner === "string",
      )
      .map((item) => ({
        name: item.name,
        provisioner: item.provisioner!,
        accessModes: [],
        verified: false,
      })),
  };
}
