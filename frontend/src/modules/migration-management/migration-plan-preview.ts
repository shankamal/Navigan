import type { ResourceCompatibilityEvaluation } from "./service";
import { buildRemediationHandoff } from "./remediation-handoff";

const WORKLOAD_KINDS = new Set([
  "Deployment",
  "StatefulSet",
  "DaemonSet",
  "Pod",
  "Job",
  "CronJob",
]);

export function buildMigrationPlanPreview(
  evaluations: ResourceCompatibilityEvaluation[],
) {
  const handoff = buildRemediationHandoff(evaluations);
  const workloads = evaluations
    .filter((item) => WORKLOAD_KINDS.has(item.resource.kind))
    .map((item) => ({
      resource: item.resource,
      sourceStatus: item.sourceStatus ?? "NOT_VERIFIED",
      targetStatus: item.targetStatus ?? "PENDING_EVIDENCE",
      remediationCount: handoff.actions.filter((task) =>
        sameResource(task.resource, item.resource),
      ).length,
      verificationCount: handoff.evidence.filter((task) =>
        sameResource(task.resource, item.resource),
      ).length,
    }));
  return {
    status: "DRAFT_PREVIEW" as const,
    executionReady: false as const,
    workloads,
    remediationCount: handoff.actions.length,
    verificationCount: handoff.evidence.length,
    prerequisites: [
      "Confirm source dependencies and stateful data-consistency requirements.",
      "Resolve required remediation actions and record owner approval.",
      "Verify target Kubernetes APIs, scheduling, storage, networking, identity and operators.",
      "Validate artifact provenance, deployment order, testing and rollback checkpoints.",
    ],
    note: "This is an unordered planning inventory, not an execution sequence, migration wave, approval or deployable artifact.",
  };
}

function sameResource(
  a: ResourceCompatibilityEvaluation["resource"],
  b: ResourceCompatibilityEvaluation["resource"],
) {
  return (
    a.apiVersion === b.apiVersion &&
    a.kind === b.kind &&
    (a.namespace ?? null) === (b.namespace ?? null) &&
    a.name === b.name
  );
}
