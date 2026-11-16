import type { EksUpgradePlan } from "@/modules/cluster-management/model";
import { utilityCatalogue } from "./utility-catalogue";

const activeStatuses = new Set([
  "DRAFT",
  "SUBMITTED",
  "APPROVED",
  "SCHEDULED",
  "EXECUTING",
]);

export function activeUtilityPlan(
  plans: EksUpgradePlan[],
  clusterId: string,
  utilityCode: string,
) {
  const canonicalCode = (code: string) =>
    code.toLowerCase() === "prometheus" ? "grafana" : code.toLowerCase();
  const code = canonicalCode(utilityCode);
  const chart = utilityCatalogue.find((entry) => entry.code === code)?.chart;
  return plans
    .filter(
      (plan) =>
        plan.kind === "UTILITY" &&
        plan.clusterId === clusterId &&
        activeStatuses.has(plan.status) &&
        (plan.managedGroup
          ? plan.managedGroup === chart
          : canonicalCode(plan.utilityCode ?? "") === code),
    )
    .sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt))[0];
}
