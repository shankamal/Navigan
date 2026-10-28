import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SourceConnectionScreen } from "@/modules/migration-management/source-connection-screen";

const api = vi.hoisted(() => ({
  customers: vi.fn(),
  list: vi.fn(),
  get: vi.fn(),
  createSource: vi.fn(),
  createDraft: vi.fn(),
  getDraft: vi.fn(),
  updateDraft: vi.fn(),
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
  migrations: {
    create: api.createDraft,
    get: api.getDraft,
    update: api.updateDraft,
  },
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
  installationCheck: {
    canRestore: true,
    code: "RESTORE_AVAILABLE",
    message: "Host available",
    conflicts: [],
  },
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
    sourceConfiguration: {
      sourceClusterId: source.sourceClusterId,
      discoveryMode: "MANUAL",
    },
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
    await screen.findByRole("button", { name: "Installation in progress…" });
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

it("restores a draft with editable name and source selection, persists changes without creating another assessment", async () => {
  const draft = {
    migrationId: "MIG-demo",
    name: "Payments migration",
    customerId: "CUS-demo",
    status: "DRAFT",
    version: 3,
    sourceConfiguration: {
      sourceClusterId: source.sourceClusterId,
      discoveryMode: "MANUAL",
    },
  };
  api.getDraft.mockResolvedValue(draft);
  api.updateDraft.mockResolvedValue({
    ...draft,
    name: "Revised migration",
    version: 4,
  });
  window.history.replaceState({}, "", "/migrations/new?draft=MIG-demo");
  open();
  const name = await screen.findByDisplayValue("Payments migration");
  expect(name).toBeEnabled();
  expect(screen.getByRole("radio", { name: /Register a new/ })).toBeEnabled();
  expect(screen.getByLabelText(/^Connected source cluster/)).toBeEnabled();
  fireEvent.change(name, { target: { value: "Revised migration" } });
  fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
  await waitFor(() =>
    expect(api.updateDraft).toHaveBeenCalledWith(
      "MIG-demo",
      expect.objectContaining({
        version: 3,
        name: "Revised migration",
        source: expect.objectContaining({
          sourceClusterId: source.sourceClusterId,
          discoveryMode: "MANUAL",
        }),
      }),
    ),
  );
  expect(api.createDraft).not.toHaveBeenCalled();
  expect(api.createSource).not.toHaveBeenCalled();
  expect(api.install).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("radio", { name: /Register a new/ }));
  expect(screen.getByLabelText(/Source cluster name/)).toBeEnabled();
  expect(screen.getByLabelText(/AWS account ID/)).toBeEnabled();
  expect(screen.getByLabelText(/SSM managed instance ID/)).toBeEnabled();
});

it("shows an established connector message only for the selected customer with a recent heartbeat", async () => {
  open();
  await identify();
  expect(
    await screen.findByText(
      "Connector is already established for this customer",
    ),
  ).toBeVisible();
  fireEvent.click(
    screen.getByRole("button", { name: "Use connected cluster" }),
  );
  expect(screen.getByLabelText(/^Connected source cluster/)).toHaveValue(
    source.sourceClusterId,
  );
  expect(api.install).not.toHaveBeenCalled();
});

it("keeps installation progress steady during polling and replaces Connect source with Verify connection", async () => {
  api.list.mockResolvedValue({ items: [] });
  api.createSource.mockResolvedValue({
    ...source,
    status: "PENDING_ENROLLMENT",
  });
  api.get.mockResolvedValue({ ...source, status: "PENDING_ENROLLMENT" });
  api.install.mockResolvedValue({ commandId: "command-1" });
  open();
  await identify();
  for (const [label, value] of [
    [/Source cluster name/, "new-cluster"],
    [/AWS region/, "ap-south-1"],
    [/AWS account ID/, "123456789012"],
    [/SSM managed instance ID/, "i-0123456789abcdef0"],
  ] as const) {
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  }
  vi.useFakeTimers();
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Connect source" }));
  });
  const progress = screen.getByText("Connector installation in progress");
  expect(
    screen.queryByRole("button", { name: "Connect source" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Installation in progress…" }),
  ).toBeDisabled();
  try {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(screen.getByText("Connector installation in progress")).toBe(
      progress,
    );
    expect(
      screen.getByRole("button", { name: "Installation in progress…" }),
    ).toBeDisabled();
    api.get.mockResolvedValue({
      ...source,
      connectorLastSeenAt: new Date().toISOString(),
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(
      screen.queryByText("Connector installation in progress"),
    ).not.toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: "Verify connection" }),
    ).toHaveLength(1);
    expect(
      screen.getByRole("button", { name: "Verify connection" }),
    ).toBeEnabled();
    expect(api.install).toHaveBeenCalledTimes(1);
  } finally {
    vi.useRealTimers();
  }
});

it("defaults a new assessment to the accessible active DB Schenker record without hardcoding its ID", async () => {
  api.customers.mockResolvedValue({
    items: [
      {
        customerId: "CUS-real-db-record",
        name: "DB Schenker",
        status: "ACTIVE",
      },
    ],
    pagination: { totalPages: 1 },
  });
  open();
  await screen.findByRole("option", { name: "DB Schenker" });
  await waitFor(() =>
    expect(screen.getByLabelText(/Active customer/)).toHaveValue(
      "CUS-real-db-record",
    ),
  );
});

async function saveExistingRegistration() {
  open();
  await identify();
  fireEvent.click(screen.getByRole("radio", { name: /Use a connected/ }));
  fireEvent.change(await screen.findByLabelText(/^Connected source cluster/), {
    target: { value: source.sourceClusterId },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
  await screen.findByRole("button", { name: "Verify connection" });
}

it.each([
  ["INSTALLATION_IN_USE", "Another assessment is using this installation."],
  [
    "OTHER_CUSTOMER_ACCESS_REQUIRED",
    "A platform administrator must resolve the association.",
  ],
  ["INSTALLATION_IN_PROGRESS", "Another installation is in progress."],
  ["FORBIDDEN", "Recovery requires edit access to this customer."],
])(
  "blocks installation and explains %s for an existing registration",
  async (code, message) => {
    const pending = {
      ...source,
      status: "PENDING_ENROLLMENT",
      connectorLastSeenAt: null,
      installationCheck: { canRestore: false, code, message, conflicts: [] },
    };
    api.list.mockResolvedValue({ items: [pending] });
    api.get.mockResolvedValue(pending);
    await saveExistingRegistration();
    expect(await screen.findByText(message)).toBeVisible();
    expect(
      screen.queryByRole("button", {
        name: /Install connector|Restore connector/,
      }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Existing registration selected")).toBeVisible();
    expect(
      screen.queryByText(/The existing connector will be reused/),
    ).not.toBeInTheDocument();
    expect(api.install).not.toHaveBeenCalled();
    expect(api.get).toHaveBeenCalledWith(source.sourceClusterId, true);
  },
);

it("does not treat recoverable conflicts as permission for a normal installation", async () => {
  api.get.mockResolvedValue({
    ...source,
    status: "PENDING_ENROLLMENT",
    installationCheck: {
      canRestore: true,
      code: "RESTORE_AVAILABLE",
      message: "Recovery available",
      conflicts: [
        { sourceClusterId: "SRC-other", customerName: "Other customer" },
      ],
    },
  });
  await saveExistingRegistration();
  expect(
    await screen.findByText(/This host has another source registration/),
  ).toBeVisible();
  expect(
    screen.queryByRole("button", {
      name: /Install connector|Restore connector/,
    }),
  ).not.toBeInTheDocument();
  expect(api.install).not.toHaveBeenCalled();
});

it("fails closed when the host check cannot be loaded and supports retry", async () => {
  api.get.mockImplementation(async (_id, check) => {
    if (check) throw new Error("Unavailable");
    return { ...source, status: "PENDING_ENROLLMENT" };
  });
  await saveExistingRegistration();
  expect(
    await screen.findByText(/Unable to check source host availability/),
  ).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Install connector" }),
  ).not.toBeInTheDocument();
  api.get.mockResolvedValue({
    ...source,
    status: "PENDING_ENROLLMENT",
    installationCheck: undefined,
  });
  fireEvent.click(screen.getByRole("button", { name: "Check host again" }));
  expect(await screen.findByText(/Unable to check this host/)).toBeVisible();
  expect(api.install).not.toHaveBeenCalled();
});

it("rechecks the host before installation and blocks a newly reported conflict", async () => {
  const pending = {
    ...source,
    status: "PENDING_ENROLLMENT",
    connectorLastSeenAt: null,
  };
  api.list.mockResolvedValue({ items: [pending] });
  api.get.mockResolvedValue(pending);
  await saveExistingRegistration();
  const install = await screen.findByRole("button", {
    name: "Install connector",
  });
  api.get.mockResolvedValue({
    ...pending,
    installationCheck: {
      canRestore: false,
      code: "INSTALLATION_IN_USE",
      message: "Host became unavailable",
      conflicts: [],
    },
  });
  fireEvent.click(install);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Host became unavailable",
  );
  expect(api.install).not.toHaveBeenCalled();
});

it("offers restore for a previously connected registration only after a clear host check", async () => {
  api.get.mockResolvedValue({
    ...source,
    connectorLastSeenAt: "2020-01-01T00:00:00Z",
  });
  await saveExistingRegistration();
  expect(
    await screen.findByRole("button", { name: "Restore connector" }),
  ).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Install connector" }),
  ).not.toBeInTheDocument();
  expect(api.install).not.toHaveBeenCalled();
});

it("reuses the matching customer host when Connect source is clicked in registration mode", async () => {
  const existing = {
    ...source,
    deliveryConfiguration: {
      accountId: "123456789012",
      region: "ap-south-1",
      managedInstanceId: "i-0123456789abcdef0",
      kubeconfigPath: "/etc/kubernetes/admin.conf",
    },
  };
  api.list.mockResolvedValue({ items: [existing] });
  api.get.mockResolvedValue(existing);
  open();
  await identify();
  for (const [label, value] of [
    [/Source cluster name/, "new-display-name"],
    [/AWS region/, "ap-south-1"],
    [/AWS account ID/, "123456789012"],
    [/SSM managed instance ID/, "i-0123456789abcdef0"],
  ] as const)
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  await screen.findByRole("button", { name: /Reuse connection/ });
  fireEvent.click(screen.getByRole("button", { name: "Connect source" }));
  await screen.findByRole("button", { name: "Verify connection" });
  expect(api.createDraft).toHaveBeenCalledTimes(1);
  expect(api.createDraft.mock.calls[0][0].source.sourceClusterId).toBe(
    source.sourceClusterId,
  );
  expect(api.createSource).not.toHaveBeenCalled();
  expect(api.install).not.toHaveBeenCalled();
  expect(screen.getByRole("radio", { name: /Use a connected/ })).toBeChecked();
});

it("does not reinstall a live registration returned by backend registration reuse", async () => {
  api.list.mockResolvedValue({ items: [] });
  api.createSource.mockResolvedValue(source);
  api.get.mockResolvedValue({
    ...source,
    connectorLastSeenAt: new Date().toISOString(),
    installationCheck: {
      canRestore: false,
      code: "ALREADY_CONNECTED",
      message: "Already connected",
      conflicts: [],
    },
  });
  open();
  await identify();
  for (const [label, value] of [
    [/Source cluster name/, "new-display-name"],
    [/AWS region/, "ap-south-1"],
    [/AWS account ID/, "123456789012"],
    [/SSM managed instance ID/, "i-0123456789abcdef0"],
  ] as const)
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  fireEvent.click(screen.getByRole("button", { name: "Connect source" }));
  expect(
    await screen.findByText(
      "Existing connector verified and reused. No installation was needed.",
    ),
  ).toBeVisible();
  expect(
    screen.getByRole("button", { name: "Continue to discovery" }),
  ).toBeEnabled();
  expect(api.install).not.toHaveBeenCalled();
});
