import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CustomerForm } from "@/modules/customer-management/components/customer-form";
import { customersService } from "@/modules/customer-management/services/customers";
import { customer } from "./fixtures";
const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/shared/auth/session", () => ({
  accessToken: vi.fn(),
  authConfigured: false,
  authManager: vi.fn(),
}));
function wrap(component: React.ReactNode) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: {
            queries: { retry: false },
            mutations: { retry: false },
          },
        })
      }
    >
      {component}
    </QueryClientProvider>,
  );
}
describe("Customer forms", () => {
  it("requires the customer name and preserves an incomplete draft", async () => {
    const create = vi
      .spyOn(customersService, "create")
      .mockResolvedValue(customer);
    wrap(<CustomerForm />);
    fireEvent.click(screen.getByRole("button", { name: "Save as draft" }));
    expect(
      await screen.findByText("Enter the customer name."),
    ).toBeInTheDocument();
    expect(create).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText(/Customer name/), {
      target: { value: "Example Corporation" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save as draft" }));
    await waitFor(() =>
      expect(create).toHaveBeenCalledWith(
        {
          name: "Example Corporation",
          description: null,
          contacts: [],
          cloudProviders: [],
        },
        expect.objectContaining({ key: expect.any(String) }),
      ),
    );
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith(`/customers/${customer.customerId}`),
    );
  });
  it("edits master data with If-Match version while leaving provider associations separate", async () => {
    const update = vi
      .spyOn(customersService, "update")
      .mockResolvedValue({ ...customer, version: 5 });
    wrap(<CustomerForm customer={customer} />);
    fireEvent.change(screen.getByLabelText(/Customer name/), {
      target: { value: "Renamed customer" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(update).toHaveBeenCalled());
    expect(update.mock.calls[0][1]).not.toHaveProperty("cloudProviders");
    expect(update.mock.calls[0][2]).toEqual({
      key: expect.any(String),
      version: 4,
    });
  });
  it("reuses the idempotency key on an identical manual retry after a failed write", async () => {
    const create = vi
      .spyOn(customersService, "create")
      .mockRejectedValueOnce(new Error("Network failed"))
      .mockResolvedValue(customer);
    wrap(<CustomerForm />);
    fireEvent.change(screen.getByLabelText(/Customer name/), {
      target: { value: "Retry customer" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save as draft" }));
    await screen.findByText("Network failed");
    fireEvent.click(screen.getByRole("button", { name: "Save as draft" }));
    await waitFor(() => expect(create).toHaveBeenCalledTimes(2));
    expect(create.mock.calls[0][1].key).toBe(create.mock.calls[1][1].key);
  });
});
