import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  AssessmentReportCard,
  MigrationCreatePage,
  MigrationManagementPage,
} from "@/modules/migration-management";

vi.mock("@/shared/auth/auth-provider", () => ({
  useAuth: () => ({
    identity: {
      subject: "engineer-1",
      displayName: "Cloud Engineer",
      roles: ["CLOUD_ENGINEER"],
      canCreate: true,
      platformScope: true,
      customerIds: [],
    },
  }),
}));

vi.mock("@/modules/customer-management/hooks/queries", () => ({
  useCustomers: () => ({
    data: {
      items: [
        {
          customerId: "CUS-active",
          name: "Active customer",
          status: "ACTIVE",
        },
      ],
    },
    isPending: false,
    isError: false,
  }),
}));

vi.mock("@/modules/environment-management/hooks/queries", () => ({
  useEnvironments: () => ({
    data: {
      items: [
        {
          environmentId: "ENV-active",
          customerId: "CUS-active",
          customerName: "Active customer",
          cloudProvider: "AWS",
          kubernetesDistribution: "EKS",
          environmentName: "Development",
          status: "ACTIVE",
          approvedVersion: 16,
        },
      ],
    },
    isPending: false,
    isError: false,
  }),
}));

vi.mock("@/modules/cluster-management/hooks/queries", () => ({
  useClusters: () => ({
    data: {
      items: [
        {
          clusterId: "CLU-active",
          customerId: "CUS-active",
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
  useCancelMigration: () => ({
    mutate: vi.fn(),
    isPending: false,
  }),
  useMigrations: () => ({
    data: {
      items: [],
      pagination: {
        page: 0,
        pageSize: 100,
        totalElements: 0,
        totalPages: 0,
      },
    },
    isPending: false,
    isError: false,
  }),
  useMigration: () => ({
    data: undefined,
    isPending: false,
    isError: false,
  }),
  useSourceClusters: () => ({
    data: { items: [] },
    isPending: false,
    isError: false,
  }),
  useMigrationAssessment: () => ({
    data: undefined,
    isError: false,
    isPending: false,
  }),
  useSourceInventory: () => ({
    data: { inventory: null },
    isError: false,
    isPending: false,
  }),
  useSourceCatalogue: (migrationId: string) => ({
    data: migrationId
      ? {
          migrationId,
          version: 4,
          status: "INVENTORY_READY",
          catalogue: {
            catalogueVersion: 1,
            migrationVersion: 3,
            schemaVersion: 1,
            observedAt: "2026-10-05T12:30:00Z",
            sourceKubernetesVersion: "v1.37.1",
            inventoryDigest: "a".repeat(64),
            nodeCount: 3,
            architectures: ["amd64"],
            namespaces: [
              {
                name: "retailflow",
                resourceCounts: {
                  Deployment: 2,
                  Service: 1,
                },
              },
            ],
            createdAt: "2026-10-05T12:30:01Z",
          },
        }
      : undefined,
    isError: false,
  }),
}));

vi.mock("@/modules/migration-management/service", () => ({
  sourceClusters: {
    create: vi.fn(async () => ({
      sourceClusterId: "SRC-" + "c".repeat(32),
      customerId: "CUS-active",
      customerName: "Active customer",
      name: "retailflow-source",
      distribution: "kubeadm",
      locationType: "ON_PREMISES",
      cloudProvider: null,
      region: "Chennai DC",
      registrationMethod: "LOCAL_KUBECONFIG",
      deliveryMethod: "MANUAL_HELM",
      deliveryConfiguration: {},
      status: "PENDING_ENROLLMENT",
      version: 1,
    })),
    enroll: vi.fn(async () => ({
      enrollmentId: "SCE-" + "d".repeat(32),
      sourceClusterId: "SRC-" + "c".repeat(32),
      status: "ISSUED",
      expiresAt: "2026-10-06T15:15:00Z",
      enrollmentToken: "e".repeat(43),
    })),
    updateDelivery: vi.fn(),
    install: vi.fn(async () => ({
      sourceClusterId: "SRC-" + "c".repeat(32),
      enrollmentId: "SCE-" + "d".repeat(32),
      commandId: "11111111-2222-3333-4444-555555555555",
      managedInstanceId: "i-08e28d9b2242cbd53",
      status: "INSTALLATION_STARTED",
    })),
  },
  migrations: {
    create: vi.fn(async () => ({
      migrationId: "MIG-" + "a".repeat(32),
      customerId: "CUS-active",
      name: "RetailFlow migration feasibility",
      status: "DRAFT",
      version: 1,
      sourceConfiguration: {},
      targetConfiguration: {},
      migrationScope: {},
    })),
    discover: vi.fn(async () => ({
      migrationId: "MIG-" + "a".repeat(32),
      customerId: "CUS-active",
      name: "RetailFlow migration feasibility",
      status: "SOURCE_ENROLLMENT_PENDING",
      version: 2,
      sourceConfiguration: {},
      targetConfiguration: {},
      migrationScope: {},
      discoveryConnector: {
        connectorId: "MGC-" + "b".repeat(32),
        status: "ENROLLED",
      },
    })),
    update: vi.fn(async () => ({
      migrationId: "MIG-" + "a".repeat(32),
      customerId: "CUS-active",
      name: "RetailFlow migration feasibility",
      status: "INVENTORY_READY",
      version: 5,
      sourceConfiguration: {},
      targetConfiguration: {},
      migrationScope: {
        namespaces: ["retailflow"],
      },
    })),
  },
}));

describe("Migration UI", () => {
  it("presents the assessment-only workflow", () => {
    render(<MigrationManagementPage />);

    expect(
      screen.getByRole("heading", { name: "Migration Overview" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Assessment only")).toBeInTheDocument();
    expect(
      screen.getByRole("link", {
        name: "New migration assessment",
      }),
    ).toHaveAttribute("href", "/migrations/new");
    expect(
      screen.queryByRole("button", { name: /execute/i }),
    ).not.toBeInTheDocument();
  });

  it("guides the user through a read-only assessment", async () => {
    render(<MigrationCreatePage />);

    expect(
      screen.getByRole("heading", {
        name: "New migration assessment",
      }),
    ).toBeInTheDocument();

    expect(screen.getByLabelText("Source platform")).toHaveValue(
      "SELF_MANAGED_KUBERNETES",
    );
    expect(screen.getByLabelText("Target platform")).toHaveValue("EKS");

    expect(
      screen.getByRole("group", { name: "Target type" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("radio", {
        name: /Existing EKS cluster/i,
      }),
    ).toBeChecked();
    expect(
      screen.getByRole("radio", {
        name: /Planned EKS platform/i,
      }),
    ).toBeDisabled();

    const continueButton = () =>
      screen.getByRole("button", { name: /continue/i });

    expect(continueButton()).toBeDisabled();

    fireEvent.change(
      screen.getByRole("textbox", {
        name: /Assessment name/i,
      }),
      {
        target: { value: "RetailFlow migration feasibility" },
      },
    );

    expect(continueButton()).toBeDisabled();

    fireEvent.change(
      screen.getByRole("combobox", { name: /Active customer/i }),
      {
        target: { value: "CUS-active" },
      },
    );
    fireEvent.change(
      screen.getByRole("combobox", { name: /Target environment/i }),
      {
        target: { value: "ENV-active" },
      },
    );

    expect(continueButton()).toBeEnabled();
    fireEvent.click(continueButton());

    expect(
      screen.getByRole("heading", {
        name: "Connect the source cluster",
      }),
    ).toBeInTheDocument();

    expect(
      screen.getByRole("radio", {
        name: /Register a new source cluster/i,
      }),
    ).toBeChecked();
    fireEvent.change(screen.getByLabelText("Source cluster name"), {
      target: { value: "retailflow-source" },
    });
    fireEvent.change(screen.getByLabelText("Kubernetes distribution"), {
      target: { value: "kubeadm" },
    });
    fireEvent.change(screen.getByLabelText("Cluster location"), {
      target: { value: "CLOUD" },
    });
    fireEvent.change(screen.getByLabelText("Region or location (optional)"), {
      target: { value: "ap-south-1" },
    });
    fireEvent.change(screen.getByLabelText("AWS account ID"), {
      target: { value: "905418045935" },
    });
    fireEvent.change(
      screen.getByLabelText("Control-plane managed instance ID"),
      {
        target: { value: "i-08e28d9b2242cbd53" },
      },
    );
    expect(
      screen.getByRole("combobox", { name: /Connector delivery/i }),
    ).toHaveValue("AWS_SSM");
    expect(
      screen.getByText(/never uploads or stores your kubeconfig/i),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Kubeconfig path"), {
      target: { value: "/etc/kubernetes/admin.conf" },
    });
    fireEvent.click(
      screen.getByRole("button", {
        name: "Register source cluster",
      }),
    );

    expect(
      await screen.findByText("Source catalogue received"),
    ).toBeInTheDocument();
    expect(screen.queryByText("e".repeat(43))).not.toBeInTheDocument();
    fireEvent.click(continueButton());

    expect(
      screen.getByRole("heading", {
        name: "Select workloads to assess",
      }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/retailflow/i)).toBeChecked();

    fireEvent.click(continueButton());

    expect(
      screen.getByRole("heading", {
        name: "Select the target EKS cluster",
      }),
    ).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Eligible target EKS cluster"), {
      target: { value: "CLU-active" },
    });

    expect(screen.getAllByText("Active EKS cluster").length).toBeGreaterThan(0);
    expect(
      screen.getByText("Collected when assessment starts"),
    ).toBeInTheDocument();

    expect(screen.getByText("Eligible active EKS cluster")).toBeInTheDocument();
    fireEvent.click(continueButton());

    expect(
      screen.getByRole("heading", {
        name: "Select compatibility checks",
      }),
    ).toBeInTheDocument();

    expect(screen.getAllByRole("checkbox")).toHaveLength(6);
    fireEvent.click(continueButton());

    expect(
      screen.getByRole("heading", {
        name: "Review before discovery starts",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getAllByText("RetailFlow migration feasibility")[0],
    ).toBeInTheDocument();
    const saveButton = screen.getByRole("button", {
      name: "Save assessment scope",
    });
    expect(saveButton).toBeEnabled();

    fireEvent.click(saveButton);

    expect(
      await screen.findByRole("button", {
        name: "Assessment scope saved",
      }),
    ).toBeDisabled();
  }, 15_000);

  it("renders the trusted feasibility scorecard", () => {
    render(
      <AssessmentReportCard
        source={{
          name: "navigan-migration-lab",
          nodeCount: 3,
          namespaceCount: 8,
          architectures: ["amd64"],
        }}
        report={{
          assessmentVersion: 1,
          migrationVersion: 6,
          reportSchemaVersion: 1,
          sourceKubernetesVersion: "v1.37.1",
          observedAt: "2026-10-06T08:00:00Z",
          inventoryDigest: "a".repeat(64),
          compatibilityScore: 82,
          containsBlockers: false,
          inventorySummary: {
            resourceCount: 12,
            resourceKinds: {
              Deployment: 5,
              Service: 3,
            },
            classification: {
              SEAMLESS: 8,
              AUTOMATED_CHANGE: 2,
              MANUAL_CHANGE: 2,
              BLOCKER: 0,
            },
            target: {
              clusterId: "CLU-active",
              clusterName: "DEV2-CLUS2-DEMO",
              status: "READY",
              nodeCount: 3,
              readyNodeCount: 3,
            },
          },
          findings: [
            {
              code: "LOAD_BALANCER_TRANSLATION",
              severity: "WARNING",
              category: "NETWORK",
              disposition: "AUTOMATED_CHANGE",
              namespace: "retailflow",
              resourceKind: "Service",
              resourceName: "retailflow",
              message: "Load balancer translation required.",
              remediation: "Generate approved AWS annotations.",
            },
            {
              code: "LOAD_BALANCER_TRANSLATION",
              severity: "WARNING",
              category: "NETWORK",
              disposition: "AUTOMATED_CHANGE",
              namespace: "retailflow",
              resourceKind: "Service",
              resourceName: "retailflow",
              message: "A second load balancer translation is required.",
              remediation: "Generate the second approved AWS annotation set.",
            },
          ],
          createdBy: "NAVIGAN_ASSESSMENT_ENGINE",
          createdAt: "2026-10-06T08:00:01Z",
        }}
      />,
    );

    expect(
      screen.getByRole("heading", {
        name: "Migration feasibility overview",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", {
        name: "Compatibility score 82 out of 100",
      }),
    ).toHaveTextContent("82%");
    expect(
      screen.getByText("Migration assessment is ready"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Assessment summary")).toBeInTheDocument();
    expect(screen.getByText("Assessed")).toBeInTheDocument();
    expect(screen.getByText("Critical")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Findings (2)" }));
    expect(
      screen.getAllByText("Load balancer translation required."),
    ).toHaveLength(1);
    expect(
      screen.getAllByText("A second load balancer translation is required."),
    ).toHaveLength(1);
    expect(screen.getByText("Automated changes")).toBeInTheDocument();
  });
});
