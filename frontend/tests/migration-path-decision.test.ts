import { describe, expect, it } from "vitest";
import { determineMigrationPath } from "@/modules/migration-management/migration-path-decision";
import type { CompatibilityResult } from "@/modules/migration-management/compatibility-intelligence";
const check = (status: CompatibilityResult["status"]): CompatibilityResult => ({
  id: "test",
  resource: "ns/app",
  capability: "target",
  status,
  reason: "evidence",
  nextAction: "review",
  evidence: "OBSERVED",
});
describe("migration path evidence gates", () => {
  it("rejects missing and incomplete target evidence", () => {
    expect(
      determineMigrationPath({
        targetEvidence: "UNAVAILABLE",
        coverageComplete: true,
        checks: [check("COMPATIBLE")],
      }).path,
    ).toBe("PENDING_EVIDENCE");
    expect(
      determineMigrationPath({
        targetEvidence: "CURRENT",
        coverageComplete: false,
        checks: [check("COMPATIBLE")],
      }).path,
    ).toBe("PENDING_EVIDENCE");
    expect(
      determineMigrationPath({
        targetEvidence: "CURRENT",
        coverageComplete: true,
        checks: [],
      }).path,
    ).toBe("PENDING_EVIDENCE");
  });
  it("classifies blocked, assisted and direct paths from complete evidence", () => {
    const base = { targetEvidence: "CURRENT" as const, coverageComplete: true };
    expect(
      determineMigrationPath({
        ...base,
        checks: [check("COMPATIBLE"), check("INCOMPATIBLE")],
      }).path,
    ).toBe("BLOCKED");
    expect(
      determineMigrationPath({ ...base, checks: [check("REVIEW_REQUIRED")] })
        .path,
    ).toBe("ASSISTED");
    expect(
      determineMigrationPath({ ...base, checks: [check("COMPATIBLE")] }).path,
    ).toBe("DIRECT");
    expect(
      determineMigrationPath({ ...base, checks: [check("UNKNOWN")] }).path,
    ).toBe("PENDING_EVIDENCE");
  });
});
