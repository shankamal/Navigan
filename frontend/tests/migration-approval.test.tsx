import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MigrationDetails } from "@/modules/migration-management/migration-details";

const state = vi.hoisted(() => ({
  role: "CLOUD_ENGINEER",
  status: "ASSESSMENT_READY",
  action: vi.fn(),
  enroll: vi.fn(),
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
      targetConfiguration: {},
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
          deliveryMethod: "MANUAL_HELM",
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
  },
  sourceClusters: {
    enroll: state.enroll,
    updateDelivery: vi.fn(),
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
    state.action.mockReset();
    state.action.mockResolvedValue({});
    state.enroll.mockReset();
    state.enroll.mockResolvedValue({
      enrollmentId: "SCE-" + "c".repeat(32),
      sourceClusterId: "SRC-" + "b".repeat(32),
      status: "ISSUED",
      expiresAt: "2026-10-06T18:30:00Z",
      enrollmentToken: "d".repeat(43),
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
