import { describe, expect, it } from "vitest";
import { clusterSchema, type ClusterInput } from "@/modules/cluster-management/model";
import { isAllowedRoute } from "@/shared/api/proxy";

describe("Cluster API contract", () => {
  it("allows only the documented cluster routes", () => {
    expect(isAllowedRoute("POST", ["clusters"])).toBe(true);
    expect(isAllowedRoute("POST", ["clusters", "CLU-demo", "plan"])).toBe(true);
    expect(isAllowedRoute("POST", ["clusters", "CLU-demo", "apply"])).toBe(true);
    expect(isAllowedRoute("DELETE", ["clusters", "CLU-demo"])).toBe(false);
    expect(isAllowedRoute("POST", ["clusters", "CLU-demo", "destroy"])).toBe(false);
  });

  it("requires the pinned approved environment version", () => {
    expect(() => clusterSchema.parse({
      clusterId: "CLU-demo", customerId: "CUS-demo", environmentId: "ENV-demo",
      platform: "EKS", clusterName: "demo", status: "DRAFT", version: 1,
      createdAt: "2026-09-10T00:00:00Z", updatedAt: "2026-09-10T00:00:00Z",
    })).toThrow();
  });

  it("keeps platform setup behind the API proxy", () => {
    expect(isAllowedRoute("POST", ["clusters"])).toBe(true);
    expect(isAllowedRoute("POST", ["clusters", "CLU-demo", "approve"])).toBe(true);
    expect(isAllowedRoute("POST", ["clusters", "CLU-demo", "apply"])).toBe(true);
  });

  it("no longer carries technical cluster fields in the create payload", () => {
    const body: ClusterInput = {
      environmentId: "ENV-demo",
      environmentApprovedVersion: 3,
      blueprintName: "default",
      clusterName: "demo",
    };
    expect(Object.keys(body).sort()).toEqual(
      [
        "blueprintName",
        "clusterName",
        "environmentApprovedVersion",
        "environmentId",
      ].sort(),
    );
  });
});
