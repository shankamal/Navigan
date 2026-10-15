import type { ResourceCompatibilityEvaluation } from "./service";

const ACTION_STATUSES = new Set(["REMEDIATION_REQUIRED", "INCOMPATIBLE", "BLOCKER"]);
const EVIDENCE_STATUSES = new Set(["PENDING_EVIDENCE", "NOT_VERIFIED", "PARTIAL"]);

export function buildRemediationHandoff(evaluations: ResourceCompatibilityEvaluation[]) {
  const actions: { resource: ResourceCompatibilityEvaluation["resource"]; capability: string; reason: string; nextAction: string; status: string }[] = [];
  const evidence: typeof actions = [];
  for (const evaluation of evaluations) {
    for (const check of evaluation.checks) {
      const entry = {
        resource: evaluation.resource, capability: check.capability,
        reason: check.reason, nextAction: check.nextAction, status: check.status,
      };
      if (ACTION_STATUSES.has(check.status)) actions.push(entry);
      else if (EVIDENCE_STATUSES.has(check.status)) evidence.push(entry);
    }
  }
  return {
    actions, evidence, resourceCount: evaluations.length,
    executionReady: false as const,
    note: "Actionable source changes are separate from evidence requests. No dependency order or migration approval is inferred.",
  };
}
