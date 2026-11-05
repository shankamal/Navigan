import { fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { UpgradeWorkspace } from "../src/modules/upgrade-management/upgrade-workspace";

const { activeCluster } = vi.hoisted(() => ({
  activeCluster: {
    clusterId: "CLU-live",
    customerId: "CUS-live",
    customerName: "DB Schenker",
    environmentId: "ENV-live",
    environmentName: "Production",
    environmentApprovedVersion: 8,
    platform: "EKS" as const,
    clusterName: "New-dbs-demo-cluster",
    configuration: { kubernetesVersion: "1.34" },
    status: "ACTIVE",
    version: 4,
    allowedActions: [],
    createdAt: "2026-11-01T10:00:00Z",
    updatedAt: "2026-11-05T10:00:00Z",
  },
}));

vi.mock("@/modules/cluster-management/service", () => ({
  clusters: {
    list: vi.fn().mockResolvedValue({
      items: [activeCluster],
      pagination: {
        page: 0,
        pageSize: 100,
        totalElements: 1,
        totalPages: 1,
      },
    }),
    get: vi.fn().mockResolvedValue(activeCluster),
    platformComponents: vi.fn().mockResolvedValue({
      clusterId: "CLU-live",
      customerId: "CUS-live",
      status: "READY",
      connectorId: "CON-live",
      sourceRevision: 7,
      observedAt: "2026-11-05T10:00:00Z",
      components: [
        {
          componentCode: "headlamp",
          status: "READY",
          version: "0.45.0",
          syncStatus: "Synced",
          healthStatus: "Healthy",
          observedAt: "2026-11-05T10:00:00Z",
          sourceRevision: 7,
        },
      ],
      runtimeInventory: {
        clusterId: "CLU-live",
        customerId: "CUS-live",
        status: "READY",
        connectorId: "CON-live",
        sourceRevision: 7,
        observedAt: "2026-11-05T10:00:00Z",
        expiresAt: "2026-11-05T10:05:00Z",
        metrics: {},
        resources: [],
        warningEvents: [],
      },
    }),
  },
}));

function mount() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: { queries: { retry: false } },
        })
      }
    >
      <UpgradeWorkspace />
    </QueryClientProvider>,
  );
}

describe("Upgrade workspace", () => {
  it("presents the approved readiness workspace without live execution claims", () => {
    mount();

    expect(
      screen.getByRole("heading", { name: "Upgrades & Patching" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Experience preview.")).toBeInTheDocument();
    expect(
      screen.getByRole("tab", { name: /Upgrade Centre/i }),
    ).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getAllByText("payments-prod-eu")).toHaveLength(2);
    expect(
      screen.getByRole("button", { name: /Refresh inventory/i }),
    ).toBeDisabled();
  });

  it("uses the approved workspace names", () => {
    mount();

    for (const label of [
      "Upgrade Centre",
      "Container Upgrades",
      "System Utilities",
      "Maintenance Schedule",
      "Plans & History",
    ]) {
      expect(
        screen.getByRole("tab", { name: new RegExp(label, "i") }),
      ).toBeInTheDocument();
    }
    expect(
      screen.queryByText("Upgrade Command Centre"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Calendar & Campaigns")).not.toBeInTheDocument();
    expect(screen.queryByText("Upgrade Overview")).not.toBeInTheDocument();
    expect(screen.queryByText("Upgrade Readiness")).not.toBeInTheDocument();
  });

  it("opens and navigates the guided upgrade plan", () => {
    mount();

    fireEvent.click(
      screen.getByRole("button", { name: "Create upgrade plan" }),
    );
    expect(
      screen.getByRole("heading", { name: "Create upgrade plan" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Confirm upgrade scope" }),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: /Continue to target version/i }),
    );
    expect(
      screen.getByRole("heading", { name: "Select a supported target" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("radio", { name: /Continue to 1.35/i }),
    ).toBeChecked();

    fireEvent.click(
      screen.getByRole("button", { name: /Continue to readiness/i }),
    );
    expect(
      screen.getByRole("heading", { name: "Review readiness evidence" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Blocked")).toHaveLength(2);
  });

  it("opens live inventory tabs without exposing cloud actions", async () => {
    mount();

    fireEvent.click(screen.getByRole("tab", { name: /System Utilities/i }));
    expect(
      await screen.findByRole("heading", { name: "System utility upgrades" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Live read-only inventory.")).toBeInTheDocument();
    expect(await screen.findAllByText("Headlamp")).not.toHaveLength(0);
    expect(screen.getAllByText("0.45.0")).not.toHaveLength(0);
    expect(
      screen.getByRole("button", { name: /Create utility upgrade plan/i }),
    ).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: /Upgrade now/i }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: /Container Upgrades/i }));
    expect(
      await screen.findByRole("heading", {
        name: "Container distribution upgrades",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Create container upgrade plan/i }),
    ).toBeDisabled();

    fireEvent.click(screen.getByRole("tab", { name: /Maintenance Schedule/i }));
    const section = screen
      .getByRole("heading", { name: "Maintenance schedule" })
      .closest("section");
    expect(section).not.toBeNull();
    expect(
      within(section!).getByText(/sandbox, non-production and production/i),
    ).toBeInTheDocument();
  });
});
