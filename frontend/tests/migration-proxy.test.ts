import { describe, expect, it } from "vitest";

import { isAllowedRoute } from "@/shared/api/proxy";

describe("Migration API proxy", () => {
  const id = `MIG-${"a".repeat(32)}`;

  it("allows the assessment workflow", () => {
    expect(isAllowedRoute("POST", ["migrations"])).toBe(true);
    expect(isAllowedRoute("POST", ["migrations", id, "discover"])).toBe(true);
    expect(isAllowedRoute("GET", ["migrations", id, "source-catalogue"])).toBe(
      true,
    );
    expect(isAllowedRoute("GET", ["migrations", id, "source-inventory"])).toBe(
      true,
    );
    expect(isAllowedRoute("GET", ["migrations", id, "assessment"])).toBe(true);
  });

  it("rejects malformed and execution routes", () => {
    expect(
      isAllowedRoute("POST", ["migrations", "MIG-invalid", "discover"]),
    ).toBe(false);
    expect(isAllowedRoute("POST", ["migrations", id, "execute"])).toBe(false);
  });

  it("allows only authenticated source-cluster registration routes", () => {
    const sourceId = `SRC-${"b".repeat(32)}`;

    expect(isAllowedRoute("GET", ["source-clusters"])).toBe(true);
    expect(isAllowedRoute("POST", ["source-clusters"])).toBe(true);
    expect(isAllowedRoute("GET", ["source-clusters", sourceId])).toBe(true);
    expect(isAllowedRoute("PUT", ["source-clusters", sourceId])).toBe(true);
    expect(
      isAllowedRoute("POST", ["source-clusters", sourceId, "enrollments"]),
    ).toBe(true);
    expect(
      isAllowedRoute("POST", ["source-clusters", sourceId, "install"]),
    ).toBe(true);
    expect(
      isAllowedRoute("POST", ["source-clusters", "SRC-invalid", "enrollments"]),
    ).toBe(false);
  });
});
