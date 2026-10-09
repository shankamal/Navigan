import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi } from "vitest";
import { ClusterAdminPage } from "@/modules/cluster-management";
import { ClusterMetrics } from "@/modules/cluster-management/cluster-metrics";
import { architect } from "./fixtures";
vi.mock("@/shared/auth/auth-provider", () => ({
  useAuth: () => ({ identity: architect }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/modules/cluster-management/hooks/queries", () => ({
  useClusterCount: (status?: string) => ({
    data: status === "ACTIVE" || status === "DRAFT" ? 1 : status ? 0 : 3,
    isError: false,
  }),
  useClusters: () => ({
    data: {
      items: [
        {
          clusterId: "CLU-one",
          clusterName: "Platform cluster",
          environmentId: "ENV-one",
          environmentName: "Dev baseline",
          environmentApprovedVersion: 9,
          customerId: "CUS-one",
          customerName: "Example customer",
          status: "ACTIVE",
          platform: "AWS_EKS",
          version: 1,
          updatedAt: "2026-10-09T09:00:00Z",
          allowedActions: [],
        },
        {
          clusterId: "CLU-two",
          clusterName: "Failed cluster",
          environmentId: "ENV-one",
          environmentName: "Dev baseline",
          environmentApprovedVersion: 9,
          customerId: "CUS-one",
          customerName: "Example customer",
          status: "FAILED",
          platform: "AWS_EKS",
          version: 1,
          updatedAt: "2026-10-09T09:00:00Z",
          allowedActions: [],
        },
      ],
      pagination: { page: 0, pageSize: 20, totalElements: 2, totalPages: 1 },
    },
    isPending: false,
    isError: false,
    isFetching: false,
    refetch: vi.fn(),
  }),
}));
function mount(mode?: "directory" | "reviews" | "operations") {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <ClusterAdminPage mode={mode} />
    </QueryClientProvider>,
  );
}
describe("Cluster workspace presentation", () => {
  it("preserves status filtering and request navigation across list and board views", () => {
    mount();
    fireEvent.change(
      screen.getByRole("combobox", { name: "Filter by status" }),
      { target: { value: "FAILED" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Board view" }));
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(
      screen.getByRole("combobox", { name: "Filter by status" }),
    ).toHaveValue("FAILED");
    expect(
      screen.getByRole("link", { name: "Failed cluster" }),
    ).toHaveAttribute("href", "/clusters/CLU-two");
    expect(
      screen.getAllByRole("link", { name: /approved v9/ })[0],
    ).toHaveAttribute("href", "/environments/ENV-one");
    expect(
      screen.getByText(/Board shows requests on this page/),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "List view" }));
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(
      screen.getByRole("combobox", { name: "Filter by status" }),
    ).toHaveValue("FAILED");
  });
  it("retains restricted review statuses", () => {
    mount("reviews");
    const status = screen.getByRole("combobox", { name: "Filter by status" });
    expect(status).toHaveValue("SUBMITTED");
    expect(status.querySelector('option[value="ACTIVE"]')).toBeNull();
  });
  it("handles zero totals and includes lifecycle stages outside the main four", () => {
    const onFilter = vi.fn();
    const { container, rerender } = render(
      <ClusterMetrics
        total={0}
        active={0}
        draft={0}
        submitted={0}
        review={0}
        failed={0}
        error={false}
        onFilter={onFilter}
      />,
    );
    expect(container.innerHTML).not.toMatch(/NaN|Infinity/);
    fireEvent.click(screen.getByRole("button", { name: /Failed executions/ }));
    expect(onFilter).toHaveBeenCalledWith("FAILED");
    rerender(
      <ClusterMetrics
        total={3}
        active={1}
        draft={1}
        submitted={0}
        review={0}
        failed={1}
        error={false}
        onFilter={onFilter}
      />,
    );
    expect(screen.getByText("Other stages")).toBeInTheDocument();
  });
});
