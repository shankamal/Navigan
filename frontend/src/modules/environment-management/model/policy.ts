import type { Identity } from "@/shared/auth/claims";
import type { Action, Environment } from "./types";
export function allowedActions(
  environment: Environment,
  identity: Identity | null,
): Action[] {
  const engineer = identity?.roles.includes("CLOUD_ENGINEER");
  const architect = identity?.roles.includes("PLATFORM_ARCHITECT");
  const author = engineer || architect;
  switch (environment.status) {
    case "DRAFT":
      return author ? ["submit"] : [];
    case "REJECTED":
      return author ? ["resubmit"] : [];
    case "SUBMITTED":
      return architect ? ["review"] : [];
    case "UNDER_REVIEW":
      return architect ? ["approve", "reject"] : [];
    case "APPROVED":
      return architect ? ["activate"] : [];
    case "ACTIVE":
      return architect ? ["suspend", "deactivate"] : [];
    case "SUSPENDED":
      return architect ? ["reactivate"] : [];
    default:
      return [];
  }
}
export const labels: Record<Action, string> = {
  submit: "Submit for review",
  resubmit: "Resubmit",
  review: "Start review",
  approve: "Approve",
  reject: "Reject",
  activate: "Activate",
  suspend: "Suspend",
  reactivate: "Reactivate",
  deactivate: "Deactivate",
};
