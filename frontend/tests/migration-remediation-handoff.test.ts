import { describe, expect, it } from "vitest";
import { buildRemediationHandoff } from "../src/modules/migration-management/remediation-handoff";

describe("compatibility remediation handoff", () => {
  const resource = {
    apiVersion: "apps/v1",
    kind: "Deployment",
    namespace: "retailflow",
    name: "api",
  };
  it("separates required fixes from evidence checks", () => {
    const result = buildRemediationHandoff([
      {
        resource,
        status: "PENDING_EVIDENCE",
        checks: [
          {
            capability: "Source",
            status: "REMEDIATION_REQUIRED",
            reason: "Change needed",
            nextAction: "Fix config",
          },
          {
            capability: "Kubernetes API",
            status: "PENDING_EVIDENCE",
            reason: "Discovery missing",
            nextAction: "Verify API",
          },
          {
            capability: "Identity",
            status: "NOT_VERIFIED",
            reason: "Permissions unknown",
            nextAction: "Check RBAC",
          },
        ],
      },
    ]);
    expect(result.actions).toHaveLength(1);
    expect(result.evidence).toHaveLength(2);
    expect(result.executionReady).toBe(false);
  });
  it("does not invent fixes or dependencies for unverified evaluations", () => {
    const result = buildRemediationHandoff([
      {
        resource,
        status: "PENDING_EVIDENCE",
        checks: [
          {
            capability: "Storage",
            status: "PENDING_EVIDENCE",
            reason: "Unknown",
            nextAction: "Verify CSI",
          },
        ],
      },
    ]);
    expect(result.actions).toHaveLength(0);
    expect(result.evidence[0].nextAction).toBe("Verify CSI");
    expect(result.executionReady).toBe(false);
  });
});
