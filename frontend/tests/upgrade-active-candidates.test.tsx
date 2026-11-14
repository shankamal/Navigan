import { render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { LiveUpgradeCentre } from "../src/modules/upgrade-management/live-upgrade-centre";

const fleet = [
  {
    clusterId: "CLU-candidate",
    customerId: "CUS-1",
    customerName: "DB Schenker",
    environmentId: "ENV-prod",
    environmentName: "Production",
    platform: "EKS",
    clusterName: "candidate-cluster",
    configuration: { kubernetesVersion: "1.36" },
    status: "ACTIVE",
    version: 1,
    allowedActions: [],
    createdAt: "2026-11-01T00:00:00Z",
    updatedAt: "2026-11-10T00:00:00Z",
  },
  {
    clusterId: "CLU-current",
    customerId: "CUS-1",
    customerName: "DB Schenker",
    environmentId: "ENV-prod",
    environmentName: "Production",
    platform: "EKS",
    clusterName: "fully-current-cluster",
    configuration: { kubernetesVersion: "1.37" },
    status: "ACTIVE",
    version: 1,
    allowedActions: [],
    createdAt: "2026-11-01T00:00:00Z",
    updatedAt: "2026-11-10T00:00:00Z",
  },
] as const;

vi.mock("@/shared/auth/auth-provider", () => ({
  useAuth: () => ({
    identity: {
      subject: "architect-reviewer",
      roles: ["PLATFORM_ARCHITECT"],
      privileges: ["cluster.upgrade.plan", "cluster.approve"],
      platformScope: true,
    },
  }),
}));

vi.mock("../src/modules/upgrade-management/upgrade-plan-data", () => ({
  useUpgradePlans: () => ({
    identity: {
      subject: "architect-reviewer",
      roles: ["PLATFORM_ARCHITECT"],
      privileges: ["cluster.upgrade.plan", "cluster.approve"],
      platformScope: true,
    },
    fleet,
    rows: [],
    pending: false,
    errors: [],
    refresh: vi.fn(),
    stateForCluster: () => ({
      pending: false,
      error: undefined,
    }),
  }),
}));

vi.mock("@/modules/cluster-management/service", () => ({
  clusters: {
    upgradeReadiness: vi.fn(async (clusterId: string) => {
      const candidate = clusterId === "CLU-candidate";
      return {
        clusterId,
        customerId: "CUS-1",
        provider: "EKS",
        region: "ap-south-1",
        source: "AWS_EKS_API",
        observedAt: "2026-11-14T08:00:00Z",
        controlPlane: {
          name: candidate ? "candidate-cluster" : "fully-current-cluster",
          version: candidate ? "1.36" : "1.37",
          platformVersion: "eks.18",
          status: "ACTIVE",
          support: {
            version: candidate ? "1.36" : "1.37",
            supportStatus: "STANDARD_SUPPORT",
            releaseDate: null,
            endOfStandardSupportDate: null,
            endOfExtendedSupportDate: null,
          },
        },
        recommendedTarget: candidate
          ? {
              version: "1.37",
              supportStatus: "STANDARD_SUPPORT",
              releaseDate: null,
              endOfStandardSupportDate: null,
              endOfExtendedSupportDate: null,
            }
          : null,
        nodeGroups: [
          {
            name: "system",
            version: candidate ? "1.36" : "1.37",
            status: "ACTIVE",
            healthIssues: [],
          },
        ],
        addons: [
          {
            name: "coredns",
            version: "v1",
            targetVersion: "v1",
            status: "ACTIVE",
            healthIssues: [],
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
      };
    }),
  },
}));

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <LiveUpgradeCentre onPlan={vi.fn()} onReview={vi.fn()} />
    </QueryClientProvider>,
  );
}

describe("Upgrade Centre Active candidate inventory", () => {
  it("shows only clusters with a verified upgrade opportunity", async () => {
    mount();

    const table = await screen.findByRole("table", {
      name: "Candidate clusters requiring upgrade",
    });

    await waitFor(() =>
      expect(
        within(table).getByText("candidate-cluster"),
      ).toBeInTheDocument(),
    );

    expect(
      within(table).queryByText("fully-current-cluster"),
    ).not.toBeInTheDocument();

    expect(
      screen.getByRole("heading", { name: "Verified Upgrade Opportunities" }),
    ).toBeInTheDocument();

    expect(
      screen.getByRole("tab", { name: "Active" }),
    ).toHaveAttribute("aria-selected", "true");
  });
});
