/** Provider-neutral target-storage validation. No provider availability is inferred. */
export interface StorageCapability {
  name: string;
  accessModes: string[];
  verified: boolean;
}
export interface StorageTargetEvidence {
  platform: string;
  storageClasses: StorageCapability[];
}
export interface StorageClaimEvidence {
  namespace: string | null;
  name: string;
  requestedStorage?: string | null;
}
export interface ProposedStorageMapping {
  namespace: string;
  sourceClaim: string;
  targetStorageClass: string;
  targetCapacity: string;
  targetAccessMode: string;
}
export interface StorageCompatibilityFinding {
  type:
    | "CAPACITY_TOO_SMALL"
    | "CAPACITY_UNVERIFIED"
    | "CLASS_UNVERIFIED"
    | "ACCESS_MODE_UNSUPPORTED";
  claim: string;
  detail: string;
}
function bytes(value: string | null | undefined): number | null {
  if (!value) return null;
  const match = /^([0-9]+(?:\.[0-9]+)?)(Ki|Mi|Gi|Ti|Pi|K|M|G|T|P)?$/.exec(
    value.trim(),
  );
  if (!match) return null;
  const powers: Record<string, number> = {
    Ki: 1024,
    Mi: 1024 ** 2,
    Gi: 1024 ** 3,
    Ti: 1024 ** 4,
    Pi: 1024 ** 5,
    K: 1000,
    M: 1000 ** 2,
    G: 1000 ** 3,
    T: 1000 ** 4,
    P: 1000 ** 5,
  };
  const result = Number(match[1]) * (powers[match[2] ?? ""] ?? 1);
  return Number.isFinite(result) && result > 0 ? result : null;
}
export function evaluateStorageCompatibility(
  claims: StorageClaimEvidence[],
  mappings: ProposedStorageMapping[],
  evidence: StorageTargetEvidence | null,
): StorageCompatibilityFinding[] {
  const findings: StorageCompatibilityFinding[] = [];
  for (const claim of claims) {
    const mapping = mappings.find(
      (m) => m.namespace === claim.namespace && m.sourceClaim === claim.name,
    );
    if (!mapping) continue; // Missing mappings are handled by scope readiness.
    const ref = claim.namespace + "/" + claim.name;
    const sourceBytes = bytes(claim.requestedStorage);
    const targetBytes = bytes(mapping.targetCapacity);
    if (
      sourceBytes !== null &&
      targetBytes !== null &&
      targetBytes < sourceBytes
    ) {
      findings.push({
        type: "CAPACITY_TOO_SMALL",
        claim: ref,
        detail: `Target capacity ${mapping.targetCapacity} is below source request ${claim.requestedStorage} for ${ref}.`,
      });
    } else if (sourceBytes === null || targetBytes === null) {
      findings.push({
        type: "CAPACITY_UNVERIFIED",
        claim: ref,
        detail: `Capacity cannot be compared for ${ref}; supply valid source and target quantities.`,
      });
    }
    if (!mapping.targetStorageClass.trim()) continue; // Missing field handled elsewhere.
    const targetClass = evidence?.storageClasses.find(
      (c) => c.name === mapping.targetStorageClass && c.verified,
    );
    if (!targetClass) {
      findings.push({
        type: "CLASS_UNVERIFIED",
        claim: ref,
        detail: `Target storage class ${mapping.targetStorageClass} is not verified for ${ref}.`,
      });
    } else if (
      mapping.targetAccessMode &&
      !targetClass.accessModes.includes(mapping.targetAccessMode)
    ) {
      findings.push({
        type: "ACCESS_MODE_UNSUPPORTED",
        claim: ref,
        detail: `Target class ${mapping.targetStorageClass} does not list access mode ${mapping.targetAccessMode} for ${ref}.`,
      });
    }
  }
  return findings;
}
