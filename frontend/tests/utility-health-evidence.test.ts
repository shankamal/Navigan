import { describe, expect, it } from "vitest";
import { falcoHealthEvidence } from "../src/modules/upgrade-management/utility-health-evidence";
const now = Date.parse("2026-11-16T12:00:00Z");
const snapshot = (desired = 2, ready = 1) =>
  ({
    runtimeInventory: {
      status: "DEGRADED",
      observedAt: new Date(now - 60_000).toISOString(),
      expiresAt: new Date(now + 60_000).toISOString(),
      resources: [
        {
          kind: "DaemonSet",
          namespace: "navigan-security",
          name: "navigan-falco",
          desired,
          ready,
          status: "Degraded",
        },
      ],
      warningEvents: [
        {
          namespace: "navigan-security",
          resourceName: "navigan-falco-abc",
          reason: "FailedScheduling",
          message: "Node selector did not match",
          lastObservedAt: new Date(now - 30_000).toISOString(),
        },
      ],
    },
  }) as unknown as NonNullable<Parameters<typeof falcoHealthEvidence>[0]>;
describe("Falco health evidence", () => {
  it("reports actual readiness and warnings without replacing Argo health", () => {
    expect(falcoHealthEvidence(snapshot(), now).join(" ")).toContain(
      "1/2 pods ready",
    );
    expect(falcoHealthEvidence(snapshot(), now).join(" ")).toContain(
      "FailedScheduling",
    );
  });
  it("does not call zero desired pods healthy", () => {
    expect(falcoHealthEvidence(snapshot(0, 0), now)[0]).toContain(
      "readiness has not been established",
    );
  });
  it("rejects stale runtime evidence", () => {
    const value = snapshot();
    value.runtimeInventory.expiresAt = new Date(now - 1).toISOString();
    expect(falcoHealthEvidence(value, now)).toEqual([
      expect.stringContaining("Fresh runtime evidence is unavailable"),
    ]);
  });
  it("does not infer absence from incomplete inventory", () => {
    const value = snapshot();
    value.runtimeInventory.resources = [];
    value.runtimeInventory.warningEvents = [];
    expect(falcoHealthEvidence(value, now)[0]).toContain(
      "not proof that Falco is absent",
    );
  });
});
