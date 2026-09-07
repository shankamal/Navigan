import type { Identity } from "@/shared/auth/claims";
import type { Customer, CustomerStatus, WorkflowAction } from "./types";
export const statusLabels: Record<CustomerStatus, string> = {
  DRAFT: "Draft",
  SUBMITTED: "Submitted",
  UNDER_REVIEW: "Under review",
  APPROVED: "Approved",
  REJECTED: "Rejected",
  ACTIVE: "Active",
  SUSPENDED: "Suspended",
  DEACTIVATED: "Deactivated",
};
// Configured initial database catalog; OTHER is optional in the specification and is not seeded.
export const cloudProviders = [
  { code: "AWS", name: "Amazon Web Services", shortName: "AWS" },
  { code: "AZURE", name: "Microsoft Azure", shortName: "Azure" },
  { code: "GCP", name: "Google Cloud", shortName: "GCP" },
  { code: "OCI", name: "Oracle Cloud Infrastructure", shortName: "OCI" },
];
export const canCreate = (identity: Identity | null) =>
  Boolean(identity?.roles.includes("CLOUD_ENGINEER") && identity.canCreate);
export const canEdit = (identity: Identity | null, customer: Customer) =>
  Boolean(
    identity?.roles.includes("CLOUD_ENGINEER") &&
    ["DRAFT", "REJECTED"].includes(customer.status),
  );
export function allowedActions(
  identity: Identity | null,
  customer: Customer,
): WorkflowAction[] {
  if (!identity) return [];
  if (
    identity.roles.includes("CLOUD_ENGINEER") &&
    ["DRAFT", "REJECTED"].includes(customer.status)
  )
    return [
      {
        action: customer.status === "REJECTED" ? "resubmit" : "submit",
        label:
          customer.status === "REJECTED"
            ? "Resubmit for review"
            : "Submit for review",
      },
    ];
  if (!identity.roles.includes("PLATFORM_ARCHITECT")) return [];
  if (
    ["SUBMITTED", "UNDER_REVIEW"].includes(customer.status) &&
    [customer.createdBy, customer.submittedBy].includes(identity.subject)
  )
    return [];
  switch (customer.status) {
    case "SUBMITTED":
      return [{ action: "review/start", label: "Start review" }];
    case "UNDER_REVIEW":
      return [
        { action: "approve", label: "Approve customer" },
        {
          action: "reject",
          label: "Reject request",
          destructive: true,
          reasonRequired: true,
        },
      ];
    case "APPROVED":
      return [{ action: "activate", label: "Activate customer" }];
    case "ACTIVE":
      return [
        {
          action: "suspend",
          label: "Suspend customer",
          destructive: true,
          reasonRequired: true,
        },
        {
          action: "deactivate",
          label: "Deactivate customer",
          destructive: true,
          reasonRequired: true,
        },
      ];
    case "SUSPENDED":
      return [{ action: "reactivate", label: "Reactivate customer" }];
    default:
      return [];
  }
}
export const submissionMissing = (customer: Customer): string[] =>
  [
    customer.cloudProviders.length ? "" : "Select at least one cloud provider.",
    customer.contacts.some((c) => c.type === "PRIMARY")
      ? ""
      : "Add a primary contact.",
  ].filter(Boolean);
