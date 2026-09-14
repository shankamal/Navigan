import type { Identity } from "@/shared/auth/claims";
import type { Customer, CustomerStatus, WorkflowAction } from "./types";
import { hasPermission } from "@/shared/auth/permissions";
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
  hasPermission(identity, "customer.create");
export const canEdit = (identity: Identity | null, customer: Customer) =>
  Boolean(
    hasPermission(identity, "customer.edit") &&
    ["DRAFT", "REJECTED"].includes(customer.status),
  );
export function allowedActions(
  identity: Identity | null,
  customer: Customer,
): WorkflowAction[] {
  if (!identity) return [];
  if (
    hasPermission(identity, "customer.submit") &&
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
  const canReview = hasPermission(identity, "customer.review");
  const canApprove = hasPermission(identity, "customer.approve");
  if (
    ["SUBMITTED", "UNDER_REVIEW"].includes(customer.status) &&
    [customer.createdBy, customer.submittedBy].includes(identity.subject)
  )
    return [];
  switch (customer.status) {
    case "SUBMITTED":
      return canReview
        ? [{ action: "review/start", label: "Start review" }]
        : [];
    case "UNDER_REVIEW":
      return canApprove
        ? [
        { action: "approve", label: "Approve customer" },
        {
          action: "reject",
          label: "Reject request",
          destructive: true,
          reasonRequired: true,
        },
          ]
        : [];
    case "APPROVED":
      return hasPermission(identity, "customer.activate")
        ? [{ action: "activate", label: "Activate customer" }]
        : [];
    case "ACTIVE":
      return [
        ...(hasPermission(identity, "customer.suspend")
          ? [
        {
          action: "suspend" as const,
          label: "Suspend customer",
          destructive: true,
          reasonRequired: true,
        },
            ]
          : []),
        ...(hasPermission(identity, "customer.deactivate")
          ? [
        {
          action: "deactivate" as const,
          label: "Deactivate customer",
          destructive: true,
          reasonRequired: true,
        },
            ]
          : []),
      ];
    case "SUSPENDED":
      return hasPermission(identity, "customer.suspend")
        ? [{ action: "reactivate", label: "Reactivate customer" }]
        : [];
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
