import { describe, expect, it } from "vitest";
import {
  inspectTargetCapabilitySnapshot,
  type TargetCapabilitySnapshot,
} from "@/modules/migration-management/target-capabilities";

const now = Date.parse("2026-10-11T15:00:00Z");
const snapshot: TargetCapabilitySnapshot = {
  schemaVersion: 1,
  platform: "EKS",
  targetId: "CLU-test",
  observedAt: "2026-10-11T14:45:00Z",
  source: "READ_ONLY_ADAPTER",
  storageClasses: [
    {
      name: "gp3",
      provisioner: "ebs.csi.aws.com",
      verified: true,
      accessModes: ["ReadWriteOnce"],
    },
  ],
};
describe("target capability snapshot evidence", () => {
  it("rejects missing evidence and mismatched target identity", () => {
    expect(
      inspectTargetCapabilitySnapshot(null, "EKS", "CLU-test", now).status,
    ).toBe("UNAVAILABLE");
    expect(
      inspectTargetCapabilitySnapshot(snapshot, "EKS", "CLU-other", now).status,
    ).toBe("INVALID");
    expect(
      inspectTargetCapabilitySnapshot(snapshot, "AKS", "CLU-test", now).status,
    ).toBe("INVALID");
  });
  it("rejects expired and future-dated observations", () => {
    expect(
      inspectTargetCapabilitySnapshot(
        snapshot,
        "EKS",
        "CLU-test",
        now + 7200000,
      ).status,
    ).toBe("STALE");
    expect(
      inspectTargetCapabilitySnapshot(
        { ...snapshot, observedAt: "2026-10-11T15:20:00Z" },
        "EKS",
        "CLU-test",
        now,
      ).status,
    ).toBe("INVALID");
  });
  it("allows current target-bound read-only evidence and retains verified flags", () => {
    const result = inspectTargetCapabilitySnapshot(
      snapshot,
      "EKS",
      "CLU-test",
      now,
    );
    expect(result.status).toBe("CURRENT");
    expect(result.evidence?.storageClasses[0].verified).toBe(true);
  });
});
