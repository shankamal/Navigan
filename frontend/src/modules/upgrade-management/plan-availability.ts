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
  if (state.readinessPending) return "Refreshing provider readiness evidence…";
  if (state.readinessError || !evidence)
    return "Provider readiness is unavailable. Refresh evidence to retry.";
  if (!evidence.recommendedTarget)
    return "The provider has not reported a supported next version.";
  if (evidence.readiness.status !== "READY")
    return "Resolve the provider readiness findings before creating a plan.";
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
