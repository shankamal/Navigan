import type { Identity } from "@/shared/auth/claims";
import { hasPermission } from "@/shared/auth/permissions";
import type {
  EksUpgradePlan,
  EksUpgradeReadiness,
} from "@/modules/cluster-management/model";

export function planningBlockReason(
  identity: Identity | null,
  evidence: EksUpgradeReadiness | undefined,
  state: {
    readinessPending: boolean;
    readinessError: boolean;
    planPending: boolean;
    planError?: string;
    activePlan?: EksUpgradePlan;
  },
): string | undefined {
  if (!hasPermission(identity, "cluster.upgrade.plan"))
    return "Your current account does not have permission to create upgrade plans.";
  if (state.planPending) return "Loading this cluster’s existing plans…";
  if (state.planError)
    return "Existing plans could not be checked for this cluster. Refresh plans before creating another.";
  if (state.activePlan)
    return "Review the existing active plan before creating another.";
  // Component-only plans remain available when the control plane has no next target
  // or node skew blocks a control-plane upgrade. The scope planner validates live data.
  return undefined;
}

export function rescheduleBlockReason(
  identity: Identity | null,
  plan: EksUpgradePlan,
): string | undefined {
  if (!["DRAFT", "SUBMITTED"].includes(plan.status))
    return "Only a draft or pending request can be rescheduled. Cancel an approved plan and create a new request.";
  if (!hasPermission(identity, "cluster.upgrade.plan"))
    return "An authorized Cloud Engineer must revise the requested maintenance time and resubmit this plan.";
  return undefined;
}
