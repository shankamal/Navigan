import { describe, it, expect } from "vitest";
import {
  allowedActions,
  canCreate,
  canEdit,
  submissionMissing,
} from "@/modules/customer-management/model/policy";
import {
  createSchema,
  updateSchema,
  listSchema,
} from "@/modules/customer-management/model/types";
import { identityFromClaims } from "@/shared/auth/claims";
import { customer, engineer, architect } from "./fixtures";
describe("Customer lifecycle affordances", () => {
  it("matches all permitted lifecycle transitions", () => {
    expect(allowedActions(engineer, customer).map((x) => x.action)).toEqual([
      "submit",
    ]);
    expect(
      allowedActions(engineer, { ...customer, status: "REJECTED" }).map(
        (x) => x.action,
      ),
    ).toEqual(["resubmit"]);
    expect(
      allowedActions(architect, { ...customer, status: "SUBMITTED" }).map(
        (x) => x.action,
      ),
    ).toEqual(["review/start"]);
    expect(
      allowedActions(architect, { ...customer, status: "UNDER_REVIEW" }).map(
        (x) => x.action,
      ),
    ).toEqual(["approve", "reject"]);
    expect(
      allowedActions(architect, { ...customer, status: "APPROVED" }).map(
        (x) => x.action,
      ),
    ).toEqual(["activate"]);
    expect(
      allowedActions(architect, { ...customer, status: "ACTIVE" }).map(
        (x) => x.action,
      ),
    ).toEqual(["suspend", "deactivate"]);
    expect(
      allowedActions(architect, { ...customer, status: "SUSPENDED" }).map(
        (x) => x.action,
      ),
    ).toEqual(["reactivate"]);
    expect(
      allowedActions(architect, { ...customer, status: "DEACTIVATED" }),
    ).toEqual([]);
  });
  it("requires an independent reviewer for both creator and submitter", () => {
    expect(
      allowedActions(
        { ...engineer, roles: ["CLOUD_ENGINEER", "PLATFORM_ARCHITECT"] },
        { ...customer, status: "UNDER_REVIEW" },
      ),
    ).toEqual([]);
    expect(
      allowedActions(architect, {
        ...customer,
        status: "SUBMITTED",
        submittedBy: architect.subject,
      }),
    ).toEqual([]);
  });
  it("prevents edits outside draft/rejected and requires creation entitlement", () => {
    expect(canEdit(engineer, { ...customer, status: "ACTIVE" })).toBe(false);
    expect(canEdit(architect, customer)).toBe(false);
    expect(canCreate({ ...engineer, canCreate: false })).toBe(false);
    expect(canCreate(engineer)).toBe(true);
  });
  it("requires a primary contact and provider before submission", () => {
    expect(
      submissionMissing({ ...customer, contacts: [], cloudProviders: [] }),
    ).toHaveLength(2);
    expect(submissionMissing(customer)).toEqual([]);
  });
  it("parses JSON-array and space-separated custom role claims", () => {
    expect(
      identityFromClaims({
        sub: "u",
        roles: '["CLOUD_ENGINEER"]',
        customer_create: "true",
      }).canCreate,
    ).toBe(true);
    expect(
      identityFromClaims({ roles: "CLOUD_ENGINEER UNKNOWN" }).roles,
    ).toEqual(["CLOUD_ENGINEER"]);
    expect(identityFromClaims({ roles: "[invalid" }).roles).toEqual([]);
  });
});
describe("API validation", () => {
  it("allows an incomplete draft but rejects extra status fields", () => {
    const input = {
      name: " Acme ",
      description: null,
      contacts: [],
      cloudProviders: [],
    };
    expect(createSchema.parse(input).name).toBe("Acme");
    expect(createSchema.safeParse({ ...input, status: "ACTIVE" }).success).toBe(
      false,
    );
    expect(
      createSchema.safeParse({ ...input, cloudProviders: ["AWS", "AWS"] })
        .success,
    ).toBe(false);
  });
  it("keeps providers out of the master update payload", () => {
    expect(
      updateSchema.safeParse({
        name: "Acme",
        description: null,
        contacts: [],
        cloudProviders: ["AWS"],
      }).success,
    ).toBe(false);
  });
  it("rejects malformed or unexpected API response shapes", () => {
    expect(listSchema.safeParse({ data: [] }).success).toBe(false);
  });
});
