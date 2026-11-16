import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PlatformDashboard } from "@/modules/dashboard/platform-dashboard";
import { useDashboardData } from "@/modules/dashboard/dashboard-data";
import {
  WorkspacePageProvider,
  useWorkspacePage,
} from "@/shared/components/workspace-page-context";
import { engineer } from "./fixtures";
vi.mock("@/modules/dashboard/dashboard-data", async (original) => ({
  ...(await original<typeof import("@/modules/dashboard/dashboard-data")>()),
  useDashboardData: vi.fn(),
}));
const refresh = vi.fn();
let data: ReturnType<typeof useDashboardData>;
function HeaderHost() {
  const { setHeaderTarget } = useWorkspacePage();
  return (
    <header aria-label="Unified header">
      <nav aria-label="Breadcrumb">Home / Platform Dashboard</nav>
      <div ref={setHeaderTarget} />
    </header>
  );
}
beforeEach(() => {
  refresh.mockReset().mockResolvedValue([]);
  data = {
    identity: engineer,
    scope: { customerId: "all", environmentId: "all" },
    customers: [{ customerId: "CUS-1", name: "DB Schenker", status: "ACTIVE" }],
    environments: [
      {
        environmentId: "ENV-1",
        customerId: "CUS-1",
        environmentName: "Production",
        cloudProvider: "AWS",
        status: "ACTIVE",
      },
    ],
    fleet: [
      {
        clusterId: "CLU-1",
        clusterName: "demo-cluster",
        customerId: "CUS-1",
        customerName: "DB Schenker",
        environmentId: "ENV-1",
        environmentName: "Production",
        status: "ACTIVE",
        configuration: { kubernetesVersion: "1.30" },
      },
    ],
    migrations: [
      {
        migrationId: "MIG-1",
        customerName: "DB Schenker",
        name: "Payments migration",
        status: "DISCOVERY_IN_PROGRESS",
      },
    ],
    planRows: [],
    inventories: new Map(),
    plansComplete: true,
    inventoriesComplete: false,
    pending: false,
    refreshing: false,
    errors: 0,
    updatedAt: Date.now(),
    refresh,
  } as unknown as ReturnType<typeof useDashboardData>;
  vi.mocked(useDashboardData).mockImplementation(() => data);
});
describe("Operational platform dashboard", () => {
  it("puts eight capability KPIs first, with planned capabilities explicit", () => {
    render(<PlatformDashboard />);
    const kpis = screen.getByRole("region", { name: "Navigan platform KPIs" });
    expect(within(kpis).getAllByRole("link")).toHaveLength(8);
    expect(within(kpis).getAllByText("Planned")).toHaveLength(2);
    for (const name of [
      "Customers",
      "Environments",
      "Clusters",
      "Migrations",
      "Cluster Onboarding",
      "App Modernization",
      "Upgrades & Patching",
      "System Utilities",
    ])
      expect(within(kpis).getByRole("heading", { name })).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "Capability coverage" }),
    ).not.toBeInTheDocument();
  });
  it("uses separate provider and health donuts and never infers health from ACTIVE", () => {
    render(<PlatformDashboard />);
    expect(
      screen.getByRole("img", {
        name: "Environment profiles by cloud provider",
      }),
    ).toBeInTheDocument();
    const health = screen.getByRole("region", { name: "Estate health" });
    expect(within(health).getByText("Unverified")).toBeInTheDocument();
    const landscape = screen.getByRole("region", {
      name: "Cluster & environment landscape",
    });
    expect(within(landscape).getByText("Unverified")).toBeInTheDocument();
    expect(within(landscape).queryByText("Ready")).not.toBeInTheDocument();
  });
  it("renders breadcrumbs and title inside the same header target", () => {
    render(
      <WorkspacePageProvider>
        <HeaderHost />
        <PlatformDashboard />
      </WorkspacePageProvider>,
    );
    const header = screen.getByRole("banner", { name: "Unified header" });
    expect(
      within(header).getByRole("navigation", { name: "Breadcrumb" }),
    ).toBeInTheDocument();
    expect(
      within(header).getByRole("heading", { name: "Platform Command Centre" }),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole("heading", { name: "Platform Command Centre" }),
    ).toHaveLength(1);
  });
  it("shows unavailable totals instead of misleading zero after a source failure", () => {
    data = { ...data, customers: undefined, plansComplete: false, errors: 1 };
    render(<PlatformDashboard />);
    const kpis = screen.getByRole("region", { name: "Navigan platform KPIs" });
    expect(within(kpis).getAllByText("—").length).toBeGreaterThanOrEqual(3);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Some data unavailable",
    );
    expect(
      screen.getByRole("region", { name: "Upcoming Maintenance & Changes" }),
    ).toHaveTextContent("incomplete or unavailable");
  });
  it("opens exact request, cluster and migration links without write actions", () => {
    render(<PlatformDashboard />);
    expect(screen.getByRole("link", { name: "View cluster" })).toHaveAttribute(
      "href",
      "/clusters/CLU-1",
    );
    expect(
      screen.getByRole("link", { name: "Discovery in progress" }),
    ).toHaveAttribute("href", "/migrations/MIG-1");
    expect(
      screen.getByRole("link", { name: "View maintenance calendar" }),
    ).toHaveAttribute("href", "/upgrades?tab=schedule");
  });
  it("refreshes every source and announces refresh failure", async () => {
    refresh.mockRejectedValue(Error("offline"));
    render(<PlatformDashboard />);
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(
        "Some data unavailable",
      ),
    );
    expect(refresh).toHaveBeenCalledOnce();
  });
  it("keeps environment-level migration count unavailable when association is unknown", () => {
    data = {
      ...data,
      scope: { ...data.scope, environmentId: "ENV-1" },
      migrations: undefined,
    };
    render(<PlatformDashboard />);
    expect(
      screen.getAllByText("Environment-level migration totals unavailable")
        .length,
    ).toBeGreaterThan(0);
  });
  it("includes scheduled changes but preserves submitted approval state", () => {
    data = {
      ...data,
      planRows: [
        {
          cluster: data.fleet![0],
          plan: {
            planId: "P-1",
            kind: "CONTAINER",
            status: "SUBMITTED",
            scheduledFor: new Date(Date.now() + 86400000).toISOString(),
            execution: {},
          },
        },
      ] as ReturnType<typeof useDashboardData>["planRows"],
    };
    render(<PlatformDashboard />);
    const maintenance = screen.getByRole("region", {
      name: "Upcoming Maintenance & Changes",
    });
    expect(within(maintenance).getByText("Submitted")).toBeInTheDocument();
    expect(within(maintenance).queryByText("Approved")).not.toBeInTheDocument();
    expect(
      within(maintenance).getByRole("link", { name: "Cluster upgrade" }),
    ).toHaveAttribute("href", "/upgrades?plan=P-1");
    expect(
      within(maintenance).queryByRole("button", { name: /execute|start/i }),
    ).not.toBeInTheDocument();
  });
});
