import { migrationNodeId, type MigrationGraph } from "./migration-graph";

export interface ReadinessSelection {
  kind: string;
  namespace: string | null;
  name: string;
  dependency?: boolean;
}
export type ReadinessIssueType = "MISSING_INVENTORY" | "NOT_SELECTED" | "COVERAGE_UNKNOWN" | "DATA_STRATEGY_REQUIRED" | "PVC_OWNERSHIP_UNVERIFIED" | "STORAGE_MAPPING_REQUIRED" | "STORAGE_MAPPING_REVIEW";
export interface ReadinessIssue { type: ReadinessIssueType; detail: string; resourceId?: string }
export interface ScopeReadiness {
  state: "INCOMPLETE" | "REVIEW_REQUIRED";
  selectedWorkloads: number;
  confirmedDependencies: number;
  issues: ReadinessIssue[];
}
/** Planning-only check. Never declares a target or workload ready for execution. */
export function evaluateScopeReadiness(
  graph: MigrationGraph,
  selection: ReadinessSelection[],
  dataStrategy: string,
  persistentDataPresent: boolean,
  unverifiedPvcOwnership = 0,
  storageClaims: {namespace: string | null; name: string}[] = [],
  storageMappings: {namespace: string; sourceClaim: string; targetStorageClass: string; targetCapacity: string; targetAccessMode: string; status: string}[] = [],
): ScopeReadiness {
  const primary = selection.filter((item) => !item.dependency);
  const chosen = new Set(selection.map((item) => migrationNodeId(item.kind, item.namespace, item.name)));
  const owners = new Set(primary.map((item) => migrationNodeId(item.kind, item.namespace, item.name)));
  const issues: ReadinessIssue[] = [];
  if (graph.coverage === "REFERENCES_NOT_COLLECTED") {
    issues.push({type:"COVERAGE_UNKNOWN",detail:"This source inventory does not contain dependency-reference evidence. Reassessment is required to validate completeness."});
  }
  const seen = new Set<string>();
  for (const edge of graph.edges.filter((item) => owners.has(item.from))) {
    const key = edge.to + ":" + edge.resolution;
    if (seen.has(key)) continue;
    seen.add(key);
    if (edge.resolution === "NOT_IN_INVENTORY") {
      issues.push({type:"MISSING_INVENTORY",resourceId:edge.to,detail:`${edge.kind} ${edge.name} is referenced by a selected workload but absent from collected inventory.`});
    } else if (!chosen.has(edge.to)) {
      issues.push({type:"NOT_SELECTED",resourceId:edge.to,detail:`${edge.kind} ${edge.name} is present in inventory but not included in the migration draft.`});
    }
  }
  for (const claim of storageClaims) {
    const mapping = storageMappings.find((m) => m.namespace === claim.namespace && m.sourceClaim === claim.name);
    if (!mapping || !mapping.targetStorageClass.trim() || !mapping.targetCapacity.trim() || !mapping.targetAccessMode.trim()) {
      issues.push({type:"STORAGE_MAPPING_REQUIRED",detail:`PVC ${claim.namespace}/${claim.name} requires target storage class, capacity and access mode mapping.`});
    } else if (mapping.status !== "REVIEWED") {
      issues.push({type:"STORAGE_MAPPING_REVIEW",detail:`PVC ${claim.namespace}/${claim.name} mapping requires human review and validation.`});
    }
  }
  if (storageClaims.length && dataStrategy === "NO_PERSISTENT_DATA") {
    issues.push({type:"DATA_STRATEGY_REQUIRED",detail:"No persistent data was selected, but persistent volume claims are inventoried in migration scope."});
  }
  if (unverifiedPvcOwnership > 0) {
    issues.push({type:"PVC_OWNERSHIP_UNVERIFIED",detail:`${unverifiedPvcOwnership} PVC ownership relationship(s) need explicit source evidence before storage readiness can be established.`});
  }
  if (persistentDataPresent && dataStrategy === "UNDECIDED") {
    issues.push({type:"DATA_STRATEGY_REQUIRED",detail:"Persistent storage is inventoried; select and validate a data migration strategy."});
  }
  return {
    state: issues.length ? "INCOMPLETE" : "REVIEW_REQUIRED",
    selectedWorkloads: primary.length,
    confirmedDependencies: selection.length-primary.length,
    issues,
  };
}
