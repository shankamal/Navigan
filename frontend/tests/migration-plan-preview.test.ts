import { describe, expect, it } from "vitest";
import { buildMigrationPlanPreview } from "../src/modules/migration-management/migration-plan-preview";

describe("migration plan preview", () => {
  it("lists workload prerequisites but never invents an execution sequence", () => {
    const preview = buildMigrationPlanPreview([
      {
        resource: {
          apiVersion: "apps/v1",
          kind: "Deployment",
          namespace: "retailflow",
          name: "api",
        },
        status: "PENDING_EVIDENCE",
        sourceStatus: "REMEDIATION_REQUIRED",
        targetStatus: "PENDING_EVIDENCE",
        checks: [
          {
            capability: "Source",
            status: "REMEDIATION_REQUIRED",
            reason: "Update needed",
            nextAction: "Fix",
          },
          {
            capability: "Kubernetes API",
            status: "PENDING_EVIDENCE",
            reason: "Unknown",
            nextAction: "Discover",
          },
        ],
      },
      {
        resource: {
          apiVersion: "v1",
          kind: "ServiceAccount",
          namespace: "retailflow",
          name: "api",
        },
        status: "PENDING_EVIDENCE",
        checks: [],
      },
    ]);
    expect(preview.workloads).toHaveLength(1);
    expect(preview.remediationCount).toBe(1);
    expect(preview.verificationCount).toBe(1);
    expect(preview.workloads[0].sourceStatus).toBe("REMEDIATION_REQUIRED");
    expect(preview.executionReady).toBe(false);
    expect(preview.note).toContain("unordered");
    expect("waves" in preview).toBe(false);
  });
  it("an empty evaluation list cannot produce an executable plan", () => {
    const preview = buildMigrationPlanPreview([]);
    expect(preview.workloads).toEqual([]);
    expect(preview.executionReady).toBe(false);
  });
});
