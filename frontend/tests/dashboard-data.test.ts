import { describe, expect, it } from "vitest";
import {
  allPages,
  runtimeState,
  scheduledChanges,
} from "@/modules/dashboard/dashboard-data";
import type {
  Cluster,
  EksUpgradePlan,
} from "@/modules/cluster-management/model";
import { clusters } from "@/modules/cluster-management/service";
const now = Date.parse("2026-11-16T06:00:00Z");
const cluster = {
  clusterId: "CLU-1",
  customerId: "CUS-1",
  status: "ACTIVE",
} as Cluster;
const inventory = (status = "READY", age = 60000, nodeCount = 3) =>
  ({
    runtimeInventory: {
      status,
      observedAt: new Date(now - age).toISOString(),
      expiresAt: new Date(now + 60000).toISOString(),
      metrics: { nodeCount },
    },
  }) as unknown as Awaited<ReturnType<typeof clusters.platformComponents>>;
describe("Dashboard evidence and maintenance", () => {
  it("never treats an active record or stale telemetry as healthy", () => {
    expect(runtimeState(cluster, undefined, now)).toBe("Unverified");
    expect(runtimeState(cluster, inventory("READY", 360000), now)).toBe(
      "Unverified",
    );
    expect(runtimeState(cluster, inventory("READY", 60000), now)).toBe("Ready");
    expect(runtimeState(cluster, inventory("DEGRADED"), now)).toBe("Degraded");
  });
  it("keeps stopped/verified zero-node clusters paused, without labeling failure", () => {
    expect(
      runtimeState({ ...cluster, status: "STOPPED" }, undefined, now),
    ).toBe("Paused");
    expect(runtimeState(cluster, inventory("READY", 60000, 0), now)).toBe(
      "Paused",
    );
    expect(runtimeState(cluster, inventory("READY", 360000, 0), now)).toBe(
      "Unverified",
    );
  });
  it("rejects expired, invalid and future-dated runtime evidence", () => {
    const i = inventory();
    i.runtimeInventory.expiresAt = "not a date";
    expect(runtimeState(cluster, i, now)).toBe("Unverified");
    expect(runtimeState(cluster, inventory("READY", -60000), now)).toBe(
      "Unverified",
    );
    i.runtimeInventory.expiresAt = new Date(now - 1).toISOString();
    expect(runtimeState(cluster, i, now)).toBe("Unverified");
  });
  it("loads every page, without using the first page as a fleet total", async () => {
    const result = await allPages(async (page) => ({
      items: [page],
      pagination: { totalPages: 3 },
    }));
    expect(result).toEqual([0, 1, 2]);
    await expect(
      allPages(async (page) => {
        if (page) throw Error("offline");
        return { items: [1], pagination: { totalPages: 2 } };
      }),
    ).rejects.toThrow("offline");
  });
  it("filters and sorts actual upcoming windows and keeps approval status", () => {
    const plan = (id: string, status: string, date: string) => ({
      cluster,
      plan: { planId: id, status, scheduledFor: date } as EksUpgradePlan,
    });
    const rows = [
      plan("late", "APPROVED", "2026-11-20T06:00:00Z"),
      plan("review", "SUBMITTED", "2026-11-18T06:00:00Z"),
      plan("cancelled", "CANCELLED", "2026-11-18T06:00:00Z"),
      plan("past", "APPROVED", "2026-11-15T06:00:00Z"),
      plan("invalid", "DRAFT", "bad"),
      plan("far", "SCHEDULED", "2026-12-01T06:00:00Z"),
    ];
    expect(scheduledChanges(rows, 7, now).map((r) => r.plan.planId)).toEqual([
      "review",
      "late",
    ]);
    expect(scheduledChanges(rows, 7, now)[0].plan.status).toBe("SUBMITTED");
    expect(scheduledChanges(rows, 30, now).map((r) => r.plan.planId)).toEqual([
      "review",
      "late",
      "far",
    ]);
  });
  it("uses stage-specific windows without duplicating a parent schedule", () => {
    const p = {
      planId: "p",
      status: "APPROVED",
      scheduledFor: "2026-11-17T06:00:00Z",
      planSpec: {
        steps: [
          {
            window: {
              scheduledFor: "2026-11-18T06:00:00Z",
              durationMinutes: 60,
            },
          },
          {
            window: {
              scheduledFor: "2026-11-19T06:00:00Z",
              durationMinutes: 90,
            },
          },
        ],
      },
    } as EksUpgradePlan;
    const rows = scheduledChanges([{ cluster, plan: p }], 7, now);
    expect(rows.map((r) => r.durationMinutes)).toEqual([60, 90]);
    expect(rows.map((r) => r.step)).toEqual([1, 2]);
  });
});
