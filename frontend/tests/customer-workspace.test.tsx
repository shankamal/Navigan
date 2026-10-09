import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { CustomerListView } from "@/modules/customer-management/components/customer-list";
import { CustomerMetrics } from "@/modules/customer-management/components/customer-metrics";
import { customer, architect } from "./fixtures";
vi.mock("@/shared/auth/auth-provider", () => ({
  useAuth: () => ({ identity: architect }),
}));
vi.mock("@/modules/customer-management/hooks/queries", () => ({
  useCustomerCount: (status?: string) => ({
    data: status === "ACTIVE" ? 1 : status === "DRAFT" ? 1 : status ? 0 : 3,
    isError: false,
    refetch: vi.fn(),
  }),
  useCustomers: () => ({
    data: {
      items: [
        customer,
        {
          ...customer,
          customerId: "approved-id",
          name: "Approved Example",
          status: "APPROVED",
        },
      ],
      pagination: { page: 0, pageSize: 5, totalElements: 2, totalPages: 1 },
    },
    isPending: false,
    isError: false,
    isFetching: false,
    refetch: vi.fn(),
  }),
}));
describe("Customer workspace", () => {
  it("switches views without losing filters and keeps additional lifecycle statuses visible", () => {
    render(<CustomerListView />);
    fireEvent.change(
      screen.getByRole("combobox", { name: "Filter by status" }),
      { target: { value: "APPROVED" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Board" }));
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(
      screen.getByRole("combobox", { name: "Filter by status" }),
    ).toHaveValue("APPROVED");
    const approved = screen.getByRole("region", { name: "Approved customers" });
    expect(
      within(approved).getByRole("link", { name: "View Approved Example" }),
    ).toHaveAttribute("href", "/customers/approved-id");
    expect(
      screen.getByText(/Board shows customers on this page/),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "List" }));
    expect(screen.getByRole("table")).toBeInTheDocument();
  });
  it("uses status shortcuts and exposes labelled record navigation", () => {
    render(<CustomerListView />);
    fireEvent.click(screen.getByRole("button", { name: "Drafts (1)" }));
    expect(
      screen.getByRole("combobox", { name: "Filter by status" }),
    ).toHaveValue("DRAFT");
    expect(
      screen.getByRole("columnheader", { name: "Customer ID" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "View Example Corporation" }),
    ).toHaveTextContent("Open");
    expect(screen.getByRole("button", { name: "Page 1" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    fireEvent.click(screen.getByRole("button", { name: "Board" }));
    expect(
      screen.getByRole("combobox", { name: "Filter by status" }),
    ).toHaveValue("DRAFT");
  });
  it("accounts for statuses beyond the main four in the chart", () => {
    render(
      <CustomerMetrics
        total={3}
        active={1}
        draft={1}
        submitted={0}
        review={0}
        failed={false}
      />,
    );
    expect(screen.getByText("Other statuses")).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: "Active customers: 1 of 3" }),
    ).toBeInTheDocument();
  });
  it("renders zero totals without invalid graph values", () => {
    const { container } = render(
      <CustomerMetrics
        total={0}
        active={0}
        draft={0}
        submitted={0}
        review={0}
        failed={false}
      />,
    );
    expect(screen.getByText("0%")).toBeInTheDocument();
    expect(container.innerHTML).not.toMatch(/NaN|Infinity/);
  });
});
