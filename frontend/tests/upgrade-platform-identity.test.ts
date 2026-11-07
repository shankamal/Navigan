import { describe, expect, it } from "vitest";
import { containerIdentity } from "../src/modules/upgrade-management/platform-identity";

describe("Upgrade platform identity", () => {
  it.each([
    ["EKS", "AWS", "Amazon EKS", true],
    ["ECS", "AWS", "Amazon ECS", false],
    ["AKS", "Azure", "AKS", true],
    ["GKE", "Google Cloud", "GKE", true],
  ])(
    "maps %s to its cloud without classifying ECS as Kubernetes",
    (code, cloud, platform, kubernetes) => {
      const result = containerIdentity(code as string);
      expect(result.cloud.label).toBe(cloud);
      expect(result.platform.label).toBe(platform);
      expect(result.kubernetes).toBe(kubernetes);
    },
  );

  it("retains an explicitly reported cloud for portable distributions", () => {
    const result = containerIdentity("OPENSHIFT", "ON_PREMISES");
    expect(result.cloud.label).toBe("On-premises");
    expect(result.platform.label).toBe("OpenShift");
    expect(result.kubernetes).toBe(true);
    expect(containerIdentity("OPENSHIFT").cloud.label).toBe("Not reported");
  });

  it("does not invent a provider or upgrade adapter for an unknown platform", () => {
    const result = containerIdentity("Custom distribution");
    expect(result.cloud.label).toBe("Not reported");
    expect(result.platform.label).toBe("Custom distribution");
    expect(result.kubernetes).toBe(false);
  });
});
