import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { WorkspaceScopeProvider } from "@/shared/components/workspace-scope-context";
import { useDashboardData } from "@/modules/dashboard/dashboard-data";
import { engineer } from "./fixtures";
const m = vi.hoisted(() => ({
  customerList: vi.fn(),
  environmentList: vi.fn(),
  clusterList: vi.fn(),
  migrationList: vi.fn(),
  plans: vi.fn(),
  inventory: vi.fn(),
}));
vi.mock("@/shared/auth/auth-provider", () => ({
  useAuth: () => ({ identity: engineer }),
}));
vi.mock("@/modules/customer-management/services/customers", () => ({
  customersService: { list: m.customerList },
}));
vi.mock("@/modules/environment-management/services/environments", () => ({
  environments: { list: m.environmentList },
}));
vi.mock("@/modules/cluster-management/service", () => ({
  clusters: {
    list: m.clusterList,
    upgradePlans: m.plans,
    platformComponents: m.inventory,
  },
}));
vi.mock("@/modules/migration-management/service", () => ({
  migrations: { list: m.migrationList },
}));
const page = (items: unknown[]) => ({ items, pagination: { totalPages: 1 } });
beforeEach(() => {
  window.localStorage.clear();
  vi.clearAllMocks();
  m.customerList.mockResolvedValue(
    page([
      { customerId: "A", status: "ACTIVE" },
      { customerId: "B", status: "ACTIVE" },
    ]),
  );
  m.environmentList.mockResolvedValue(
    page([
      { customerId: "A", environmentId: "EA" },
      { customerId: "B", environmentId: "EB" },
    ]),
  );
  m.clusterList.mockResolvedValue(
    page([
      {
        customerId: "A",
        environmentId: "EA",
        clusterId: "CA",
        status: "ACTIVE",
      },
      {
        customerId: "B",
        environmentId: "EB",
        clusterId: "CB",
        status: "ACTIVE",
      },
    ]),
  );
  m.migrationList.mockResolvedValue(
    page([
      { customerId: "A", migrationId: "MA" },
      { customerId: "B", migrationId: "MB" },
    ]),
  );
  m.plans.mockResolvedValue({ items: [] });
  m.inventory.mockResolvedValue({
    components: [],
    runtimeInventory: { status: "NOT_REPORTED" },
  });
});
function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return renderHook(() => useDashboardData(), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>
        <WorkspaceScopeProvider>{children}</WorkspaceScopeProvider>
      </QueryClientProvider>
    ),
  });
}
it("filters customer/environment/fleet and does not misstate environment migration counts", async () => {
  const { result } = mount();
  await waitFor(() => expect(result.current.fleet).toHaveLength(2));
  act(() => result.current.scope.setCustomerId("A"));
  await waitFor(() => expect(result.current.customers).toHaveLength(1));
  expect(result.current.fleet?.map((c) => c.clusterId)).toEqual(["CA"]);
  expect(result.current.environments?.map((e) => e.environmentId)).toEqual([
    "EA",
  ]);
  expect(result.current.migrations?.map((m) => m.migrationId)).toEqual(["MA"]);
  act(() => result.current.scope.setEnvironmentId("EA"));
  await waitFor(() => expect(result.current.migrations).toBeUndefined());
  expect(result.current.fleet).toHaveLength(1);
});
it("does not publish a partial first-page count after pagination failure", async () => {
  m.customerList.mockImplementation(async ({ page: p }: { page: number }) => {
    if (p === 1) throw Error("page unavailable");
    return { items: [{ customerId: "A" }], pagination: { totalPages: 2 } };
  });
  const { result } = mount();
  await waitFor(() => expect(result.current.errors).toBeGreaterThan(0));
  expect(result.current.customers).toBeUndefined();
  expect(result.current.fleet).toHaveLength(2);
});
