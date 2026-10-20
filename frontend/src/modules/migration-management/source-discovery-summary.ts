import type { Assessment, SourceInventoryResource } from "./model";

type Finding = Assessment["findings"][number];
export const workloadKinds = new Set([
  "Deployment",
  "StatefulSet",
  "DaemonSet",
  "Job",
  "CronJob",
]);
const platformNamespaces = new Set([
  "kube-system",
  "kube-public",
  "kube-node-lease",
  "calico-system",
  "tigera-operator",
  "ingress-nginx",
  "headlamp",
  "navigan-migration",
]);

/** Namespace hints describe presentation only, never migration eligibility. */
export function discoveryScope(namespace?: string | null) {
  return !namespace
    ? "cluster"
    : platformNamespaces.has(namespace)
      ? "platform"
      : "application";
}

export function inventorySummary(resources: SourceInventoryResource[]) {
  const kinds = new Map<string, number>();
  const identities = new Set<string>();
  let repeatedIdentities = 0;
  let controllers = 0;
  let batch = 0;
  const workloads = { application: 0, platform: 0, cluster: 0 };
  for (const resource of resources) {
    kinds.set(resource.kind, (kinds.get(resource.kind) ?? 0) + 1);
    if (resource.name) {
      const group = resource.apiVersion.includes("/")
        ? resource.apiVersion.split("/")[0]
        : "";
      const key = JSON.stringify([
        group,
        resource.kind,
        resource.namespace ?? "",
        resource.name,
      ]);
      if (identities.has(key)) repeatedIdentities++;
      identities.add(key);
    }
    if (!workloadKinds.has(resource.kind)) continue;
    workloads[discoveryScope(resource.namespace)]++;
    if (["Job", "CronJob"].includes(resource.kind)) batch++;
    else controllers++;
  }
  return {
    kinds: [...kinds].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])),
    controllers,
    batch,
    workloads,
    repeatedIdentities,
  };
}

export function groupSourceFindings(findings: Finding[]) {
  const groups = new Map<
    string,
    {
      key: string;
      code: string;
      severity: Finding["severity"];
      category: string;
      observations: Finding[];
      resources: Set<string>;
      unlinked: number;
    }
  >();
  for (const finding of findings) {
    const key = JSON.stringify([
      finding.code,
      finding.severity,
      finding.category,
    ]);
    let group = groups.get(key);
    if (!group) {
      group = {
        key,
        code: finding.code,
        severity: finding.severity,
        category: finding.category,
        observations: [],
        resources: new Set(),
        unlinked: 0,
      };
      groups.set(key, group);
    }
    group.observations.push(finding);
    if (finding.resourceName)
      group.resources.add(
        JSON.stringify([
          finding.namespace ?? "",
          finding.resourceKind ?? "",
          finding.resourceName,
        ]),
      );
    else group.unlinked++;
  }
  const rank = { BLOCKER: 0, WARNING: 1, INFO: 2 };
  return [...groups.values()].sort(
    (a, b) =>
      rank[a.severity] - rank[b.severity] ||
      b.observations.length - a.observations.length ||
      a.code.localeCompare(b.code),
  );
}
