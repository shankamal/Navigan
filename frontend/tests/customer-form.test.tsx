import {
  afterAll,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CustomerForm } from "@/modules/customer-management/components/customer-form";
import { customersService } from "@/modules/customer-management/services/customers";
import { customer } from "./fixtures";
const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/shared/auth/session", () => ({
  accessToken: vi.fn(),
  authConfigured: false,
  clearSession: vi.fn(),
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

describe("Customer onboarding workspace", () => {
  // jsdom does not implement native modal dialog methods.
  const originalShow = HTMLDialogElement.prototype.showModal;
  const originalClose = HTMLDialogElement.prototype.close;
  beforeAll(() => {
    HTMLDialogElement.prototype.showModal = function () {
      this.setAttribute("open", "");
    };
    HTMLDialogElement.prototype.close = function () {
      this.removeAttribute("open");
    };
  });
  afterAll(() => {
    HTMLDialogElement.prototype.showModal = originalShow;
    HTMLDialogElement.prototype.close = originalClose;
  });
  beforeEach(() => vi.restoreAllMocks());

  function startContact(name = "Alex Morgan") {
    fireEvent.click(screen.getByRole("button", { name: "Add contact" }));
    fireEvent.change(screen.getByLabelText(/Full name/), {
      target: { value: name },
    });
  }
  function addContact(name = "Alex Morgan") {
    startContact(name);
    fireEvent.click(screen.getByRole("button", { name: "Add to customer" }));
  }
  it("counts only validated, added primary contacts toward readiness", async () => {
    wrap(<CustomerForm />);
    fireEvent.change(screen.getByLabelText(/Customer name/), {
      target: { value: "Northstar" },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: /AWS.*Amazon/ }));
    startContact();
    expect(
      within(
        screen.getByRole("list", { name: "Completion checklist" }),
      ).getByText(/Primary contact/),
    ).toHaveTextContent("Pending");
    fireEvent.change(screen.getByLabelText(/Email \(optional\)/), {
      target: { value: "invalid" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add to customer" }));
    expect(
      await screen.findByText("Enter a valid email address."),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("list", { name: "Added contacts" }),
    ).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Email \(optional\)/), {
      target: { value: " alex@example.com " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add to customer" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Complete for review.",
    );
    expect(screen.getByText("alex@example.com")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Remove contact Alex Morgan" }),
    );
    expect(screen.getByRole("status")).not.toHaveTextContent(
      "Complete for review.",
    );
  });
  it("keeps added values when a contact edit is cancelled and updates readiness after changing its type", () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    wrap(<CustomerForm />);
    addContact();
    fireEvent.click(
      screen.getByRole("button", { name: "Edit contact Alex Morgan" }),
    );
    fireEvent.change(screen.getByLabelText(/Full name/), {
      target: { value: "Changed" },
    });
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "Cancel",
      }),
    );
    expect(screen.getByText("Alex Morgan")).toBeInTheDocument();
    expect(screen.queryByText("Changed")).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Edit contact Alex Morgan" }),
    );
    fireEvent.change(screen.getByLabelText("Contact type"), {
      target: { value: "TECHNICAL" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Update contact" }));
    expect(
      within(
        screen.getByRole("list", { name: "Completion checklist" }),
      ).getByText(/Primary contact/),
    ).toHaveTextContent("Pending");
    expect(
      screen.getByRole("list", { name: "Added contacts" }),
    ).toHaveTextContent("Technical");
  });
  it("preserves all provider selections and normalized contacts in the existing create request", async () => {
    const create = vi
      .spyOn(customersService, "create")
      .mockResolvedValue(customer);
    wrap(<CustomerForm />);
    fireEvent.change(screen.getByLabelText(/Customer name/), {
      target: { value: "Northstar" },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: /AWS.*Amazon/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Azure.*Microsoft/ }));
    addContact(" Alex Morgan ");
    fireEvent.click(screen.getByRole("button", { name: "Save as draft" }));
    await waitFor(() =>
      expect(create).toHaveBeenCalledWith(
        {
          name: "Northstar",
          description: null,
          cloudProviders: ["AWS", "AZURE"],
          contacts: [
            { type: "PRIMARY", name: "Alex Morgan", email: null, phone: null },
          ],
        },
        expect.objectContaining({ key: expect.any(String) }),
      ),
    );
    expect(
      within(
        screen.getByRole("list", { name: "Selected cloud providers" }),
      ).getAllByRole("listitem"),
    ).toHaveLength(2);
  });
  it("clears the editor for another contact and never marks an empty contact complete", () => {
    wrap(<CustomerForm />);
    fireEvent.click(screen.getByRole("button", { name: "Add contact" }));
    fireEvent.click(screen.getByRole("button", { name: "Add to customer" }));
    expect(screen.getByText("Enter the contact name.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Full name/), {
      target: { value: "Alex" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add to customer" }));
    fireEvent.click(screen.getByRole("button", { name: "Add contact" }));
    expect(screen.getByLabelText(/Full name/)).toHaveValue("");
    expect(screen.getByLabelText("Contact type")).toHaveValue("TECHNICAL");
  });
  it("warns before discarding dirty customer changes but does not warn after a successful save", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    vi.spyOn(customersService, "create").mockResolvedValue(customer);
    wrap(<CustomerForm />);
    const cleanUnload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(cleanUnload);
    expect(cleanUnload.defaultPrevented).toBe(false);
    fireEvent.change(screen.getByLabelText(/Customer name/), {
      target: { value: "Northstar" },
    });
    const dirtyUnload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(dirtyUnload);
    expect(dirtyUnload.defaultPrevented).toBe(true);
    const click = new MouseEvent("click", { bubbles: true, cancelable: true });
    screen.getByRole("link", { name: "Cancel" }).dispatchEvent(click);
    expect(confirm).toHaveBeenCalledOnce();
    expect(click.defaultPrevented).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Save as draft" }));
    await waitFor(() =>
      expect(screen.queryByText("Unsaved changes")).not.toBeInTheDocument(),
    );
    const savedUnload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(savedUnload);
    expect(savedUnload.defaultPrevented).toBe(false);
  });
});
