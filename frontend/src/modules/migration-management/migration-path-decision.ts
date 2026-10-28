import type { CompatibilityResult } from "./compatibility-intelligence";
import type { CapabilityEvidenceStatus } from "./target-capabilities";

export type MigrationPath =
  "DIRECT" | "ASSISTED" | "BLOCKED" | "PENDING_EVIDENCE";
export interface MigrationPathDecision {
  path: MigrationPath;
  reason: string;
}
/**
 * This classification is a planning recommendation, not execution approval.
 * Callers must provide full, authoritative target checks; an empty array is
 * explicitly considered incomplete evidence.
 */
export function determineMigrationPath(args: {
  targetEvidence: CapabilityEvidenceStatus;
  checks: CompatibilityResult[];
  coverageComplete: boolean;
}): MigrationPathDecision {
  if (
    args.targetEvidence !== "CURRENT" ||
    !args.coverageComplete ||
    !args.checks.length
  ) {
    return {
      path: "PENDING_EVIDENCE",
      reason:
        "Fresh, complete source-to-target compatibility evidence is required.",
    };
  }
  if (args.checks.some((check) => check.status === "INCOMPATIBLE")) {
    return {
      path: "BLOCKED",
      reason: "One or more required target capabilities are incompatible.",
    };
  }
  if (args.checks.some((check) => check.status === "UNKNOWN")) {
    return {
      path: "PENDING_EVIDENCE",
      reason: "Required target capabilities remain unverified.",
    };
  }
  if (args.checks.some((check) => check.status === "REVIEW_REQUIRED")) {
    return {
      path: "ASSISTED",
      reason: "Remediation decisions or manual validation are required.",
    };
  }
  return {
    path: "DIRECT",
    reason:
      "All required compatibility checks passed. Execution approval remains separate.",
  };
}
