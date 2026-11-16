import { fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { EksUpgradePlan } from "@/modules/cluster-management/model";
import { SystemUtilitiesWorkspace } from "@/modules/upgrade-management/system-utilities-workspace";

const fixture = vi.hoisted(() => ({
  plans: [] as EksUpgradePlan[],
  pending: false,
  error: undefined as string | undefined,
  canPlan: true,
  cluster: {
    clusterId: "CLU-example",
    customerId: "CUS-example",
    environmentId: "ENV-example",
    clusterName: "Example cluster",
    environmentName: "Example environment",
    status: "ACTIVE",
    platform: "EKS",
  },
}));
vi.mock("@/shared/auth/auth-provider", () => ({
  useAuth: () => ({
    identity: { subject: "example-user", authorizationRevision: 1 },
  }),
}));
vi.mock("@/shared/auth/permissions", () => ({
  hasPermission: () => fixture.canPlan,
}));
vi.mock("@/shared/components/workspace-scope-context", () => ({
  useOptionalWorkspaceScope: () => null,
}));
vi.mock("@/modules/upgrade-management/upgrade-plan-data", () => ({
  useUpgradePlans: () => ({
    fleet: [fixture.cluster],
    rows: fixture.plans.map((plan) => ({ plan })),
    stateForCluster: () => ({ pending: fixture.pending, error: fixture.error }),
    pending: fixture.pending,
    errors: [],
    refresh: vi.fn(),
  }),
}));
vi.mock("@/modules/cluster-management/service", () => ({
  clusters: {
    platformComponents: async () => ({
      clusterId: "CLU-example",
      observedAt: new Date().toISOString(),
      components: ["headlamp", "grafana", "prometheus"].map(
        (componentCode) => ({
          componentCode,
          status: "READY",
          syncStatus: "Synced",
          healthStatus: "Healthy",
          version: componentCode === "headlamp" ? "0.45.0" : "89.2.4",
          observedAt: new Date().toISOString(),
        }),
      ),
    }),
    utilityUpgradeOptions: async () => ({
      versions: ["0.46.0"],
      releaseStatus: "UPDATE_AVAILABLE",
    }),
  },
}));

function plan(overrides: Partial<EksUpgradePlan> = {}): EksUpgradePlan {
  return {
    planId: "UPG-example",
    clusterId: "CLU-example",
    customerId: "CUS-example",
    provider: "EKS",
    kind: "UTILITY",
    utilityCode: "headlamp",
    managedGroup: "headlamp",
    status: "DRAFT",
    currentVersion: "0.45.0",
    targetVersion: "0.46.0",
    strategy: "GITOPS_REVIEW",
    scheduledFor: null,
    changeReason: "Example upgrade",
    execution: {},
    version: 1,
    createdBy: "example-user",
    updatedBy: "example-user",
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    ...overrides,
  };
}
function mount() {
  const onReview = vi.fn();
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const tree = () => (
    <QueryClientProvider client={client}>
      <SystemUtilitiesWorkspace onReview={onReview} />
    </QueryClientProvider>
  );
  const rendered = render(tree());
  return { onReview, rerender: () => rendered.rerender(tree()) };
}
async function rowFor(label: string) {
  const labelNode = await screen.findByText(label, { selector: "strong" });
  return within(labelNode.closest("tr")!);
}

beforeEach(() => {
  fixture.plans = [];
  fixture.pending = false;
  fixture.error = undefined;
  fixture.canPlan = true;
});
describe("installed utility plan actions", () => {
  it.each([
    "DRAFT",
    "SUBMITTED",
    "APPROVED",
    "SCHEDULED",
    "EXECUTING",
  ] as const)(
    "opens the existing %s plan instead of creating another",
    async (status) => {
      fixture.plans = [plan({ status })];
      const { onReview } = mount();
      const row = await rowFor("Headlamp");
      expect(
        row.queryByRole("button", { name: "Plan upgrade" }),
      ).not.toBeInTheDocument();
      const review = row.getByRole("button", { name: "Review plan" });
      expect(review).toHaveClass("button-primary");
      fireEvent.click(review);
      expect(onReview).toHaveBeenCalledWith("UPG-example");
    },
  );
  it.each(["SUCCEEDED", "FAILED", "REJECTED", "CANCELLED"] as const)(
    "allows another plan after %s",
    async (status) => {
      fixture.plans = [plan({ status })];
      mount();
      expect(
        (await rowFor("Headlamp")).getByRole("button", {
          name: "Plan upgrade",
        }),
      ).toBeEnabled();
    },
  );
  it("switches the row action when the plan inventory updates", async () => {
    const page = mount();
    expect(
      (await rowFor("Headlamp")).getByRole("button", { name: "Plan upgrade" }),
    ).toBeEnabled();
    fixture.plans = [plan({ status: "SUBMITTED" })];
    page.rerender();
    expect(
      (await rowFor("Headlamp")).getByRole("button", { name: "Review plan" }),
    ).toBeEnabled();
  });
  it("matches a Prometheus plan to the shared monitoring chart", async () => {
    fixture.plans = [
      plan({
        utilityCode: "prometheus",
        managedGroup: "kube-prometheus-stack",
        status: "SUBMITTED",
      }),
    ];
    const { onReview } = mount();
    fireEvent.click(
      (await rowFor("Monitoring stack")).getByRole("button", {
        name: "Review plan",
      }),
    );
    expect(onReview).toHaveBeenCalledWith("UPG-example");
    expect(
      (await rowFor("Headlamp")).getByRole("button", { name: "Plan upgrade" }),
    ).toBeEnabled();
  });
  it.each([
    { clusterId: "CLU-other" },
    { managedGroup: "kube-prometheus-stack" },
    { kind: "CONTAINER" as const },
  ])("does not attach an unrelated plan: %j", async (overrides) => {
    fixture.plans = [plan(overrides)];
    mount();
    expect(
      (await rowFor("Headlamp")).getByRole("button", { name: "Plan upgrade" }),
    ).toBeEnabled();
  });
  it.each(["loading", "error"])(
    "does not offer a new plan while plan inventory is %s",
    async (state) => {
      fixture.pending = state === "loading";
      fixture.error = state === "error" ? "Unavailable" : undefined;
      mount();
      const row = await rowFor("Headlamp");
      expect(row.getByRole("button")).toBeDisabled();
      expect(
        row.queryByRole("button", { name: "Plan upgrade" }),
      ).not.toBeInTheDocument();
    },
  );
  it("also offers Review plan in the catalogue without requiring create permission", async () => {
    fixture.plans = [plan({ status: "APPROVED" })];
    fixture.canPlan = false;
    const { onReview } = mount();
    await rowFor("Headlamp");
    fireEvent.click(screen.getByRole("button", { name: "Catalogue" }));
    fireEvent.click(
      within(
        screen.getByRole("complementary", { name: "Utility details" }),
      ).getByRole("button", { name: "Review plan" }),
    );
    expect(onReview).toHaveBeenCalledWith("UPG-example");
  });
});
