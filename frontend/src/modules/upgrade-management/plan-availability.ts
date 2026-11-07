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
  if (!hasPermission(identity, "cluster.plan"))
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
  if (identity?.subject !== plan.createdBy)
    return `Only the plan creator, ${plan.createdByName || plan.createdBy}, can change its schedule. You are signed in as ${identity?.displayName || identity?.subject || "another user"}.`;
  if (!hasPermission(identity, "cluster.plan"))
    return "You created this plan, but your current account no longer has permission to reschedule it. Contact your platform administrator.";
  return undefined;
}
