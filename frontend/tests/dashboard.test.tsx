import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DashboardPage } from "@/modules/dashboard";
import { customersService } from "@/modules/customer-management/services/customers";
import { environments } from "@/modules/environment-management/services/environments";
import { clusters } from "@/modules/cluster-management/service";

const pagination = { page: 0, pageSize: 1, totalElements: 0, totalPages: 0 };

function wrap(component: React.ReactNode) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: { queries: { retry: false } },
        })
      }
    >
      {component}
    </QueryClientProvider>,
  );
}

describe("Dashboard", () => {
  it("renders the platform overview heading with live counts", async () => {
    vi.spyOn(customersService, "list").mockResolvedValue({
      items: [],
      pagination: { ...pagination, totalElements: 4 },
    });
    vi.spyOn(environments, "list").mockResolvedValue({
      items: [],
      pagination: { ...pagination, totalElements: 2 },
    });
    vi.spyOn(clusters, "list").mockResolvedValue({
      items: [],
      pagination: { ...pagination, totalElements: 1 },
    });
    wrap(<DashboardPage />);
    expect(
      await screen.findByRole("heading", { name: "Platform overview" }),
    ).toBeInTheDocument();
    expect(await screen.findAllByText("4")).not.toHaveLength(0);
  });
});
