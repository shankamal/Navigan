import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UpgradePlansWorkspace } from "@/modules/upgrade-management/upgrade-plans-workspace";
import { clusters } from "@/modules/cluster-management/service";
import { rescheduleBlockReason } from "@/modules/upgrade-management/plan-availability";
import { scheduleOverdue } from "@/modules/upgrade-management/schedule-state";
import type { EksUpgradePlan } from "@/modules/cluster-management/model";

const fixture = vi.hoisted(() => ({
  plan: null as EksUpgradePlan | null,
  reviewer: false,
  refresh: vi.fn(),
  cluster: {
    clusterId: "CLU-example",
    clusterName: "Example cluster",
    customerId: "CUS-example",
    environmentId: "ENV-example",
    environmentName: "Example environment",
    platform: "EKS",
    status: "ACTIVE",
    configuration: { cloudProvider: "AWS" },
  },
}));
vi.mock("@/modules/upgrade-management/upgrade-plan-data", () => ({
  useUpgradePlans: () => ({
    identity: {
      subject: fixture.reviewer ? "reviewer" : "engineer",
      roles: [],
      privileges: [],
    },
    rows: fixture.plan
      ? [
          {
            plan: fixture.plan,
            cluster: fixture.cluster,
            clusterName: "Example cluster",
            environment: "Example environment",
          },
        ]
      : [],
    pending: false,
    errors: [],
    refresh: fixture.refresh,
  }),
}));
vi.mock("@/shared/auth/permissions", () => ({
  hasPermission: (_: unknown, permission: string) =>
    permission === "cluster.upgrade.plan" ||
    permission === "cluster.upgrade.execute" ||
    (fixture.reviewer && permission === "cluster.upgrade.approve"),
}));
vi.mock("@/modules/cluster-management/service", () => ({
  clusters: { changeUpgradePlan: vi.fn().mockResolvedValue({}) },
}));

function examplePlan(policy = false): EksUpgradePlan {
  return {
    planId: "UPG-example",
    clusterId: "CLU-example",
    customerId: "CUS-example",
    kind: "UTILITY",
    provider: "EKS",
    utilityCode: "headlamp",
    managedGroup: "headlamp",
    currentVersion: "0.45.0",
    targetVersion: "0.46.0",
    strategy: "GITOPS_REVIEW",
    status: "SCHEDULED",
    scheduledFor: new Date(Date.now() - 3 * 3600000).toISOString(),
    changeReason: "Example upgrade",
    version: 4,
    createdBy: "engineer",
    updatedBy: "engineer",
    submittedBy: "engineer",
    approvedBy: "reviewer",
    approvedAt: new Date().toISOString(),
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    execution: {},
    utilityEvidence: {
      label: "Headlamp",
      chart: "headlamp",
      currentVersion: "0.45.0",
      versions: ["0.46.0"],
      observedAt: new Date().toISOString(),
      ...(policy
        ? {
            executionPolicy: {
              adapter: "HEADLAMP_045_TO_046_V1" as const,
              durationMinutes: 120 as const,
              snapshot: {
                repositoryUrl: "https://github.com/example/cluster-system",
                branch: "main",
                baseCommit: "base",
                manifestSha: "manifest",
                valuesSha: "values",
                manifestHash: "hash",
                valuesHash: "hash",
              },
              artifact: {
                chartVersion: "0.46.0",
                applicationVersion: "0.46.0",
                sha256: "reviewed-package-hash",
              },
            },
          }
        : {}),
    },
  };
}
function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <UpgradePlansWorkspace
        mode="history"
        drawerOnly
        initialPlanId="UPG-example"
      />
    </QueryClientProvider>,
  );
  return within(screen.getByRole("dialog"));
}
beforeEach(() => {
  fixture.plan = examplePlan();
  fixture.reviewer = false;
  vi.clearAllMocks();
});

describe("utility maintenance and execution", () => {
  it.each(["APPROVED", "SCHEDULED"] as const)(
    "reschedules an overdue %s utility and sends its current revision",
    async (status) => {
      fixture.plan!.status = status;
      const drawer = mount();
      const input = drawer.getByLabelText("New maintenance start");
      expect(input).toBeEnabled();
      fireEvent.change(input, { target: { value: "2099-01-01T12:00" } });
      fireEvent.click(
        drawer.getByRole("button", { name: "Save new schedule" }),
      );
      await waitFor(() =>
        expect(clusters.changeUpgradePlan).toHaveBeenCalledWith(
          "CLU-example",
          "UPG-example",
          "reschedule",
          4,
          undefined,
          new Date("2099-01-01T12:00").toISOString(),
        ),
      );
      expect(fixture.refresh).toHaveBeenCalled();
    },
  );
  it("preserves the container approval restriction", () => {
    const plan = { ...examplePlan(), kind: "CONTAINER" as const };
    expect(rescheduleBlockReason(null, plan)).toMatch(
      /Cancel an approved plan/,
    );
  });
  it("does not treat the beginning of a reviewed two-hour window as overdue", () => {
    const plan = examplePlan(true);
    plan.scheduledFor = new Date(Date.now() - 60000).toISOString();
    expect(scheduleOverdue(plan)).toBe(false);
    plan.scheduledFor = new Date(Date.now() - 121 * 60000).toISOString();
    expect(scheduleOverdue(plan)).toBe(true);
  });
  it("does not expose execution for old planning-only approvals", () => {
    const drawer = mount();
    expect(
      drawer.queryByRole("button", { name: "Start approved Headlamp upgrade" }),
    ).not.toBeInTheDocument();
  });
  it("requires two clicks to prepare a reviewed Headlamp upgrade", async () => {
    fixture.plan = examplePlan(true);
    fixture.plan.scheduledFor = new Date(Date.now() - 60000).toISOString();
    const drawer = mount();
    fireEvent.click(
      drawer.getByRole("button", { name: "Start approved Headlamp upgrade" }),
    );
    expect(clusters.changeUpgradePlan).not.toHaveBeenCalled();
    fireEvent.click(
      drawer.getByRole("button", { name: "Confirm prepare Headlamp upgrade" }),
    );
    await waitFor(() =>
      expect(clusters.changeUpgradePlan).toHaveBeenCalledWith(
        "CLU-example",
        "UPG-example",
        "execute",
        4,
        undefined,
      ),
    );
  });
  it("publishes a durable prepared intent through the refresh action", async () => {
    fixture.plan = examplePlan(true);
    fixture.plan.status = "EXECUTING";
    fixture.plan.execution = { phase: "GITOPS_PREPARED" };
    const drawer = mount();
    fireEvent.click(
      drawer.getByRole("button", { name: "Publish prepared upgrade" }),
    );
    await waitFor(() =>
      expect(clusters.changeUpgradePlan).toHaveBeenCalledWith(
        "CLU-example",
        "UPG-example",
        "refresh",
        4,
        undefined,
      ),
    );
  });
  it("requires the reviewers compatibility and recovery sign-off", () => {
    fixture.reviewer = true;
    fixture.plan = examplePlan(true);
    fixture.plan.status = "SUBMITTED";
    fixture.plan.scheduledFor = new Date(Date.now() + 3600000).toISOString();
    const drawer = mount();
    expect(drawer.getByRole("button", { name: "Approve plan" })).toBeDisabled();
    fireEvent.change(drawer.getByLabelText("Review comment"), {
      target: { value: "Release compatibility and recovery checked" },
    });
    expect(drawer.getByRole("button", { name: "Approve plan" })).toBeEnabled();
  });
});
