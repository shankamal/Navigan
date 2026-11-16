import type { z } from "zod";
import type { platformComponentInventorySchema } from "@/modules/cluster-management/model";

export const utilityCatalogue = [
  {
    code: "headlamp",
    name: "Headlamp",
    category: "Cluster services",
    chart: "headlamp",
    description: "Kubernetes cluster management dashboard.",
    source: "https://github.com/kubernetes-sigs/headlamp/releases",
    planning: true,
  },
  {
    code: "grafana",
    name: "Monitoring stack",
    category: "Observability",
    chart: "kube-prometheus-stack",
    description: "Grafana and Prometheus share one chart and one change plan.",
    source: "https://github.com/prometheus-community/helm-charts/releases",
    planning: true,
  },
  {
    code: "falco",
    name: "Falco",
    category: "Security",
    chart: "falco",
    description: "Runtime security and threat detection.",
    source: "https://github.com/falcosecurity/charts/releases",
    planning: true,
  },
  {
    code: "argocd",
    name: "Argo CD",
    category: "Continuous delivery",
    chart: "argo-cd",
    description:
      "GitOps reconciliation. Upgrades are not available from this screen yet.",
    source: null,
    planning: false,
  },
  {
    code: "connector",
    name: "Navigan connector",
    category: "Platform integration",
    chart: "navigan-cluster-connector",
    description:
      "Cluster observations and platform integration. Upgrades are not available here yet.",
    source: null,
    planning: false,
  },
] as const;

type Component = z.infer<
  typeof platformComponentInventorySchema
>["components"][number];
export function utilityIsFresh(component: Component, now: number) {
  const time = Date.parse(component.observedAt ?? "");
  return Number.isFinite(time) && time <= now + 60_000 && now - time <= 900_000;
}

export function utilityRows(components: Component[], now: number) {
  const codes = [
    ...new Set(
      components.map((item) =>
        ["grafana", "prometheus"].includes(item.componentCode.toLowerCase())
          ? "grafana"
          : item.componentCode.toLowerCase(),
      ),
    ),
  ];
  return codes.map((code) => {
    const entry = utilityCatalogue.find((item) => item.code === code);
    const members = components.filter((item) =>
      code === "grafana"
        ? ["grafana", "prometheus"].includes(item.componentCode.toLowerCase())
        : item.componentCode.toLowerCase() === code,
    );
    const versions = [
      ...new Set(members.map((item) => item.version).filter(Boolean)),
    ];
    const fresh = members.every((item) => utilityIsFresh(item, now));
    const complete =
      code !== "grafana" ||
      ["grafana", "prometheus"].every((peer) =>
        members.some((item) => item.componentCode.toLowerCase() === peer),
      );
    const healthy =
      fresh &&
      complete &&
      versions.length === 1 &&
      members.every(
        (item) =>
          item.status === "READY" &&
          item.syncStatus === "Synced" &&
          item.healthStatus === "Healthy",
      );
    const status = !fresh
      ? "Unverified"
      : !complete || versions.length > 1
        ? "Needs verification"
        : healthy
          ? "Healthy"
          : members.some(
                (item) =>
                  item.status === "DEGRADED" ||
                  item.healthStatus === "Degraded",
              )
            ? "Degraded"
            : members.some((item) => item.status === "MISSING")
              ? "Not reported"
              : members.some((item) => item.status === "PROGRESSING")
                ? "Progressing"
                : "Needs verification";
    return {
      code,
      name: entry?.name ?? code,
      category: entry?.category ?? "Cluster services",
      version:
        versions.length > 1
          ? "Conflicting evidence"
          : (versions[0] ?? "Not reported"),
      status,
      healthy,
      planning: Boolean(entry?.planning),
      observedAt:
        members
          .map((item) => item.observedAt)
          .filter(Boolean)
          .sort()[0] ?? null,
      reported: versions.length > 0,
      memberCount: members.length,
    };
  });
}
