import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SourceConnectionScreen } from "@/modules/migration-management/source-connection-screen";

const api = vi.hoisted(() => ({
  customers: vi.fn(),
  list: vi.fn(),
  get: vi.fn(),
  createSource: vi.fn(),
  createDraft: vi.fn(),
  install: vi.fn(),
  enroll: vi.fn(),
}));
vi.mock("@/modules/customer-management/services/customers", () => ({
  customersService: { list: api.customers },
}));
vi.mock("@/modules/migration-management/service", () => ({
  sourceClusters: {
    list: api.list,
    get: api.get,
    create: api.createSource,
    install: api.install,
    enroll: api.enroll,
  },
  migrations: { create: api.createDraft, get: vi.fn() },
}));
const source = {
  sourceClusterId: "SRC-" + "a".repeat(32),
  customerId: "CUS-demo",
  name: "source-cluster",
  distribution: "Kubernetes",
  status: "CONNECTED",
  version: 1,
  deliveryMethod: "AWS_SSM",
  connectorLastSeenAt: new Date().toISOString(),
};
function open() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <SourceConnectionScreen />
    </QueryClientProvider>,
  );
}
async function identify() {
  await screen.findByRole(
    "option",
    { name: /Demo customer/ },
    { timeout: 5000 },
  );
  fireEvent.change(screen.getByLabelText(/Assessment name/), {
    target: { value: "Payments migration" },
  });
  fireEvent.change(screen.getByLabelText(/Active customer/), {
    target: { value: "CUS-demo" },
  });
}
beforeEach(() => {
  window.history.replaceState({}, "", "/migrations/new");
  vi.clearAllMocks();
  api.customers.mockResolvedValue({
    items: [
      { customerId: "CUS-demo", name: "Demo customer", status: "ACTIVE" },
    ],
    pagination: { totalPages: 1 },
  });
  api.list.mockResolvedValue({ items: [source] });
  api.get.mockResolvedValue(source);
  api.createDraft.mockResolvedValue({
    migrationId: "MIG-demo",
    name: "Payments migration",
    status: "DRAFT",
    version: 1,
  });
});
describe("Source connection screen", () => {
  it("includes the assessment name and only connection inputs", async () => {
    open();
    await identify();
    expect(screen.getByLabelText(/SSM managed instance ID/)).toBeVisible();
    expect(
      screen.queryByLabelText(/Target environment/),
    ).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Cluster location/), {
      target: { value: "ON_PREMISES" },
    });
    expect(screen.queryByLabelText(/AWS account ID/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Kubeconfig path/)).not.toBeInTheDocument();
    expect(
      screen.getByRole("combobox", { name: /Connector delivery method/ }),
    ).toHaveValue("MANUAL_HELM");
  });
  it("loads every active customer page", async () => {
    api.customers.mockImplementation(async ({ page }) => ({
      items: [
        {
          customerId: `CUS-${page}`,
          name: `Customer ${page}`,
          status: "ACTIVE",
        },
      ],
      pagination: { totalPages: 2 },
    }));
    open();
    await screen.findByRole("option", { name: /Customer 1/ });
    expect(api.customers).toHaveBeenCalledTimes(2);
  });
  it("reuses a connected cluster, creates a source-first draft without a target and verifies its heartbeat", async () => {
    open();
    await identify();
    fireEvent.click(screen.getByRole("radio", { name: /Use a connected/ }));
    fireEvent.change(
      await screen.findByLabelText(/^Connected source cluster/),
      { target: { value: source.sourceClusterId } },
    );
    fireEvent.submit(
      screen
        .getByRole("button", { name: /Use source connection/ })
        .closest("form")!,
    );
    await screen.findByRole("button", { name: "Verify connection" });
    const body = api.createDraft.mock.calls[0][0];
    expect(body.name).toBe("Payments migration");
    expect(body.target).toBeUndefined();
    expect(body.source.discoveryMode).toBe("MANUAL");
    expect(api.createSource).not.toHaveBeenCalled();
    expect(api.install).not.toHaveBeenCalled();
    expect(api.enroll).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Verify connection" }));
    await screen.findByText("Connected · recent connector heartbeat verified");
    expect(window.location.search).toContain("draft=MIG-demo");
  });
  it("does not treat enrollment or an old heartbeat as a verified connection", async () => {
    api.get.mockResolvedValue({
      ...source,
      connectorLastSeenAt: "2020-01-01T00:00:00Z",
    });
    open();
    await identify();
    fireEvent.click(screen.getByRole("radio", { name: /Use a connected/ }));
    fireEvent.change(
      await screen.findByLabelText(/^Connected source cluster/),
      { target: { value: source.sourceClusterId } },
    );
    fireEvent.submit(
      screen
        .getByRole("button", { name: /Use source connection/ })
        .closest("form")!,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Verify connection" }),
    );
    await screen.findByText(/Waiting for a recent connector heartbeat/);
    expect(
      screen.queryByText("Connected · recent connector heartbeat verified"),
    ).not.toBeInTheDocument();
  });
  it("retains the registered source if draft creation fails, so retry cannot create another cluster", async () => {
    api.createSource.mockResolvedValue({
      ...source,
      status: "PENDING_ENROLLMENT",
    });
    api.createDraft.mockRejectedValueOnce(new Error("Temporary failure"));
    api.install.mockResolvedValue({ commandId: "command-1" });
    open();
    await identify();
    fireEvent.change(screen.getByLabelText(/Source cluster name/), {
      target: { value: "source-cluster" },
    });
    fireEvent.change(screen.getByLabelText(/AWS region/), {
      target: { value: "ap-south-1" },
    });
    fireEvent.change(screen.getByLabelText(/AWS account ID/), {
      target: { value: "123456789012" },
    });
    fireEvent.change(screen.getByLabelText(/SSM managed instance ID/), {
      target: { value: "i-0123456789abcdef0" },
    });
    const form = screen
      .getByRole("button", { name: /Connect source/ })
      .closest("form")!;
    fireEvent.submit(form);
    await screen.findByRole("alert");
    fireEvent.submit(form);
    await screen.findByRole("button", { name: "Verify connection" });
    expect(api.createSource).toHaveBeenCalledTimes(1);
    expect(api.createDraft.mock.calls[0][1]).toBe(
      api.createDraft.mock.calls[1][1],
    );
  });
});

it("offers reuse for an existing SSM registration without installing a new connector", async () => {
  api.list.mockResolvedValue({
    items: [
      {
        ...source,
        deliveryConfiguration: {
          accountId: "123456789012",
          region: "ap-south-1",
          managedInstanceId: "i-0123456789abcdef0",
          kubeconfigPath: "/etc/kubernetes/admin.conf",
        },
      },
    ],
  });
  open();
  await identify();
  fireEvent.change(screen.getByLabelText(/Source cluster name/), {
    target: { value: "different-display-name" },
  });
  fireEvent.change(screen.getByLabelText(/AWS region/), {
    target: { value: "ap-south-1" },
  });
  fireEvent.change(screen.getByLabelText(/AWS account ID/), {
    target: { value: "123456789012" },
  });
  fireEvent.change(screen.getByLabelText(/SSM managed instance ID/), {
    target: { value: "i-0123456789abcdef0" },
  });
  fireEvent.click(
    await screen.findByRole("button", { name: /Reuse connection/ }),
  );
  expect(screen.getByRole("radio", { name: /Use a connected/ })).toBeChecked();
  fireEvent.submit(
    screen
      .getByRole("button", { name: "Use source connection" })
      .closest("form")!,
  );
  await screen.findByRole("button", { name: "Verify connection" });
  expect(api.createSource).not.toHaveBeenCalled();
  expect(api.install).not.toHaveBeenCalled();
});

it("saves a draft without starting connector installation", async () => {
  api.createSource.mockResolvedValue({
    ...source,
    status: "PENDING_ENROLLMENT",
  });
  open();
  await identify();
  fireEvent.change(screen.getByLabelText(/Source cluster name/), {
    target: { value: "another-source-cluster" },
  });
  fireEvent.change(screen.getByLabelText(/AWS region/), {
    target: { value: "ap-south-1" },
  });
  fireEvent.change(screen.getByLabelText(/AWS account ID/), {
    target: { value: "123456789012" },
  });
  fireEvent.change(screen.getByLabelText(/SSM managed instance ID/), {
    target: { value: "i-0123456789abcdef0" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
  await screen.findByRole("button", { name: "Verify connection" });
  expect(api.createDraft).toHaveBeenCalledTimes(1);
  expect(api.install).not.toHaveBeenCalled();
  expect(api.enroll).not.toHaveBeenCalled();
});

it("shows field-level errors when Save draft is clicked with missing mandatory inputs", async () => {
  open();
  fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Assessment name must contain 8–100 characters.",
  );
  expect(screen.getByLabelText(/Assessment name/)).toHaveAttribute(
    "aria-invalid",
    "true",
  );
  expect(api.createSource).not.toHaveBeenCalled();
  expect(api.createDraft).not.toHaveBeenCalled();
});
