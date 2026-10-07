import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MigrationDetails } from "@/modules/migration-management/migration-details";

const state = vi.hoisted(() => ({
  role: "CLOUD_ENGINEER",
  status: "ASSESSMENT_READY",
  deliveryMethod: "MANUAL_HELM",
  action: vi.fn(),
  update: vi.fn(),
  assess: vi.fn(),
  enroll: vi.fn(),
  install: vi.fn(),
}));

vi.mock("@/shared/auth/auth-provider", () => ({
  useAuth: () => ({
    identity: {
      subject: "demo-user",
      displayName: "Demo user",
      roles: [state.role],
      canCreate: true,
      platformScope: true,
      customerIds: [],
    },
  }),
}));

vi.mock("@/modules/cluster-management/hooks/queries", () => ({
  useClusters: () => ({
    data: {
      items: [
        {
          clusterId: "CLU-active",
          customerId: "CUS-demo",
          environmentId: "ENV-active",
          environmentApprovedVersion: 16,
          platform: "EKS",
          clusterName: "Active EKS cluster",
          status: "ACTIVE",
        },
      ],
    },
    isPending: false,
    isError: false,
  }),
}));

vi.mock("@/modules/migration-management/hooks", () => ({
  useMigration: () => ({
    data: {
      migrationId: "MIG-" + "a".repeat(32),
      customerId: "CUS-demo",
      name: "RetailFlow migration",
      status: state.status,
      version: 7,
      sourceConfiguration: {
        sourceClusterId: "SRC-" + "b".repeat(32),
      },
      targetConfiguration: {
        environmentId: "ENV-active",
        environmentApprovedVersion: 16,
      },
      migrationScope: {},
    },
    isPending: false,
    isError: false,
  }),
  useMigrationAssessment: () => ({
    data: { assessment: null },
    isPending: false,
    isError: false,
  }),
  useSourceCatalogue: () => ({
    data: {
      migrationId: "MIG-" + "a".repeat(32),
      version: 7,
      status: state.status,
      catalogue: {
        catalogueVersion: 1,
        migrationVersion: 6,
        schemaVersion: 1,
        observedAt: "2026-10-06T19:29:02Z",
        sourceKubernetesVersion: "v1.31.0",
        inventoryDigest: "a".repeat(64),
        nodeCount: 3,
        architectures: ["amd64"],
        namespaces: [
          {
            name: "retailflow",
            resourceCounts: { Deployment: 2, Service: 1 },
          },
        ],
        createdAt: "2026-10-06T19:29:02Z",
      },
    },
    isPending: false,
    isError: false,
  }),
  useSourceClusters: () => ({
    data: {
      items: [
        {
          sourceClusterId: "SRC-" + "b".repeat(32),
          customerId: "CUS-demo",
          name: "navigan-migration-lab",
          locationType: "CLOUD",
          cloudProvider: "AWS",
          registrationMethod: "LOCAL_KUBECONFIG",
          deliveryMethod: state.deliveryMethod,
          deliveryConfiguration: {},
          status: "PENDING_ENROLLMENT",
          version: 1,
        },
      ],
    },
    isPending: false,
    isError: false,
  }),
}));

vi.mock("@/modules/migration-management/service", () => ({
  migrations: {
    action: state.action,
    update: state.update,
    assess: state.assess,
  },
  sourceClusters: {
    enroll: state.enroll,
    updateDelivery: vi.fn(),
    install: state.install,
  },
}));

function renderDetails() {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MigrationDetails migrationId={"MIG-" + "a".repeat(32)} />
    </QueryClientProvider>,
  );
}

describe("Migration approval gate", () => {
  beforeEach(() => {
    state.role = "CLOUD_ENGINEER";
    state.status = "ASSESSMENT_READY";
    state.deliveryMethod = "MANUAL_HELM";
    state.action.mockReset();
    state.action.mockResolvedValue({});
    state.update.mockReset();
    state.update.mockResolvedValue({
      migrationId: "MIG-" + "a".repeat(32),
      customerId: "CUS-demo",
      name: "RetailFlow migration",
      status: "INVENTORY_READY",
      version: 8,
      sourceConfiguration: {
        sourceClusterId: "SRC-" + "b".repeat(32),
      },
      targetConfiguration: {
        environmentId: "ENV-active",
        environmentApprovedVersion: 16,
        clusterId: "CLU-active",
      },
      migrationScope: { namespaces: ["retailflow"] },
    });
    state.assess.mockReset();
    state.assess.mockResolvedValue({
      migrationId: "MIG-" + "a".repeat(32),
      status: "DISCOVERY_PENDING",
      version: 9,
    });
    state.enroll.mockReset();
    state.enroll.mockResolvedValue({
      enrollmentId: "SCE-" + "c".repeat(32),
      sourceClusterId: "SRC-" + "b".repeat(32),
      status: "ISSUED",
      expiresAt: "2026-10-06T18:30:00Z",
      enrollmentToken: "d".repeat(43),
    });
    state.install.mockReset();
    state.install.mockResolvedValue({
      sourceClusterId: "SRC-" + "b".repeat(32),
      enrollmentId: "SCE-" + "c".repeat(32),
      commandId: "11111111-2222-3333-4444-555555555555",
      managedInstanceId: "i-08e28d9b2242cbd53",
      status: "INSTALLATION_STARTED",
    });
  });

  it("reissues setup for an existing pending source registration", async () => {
    state.status = "SOURCE_ENROLLMENT_PENDING";
    renderDetails();

    fireEvent.click(
      screen.getByRole("button", { name: "Prepare new connector setup" }),
    );

    await waitFor(() =>
      expect(state.enroll).toHaveBeenCalledWith("SRC-" + "b".repeat(32), 1),
    );
    expect(
      await screen.findByRole("button", {
        name: "Download connector setup",
      }),
    ).toBeEnabled();
  });

  it("starts automatic installation for an AWS SSM source", async () => {
    state.status = "SOURCE_ENROLLMENT_PENDING";
    state.deliveryMethod = "AWS_SSM";
    renderDetails();

    fireEvent.click(
      screen.getByRole("button", { name: "Install source connector" }),
    );

    await waitFor(() =>
      expect(state.install).toHaveBeenCalledWith("SRC-" + "b".repeat(32), 1),
    );
    expect(
      await screen.findByText("Connector installation started"),
    ).toBeInTheDocument();
  });

  it("resumes an inventory-ready migration and starts assessment", async () => {
    state.status = "INVENTORY_READY";
    renderDetails();

    expect(
      screen.getByRole("heading", {
        name: "Continue migration assessment",
      }),
    ).toBeInTheDocument();
    const workload = screen.getByRole("checkbox", {
      name: /retailflow/i,
    });
    await waitFor(() => expect(workload).toBeChecked());

    fireEvent.change(screen.getByLabelText("Target EKS cluster"), {
      target: { value: "CLU-active" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Save assessment scope" }),
    );

    await waitFor(() => expect(state.update).toHaveBeenCalledTimes(1));
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Start detailed assessment",
      }),
    );

    await waitFor(() =>
      expect(state.assess).toHaveBeenCalledWith("MIG-" + "a".repeat(32), 8),
    );
  });

  it("allows the Cloud Engineer to submit a completed assessment", async () => {
    renderDetails();

    fireEvent.click(screen.getByRole("button", { name: "Submit for review" }));

    await waitFor(() =>
      expect(state.action).toHaveBeenCalledWith(
        "MIG-" + "a".repeat(32),
        "submit",
        7,
        "Submit feasibility assessment for review",
      ),
    );
    expect(
      screen.queryByRole("button", { name: "Approve" }),
    ).not.toBeInTheDocument();
  });

  it("allows only the Platform Architect to approve an active review", async () => {
    state.role = "PLATFORM_ARCHITECT";
    state.status = "UNDER_REVIEW";
    renderDetails();

    fireEvent.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() =>
      expect(state.action).toHaveBeenCalledWith(
        "MIG-" + "a".repeat(32),
        "approve",
        7,
        "Approve migration for controlled planning",
      ),
    );
    expect(
      screen.queryByRole("button", { name: "Submit for review" }),
    ).not.toBeInTheDocument();
  });
});
