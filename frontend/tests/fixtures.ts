import type { Customer } from "@/modules/customer-management/model/types";
import type { Identity } from "@/shared/auth/claims";
export const engineer: Identity = {
  subject: "engineer-1",
  displayName: "Cloud Engineer",
  roles: ["CLOUD_ENGINEER"],
  canCreate: true,
  platformScope: true,
  customerIds: [],
};
export const architect: Identity = {
  ...engineer,
  subject: "architect-1",
  displayName: "Platform Architect",
  roles: ["PLATFORM_ARCHITECT"],
  canCreate: false,
};
export const customer: Customer = {
  customerId: "CUS-test-123",
  onboardingRequestId: "ONB-test-123",
  name: "Example Corporation",
  description: "Test customer",
  status: "DRAFT",
  cloudProviders: ["AWS", "AZURE"],
  contacts: [
    { type: "PRIMARY", name: "Test Contact", email: "test@example.com" },
  ],
  version: 4,
  createdBy: engineer.subject,
  createdAt: "2026-09-01T10:00:00Z",
};
