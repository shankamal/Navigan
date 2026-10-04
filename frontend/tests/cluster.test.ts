import { describe, expect, it } from "vitest";
import {
  clusterSchema,
  executionLogsSchema,
  kubernetesAccessSchema,
  clusterNamespaceInventorySchema,
  clusterRuntimeInventorySchema,
  platformComponentInventorySchema,
  clusterToolAccessSchema,
  clusterLifecycleActions,
  shouldShowClusterExecutionPanel,
  supportedEksVersions,
  type ClusterInput,
} from "@/modules/cluster-management/model";
import { isAllowedRoute } from "@/shared/api/proxy";

describe("Cluster API contract", () => {
  it("offers only supported Kubernetes versions from the environment contract", () => {
    expect(
      supportedEksVersions([
        { version: "1.33", support: "STANDARD_SUPPORT", default: true },
        { version: "1.34", support: "EXTENDED_SUPPORT", default: false },
        { version: "1.35", support: "UNSUPPORTED", default: false },
      ]),
    ).toEqual(["1.34", "1.33"]);
  });

  it("keeps governed cluster review actions in their required sequence", () => {
    const permissions = {
      canSubmit: false,
      canReview: true,
      canOperate: true,
      canDelete: true,
      certificationPassed: false,
    };
    expect(
      clusterLifecycleActions({ ...permissions, status: "SUBMITTED" }),
    ).toEqual(["review"]);
    expect(
      clusterLifecycleActions({ ...permissions, status: "UNDER_REVIEW" }),
    ).toEqual(["approve", "reject"]);
  });

  it("keeps Terraform history visible during platform bootstrap", () => {
    expect(
      shouldShowClusterExecutionPanel({
        hasExecutionId: true,
        historicalExecution: true,
        status: "BOOTSTRAPPING",
      }),
    ).toBe(true);
  });

  it("allows only the documented cluster routes", () => {
    expect(isAllowedRoute("POST", ["clusters"])).toBe(true);
    expect(isAllowedRoute("POST", ["clusters", "CLU-demo", "plan"])).toBe(true);
    expect(isAllowedRoute("POST", ["clusters", "CLU-demo", "apply"])).toBe(
      true,
    );
    expect(isAllowedRoute("POST", ["clusters", "CLU-demo", "stop"])).toBe(true);
    expect(isAllowedRoute("POST", ["clusters", "CLU-demo", "start"])).toBe(
      true,
    );
    expect(isAllowedRoute("POST", ["clusters", "CLU-demo", "delete"])).toBe(
      true,
    );
    expect(
      isAllowedRoute("POST", [
        "clusters",
        "CLU-demo",
        "migrate-system-node-group",
      ]),
    ).toBe(true);
    expect(isAllowedRoute("GET", ["clusters", "CLU-demo", "node-groups"])).toBe(
      true,
    );
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
    expect(isAllowedRoute("GET", ["clusters", "CLU-demo", "audit-log"])).toBe(
      true,
    );
    expect(
      isAllowedRoute("GET", ["clusters", "CLU-demo", "platform-components"]),
    ).toBe(true);
    expect(isAllowedRoute("GET", ["clusters", "CLU-demo", "tools"])).toBe(true);
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
      isAllowedRoute("POST", ["clusters", "CLU-demo", "access", "assignments"]),
    ).toBe(true);
    expect(
      isAllowedRoute("POST", ["clusters", "CLU-demo", "connector", "install"]),
    ).toBe(true);
    expect(
      isAllowedRoute("GET", ["clusters", "CLU-demo", "access", "subjects"]),
    ).toBe(true);
    expect(
      isAllowedRoute("GET", ["clusters", "CLU-demo", "access", "namespaces"]),
    ).toBe(true);
    expect(
      isAllowedRoute("POST", [
        "clusters",
        "CLU-demo",
        "access",
        "assignments",
        "KAA-0123456789abcdef0123456789abcdef",
        "revoke",
      ]),
    ).toBe(true);
    expect(isAllowedRoute("DELETE", ["clusters", "CLU-demo"])).toBe(false);
    expect(isAllowedRoute("POST", ["clusters", "CLU-demo", "destroy"])).toBe(
      false,
    );
  });

  it("requires the pinned approved environment version", () => {
    expect(() =>
      clusterSchema.parse({
        clusterId: "CLU-demo",
        customerId: "CUS-demo",
        environmentId: "ENV-demo",
        platform: "EKS",
        clusterName: "demo",
        status: "DRAFT",
        version: 1,
        createdAt: "2026-09-10T00:00:00Z",
        updatedAt: "2026-09-10T00:00:00Z",
      }),
    ).toThrow();
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
      namespaces: [
        {
          namespace: "payments",
          isSystem: false,
          observedAt: "2026-09-15T10:00:00Z",
        },
      ],
    });
    expect(result.namespaces[0]?.namespace).toBe("payments");
  });

  it("accepts connector-reported runtime inventory", () => {
    const result = clusterRuntimeInventorySchema.parse({
      clusterId: "CLU-demo",
      customerId: "CUS-demo",
      status: "READY",
      connectorId: "KCC-0123456789abcdef0123456789abcdef",
      sourceRevision: 123,
      observedAt: "2026-09-19T10:00:00Z",
      expiresAt: "2026-09-19T10:10:00Z",
      metrics: {
        nodeCount: 2,
        readyNodeCount: 2,
        podCount: 8,
        readyPodCount: 8,
        containerRestartCount: 0,
        warningEventCount: 0,
      },
      resources: [
        {
          kind: "Deployment",
          namespace: "apps",
          name: "checkout",
          status: "HEALTHY",
          ready: 2,
          desired: 2,
          restarts: 0,
        },
      ],
      warningEvents: [],
    });

    expect(result.resources[0]?.name).toBe("checkout");
    expect(result.metrics.readyNodeCount).toBe(2);
  });

  it("accepts an expired runtime inventory for automatic refresh", () => {
    const result = clusterRuntimeInventorySchema.parse({
      clusterId: "CLU-demo",
      customerId: "CUS-demo",
      status: "STALE",
      connectorId: "KCC-0123456789abcdef0123456789abcdef",
      sourceRevision: 123,
      observedAt: "2026-09-19T10:00:00Z",
      expiresAt: "2026-09-19T10:10:00Z",
      metrics: {
        nodeCount: 2,
        readyNodeCount: 2,
      },
      resources: [],
      warningEvents: [],
    });

    expect(result.status).toBe("STALE");
    expect(result.metrics.nodeCount).toBe(2);
  });

  it("returns runtime inventory with the existing platform status response", () => {
    const runtimeInventory = clusterRuntimeInventorySchema.parse({
      clusterId: "CLU-demo",
      customerId: "CUS-demo",
      status: "NOT_REPORTED",
      connectorId: null,
      sourceRevision: null,
      observedAt: null,
      expiresAt: null,
      metrics: {},
      resources: [],
      warningEvents: [],
    });
    const result = platformComponentInventorySchema.parse({
      clusterId: "CLU-demo",
      customerId: "CUS-demo",
      status: "READY",
      connectorId: "KCC-0123456789abcdef0123456789abcdef",
      sourceRevision: 123,
      observedAt: "2026-09-19T10:00:00Z",
      components: [
        {
          componentCode: "connector",
          status: "READY",
          version: null,
          syncStatus: "Synced",
          healthStatus: "Healthy",
          observedAt: "2026-09-19T10:00:00Z",
          sourceRevision: 123,
        },
      ],
      runtimeInventory,
    });

    expect(result.runtimeInventory.status).toBe("NOT_REPORTED");
  });

  it("accepts disabled tool access until the shared gateway is ready", () => {
    const result = clusterToolAccessSchema.parse({
      clusterId: "CLU-demo",
      customerId: "CUS-demo",
      gateway: {
        status: "NOT_DEPLOYED",
        baseUrl: "https://dev.navigan.click/tools",
      },
      tunnel: {
        status: "NOT_CONNECTED",
        connectorReady: true,
      },
      tools: [
        {
          code: "GRAFANA",
          label: "Grafana",
          status: "UNAVAILABLE",
          componentStatus: "READY",
          interactive: false,
          launchUrl: null,
          disabledReason:
            "The shared platform tools gateway is not deployed in this environment.",
        },
      ],
    });

    expect(result.tools[0]?.launchUrl).toBeNull();
    expect(result.gateway.baseUrl).toBe("https://dev.navigan.click/tools");
  });

  it("accepts managed Kubernetes access profiles and pending assignments", () => {
    const result = kubernetesAccessSchema.parse({
      clusterId: "CLU-demo",
      customerId: "CUS-demo",
      profiles: [
        {
          profileCode: "NAMESPACE_VIEWER",
          profileName: "Namespace Viewer",
          description: "Read workloads",
          scopeType: "NAMESPACE",
        },
      ],
      assignments: [
        {
          assignmentId: "KAA-0123456789abcdef0123456789abcdef",
          subjectType: "GROUP",
          subjectId: "NAVIGAN_CUSTOMER_CUS-demo",
          profileCode: "NAMESPACE_VIEWER",
          profileName: "Namespace Viewer",
          scopeType: "NAMESPACE",
          namespace: "apps",
          status: "PENDING",
        },
      ],
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
    expect(isAllowedRoute("POST", ["clusters", "CLU-demo", "approve"])).toBe(
      true,
    );
    expect(isAllowedRoute("POST", ["clusters", "CLU-demo", "apply"])).toBe(
      true,
    );
    expect(
      isAllowedRoute("POST", ["clusters", "CLU-demo", "github", "authorize"]),
    ).toBe(true);
    expect(
      isAllowedRoute("POST", ["clusters", "CLU-demo", "github", "complete"]),
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
      nodeGroups: [
        {
          name: "general",
          purpose: "SYSTEM",
          instanceTypes: ["m7i.large"],
          capacityType: "ON_DEMAND",
          minSize: 1,
          desiredSize: 1,
          maxSize: 2,
          diskSizeGiB: 50,
        },
      ],
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
