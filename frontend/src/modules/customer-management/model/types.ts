import { z } from "zod";
export const statuses = [
  "DRAFT",
  "SUBMITTED",
  "UNDER_REVIEW",
  "APPROVED",
  "REJECTED",
  "ACTIVE",
  "SUSPENDED",
  "DEACTIVATED",
] as const;
export type CustomerStatus = (typeof statuses)[number];
export const contactTypes = [
  "PRIMARY",
  "TECHNICAL",
  "BUSINESS",
  "SECURITY",
  "ESCALATION",
] as const;
export const statusSchema = z.enum(statuses);
export const contactSchema = z.object({
  type: z.enum(contactTypes),
  name: z.string().trim().min(1, "Enter the contact name.").max(255),
  email: z
    .string()
    .trim()
    .email("Enter a valid email address.")
    .max(255)
    .nullable()
    .optional(),
  phone: z.string().trim().max(50).nullable().optional(),
});
export interface Contact extends z.infer<typeof contactSchema> {}
const providers = z
  .array(z.string().regex(/^[A-Z][A-Z0-9_]{0,49}$/))
  .max(100)
  .refine(
    (items) => new Set(items).size === items.length,
    "Select each provider once.",
  );
export const updateSchema = z
  .object({
    name: z.string().trim().min(1, "Enter the customer name.").max(255),
    description: z.string().trim().max(2000).nullable(),
    contacts: z.array(contactSchema).max(100),
  })
  .strict();
export const createSchema = updateSchema.extend({ cloudProviders: providers });
export interface CreateCustomerInput extends z.infer<typeof createSchema> {}
export interface UpdateCustomerInput extends z.infer<typeof updateSchema> {}
export const summarySchema = z.object({
  customerId: z.string(),
  name: z.string(),
  status: statusSchema,
  version: z.number().int().positive(),
  cloudProviders: z.array(z.string()),
  createdAt: z.string().nullable().optional(),
  updatedAt: z.string().nullable().optional(),
});
const nullableText = z.string().nullable().optional();
export const customerSchema = summarySchema.extend({
  onboardingRequestId: z.string(),
  description: nullableText,
  contacts: z.array(contactSchema),
  reviewCycle: z.number().optional(),
  createdBy: nullableText,
  updatedBy: nullableText,
  submittedBy: nullableText,
  submittedAt: nullableText,
  approvedBy: nullableText,
  approvedAt: nullableText,
  rejectedBy: nullableText,
  rejectedAt: nullableText,
  activatedBy: nullableText,
  activatedAt: nullableText,
  suspendedBy: nullableText,
  suspendedAt: nullableText,
  reactivatedBy: nullableText,
  reactivatedAt: nullableText,
  deactivatedBy: nullableText,
  deactivatedAt: nullableText,
  rejectionReason: nullableText,
  suspensionReason: nullableText,
  deactivationReason: nullableText,
});
export interface Customer extends z.infer<typeof customerSchema> {}
export interface CustomerSummary extends z.infer<typeof summarySchema> {}
export const paginationSchema = z.object({
  page: z.number().int().nonnegative(),
  pageSize: z.number().int().nonnegative(),
  totalElements: z.number().int().nonnegative(),
  totalPages: z.number().int().nonnegative(),
});
export interface Pagination extends z.infer<typeof paginationSchema> {}
export const listSchema = z.object({
  items: z.array(summarySchema),
  pagination: paginationSchema,
});
export interface CustomerList extends z.infer<typeof listSchema> {}
export const providerSetSchema = z.object({
  customerId: z.string(),
  version: z.number().int().positive(),
  cloudProviders: z.array(z.string()),
});
export const historySchema = z.object({
  customerId: z.string(),
  pagination: paginationSchema,
  history: z.array(
    z.object({
      historyId: z.number(),
      customerId: z.string(),
      fromStatus: statusSchema.nullable(),
      toStatus: statusSchema,
      changedBy: z.string(),
      changedAt: z.string(),
      reason: nullableText,
      comments: nullableText,
      correlationId: z.string(),
    }),
  ),
});
export const reviewsSchema = z.object({
  customerId: z.string(),
  pagination: paginationSchema,
  items: z.array(
    z.object({
      reviewId: z.string(),
      customerId: z.string(),
      reviewCycle: z.number(),
      reviewerId: z.string(),
      reviewStatus: z.string(),
      reviewedAt: z.string(),
      comments: nullableText,
      rejectionReason: nullableText,
    }),
  ),
});
export const auditSchema = z.object({
  customerId: z.string(),
  pagination: paginationSchema,
  items: z.array(
    z.object({
      auditId: z.number(),
      customerId: z.string(),
      action: z.string(),
      performedBy: z.string(),
      performedAt: z.string(),
      source: z.string(),
      correlationId: z.string(),
      oldValue: z.unknown(),
      newValue: z.unknown(),
    }),
  ),
});
export interface CustomerFilters {
  page: number;
  pageSize: number;
  search?: string;
  status?: CustomerStatus;
  cloudProvider?: string;
  createdBy?: string;
  sort: `${"name" | "createdAt" | "updatedAt" | "status"},${"asc" | "desc"}`;
}
export type CustomerAction =
  | "submit"
  | "resubmit"
  | "review/start"
  | "approve"
  | "reject"
  | "activate"
  | "suspend"
  | "reactivate"
  | "deactivate";
export interface ActionInput {
  reason?: string;
  comments?: string;
}
export type HistoryKind = "status-history" | "reviews" | "audit-log";
export interface WorkflowAction {
  action: CustomerAction;
  label: string;
  destructive?: boolean;
  reasonRequired?: boolean;
}
