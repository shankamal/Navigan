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
  useMigrationAssessment: () => ({
    data: undefined,
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
      screen.getByRole("heading", { name: "Migrations" }),
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

    fireEvent.click(
      screen.getByRole("button", {
        name: "Prepare secure source connector",
      }),
    );

    expect(
      await screen.findByText("Source catalogue received"),
    ).toBeInTheDocument();
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

    expect(screen.getByText("Active EKS cluster")).toBeInTheDocument();
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
      screen.getByText("RetailFlow migration feasibility"),
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
  });

  it("renders the trusted feasibility scorecard", () => {
    render(
      <AssessmentReportCard
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
          ],
          createdBy: "NAVIGAN_ASSESSMENT_ENGINE",
          createdAt: "2026-10-06T08:00:01Z",
        }}
      />,
    );

    expect(
      screen.getByRole("heading", {
        name: "Migration feasibility report",
      }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Compatibility score")).toHaveTextContent(
      "82/100",
    );
    expect(
      screen.getByText("Load balancer translation required."),
    ).toBeInTheDocument();
    expect(screen.getByText("AUTOMATED CHANGE")).toBeInTheDocument();
  });
});
