import { describe, it, expect } from "vitest";
import { hasPermission } from "../src/shared/auth/permissions";
import type { Identity } from "../src/shared/auth/claims";
describe("upgrade maker and reviewer roles", () => {
  it("lets an engineer plan without granting provisioning or approval", () => {
    const identity = {
      subject: "suhas",
      roles: ["CLOUD_ENGINEER"],
    } as Identity;
    expect(hasPermission(identity, "cluster.upgrade.plan")).toBe(true);
    expect(hasPermission(identity, "cluster.upgrade.approve")).toBe(false);
    expect(hasPermission(identity, "cluster.plan")).toBe(false);
    expect(hasPermission(identity, "cluster.apply")).toBe(false);
  });
  it("lets an architect approve while honoring explicit dynamic permissions", () => {
    const identity = {
      subject: "reviewer",
      roles: ["PLATFORM_ARCHITECT"],
    } as Identity;
    expect(hasPermission(identity, "cluster.upgrade.approve")).toBe(true);
    expect(hasPermission(identity, "cluster.upgrade.plan")).toBe(false);
    expect(
      hasPermission({ ...identity, privileges: [] }, "cluster.upgrade.approve"),
    ).toBe(false);
  });
});
