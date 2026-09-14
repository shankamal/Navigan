import type { Identity } from "@/shared/auth/claims";
import type { Action, Environment } from "./types";
import { hasPermission } from "@/shared/auth/permissions";
export function allowedActions(
  environment: Environment,
  identity: Identity | null,
): Action[] {
  const author = hasPermission(identity, "environment.submit");
  switch (environment.status) {
    case "DRAFT":
      return author ? ["submit"] : [];
    case "REJECTED":
      return author ? ["resubmit"] : [];
    case "SUBMITTED":
      return hasPermission(identity, "environment.approve")
        ? ["approve", "reject"]
        : [];
    case "UNDER_REVIEW":
      return hasPermission(identity, "environment.approve")
        ? ["approve", "reject"]
        : [];
    case "APPROVED":
      return hasPermission(identity, "environment.activate")
        ? ["activate"]
        : [];
    case "ACTIVE":
      return [
        ...(hasPermission(identity, "environment.revision.manage")
          ? (["revise"] as Action[])
          : []),
        ...(hasPermission(identity, "environment.suspend")
          ? (["suspend"] as Action[])
          : []),
        ...(hasPermission(identity, "environment.deactivate")
          ? (["deactivate"] as Action[])
          : []),
      ];
    case "SUSPENDED":
      return hasPermission(identity, "environment.suspend")
        ? ["reactivate"]
        : [];
    default:
      return [];
  }
}
export const labels: Record<Action, string> = {
  revise: "Create new revision",
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
