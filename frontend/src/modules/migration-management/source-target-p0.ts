import type { PlannedResource, SourceInventoryResource } from "./model";

export type P0Status = "COMPATIBLE" | "REMEDIATION_REQUIRED" | "BLOCKED" | "NOT_VERIFIED";
export interface P0Check {
  capability: "Kubernetes API" | "Compute & scheduling" | "Persistent storage" | "Networking" | "Identity & security" | "Dependencies";
  status: P0Status;
  reason: string;
  nextAction: string;
}
export interface P0ResourceResult {
  resource: PlannedResource;
  checks: P0Check[];
  status: P0Status;
}
const APPLICABLE: Record<string, P0Check["capability"][]> = {
  Deployment: ["Kubernetes API", "Compute & scheduling", "Networking", "Identity & security", "Dependencies"],
  StatefulSet: ["Kubernetes API", "Compute & scheduling", "Persistent storage", "Networking", "Identity & security", "Dependencies"],
  DaemonSet: ["Kubernetes API", "Compute & scheduling", "Networking", "Identity & security", "Dependencies"],
  Job: ["Kubernetes API", "Compute & scheduling", "Identity & security", "Dependencies"],
  CronJob: ["Kubernetes API", "Compute & scheduling", "Identity & security", "Dependencies"],
  Pod: ["Kubernetes API", "Compute & scheduling", "Networking", "Identity & security", "Dependencies"],
  PersistentVolumeClaim: ["Kubernetes API", "Persistent storage", "Dependencies"],
  Ingress: ["Kubernetes API", "Networking", "Dependencies"],
  Service: ["Kubernetes API", "Networking", "Dependencies"],
  ServiceAccount: ["Kubernetes API", "Identity & security", "Dependencies"],
};
const actions: Record<P0Check["capability"], string> = {
  "Kubernetes API": "Verify the resource apiVersion and kind against the observed target Kubernetes version and enabled APIs.",
  "Compute & scheduling": "Collect target allocatable CPU/memory, quotas, taints, tolerations and workload requests.",
  "Persistent storage": "Validate the actual target StorageClasses, CSI drivers, access modes and capacity against each claim.",
  Networking: "Validate ingress controllers, routes, NetworkPolicies, service exposure and DNS/TLS dependencies.",
  "Identity & security": "Verify ServiceAccounts, workload IAM mappings, permissions, secrets and image-pull access.",
  Dependencies: "Confirm selected and external dependencies and required operators/controllers are available on the target.",
};
const statusOrder: P0Status[] = ["BLOCKED", "REMEDIATION_REQUIRED", "NOT_VERIFIED", "COMPATIBLE"];
/**
 * Evidence-first assessment. Connector summary proves inventory exists, NOT that
 * a workload can be scheduled or its dependencies can run on the destination.
 * Never assign COMPATIBLE or a migration score without concrete target checks.
 */
export function analyzeP0Compatibility(
  selected: PlannedResource[],
  sourceResources: SourceInventoryResource[],
  connectorInventoryAvailable: boolean,
): P0ResourceResult[] {
  return selected.map(resource => {
    const source = sourceResources.find(item => item.kind === resource.kind &&
      item.name === resource.name && (item.namespace ?? null) === (resource.namespace ?? null));
    const capabilities = APPLICABLE[resource.kind] ?? ["Kubernetes API", "Dependencies"];
    const checks: P0Check[] = capabilities.map(capability => ({
      capability,
      status: "NOT_VERIFIED",
      reason: source
        ? connectorInventoryAvailable
          ? "Source resource is observed and target connector inventory is available, but the required target capability comparison is not recorded."
          : "Source resource is observed; target capability evidence is unavailable."
        : "Selected resource is not present in the current source inventory snapshot.",
      nextAction: actions[capability],
    }));
    return {
      resource,
      checks,
      status: statusOrder.find(status => checks.some(check => check.status === status)) ?? "NOT_VERIFIED",
    };
  });
}
