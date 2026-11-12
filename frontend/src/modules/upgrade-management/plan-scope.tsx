import { Cpu, Layers3, Puzzle, Wrench } from "lucide-react";
import type { EksUpgradePlan } from "@/modules/cluster-management/model";

export const scopeTypes = [
  { id: "cluster", label: "Cluster upgrades", Icon: Cpu },
  { id: "nodes", label: "Node group upgrades", Icon: Layers3 },
  { id: "addons", label: "Managed add-ons", Icon: Puzzle },
  { id: "utilities", label: "System utilities", Icon: Wrench },
] as const;
export type PlanScope = (typeof scopeTypes)[number]["id"];
export function planScopes(plan: EksUpgradePlan): PlanScope[] {
  if (plan.kind === "UTILITY") return ["utilities"];
  if (plan.planSpec) {
    const kinds = new Set(
      plan.planSpec.steps.flatMap((s) => s.operations.map((o) => o.kind)),
    );
    return [
      ...(kinds.has("CONTROL_PLANE") ? ["cluster" as const] : []),
      ...(kinds.has("NODEGROUP") ? ["nodes" as const] : []),
      ...(kinds.has("ADDON") ? ["addons" as const] : []),
    ];
  }
  const evidence = plan.readinessEvidence;
  return [
    ...(plan.currentVersion !== plan.targetVersion ? ["cluster" as const] : []),
    ...(evidence?.nodeGroups.some(
      (n) => n.version && n.version !== plan.targetVersion,
    )
      ? ["nodes" as const]
      : []),
    ...(evidence?.addons.some(
      (a) => a.version && a.targetVersion && a.version !== a.targetVersion,
    )
      ? ["addons" as const]
      : []),
  ];
}
export function planTypeLabel(plan: EksUpgradePlan): string {
  if (plan.kind === "UTILITY")
    return plan.utilityEvidence?.label || "System utility upgrade";
  return plan.planSpec?.scope === "NODES"
    ? "Node group upgrade"
    : plan.planSpec?.scope === "ADDONS"
      ? "Managed add-on upgrade"
      : "Cluster upgrade";
}
export function planVersionLabel(plan: EksUpgradePlan): string {
  if (!plan.planSpec || plan.planSpec.scope === "CLUSTER")
    return `${plan.currentVersion} → ${plan.targetVersion}`;
  const ops = plan.planSpec.steps.flatMap((s) => s.operations);
  return ops.length === 1
    ? `${ops[0].from} → ${ops[0].to}`
    : `${new Set(ops.map((o) => o.name)).size} components · ${ops.length} updates`;
}
export function PlanScopeLabel({ plan }: { plan: EksUpgradePlan }) {
  if (plan.kind === "UTILITY") {
    const logos: Record<string, string> = {
      argocd: "argo",
      grafana: "grafana",
      prometheus: "prometheus",
    };
    const logo = logos[plan.utilityCode ?? ""];
    return (
      <span className="upgrade-scope-label">
        {logo ? (
          <img src={`/logos/${logo}.svg`} alt="" width={20} height={20} />
        ) : (
          <Wrench size={18} aria-hidden="true" />
        )}
        {plan.utilityEvidence?.label ?? plan.utilityCode ?? "System utility"}
        <small>System utility</small>
      </span>
    );
  }
  const scopes = planScopes(plan);
  return (
    <span className="upgrade-scope-label">
      {plan.planSpec?.scope === "NODES" ? (
        <Layers3 size={18} aria-hidden="true" />
      ) : plan.planSpec?.scope === "ADDONS" ? (
        <Puzzle size={18} aria-hidden="true" />
      ) : (
        <Cpu size={18} aria-hidden="true" />
      )}
      {scopes.length
        ? scopes
            .map((s) =>
              scopeTypes
                .find((t) => t.id === s)!
                .label.replace(" upgrades", ""),
            )
            .join(" + ")
        : "Container plan"}
    </span>
  );
}
