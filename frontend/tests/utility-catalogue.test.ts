import { describe, expect, it } from "vitest";
import { utilityRows } from "../src/modules/upgrade-management/utility-catalogue";

const now = Date.parse("2026-11-16T12:00:00Z");
const component = (code: string, overrides = {}) => ({
  componentCode: code,
  status: "READY" as const,
  version: "89.2.4",
  syncStatus: "Synced",
  healthStatus: "Healthy",
  observedAt: new Date(now - 60_000).toISOString(),
  sourceRevision: 1,
  ...overrides,
});

describe("System utility inventory evidence", () => {
  it("groups Grafana and Prometheus by their shared package", () => {
    const rows = utilityRows(
      [component("grafana"), component("prometheus")],
      now,
    );
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      name: "Monitoring stack",
      memberCount: 2,
      status: "Healthy",
      healthy: true,
    });
  });
  it("does not claim healthy when a monitoring peer is missing or versions differ", () => {
    expect(utilityRows([component("grafana")], now)[0].status).toBe(
      "Needs verification",
    );
    expect(
      utilityRows(
        [component("grafana"), component("prometheus", { version: "90.0.0" })],
        now,
      )[0],
    ).toMatchObject({ version: "Conflicting evidence", healthy: false });
  });
  it("marks stale, missing and future observations unverified", () => {
    for (const observedAt of [
      null,
      "invalid",
      new Date(now - 901_000).toISOString(),
      new Date(now + 61_000).toISOString(),
    ]) {
      expect(
        utilityRows([component("headlamp", { observedAt })], now)[0],
      ).toMatchObject({ status: "Unverified", healthy: false });
    }
  });
  it("keeps unknown utilities visible and does not invent an adapter", () => {
    expect(utilityRows([component("customer-tool")], now)[0]).toMatchObject({
      name: "customer-tool",
      planning: false,
    });
  });
  it("does not count missing version evidence as a reported installation", () => {
    expect(
      utilityRows(
        [component("headlamp", { version: null, status: "MISSING" })],
        now,
      )[0],
    ).toMatchObject({
      version: "Not reported",
      reported: false,
      status: "Not reported",
      healthy: false,
    });
  });
});
