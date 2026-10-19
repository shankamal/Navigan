import type {
  MigrationPlanningDraft,
  PlannedResource,
  SourceInventoryResource,
} from "./model";
import {
  graphFromSanitizedInventory,
  migrationNodeId,
} from "./migration-graph";

export const applicationKinds = new Set([
  "Deployment",
  "StatefulSet",
  "DaemonSet",
  "Job",
  "CronJob",
  "Pod",
  "DeploymentConfig",
]);
export const scopeKey = (r: {
  apiVersion: string;
  kind: string;
  namespace?: string | null;
  name: string;
}) => JSON.stringify([r.apiVersion, r.kind, r.namespace ?? null, r.name]);
export type NamedSourceResource = SourceInventoryResource & { name: string };
export const namedResources = (resources: SourceInventoryResource[]) =>
  resources.filter(
    (r): r is NamedSourceResource =>
      typeof r.name === "string" && Boolean(r.name),
  );

/** Only observed references and StatefulSet claim ownership; never include a whole namespace by implication. */
export function selectedApplicationScope(
  resources: SourceInventoryResource[],
  workloadKeys: ReadonlySet<string>,
) {
  const named = namedResources(resources);
  const workloads = named.filter(
    (r) => applicationKinds.has(r.kind) && workloadKeys.has(scopeKey(r)),
  );
  const graph = graphFromSanitizedInventory(named);
  const ingressIds = new Set(
    graph.nodes.filter((n) => n.kind === "Ingress").map((n) => n.id),
  );
  const ids = new Set(
    workloads.map((r) => migrationNodeId(r.kind, r.namespace, r.name)),
  );
  const missing = new Map<string, { kind: string; name: string }>();
  let changed = true;
  while (changed) {
    changed = false;
    for (const edge of graph.edges) {
      if (!ids.has(edge.from) || ingressIds.has(edge.from)) continue;
      if (edge.resolution === "NOT_IN_INVENTORY")
        missing.set(edge.to, { kind: edge.kind, name: edge.name });
      else if (!ids.has(edge.to)) {
        ids.add(edge.to);
        changed = true;
      }
    }
    // Include an observed ingress only when it routes to an included service.
    for (const node of graph.nodes.filter((n) => n.kind === "Ingress")) {
      if (
        graph.edges.some((e) => e.from === node.id && ids.has(e.to)) &&
        !ids.has(node.id)
      ) {
        ids.add(node.id);
        changed = true;
      }
    }
  }
  const namespaces = [
    ...new Set(
      workloads
        .map((r) => r.namespace)
        .filter((ns): ns is string => Boolean(ns)),
    ),
  ].sort();
  const selected = named.filter(
    (r) =>
      ids.has(migrationNodeId(r.kind, r.namespace, r.name)) ||
      (r.kind === "Namespace" && namespaces.includes(r.name)),
  );
  const planned: PlannedResource[] = selected.map((r) => ({
    apiVersion: r.apiVersion,
    kind: r.kind,
    namespace: r.namespace ?? null,
    name: r.name,
    treatment: applicationKinds.has(r.kind) ? "MIGRATE" : "RECREATE",
    dependency: !workloadKeys.has(scopeKey(r)),
  }));
  return {
    workloads,
    dependencies: selected.filter((r) => !workloadKeys.has(scopeKey(r))),
    resources: planned,
    namespaces,
    missing: [...missing.values()],
    coverage: graph.coverage,
  };
}

export function restoredWorkloadKeys(
  resources: SourceInventoryResource[],
  draft?: MigrationPlanningDraft,
) {
  const available = new Set(
    namedResources(resources)
      .filter((r) => applicationKinds.has(r.kind))
      .map(scopeKey),
  );
  return new Set(
    (draft?.resources ?? [])
      .filter(
        (r) =>
          !r.dependency &&
          r.treatment !== "RETIRE" &&
          available.has(scopeKey(r)),
      )
      .map(scopeKey),
  );
}
