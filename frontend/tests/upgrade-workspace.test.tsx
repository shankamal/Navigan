import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { UpgradeWorkspace } from "../src/modules/upgrade-management/upgrade-workspace";
import { clusters } from "@/modules/cluster-management/service";

vi.mock("@/shared/auth/auth-provider", () => ({
  useAuth: () => ({
    identity: {
      subject: "architect-reviewer",
      roles: ["PLATFORM_ARCHITECT"],
      privileges: ["cluster.plan", "cluster.approve"],
      platformScope: true,
    },
  }),
}));

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
    upgradeReadiness: vi.fn().mockResolvedValue({
      clusterId: "CLU-live",
      customerId: "CUS-live",
      provider: "EKS",
      region: "ap-south-1",
      source: "AWS_EKS_API",
      observedAt: "2026-11-05T10:00:00Z",
      controlPlane: {
        name: "New-dbs-demo-cluster",
        version: "1.34",
        platformVersion: "eks.18",
        status: "ACTIVE",
        support: {
          version: "1.34",
          supportStatus: "STANDARD_SUPPORT",
          releaseDate: null,
          endOfStandardSupportDate: "2027-08-01T00:00:00Z",
          endOfExtendedSupportDate: "2028-08-01T00:00:00Z",
        },
      },
      recommendedTarget: {
        version: "1.35",
        supportStatus: "STANDARD_SUPPORT",
        releaseDate: null,
        endOfStandardSupportDate: "2027-12-01T00:00:00Z",
        endOfExtendedSupportDate: "2028-12-01T00:00:00Z",
      },
      nodeGroups: [
        {
          name: "system",
          version: "1.34",
          status: "ACTIVE",
          healthIssues: [],
        },
      ],
      addons: [
        {
          name: "coredns",
          version: "v1.11.4-eksbuild.20",
          status: "ACTIVE",
          healthIssues: [],
          targetVersion: "v1.12.3-eksbuild.1",
        },
      ],
      insights: [],
      updates: [],
      readiness: {
        status: "READY",
        blockers: [],
        warnings: [],
        checks: {
          controlPlaneActive: true,
          nodeGroupsAligned: true,
          addonsHealthy: true,
          upgradeInsightsPassing: true,
          noUpdateInProgress: true,
        },
      },
    }),
    upgradePlans: vi.fn().mockResolvedValue({
      clusterId: "CLU-live",
      customerId: "CUS-live",
      items: [],
    }),
    createUpgradePlan: vi.fn(),
    changeUpgradePlan: vi.fn(),
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
  it("presents live fleet readiness without preview data", async () => {
    mount();

    expect(
      screen.getByRole("heading", { name: "Upgrades & Patching" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Live governed inventory.")).toBeInTheDocument();
    expect(
      screen.getByRole("tab", { name: /Upgrade Centre/i }),
    ).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(screen.getAllByText("New-dbs-demo-cluster")).toHaveLength(2);
    expect(screen.queryByText("payments-prod-eu")).not.toBeInTheDocument();
    expect(screen.getAllByText("1.34")).not.toHaveLength(0);
    expect(screen.getAllByText("1.35")).not.toHaveLength(0);
    expect(
      screen.getByRole("button", { name: /Refresh inventory/i }),
    ).toBeEnabled();
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

  it("shows a single-page planner with evidence ticks and saves then submits", async () => {
    mount();

    fireEvent.click(
      await screen.findByRole("button", { name: "Create upgrade plan" }),
    );
    expect(
      screen.getByRole("heading", { name: "Create upgrade plan" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "1. Cluster & target" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "2. Components & readiness" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "3. Maintenance & reason" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Managed node groups aligned").closest("li"),
    ).toHaveClass("check-passed");
    expect(screen.getByText("Independent approval").closest("li")).toHaveClass(
      "check-pending",
    );
    expect(
      screen.getByRole("button", { name: "Save & submit" }),
    ).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Change reason"), {
      target: { value: "Apply supported cluster upgrade" },
    });
    const saved = {
      planId: "UPG-test",
      version: 1,
      status: "DRAFT",
    } as Awaited<ReturnType<typeof clusters.createUpgradePlan>>;
    vi.mocked(clusters.createUpgradePlan).mockResolvedValueOnce(saved);
    vi.mocked(clusters.changeUpgradePlan).mockResolvedValueOnce({
      ...saved,
      version: 2,
      status: "SUBMITTED",
    });
    fireEvent.click(screen.getByRole("button", { name: "Save & submit" }));
    await waitFor(() =>
      expect(clusters.changeUpgradePlan).toHaveBeenCalledWith(
        "CLU-live",
        "UPG-test",
        "submit",
        1,
      ),
    );
    expect(
      await screen.findByText(/Awaiting independent approval. Find it/),
    ).toBeInTheDocument();
  });

  it("shows submitted requests and requested windows to an independent architect", async () => {
    const evidence = await clusters.upgradeReadiness("CLU-live");
    const submitted = {
      planId: "UPG-review",
      clusterId: "CLU-live",
      customerId: "CUS-live",
      provider: "EKS",
      currentVersion: "1.34",
      targetVersion: "1.35",
      strategy: "PROVIDER_MANAGED_ROLLING",
      status: "SUBMITTED",
      scheduledFor: "2027-01-01T16:30:00Z",
      changeReason: "Keep cluster supported",
      readinessEvidence: evidence,
      execution: {},
      version: 2,
      createdBy: "engineer-maker",
      submittedBy: "engineer-maker",
      submittedByName: "Ashok Rajendran",
      submittedAt: "2026-11-06T10:01:00Z",
      createdAt: "2026-11-06T10:00:00Z",
      updatedAt: "2026-11-06T10:01:00Z",
      updatedBy: "engineer-maker",
    } as Awaited<ReturnType<typeof clusters.upgradePlan>>;
    vi.mocked(clusters.upgradePlans).mockResolvedValue({
      clusterId: "CLU-live",
      customerId: "CUS-live",
      items: [submitted],
    });
    try {
      mount();
      expect(await screen.findByText(/Awaiting approval/)).toBeInTheDocument();
      expect(screen.queryByText("Not scheduled")).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole("tab", { name: /Plans & History/ }));
      fireEvent.click(
        await screen.findByRole("button", { name: "Awaiting my review (1)" }),
      );
      fireEvent.click(
        await screen.findByRole("button", { name: "Review plan" }),
      );
      const drawer = screen.getByRole("dialog", {
        name: "Review upgrade plan",
      });
      expect(within(drawer).getByText("Ashok Rajendran")).toBeInTheDocument();
      expect(within(drawer).getByText("Submitted at")).toBeInTheDocument();
      expect(
        within(drawer).getByText("Keep cluster supported"),
      ).toBeInTheDocument();
      expect(
        within(drawer).getByText("Independent approval recorded").closest("li"),
      ).toHaveClass("check-pending");
      expect(
        within(drawer).getByRole("button", { name: "Reject with reason" }),
      ).toBeDisabled();
      vi.mocked(clusters.changeUpgradePlan).mockResolvedValueOnce({
        ...submitted,
        status: "SCHEDULED",
        approvedBy: "architect-reviewer",
      });
      fireEvent.click(
        within(drawer).getByRole("button", { name: "Approve plan" }),
      );
      await waitFor(() =>
        expect(clusters.changeUpgradePlan).toHaveBeenCalledWith(
          "CLU-live",
          "UPG-review",
          "approve",
          2,
          undefined,
        ),
      );
      expect(clusters.list).toHaveBeenCalledWith({ page: 0, pageSize: 100 });
    } finally {
      vi.mocked(clusters.upgradePlans).mockResolvedValue({
        clusterId: "CLU-live",
        customerId: "CUS-live",
        items: [],
      });
    }
  });

  it("opens live inventory tabs without exposing cloud actions", async () => {
    mount();

    fireEvent.click(screen.getByRole("tab", { name: /System Utilities/i }));
    expect(
      await screen.findByRole("heading", { name: "System utility upgrades" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Live governed inventory.")).toBeInTheDocument();
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
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /Create container upgrade plan/i }),
      ).toBeEnabled(),
    );
    expect(await screen.findByText("Kubernetes 1.35")).toBeInTheDocument();
    expect(screen.getByText("Ready for planning")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: /Maintenance Schedule/i }));
    const section = (
      await screen.findByRole("heading", { name: "Maintenance schedule" })
    ).closest("section");
    expect(section).not.toBeNull();
    expect(
      await within(section!).findByText(
        /No requested maintenance windows match/i,
      ),
    ).toBeInTheDocument();
  });
});
