import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PlatformDashboard } from "@/modules/dashboard/platform-dashboard";
import { architect } from "./fixtures";
const mocks = vi.hoisted(() => ({ refresh: vi.fn() }));
const query = (data: unknown) => ({
  data,
  isPending: false,
  isFetching: false,
  error: null,
  dataUpdatedAt: 1791519000000,
  refetch: mocks.refresh,
});
vi.mock("@/shared/auth/auth-provider", () => ({
  useAuth: () => ({ identity: architect }),
}));
vi.mock("@/modules/customer-management/hooks/queries", () => ({
  useCustomerCount: (s?: string) => query(s === "ACTIVE" ? 6 : s ? 0 : 18),
  useCustomers: () => query({ items: [] }),
}));
vi.mock("@/modules/environment-management/hooks/queries", () => ({
  useEnvironmentCount: (s?: string) => query(s === "ACTIVE" ? 4 : s ? 0 : 6),
  useEnvironments: () => query({ items: [] }),
}));
vi.mock("@/modules/cluster-management/hooks/queries", () => ({
  useClusterCount: (s?: string) => query(s === "ACTIVE" ? 2 : s ? 0 : 4),
  useClusters: () => query({ items: [] }),
}));
describe("Dashboard navigation and freshness", () => {
  beforeEach(() => {
    mocks.refresh.mockReset().mockResolvedValue({ data: {} });
  });
  it("opens exact filters for active records and failed operations", () => {
    render(<PlatformDashboard />);
    expect(
      screen.getByRole("link", { name: /Onboarded customers/ }),
    ).toHaveAttribute("href", "/customers?status=ACTIVE");
    expect(
      screen.getByRole("link", { name: /Governed environments/ }),
    ).toHaveAttribute("href", "/environments?status=ACTIVE");
    expect(
      screen.getByRole("link", { name: /Active clusters/ }),
    ).toHaveAttribute("href", "/clusters?status=ACTIVE");
    expect(
      screen.getByRole("link", { name: /Failed operations/ }),
    ).toHaveAttribute("href", "/clusters?status=FAILED");
    expect(
      screen.getByRole("link", { name: /Awaiting action/ }),
    ).toHaveAttribute("href", "#dashboard-attention");
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
  });
  it("refreshes counts and supporting sections together", async () => {
    render(<PlatformDashboard />);
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(mocks.refresh).toHaveBeenCalledTimes(20));
    expect(screen.getByRole("status")).toHaveTextContent("Updated");
  });
  it("announces failed refreshes instead of implying all data is current", async () => {
    mocks.refresh.mockRejectedValue(new Error("Network unavailable"));
    render(<PlatformDashboard />);
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(
        "Some data could not be refreshed",
      ),
    );
  });
});
