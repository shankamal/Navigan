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

const { authIdentity } = vi.hoisted(() => ({
  authIdentity: {
    subject: "architect-reviewer",
    displayName: "Platform Architect",
    roles: ["PLATFORM_ARCHITECT"],
    privileges: ["cluster.upgrade.plan", "cluster.approve"],
    platformScope: true,
  },
}));
vi.mock("@/shared/auth/auth-provider", () => ({
  useAuth: () => ({ identity: authIdentity }),
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
    get: vi.fn().mockResolvedValue({
      ...activeCluster,
      provisioningRoleArn: "arn:aws:iam::123456789012:role/Provisioning",
    }),
    utilityUpgradeOptions: vi.fn().mockResolvedValue({
      utilityCode: "headlamp",
      label: "Headlamp",
      chart: "headlamp",
      currentVersion: "0.45.0",
      versions: ["0.46.0"],
      blockReason: null,
      observedAt: "2026-11-07T10:00:00Z",
    }),
    createUtilityUpgradePlan: vi.fn(),
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
  it("shows four distinct tabs and component metrics without cluster accordions", async () => {
    mount();
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual([
      "Upgrade Centre",
      "System Utilities",
      "Plans & Approvals",
      "Maintenance Calendar",
    ]);
    expect(
      screen.queryByRole("tab", { name: "Container Upgrades" }),
    ).not.toBeInTheDocument();
    expect(
      await screen.findByRole("region", { name: "Upgrade plans by component" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Expand .*cluster/ }),
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Explore opportunities" }),
    );
    expect(
      await screen.findByRole("table", {
        name: "Registered active clusters and upgrade readiness",
      }),
    ).toBeInTheDocument();
    const create = await screen.findByRole("button", {
      name: "Create container plan",
    });
    await waitFor(() => expect(create).toBeEnabled());
  });

  it("retains the permission guard on the container planning entry point", async () => {
    const previous = authIdentity.privileges;
    authIdentity.privileges = [];
    try {
      mount();
      fireEvent.click(screen.getByRole("button", { name: "Create plan" }));
      expect(
        await screen.findByText(
          "Your current account does not have permission to create upgrade plans.",
        ),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "Create container plan" }),
      ).toBeDisabled();
    } finally {
      authIdentity.privileges = previous;
    }
  });

  it("supports keyboard navigation between the four tabs", async () => {
    mount();
    fireEvent.keyDown(screen.getByRole("tab", { name: "Upgrade Centre" }), {
      key: "ArrowRight",
    });
    expect(
      screen.getByRole("tab", { name: "System Utilities" }),
    ).toHaveAttribute("aria-selected", "true");
    expect(
      await screen.findByRole("heading", { name: "System utility upgrades" }),
    ).toBeInTheDocument();
  });

  it("shows a single-page planner with evidence ticks and saves then submits", async () => {
    mount();

    fireEvent.click(
      screen.getByRole("button", { name: "Explore opportunities" }),
    );
    const create = await screen.findByRole("button", {
      name: "Create container plan",
    });
    await waitFor(() => expect(create).toBeEnabled());
    fireEvent.click(create);
    expect(
      screen.getByRole("heading", {
        name: "Create upgrade plan",
      }),
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
    expect(
      screen.getByText("Independent approval pending").closest("li"),
    ).toHaveClass("check-pending");
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
    fireEvent.click(screen.getByRole("tab", { name: /Plans & Approvals/ }));
    expect(
      screen.getByRole("tab", { name: /Plans & Approvals/ }),
    ).toHaveAttribute("aria-selected", "true");
    expect(
      screen.queryByRole("heading", { name: "1. Cluster & target" }),
    ).not.toBeInTheDocument();
  });

  it.each(["cluster.approve", "cluster.upgrade.approve"])(
    "allows an independent reviewer with %s to review the submitted request",
    async (privilege) => {
      const previousPrivileges = authIdentity.privileges;
      authIdentity.privileges = ["cluster.upgrade.plan", privilege];
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
        expect(
          (await screen.findAllByText(/Awaiting approval/)).length,
        ).toBeGreaterThan(0);
        expect(screen.queryByText("Not scheduled")).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole("tab", { name: /Plans & Approvals/ }));
        fireEvent.click(
          await screen.findByRole("button", { name: "Awaiting my review (1)" }),
        );
        fireEvent.click(
          await screen.findByRole("button", { name: "Review plan" }),
        );
        const drawer = screen.getByRole("dialog", {
          name: "Review upgrade plan",
        });
        expect(
          within(drawer).getByLabelText("Review comment"),
        ).toBeInTheDocument();
        expect(within(drawer).getByText("Ashok Rajendran")).toBeInTheDocument();
        expect(within(drawer).getByText("Submitted at")).toBeInTheDocument();
        expect(
          within(drawer).getByText("Keep cluster supported"),
        ).toBeInTheDocument();
        expect(
          within(drawer)
            .getByText("Independent approval recorded")
            .closest("li"),
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
        authIdentity.privileges = previousPrivileges;
        vi.mocked(clusters.upgradePlans).mockResolvedValue({
          clusterId: "CLU-live",
          customerId: "CUS-live",
          items: [],
        });
      }
    },
  );

  it.each([
    ["new engineer submission", ["cluster.upgrade.plan"], "architect-reviewer"],
    ["engineer resubmission", ["cluster.upgrade.plan"], "original-maker"],
    [
      "reviewer submitting their own plan",
      ["cluster.upgrade.plan", "cluster.upgrade.approve"],
      "architect-reviewer",
    ],
  ])(
    "shows a read-only approval handoff for %s",
    async (_, privileges, creator) => {
      const previousPrivileges = authIdentity.privileges;
      authIdentity.privileges = privileges as string[];
      const original = vi
        .mocked(clusters.upgradePlans)
        .getMockImplementation()!;
      const evidence = await clusters.upgradeReadiness("CLU-live");
      const plan = {
        planId: "UPG-submitted-handoff",
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
        version: 3,
        createdBy: creator,
        submittedBy: "architect-reviewer",
        submittedAt: "2026-11-11T06:00:00Z",
        createdAt: "2026-11-06T10:00:00Z",
        updatedAt: "2026-11-11T06:00:00Z",
        updatedBy: "architect-reviewer",
      } as Awaited<ReturnType<typeof clusters.upgradePlan>>;
      vi.mocked(clusters.upgradePlans).mockResolvedValue({
        clusterId: "CLU-live",
        customerId: "CUS-live",
        items: [plan],
      });
      const originalHistoryState = window.history.state;
      window.history.replaceState({ ...originalHistoryState, __NA: true }, "");
      try {
        mount();
        fireEvent.change(screen.getByLabelText("Search upgrade plans"), {
          target: { value: "UPG-submitted-handoff" },
        });
        fireEvent.click(
          await screen.findByRole("button", { name: "View plan" }),
        );
        const drawer = screen.getByRole("dialog", {
          name: "Upgrade plan details",
        });
        expect(
          within(drawer).getByText(/Submitted for Platform Architect approval/),
        ).toBeInTheDocument();
        expect(
          within(drawer).queryByLabelText("Review comment"),
        ).not.toBeInTheDocument();
        expect(
          within(drawer).queryByRole("button", { name: "Approve plan" }),
        ).not.toBeInTheDocument();
        expect(
          within(drawer).queryByRole("button", { name: "Reject with reason" }),
        ).not.toBeInTheDocument();
        expect(
          within(drawer).queryByText(
            /does not have upgrade approval permission/,
          ),
        ).not.toBeInTheDocument();
        expect(within(drawer).getByText("Customer")).toBeInTheDocument();
        expect(within(drawer).getByText("Environment")).toBeInTheDocument();
        expect(within(drawer).getByText("Cluster")).toBeInTheDocument();
        if (creator === "original-maker") window.history.back();
        else
          fireEvent.click(
            within(drawer).getByRole("button", { name: "Close" }),
          );
        await waitFor(() =>
          expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
        );
        await waitFor(() => expect(window.history.state?.__NA).toBe(true));
        expect(
          screen.getByRole("tab", { name: "Upgrade Centre" }),
        ).toHaveAttribute("aria-selected", "true");
        expect(screen.getByLabelText("Search upgrade plans")).toHaveValue(
          "UPG-submitted-handoff",
        );
      } finally {
        window.history.replaceState(originalHistoryState, "");
        authIdentity.privileges = previousPrivileges;
        vi.mocked(clusters.upgradePlans).mockImplementation(original);
      }
    },
  );

  it("marks an overdue submission inactive and requires a new schedule before review", async () => {
    const evidence = await clusters.upgradeReadiness("CLU-live");
    const overdue = {
      planId: "UPG-overdue",
      clusterId: "CLU-live",
      customerId: "CUS-live",
      provider: "EKS",
      currentVersion: "1.34",
      targetVersion: "1.35",
      strategy: "PROVIDER_MANAGED_ROLLING",
      status: "SUBMITTED",
      scheduledFor: "2020-01-01T08:15:00Z",
      changeReason: "Keep cluster supported",
      readinessEvidence: evidence,
      execution: {},
      version: 2,
      createdBy: "architect-reviewer",
      submittedBy: "architect-reviewer",
      createdAt: "2020-01-01T06:00:00Z",
      updatedAt: "2020-01-01T06:00:00Z",
      updatedBy: "architect-reviewer",
    } as Awaited<ReturnType<typeof clusters.upgradePlan>>;
    vi.mocked(clusters.upgradePlans).mockResolvedValue({
      clusterId: "CLU-live",
      customerId: "CUS-live",
      items: [overdue],
    });
    try {
      mount();
      expect(
        await screen.findByText("1 maintenance request needs a new time"),
      ).toBeInTheDocument();
      const fleet = screen.getByRole("table", {
        name: "Upgrade plans across component types",
      });
      fireEvent.click(
        within(fleet).getByRole("button", { name: "Review & reschedule" }),
      );
      const drawer = screen.getByRole("dialog", {
        name: "Upgrade plan details",
      });
      expect(
        within(drawer).getByText("Overdue · inactive"),
      ).toBeInTheDocument();
      expect(
        within(drawer).queryByRole("button", { name: "Approve plan" }),
      ).not.toBeInTheDocument();
      expect(
        within(drawer).queryByRole("button", { name: "Submit for approval" }),
      ).not.toBeInTheDocument();
      expect(
        within(drawer).getByLabelText("New maintenance start"),
      ).toHaveFocus();
      expect(
        within(drawer).getByRole("button", { name: "Save new schedule" }),
      ).toBeDisabled();
      fireEvent.change(within(drawer).getByLabelText("New maintenance start"), {
        target: { value: "2027-01-01T22:00" },
      });
      vi.mocked(clusters.changeUpgradePlan).mockResolvedValueOnce({
        ...overdue,
        status: "DRAFT",
        scheduledFor: "2027-01-01T22:00:00Z",
      });
      fireEvent.click(
        within(drawer).getByRole("button", { name: "Save new schedule" }),
      );
      await waitFor(() =>
        expect(clusters.changeUpgradePlan).toHaveBeenCalledWith(
          "CLU-live",
          "UPG-overdue",
          "reschedule",
          2,
          undefined,
          new Date("2027-01-01T22:00").toISOString(),
        ),
      );
    } finally {
      vi.mocked(clusters.upgradePlans).mockResolvedValue({
        clusterId: "CLU-live",
        customerId: "CUS-live",
        items: [],
      });
    }
  });

  it("allows an authorized planner to reschedule another users overdue plan", async () => {
    const evidence = await clusters.upgradeReadiness("CLU-live");
    const original = vi.mocked(clusters.upgradePlans).getMockImplementation()!;
    const plan = {
      planId: "UPG-other-owner",
      clusterId: "CLU-live",
      customerId: "CUS-live",
      provider: "EKS",
      currentVersion: "1.34",
      targetVersion: "1.35",
      strategy: "PROVIDER_MANAGED_ROLLING",
      status: "SUBMITTED",
      scheduledFor: "2020-01-01T08:15:00Z",
      changeReason: "Keep cluster supported",
      readinessEvidence: evidence,
      execution: {},
      version: 2,
      createdBy: "other-engineer",
      createdByName: "Plan Creator",
      submittedBy: "other-engineer",
      createdAt: "2020-01-01T06:00:00Z",
      updatedAt: "2020-01-01T06:00:00Z",
      updatedBy: "other-engineer",
    } as Awaited<ReturnType<typeof clusters.upgradePlan>>;
    vi.mocked(clusters.upgradePlans).mockResolvedValue({
      clusterId: "CLU-live",
      customerId: "CUS-live",
      items: [plan],
    });
    try {
      mount();
      const fleet = await screen.findByRole("table", {
        name: "Upgrade plans across component types",
      });
      fireEvent.click(
        await within(fleet).findByRole("button", {
          name: "Review & reschedule",
        }),
      );
      const drawer = screen.getByRole("dialog", {
        name: "Upgrade plan details",
      });
      expect(
        within(drawer).queryByText(/Only the plan creator/),
      ).not.toBeInTheDocument();
      expect(
        within(drawer).getByLabelText("New maintenance start"),
      ).toBeEnabled();
      fireEvent.change(within(drawer).getByLabelText("New maintenance start"), {
        target: { value: "2027-01-01T12:00" },
      });
      expect(
        within(drawer).getByRole("button", { name: "Save new schedule" }),
      ).toBeEnabled();
    } finally {
      vi.mocked(clusters.upgradePlans).mockImplementation(original);
    }
  });

  it.each(["utilities", "containers"])(
    "preserves a calendar date when opening a %s request",
    async (kind) => {
      mount();
      fireEvent.click(
        screen.getByRole("tab", { name: "Maintenance Calendar" }),
      );
      const future = new Date();
      future.setDate(future.getDate() + 1);
      const key = `${future.getFullYear()}-${String(future.getMonth() + 1).padStart(2, "0")}-${String(future.getDate()).padStart(2, "0")}`;
      fireEvent.click(
        await screen.findByRole("button", { name: `Create upgrade on ${key}` }),
      );
      fireEvent.click(
        screen.getByRole("button", {
          name: kind === "utilities" ? "Utility upgrade" : "Container upgrade",
        }),
      );
      if (kind === "utilities") {
        await screen.findByRole("heading", { name: "System utility upgrades" });
        expect(
          (
            screen.getByLabelText(
              "Utility maintenance start",
            ) as HTMLInputElement
          ).value,
        ).toBe(key + "T09:00");
      } else {
        const button = await screen.findByRole("button", {
          name: "Create container plan",
        });
        await waitFor(() => expect(button).toBeEnabled());
        fireEvent.click(button);
        expect(
          (screen.getByLabelText("Maintenance start") as HTMLInputElement)
            .value,
        ).toBe(key + "T09:00");
      }
    },
  );

  it("populates chart targets and persists a utility draft with a reason", async () => {
    const originalPlans = vi
      .mocked(clusters.upgradePlans)
      .getMockImplementation()!;
    const utilityPlan = {
      planId: "UPG-utility",
      clusterId: "CLU-live",
      customerId: "CUS-live",
      kind: "UTILITY",
      status: "DRAFT",
      provider: "EKS",
      strategy: "GITOPS_REVIEW",
      currentVersion: "0.45.0",
      targetVersion: "0.46.0",
      version: 1,
      changeReason: "Upgrade dashboard chart",
      execution: {},
      createdBy: "architect-reviewer",
      updatedBy: "architect-reviewer",
      createdAt: "2026-11-07T10:00:00Z",
      updatedAt: "2026-11-07T10:00:00Z",
      utilityCode: "headlamp",
      managedGroup: "headlamp",
      utilityEvidence: {
        label: "Headlamp",
        chart: "headlamp",
        currentVersion: "0.45.0",
        versions: ["0.46.0"],
        observedAt: "2026-11-07T10:00:00Z",
      },
    } as Awaited<ReturnType<typeof clusters.createUtilityUpgradePlan>>;
    vi.mocked(clusters.createUtilityUpgradePlan).mockImplementationOnce(
      async () => {
        vi.mocked(clusters.upgradePlans).mockResolvedValue({
          clusterId: "CLU-live",
          customerId: "CUS-live",
          items: [utilityPlan],
        });
        return utilityPlan;
      },
    );
    mount();
    fireEvent.click(screen.getByRole("tab", { name: "System Utilities" }));
    const targets = await screen.findByRole("combobox", {
      name: "Requested target version",
    });
    await waitFor(() => expect(targets).toHaveValue("0.46.0"));
    expect(
      screen.getByText(/Chart and application versions can differ/),
    ).toBeInTheDocument();
    expect(await screen.findByText("123456789012")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Utility change reason"), {
      target: { value: "Upgrade dashboard chart" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Create utility upgrade plan" }),
    );
    await waitFor(() =>
      expect(clusters.createUtilityUpgradePlan).toHaveBeenCalledWith(
        "CLU-live",
        {
          utilityCode: "headlamp",
          targetVersion: "0.46.0",
          changeReason: "Upgrade dashboard chart",
        },
      ),
    );
    expect(
      await screen.findByRole("dialog", { name: "Upgrade plan details" }),
    ).toBeInTheDocument();
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Close" }),
    );
    expect(
      screen.getByRole("tab", { name: "System Utilities" }),
    ).toHaveAttribute("aria-selected", "true");
    vi.mocked(clusters.upgradePlans).mockImplementation(originalPlans);
  });

  it("keeps maintenance separate from plans and exposes both calendar views", async () => {
    mount();
    fireEvent.click(screen.getByRole("tab", { name: "Maintenance Calendar" }));
    expect(
      await screen.findByRole("button", { name: "Month" }),
    ).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Week" }));
    expect(
      screen.getByLabelText("Weekly maintenance starts"),
    ).toBeInTheDocument();
    expect(screen.getByText(/Durations are not recorded/)).toBeInTheDocument();
  });
});
