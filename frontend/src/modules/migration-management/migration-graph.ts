/** Provider-neutral planning graph. Adapters normalize their inventory into this contract. */
export type MigrationPlatform = "KUBERNETES" | "ECS" | "OPENSHIFT" | "OTHER";
export type MigrationResourceCategory = "WORKLOAD" | "SERVICE" | "CONFIGURATION" | "STORAGE" | "SECURITY" | "OTHER";
export type RelationshipEvidence = "EXPLICIT_REFERENCE" | "SELECTOR_MATCH" | "INFERRED";
export interface MigrationNode {
  id: string;
  platform: MigrationPlatform;
  kind: string;
  name: string;
  namespace: string | null;
  category: MigrationResourceCategory;
}
export interface MigrationEdge {
  from: string;
  to: string;
  kind: string;
  name: string;
  evidence: RelationshipEvidence;
  resolution: "IN_INVENTORY" | "NOT_IN_INVENTORY";
}
export interface MigrationGraph {
  nodes: MigrationNode[];
  edges: MigrationEdge[];
  coverage: "REFERENCES_AVAILABLE" | "REFERENCES_NOT_COLLECTED";
}
export interface MigrationInventoryItem {
  kind: string;
  name?: string | null;
  namespace?: string | null;
  dependencyReferences?: unknown;
  backendServiceReferences?: unknown;
  volumeClaimTemplateNames?: unknown;
}
const workloadKinds = new Set(["Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob", "Pod", "TaskDefinition", "EcsService", "DeploymentConfig"]);
const storageKinds = new Set(["PersistentVolumeClaim", "PersistentVolume", "StorageClass", "VolumeSnapshot", "EfsVolume"]);
const serviceKinds = new Set(["Service", "EcsService", "Route", "Ingress"]);
const configurationKinds = new Set(["ConfigMap", "Secret", "ServiceAccount", "TaskDefinition", "NetworkPolicy"]);
export function migrationResourceCategory(kind: string): MigrationResourceCategory {
  if (workloadKinds.has(kind)) return "WORKLOAD";
  if (storageKinds.has(kind)) return "STORAGE";
  if (serviceKinds.has(kind)) return "SERVICE";
  if (configurationKinds.has(kind)) return "CONFIGURATION";
  return "OTHER";
}
export function migrationNodeId(kind: string, namespace: string | null | undefined, name: string): string {
  return JSON.stringify([kind, namespace ?? null, name]);
}
/** This adapter consumes sanitized Kubernetes/OpenShift-shaped inventory. ECS adapters
 * must supply normalized references before claiming support for ECS discovery. */
export function graphFromSanitizedInventory(items: MigrationInventoryItem[], platform: MigrationPlatform = "KUBERNETES"): MigrationGraph {
  const nodes: MigrationNode[] = items.filter((r): r is MigrationInventoryItem & {name:string} => typeof r.name === "string" && r.name.length > 0).map((r) => ({
    id: migrationNodeId(r.kind, r.namespace, r.name), platform, kind: r.kind, name: r.name,
    namespace: r.namespace ?? null, category: migrationResourceCategory(r.kind),
  }));
  const index = new Set(nodes.map((n) => n.id));
  const edges: MigrationEdge[] = [];
  let hasReferences = false;
  for (const item of items) {
    if (!item.name) continue;
    for (const field of ["dependencyReferences", "backendServiceReferences"] as const) {
      const refs = item[field];
      if (!Array.isArray(refs)) continue;
      hasReferences = true;
      for (const ref of refs) {
        if (!ref || typeof ref !== "object" || typeof ref.kind !== "string" || typeof ref.name !== "string") continue;
        const id = migrationNodeId(ref.kind, item.namespace, ref.name);
        edges.push({
          from: migrationNodeId(item.kind, item.namespace, item.name), to: id,
          kind: ref.kind, name: ref.name,
          evidence: "EXPLICIT_REFERENCE",
          resolution: index.has(id) ? "IN_INVENTORY" : "NOT_IN_INVENTORY",
        });
      }
    }
  }
  // StatefulSet claim template names plus an existing concrete PVC name provide
  // derived ownership evidence; do not invent claims for absent replicas.
  for (const item of items) {
    if (item.kind !== "StatefulSet" || !item.name || !Array.isArray(item.volumeClaimTemplateNames)) continue;
    const ownerId = migrationNodeId(item.kind, item.namespace, item.name);
    for (const template of item.volumeClaimTemplateNames) {
      if (typeof template !== "string" || !template) continue;
      const prefix = template + "-" + item.name + "-";
      for (const node of nodes) {
        if (node.kind !== "PersistentVolumeClaim" || node.namespace !== (item.namespace ?? null) || !node.name.startsWith(prefix)) continue;
        if (!/^[0-9]+$/.test(node.name.slice(prefix.length))) continue;
        if (edges.some((edge) => edge.from === ownerId && edge.to === node.id)) continue;
        edges.push({from: ownerId, to: node.id, kind: node.kind, name: node.name, evidence: "INFERRED", resolution: "IN_INVENTORY"});
      }
    }
  }
  return { nodes, edges, coverage: hasReferences ? "REFERENCES_AVAILABLE" : "REFERENCES_NOT_COLLECTED" };
}
