import { describe, expect, it, vi } from "vitest";
const { redirect } = vi.hoisted(() => ({
  redirect: vi.fn((url: string) => {
    throw new Error(`REDIRECT:${url}`);
  }),
}));
vi.mock("next/navigation", () => ({ redirect }));
vi.mock("@/modules/upgrade-management/upgrade-workspace", () => ({
  UpgradeWorkspace: () => null,
}));
import Page from "../src/app/(workspace)/upgrades/page";

describe("Separated maintenance capability routes", () => {
  it.each(["utilities", "patching"])(
    "redirects legacy %s links and preserves plan/date context",
    async (tab) => {
      await expect(
        Page({
          searchParams: Promise.resolve({
            tab,
            plan: "UPG-test",
            date: "2027-01-01",
          }),
        }),
      ).rejects.toThrow(
        `REDIRECT:/upgrades/${tab}?plan=UPG-test&date=2027-01-01`,
      );
    },
  );
  it("keeps Upgrade Centre and calendar on the existing upgrade route", async () => {
    await expect(
      Page({ searchParams: Promise.resolve({ tab: "schedule" }) }),
    ).resolves.toBeTruthy();
    expect(redirect).not.toHaveBeenCalled();
  });
});
