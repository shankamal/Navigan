import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
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

  it("guides the user through a read-only assessment", () => {
    render(<MigrationCreatePage />);

    expect(
      screen.getByRole("heading", {
        name: "New migration assessment",
      }),
    ).toBeInTheDocument();

    expect(
      screen.getByLabelText("Source platform"),
    ).toHaveValue("SELF_MANAGED_KUBERNETES");
    expect(
      screen.getByLabelText("Target platform"),
    ).toHaveValue("EKS");

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

    fireEvent.change(screen.getByRole("combobox", { name: /Active customer/i }), {
      target: { value: "CUS-active" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: /Target environment/i }), {
      target: { value: "ENV-active" },
    });

    expect(continueButton()).toBeEnabled();
    fireEvent.click(continueButton());

    expect(
      screen.getByRole("heading", {
        name: "Connect the source cluster",
      }),
    ).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Source connection"), {
      target: { value: "preview-lab" },
    });

    expect(screen.getByText("Connected")).toBeInTheDocument();
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
    expect(
      screen.getByRole("button", { name: "Start assessment" }),
    ).toBeDisabled();
  });
});
