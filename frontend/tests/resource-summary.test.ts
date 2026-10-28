// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiClient } from "@/shared/api/client";
import { resourceSummary } from "@/shared/api/summary";
import { isAllowedRoute } from "@/shared/api/proxy";

afterEach(() => vi.restoreAllMocks());

describe("Scoped resource summaries", () => {
  it("only exposes authenticated GET summary paths through the API proxy", () => {
    for (const resource of ["customers", "environments", "clusters"]) {
      expect(isAllowedRoute("GET", [resource, "summary"])).toBe(true);
      expect(isAllowedRoute("POST", [resource, "summary"])).toBe(false);
    }
  });

  it("loads one server aggregate without requesting legacy counts", async () => {
    const request = vi.spyOn(apiClient, "get").mockResolvedValue({
      data: { total: 3, byStatus: { ACTIVE: 2 }, byProvider: { AWS: 3 } },
    });
    const fallback = vi.fn();
    const summary = await resourceSummary(
      "customers",
      ["ACTIVE"],
      ["AWS"],
      fallback,
    );
    expect(request).toHaveBeenCalledOnce();
    expect(fallback).not.toHaveBeenCalled();
    expect(summary.total).toBe(3);
  });

  it("falls back only for unavailable summary routes", async () => {
    vi.spyOn(apiClient, "get").mockRejectedValue(
      new ApiError("Missing", 404, "ROUTE_NOT_FOUND"),
    );
    const fallback = vi.fn(async (status?: string, provider?: string) =>
      status ? 2 : provider ? 1 : 3,
    );
    expect(
      await resourceSummary("environments", ["ACTIVE"], ["AWS"], fallback),
    ).toEqual({
      total: 3,
      byStatus: { ACTIVE: 2 },
      byProvider: { AWS: 1 },
    });
    expect(fallback).toHaveBeenCalledTimes(3);
  });

  it("never hides authorization failures behind fallback requests", async () => {
    vi.spyOn(apiClient, "get").mockRejectedValue(
      new ApiError("Forbidden", 403, "FORBIDDEN"),
    );
    const fallback = vi.fn();
    await expect(
      resourceSummary("clusters", [], [], fallback),
    ).rejects.toMatchObject({ status: 403 });
    expect(fallback).not.toHaveBeenCalled();
  });
});
