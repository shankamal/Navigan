/** Read-only, provider-neutral capability snapshot contract.
 * An adapter must supply actual target observations; platform defaults are never verified evidence. */
import type { StorageTargetEvidence } from "./storage-validation";

export interface TargetCapabilitySnapshot {
  schemaVersion: 1;
  platform: string;
  targetId: string;
  observedAt: string;
  source: "READ_ONLY_ADAPTER";
  storageClasses: {name: string; provisioner: string; accessModes: string[]; verified: boolean}[];
}
export type CapabilityEvidenceStatus = "UNAVAILABLE" | "INVALID" | "STALE" | "CURRENT";
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
): {status: CapabilityEvidenceStatus; evidence: StorageTargetEvidence | null} {
  if (!snapshot) return {status:"UNAVAILABLE",evidence:null};
  const observed = Date.parse(snapshot.observedAt);
  if (snapshot.schemaVersion !== 1 || snapshot.source !== "READ_ONLY_ADAPTER" ||
      snapshot.platform !== expectedPlatform || snapshot.targetId !== expectedTargetId ||
      !Array.isArray(snapshot.storageClasses) ||
      snapshot.storageClasses.some(c => !c || typeof c.name !== "string" || typeof c.provisioner !== "string" ||
        !Array.isArray(c.accessModes) || !c.accessModes.every(mode => typeof mode === "string") ||
        typeof c.verified !== "boolean") ||
      !Number.isFinite(observed) || observed > now + 300000) return {status:"INVALID",evidence:null};
  if (now - observed > maxAgeMs) return {status:"STALE",evidence:null};
  return {status:"CURRENT",evidence:{platform:snapshot.platform,storageClasses:snapshot.storageClasses}};
}
