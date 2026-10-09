import { fireEvent, render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { EnvironmentList } from "@/modules/environment-management/components/environment-list";
import { architect } from "./fixtures";
vi.mock("@/shared/auth/auth-provider", () => ({
  useAuth: () => ({ identity: architect }),
}));
const listQuery = vi.fn(() => ({
  data: {
    items: [
      {
        environmentId: "env-active",
        environmentName: "AWS baseline",
        customerId: "customer-one",
        customerName: "Example customer",
        cloudProvider: "AWS",
        kubernetesDistribution: "EKS",
        environmentType: "DEV",
        status: "ACTIVE",
        version: 3,
        createdAt: "2026-10-09T10:00:00Z",
      },
      {
        environmentId: "env-suspended",
        environmentName: "Suspended baseline",
        customerId: "customer-one",
        customerName: "Example customer",
        cloudProvider: "AZURE",
        kubernetesDistribution: "AKS",
        environmentType: "UAT",
        status: "SUSPENDED",
        version: 2,
        createdAt: "2026-10-09T10:00:00Z",
      },
    ],
    pagination: { page: 0, pageSize: 20, totalElements: 2, totalPages: 1 },
  },
  isPending: false,
  error: null,
  refetch: vi.fn(),
}));
vi.mock("@/modules/environment-management/hooks/queries", () => ({
  useEnvironments: (...args: unknown[]) => listQuery(...(args as [])),
  useEnvironmentCount: (status?: string) => ({
    data: status === "ACTIVE" ? 1 : status ? 0 : 2,
  }),
  useMetadata: () => ({ data: { environmentTypes: ["DEV", "UAT"] } }),
}));
describe("Environment UI preserves existing interactions", () => {
  it("keeps filters and record links when switching display modes, including suspended records", () => {
    render(<EnvironmentList />);
    fireEvent.change(screen.getByRole("combobox", { name: "Cloud provider" }), {
      target: { value: "AZURE" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Board view" }));
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(
      screen.getByRole("combobox", { name: "Cloud provider" }),
    ).toHaveValue("AZURE");
    expect(
      screen.getByRole("link", { name: "Suspended baseline" }),
    ).toHaveAttribute("href", "/environments/env-suspended");
    expect(screen.getAllByText("1 on this page")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "List view" }));
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(
      screen.getByRole("combobox", { name: "Cloud provider" }),
    ).toHaveValue("AZURE");
  });
  it("retains the restricted review queue and status filters", () => {
    render(<EnvironmentList mode="reviews" />);
    expect(
      screen.queryByRole("link", { name: "New Environment" }),
    ).not.toBeInTheDocument();
    const status = screen.getByRole("combobox", { name: "Status" });
    expect(status).toHaveValue("SUBMITTED");
    expect(status.querySelector('option[value="ACTIVE"]')).toBeNull();
    fireEvent.change(status, { target: { value: "UNDER_REVIEW" } });
    expect(status).toHaveValue("UNDER_REVIEW");
  });
});
