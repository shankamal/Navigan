import { describe, expect, it } from "vitest";
import {
  clusterSchema,
  executionLogsSchema,
  kubernetesAccessSchema,
  clusterNamespaceInventorySchema,
  type ClusterInput,
} from "@/modules/cluster-management/model";
import { isAllowedRoute } from "@/shared/api/proxy";

describe("Cluster API contract", () => {
  it("allows only the documented cluster routes", () => {
    expect(isAllowedRoute("POST", ["clusters"])).toBe(true);
    expect(isAllowedRoute("POST", ["clusters", "CLU-demo", "plan"])).toBe(true);
    expect(isAllowedRoute("POST", ["clusters", "CLU-demo", "apply"])).toBe(true);
    expect(isAllowedRoute("POST", ["clusters", "CLU-demo", "stop"])).toBe(true);
    expect(isAllowedRoute("POST", ["clusters", "CLU-demo", "start"])).toBe(true);
    expect(isAllowedRoute("POST", ["clusters", "CLU-demo", "delete"])).toBe(true);
    expect(
      isAllowedRoute("POST", [
        "clusters",
        "CLU-demo",
        "migrate-system-node-group",
      ]),
    ).toBe(true);
    expect(
      isAllowedRoute("GET", ["clusters", "CLU-demo", "node-groups"]),
    ).toBe(true);
    expect(
      isAllowedRoute("POST", ["clusters", "CLU-demo", "node-groups"]),
    ).toBe(true);
    expect(
      isAllowedRoute("POST", [
        "clusters",
        "CLU-demo",
        "node-groups",
        "KNG-0123456789abcdef0123456789abcdef",
        "submit",
      ]),
    ).toBe(true);
    expect(
      isAllowedRoute("GET", [
        "clusters",
        "CLU-demo",
        "node-groups",
        "KNG-0123456789abcdef0123456789abcdef",
        "execution-logs",
      ]),
    ).toBe(true);
    expect(
      isAllowedRoute("GET", ["clusters", "CLU-demo", "audit-log"]),
    ).toBe(true);
    expect(
      isAllowedRoute("POST", [
        "clusters",
        "CLU-demo",
        "node-groups",
        "KNG-0123456789abcdef0123456789abcdef",
        "retry",
      ]),
    ).toBe(true);
    expect(
      isAllowedRoute("POST", [
        "clusters", "CLU-demo", "access", "assignments",
      ]),
    ).toBe(true);
    expect(
      isAllowedRoute("POST", [
        "clusters", "CLU-demo", "connector", "install",
      ]),
    ).toBe(true);
    expect(
      isAllowedRoute("GET", [
        "clusters", "CLU-demo", "access", "subjects",
      ]),
    ).toBe(true);
    expect(
      isAllowedRoute("GET", [
        "clusters", "CLU-demo", "access", "namespaces",
      ]),
    ).toBe(true);
    expect(
      isAllowedRoute("POST", [
        "clusters", "CLU-demo", "access", "assignments",
        "KAA-0123456789abcdef0123456789abcdef", "revoke",
      ]),
    ).toBe(true);
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

  it("accepts verified cluster namespace inventory", () => {
    const result = clusterNamespaceInventorySchema.parse({
      clusterId: "CLU-demo",
      customerId: "CUS-demo",
      status: "READY",
      source: "IN_CLUSTER_CONNECTOR",
      connectorId: "KCC-0123456789abcdef0123456789abcdef",
      observedAt: "2026-09-15T10:00:00Z",
      expiresAt: "2026-09-15T10:10:00Z",
      failureCode: null,
      namespaces: [{
        namespace: "payments",
        isSystem: false,
        observedAt: "2026-09-15T10:00:00Z",
      }],
    });
    expect(result.namespaces[0]?.namespace).toBe("payments");
  });

  it("accepts managed Kubernetes access profiles and pending assignments", () => {
    const result = kubernetesAccessSchema.parse({
      clusterId: "CLU-demo",
      customerId: "CUS-demo",
      profiles: [{
        profileCode: "NAMESPACE_VIEWER",
        profileName: "Namespace Viewer",
        description: "Read workloads",
        scopeType: "NAMESPACE",
      }],
      assignments: [{
        assignmentId: "KAA-0123456789abcdef0123456789abcdef",
        subjectType: "GROUP",
        subjectId: "NAVIGAN_CUSTOMER_CUS-demo",
        profileCode: "NAMESPACE_VIEWER",
        profileName: "Namespace Viewer",
        scopeType: "NAMESPACE",
        namespace: "apps",
        status: "PENDING",
      }],
    });

    expect(result.assignments[0]?.status).toBe("PENDING");
  });

  it("accepts backend-provided cluster action capabilities", () => {
    const value = clusterSchema.parse({
      clusterId: "CLU-demo",
      customerId: "CUS-demo",
      environmentId: "ENV-demo",
      environmentApprovedVersion: 3,
      blueprintName: "standard-private",
      platform: "EKS",
      clusterName: "demo",
      status: "ACTIVE",
      version: 2,
      createdAt: "2026-09-14T00:00:00Z",
      updatedAt: "2026-09-14T00:00:00Z",
      allowedActions: [
        {
          code: "STOP",
          label: "Stop",
          enabled: true,
          destructive: false,
          confirmation: "Stop this cluster?",
        },
      ],
    });

    expect(value.allowedActions[0]?.code).toBe("STOP");
  });

  it("identifies lifecycle execution logs separately from provisioning", () => {
    const value = executionLogsSchema.parse({
      status: "FAILED",
      operation: "stop",
      executionId: "project:build-id",
      errorCode: "ResourceInUseException",
      complete: true,
      events: [],
    });

    expect(value.operation).toBe("stop");
    expect(value.errorCode).toBe("ResourceInUseException");
  });

  it("keeps platform setup behind the API proxy", () => {
    expect(isAllowedRoute("POST", ["clusters"])).toBe(true);
    expect(isAllowedRoute("POST", ["clusters", "CLU-demo", "approve"])).toBe(true);
    expect(isAllowedRoute("POST", ["clusters", "CLU-demo", "apply"])).toBe(true);
    expect(
      isAllowedRoute("POST", [
        "clusters",
        "CLU-demo",
        "github",
        "authorize",
      ]),
    ).toBe(true);
    expect(
      isAllowedRoute("POST", [
        "clusters",
        "CLU-demo",
        "github",
        "complete",
      ]),
    ).toBe(true);
  });

  it("owns cluster configuration independently of the environment baseline", () => {
    const body: ClusterInput = {
      environmentId: "ENV-demo",
      environmentApprovedVersion: 3,
      blueprintName: "standard-private",
      clusterName: "demo",
      kubernetesVersion: "1.35",
      endpointAccess: "PRIVATE",
      nodeGroups: [{
        name: "general",
        purpose: "SYSTEM",
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
      githubOrganization: "customer-platform",
    };
    expect(body.blueprintName).toBe("standard-private");
    expect(body.nodeGroups[0].desiredSize).toBe(1);
  });
});
