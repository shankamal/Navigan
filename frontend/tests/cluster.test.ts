import { describe, expect, it } from "vitest";
import { clusterSchema, type ClusterInput } from "@/modules/cluster-management/model";
import { isAllowedRoute } from "@/shared/api/proxy";

describe("Cluster API contract", () => {
  it("allows only the documented cluster routes", () => {
    expect(isAllowedRoute("POST", ["clusters"])).toBe(true);
    expect(isAllowedRoute("POST", ["clusters", "CLU-demo", "plan"])).toBe(true);
    expect(isAllowedRoute("POST", ["clusters", "CLU-demo", "apply"])).toBe(true);
    expect(isAllowedRoute("POST", ["clusters", "CLU-demo", "stop"])).toBe(true);
    expect(isAllowedRoute("POST", ["clusters", "CLU-demo", "start"])).toBe(true);
    expect(isAllowedRoute("POST", ["clusters", "CLU-demo", "delete"])).toBe(true);
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

  it("owns cluster configuration independently of the environment baseline", () => {
    const body: ClusterInput = {
      environmentId: "ENV-demo",
      environmentApprovedVersion: 3,
      clusterName: "demo",
      kubernetesVersion: "1.35",
      endpointAccess: "PRIVATE",
      nodeGroups: [{
        name: "general",
        instanceTypes: ["m7i.large"],
        capacityType: "ON_DEMAND",
        minSize: 1,
        desiredSize: 1,
        maxSize: 2,
        diskSizeGiB: 50,
      }],
      provisioningRoleArn:
        "arn:aws:iam::123456789012:role/NaviganProvisioningRole",
      externalIdSecretArn:
        "arn:aws:secretsmanager:ap-south-1:123456789012:secret:navigan/provisioning/demo",
    };
    expect(body).not.toHaveProperty("blueprintName");
    expect(body.nodeGroups[0].desiredSize).toBe(1);
  });
});
