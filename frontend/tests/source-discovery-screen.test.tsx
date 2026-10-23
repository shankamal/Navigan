import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { SourceDiscoveryScreen } from "@/modules/migration-management/source-discovery-screen";
import { deploymentDiscovery } from "@/modules/migration-management/deployment-evidence-service";
import { sourceWorkspaceReady } from "@/modules/migration-management/source-discovery-state";
vi.mock("@/modules/migration-management/deployment-evidence-service", () => ({
  deploymentDiscovery: {
    evidence: vi.fn().mockResolvedValue({
      inventoryDigest: "a".repeat(64),
      workloads: [],
      repositories: [],
      images: [],
      limitations: [],
    }),
    settings: vi.fn().mockResolvedValue({
      version: 2,
      readyForDiscovery: true,
      configuration: { repositories: [], registries: [] },
      githubOrganizations: [],
    }),
  },
}));
const api = vi.hoisted(() => ({
  get: vi.fn(),
  catalogue: vi.fn(),
  inventory: vi.fn(),
  assessment: vi.fn(),
  source: vi.fn(),
  customer: vi.fn(),
  discover: vi.fn(),
  assess: vi.fn(),
  install: vi.fn(),
}));
vi.mock("@/modules/customer-management/services/customers", () => ({
  customersService: { detail: api.customer },
}));
vi.mock("@/modules/migration-management/service", () => ({
  migrations: {
    get: api.get,
    sourceCatalogue: api.catalogue,
    sourceInventory: api.inventory,
    assessment: api.assessment,
    discover: api.discover,
    assess: api.assess,
  },
  sourceClusters: { get: api.source, install: api.install },
}));
const migration = {
  migrationId: "MIG-demo",
  name: "DB source assessment",
  customerId: "CUS-db",
  version: 6,
  status: "ASSESSMENT_READY",
  sourceConfiguration: { sourceClusterId: "SRC-db", discoveryMode: "MANUAL" },
  targetConfiguration: {},
  migrationScope: {},
};
const inventory = {
  inventoryVersion: 1,
  migrationVersion: 4,
  inventoryDigest: "a".repeat(64),
  resourceCount: 1,
  resources: [
    {
      apiVersion: "apps/v1",
      kind: "Deployment",
      namespace: "payments",
      name: "api",
    },
  ],
  sourceKubernetesVersion: "1.34",
  observedAt: "2026-10-18T17:00:00Z",
};
const assessment = {
  migrationVersion: 4,
  inventoryDigest: "a".repeat(64),
  findings: [],
  inventorySummary: {
    assessmentMode: "SOURCE_ONLY",
    sourceClusterId: "SRC-db",
  },
};
function open() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <SourceDiscoveryScreen migrationId="MIG-demo" />
    </QueryClientProvider>,
  );
}
async function openDiagnostics() {
  fireEvent.click(await screen.findByRole("button", { name: /^Inventory$/ }));
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(deploymentDiscovery.settings).mockResolvedValue({
    version: 2,
    sourceClusterId: "SRC-db",
    readyForDiscovery: true,
    configuration: { repositories: [], registries: [] },
    githubOrganizations: [],
    registryAdapters: [],
  });
  api.get.mockResolvedValue(migration);
  api.catalogue.mockResolvedValue({
    catalogue: {
      nodeCount: 2,
      architectures: ["amd64"],
      namespaces: [{ name: "payments", resourceCounts: { Deployment: 1 } }],
    },
  });
  api.inventory.mockResolvedValue({ inventory });
  api.assessment.mockResolvedValue({ assessment });
  api.customer.mockResolvedValue({ name: "DB Schenker" });
  api.source.mockResolvedValue({
    name: "Authorised source",
    sourceClusterId: "SRC-db",
    customerId: "CUS-db",
    version: 2,
    status: "CONNECTED",
    connectorLastSeenAt: new Date().toISOString(),
    distribution: "kubeadm",
    region: "ap-south-1",
  });
});
it("enables workspace only for completed matching evidence and shows source facts without a target score", async () => {
  open();
  const link = await screen.findByRole("link", {
    name: "Continue to migration scope",
  });
  expect(link).toHaveAttribute("href", "/migrations/MIG-demo/plan");
  expect(await screen.findByText("DB Schenker")).toBeVisible();
  await openDiagnostics();
  fireEvent.click(screen.getByRole("button", { name: "View resources" }));
  expect(screen.getByText("api")).toBeVisible();
  expect(screen.queryByText(/compatibility score/i)).not.toBeInTheDocument();
  expect(api.discover).not.toHaveBeenCalled();
  expect(api.assess).not.toHaveBeenCalled();
});
it("keeps workspace disabled for an incomplete or stale assessment", async () => {
  api.assessment.mockResolvedValue({
    assessment: { ...assessment, inventoryDigest: "b".repeat(64) },
  });
  open();
  expect(
    await screen.findByRole("button", { name: "Continue to migration scope" }),
  ).toBeDisabled();
  expect(
    screen.queryByRole("link", { name: "Continue to migration scope" }),
  ).not.toBeInTheDocument();
});
it("starts discovery only on explicit action using a current version", async () => {
  api.get.mockResolvedValue({ ...migration, status: "DRAFT", version: 1 });
  api.inventory.mockResolvedValue({ inventory: null });
  api.assessment.mockResolvedValue({ assessment: null });
  api.catalogue.mockResolvedValue({ catalogue: null });
  open();
  const button = await screen.findByRole("button", {
    name: "Discover source inventory",
  });
  await waitFor(() => expect(button).toBeEnabled());
  expect(api.discover).not.toHaveBeenCalled();
  fireEvent.click(button);
  await waitFor(() => expect(api.discover).toHaveBeenCalledWith("MIG-demo", 1));
  expect(api.assess).not.toHaveBeenCalled();
});
it("assesses the entire discovered source before selecting migration scope or target", async () => {
  api.get.mockResolvedValue({
    ...migration,
    status: "INVENTORY_READY",
    version: 3,
  });
  api.inventory.mockResolvedValue({ inventory: null });
  api.assessment.mockResolvedValue({ assessment: null });
  open();
  const button = await screen.findByRole("button", {
    name: "Run source assessment",
  });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  await waitFor(() => expect(api.assess).toHaveBeenCalledWith("MIG-demo", 3));
  expect(api.discover).not.toHaveBeenCalled();
});
it("blocks discovery when source ownership differs from the assessment customer", async () => {
  api.get.mockResolvedValue({ ...migration, status: "DRAFT" });
  api.source.mockResolvedValue({
    name: "Other customer source",
    customerId: "CUS-other",
  });
  open();
  expect(
    await screen.findByRole("button", { name: "Discover source inventory" }),
  ).toBeDisabled();
  await screen.findByRole("alert");
  expect(api.discover).not.toHaveBeenCalled();
});
it("rejects a previously completed snapshot when the source registration changes", () => {
  expect(
    sourceWorkspaceReady(
      {
        ...migration,
        sourceConfiguration: {
          ...migration.sourceConfiguration,
          sourceClusterId: "SRC-other",
        },
      } as never,
      assessment as never,
      inventory as never,
    ),
  ).toBe(false);
});

it("keeps completed source evidence accessible after planning-only version updates", () => {
  expect(
    sourceWorkspaceReady(
      { ...migration, version: 7 } as never,
      assessment as never,
      inventory as never,
    ),
  ).toBe(true);
});

it("offers guarded recovery for a stale registered connector instead of claiming discovery progress", async () => {
  api.get.mockResolvedValue({
    ...migration,
    status: "DISCOVERY_PENDING",
    version: 5,
  });
  api.inventory.mockResolvedValue({ inventory: null });
  api.assessment.mockResolvedValue({ assessment: null });
  api.source.mockResolvedValue({
    sourceClusterId: "SRC-db",
    customerId: "CUS-db",
    name: "Authorised source",
    version: 2,
    status: "CONNECTED",
    connectorLastSeenAt: "2026-01-01T00:00:00Z",
    installationCheck: {
      canRestore: true,
      code: "RESTORE_AVAILABLE",
      message: "Restore this existing registration",
      conflicts: [
        { sourceClusterId: "SRC-other", customerName: "Demo customer" },
      ],
    },
  });
  api.install.mockResolvedValue({ commandId: "ssm-command-1" });
  open();
  const button = await screen.findByRole("button", {
    name: "Restore source connection",
  });
  expect(
    screen.getByRole("heading", { name: "Waiting for source connector" }),
  ).toBeVisible();
  expect(screen.getByText(/Demo customer \(SRC-other\)/)).toBeVisible();
  expect(
    screen.getByRole("button", { name: "Continue to migration scope" }),
  ).toBeDisabled();
  expect(api.install).not.toHaveBeenCalled();
  fireEvent.click(button);
  await waitFor(() =>
    expect(api.install).toHaveBeenCalledWith("SRC-db", 2, "MIG-demo"),
  );
  expect(
    await screen.findByRole("button", { name: "Restoring connection…" }),
  ).toBeDisabled();
  expect(api.assess).not.toHaveBeenCalled();
  expect(api.discover).not.toHaveBeenCalled();
});

it("keeps recovery unavailable when backend reports another active assessment", async () => {
  api.get.mockResolvedValue({ ...migration, status: "DISCOVERY_PENDING" });
  api.source.mockResolvedValue({
    sourceClusterId: "SRC-db",
    customerId: "CUS-db",
    name: "Authorised source",
    version: 2,
    status: "CONNECTED",
    connectorLastSeenAt: "2026-01-01T00:00:00Z",
    installationCheck: {
      canRestore: false,
      code: "INSTALLATION_IN_USE",
      message: "Another assessment is using this installation.",
      conflicts: [],
    },
  });
  open();
  await screen.findByText("Another assessment is using this installation.");
  expect(
    screen.queryByRole("button", { name: "Restore source connection" }),
  ).not.toBeInTheDocument();
  expect(api.install).not.toHaveBeenCalled();
});

it("refreshes connector diagnostics together with migration status", async () => {
  api.source.mockRejectedValue(new Error("Status unavailable"));
  open();
  const button = await screen.findByRole("button", {
    name: "Retry status check",
  });
  await waitFor(() => expect(button).toBeEnabled());
  api.source.mockClear();
  fireEvent.click(button);
  await waitFor(() => expect(api.source).toHaveBeenCalledWith("SRC-db", true));
});

it("hides routine status refresh when polling has not failed", async () => {
  open();
  await screen.findByRole("link", { name: "Continue to migration scope" });
  expect(
    screen.queryByRole("button", { name: "Retry status check" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Refresh status" }),
  ).not.toBeInTheDocument();
});

it("brings the selected namespace resources into view and moves keyboard focus", async () => {
  const scroll = vi.fn();
  const previous = Object.getOwnPropertyDescriptor(
    HTMLElement.prototype,
    "scrollIntoView",
  );
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: scroll,
  });
  try {
    api.inventory.mockResolvedValue({
      inventory: {
        ...inventory,
        resources: [
          ...inventory.resources,
          {
            apiVersion: "apps/v1",
            kind: "Deployment",
            namespace: "other",
            name: "other-api",
          },
        ],
      },
    });
    open();
    await openDiagnostics();
    await screen.findByRole("heading", { name: "Discovered namespaces" });
    fireEvent.click(
      await screen.findByRole("button", { name: "View resources" }),
    );
    const region = screen.getByRole("region", {
      name: "Application resource inventory",
    });
    expect(region).toHaveFocus();
    expect(scroll).toHaveBeenCalledWith({ block: "start" });
    expect(
      within(region).getByText("Showing resources in payments."),
    ).toBeVisible();
    expect(
      within(region).getByRole("combobox", { name: "Namespace" }),
    ).toHaveValue("payments");
    expect(within(region).getByText("api")).toBeVisible();
    expect(within(region).queryByText("other-api")).not.toBeInTheDocument();
  } finally {
    if (previous)
      Object.defineProperty(HTMLElement.prototype, "scrollIntoView", previous);
    else Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView");
  }
});

it("keeps the existing discovery readiness gate without rendering connection configuration", async () => {
  vi.mocked(deploymentDiscovery.settings).mockResolvedValue({
    version: 2,
    configuration: { repositories: [], registries: [] },
    githubOrganizations: [],
    registryAdapters: [],
    sourceClusterId: "SRC-db",
    readyForDiscovery: false,
  });
  api.get.mockResolvedValue({ ...migration, status: "DRAFT" });
  open();
  await screen.findByRole("region", { name: "Discovery progress" });
  expect(
    screen.queryByRole("region", { name: "Source connections" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Discover source inventory" }),
  ).toBeDisabled();
  expect(api.discover).not.toHaveBeenCalled();
});

it("offers a fresh discovery run for a completed assessment using the current version", async () => {
  const refresh = vi.fn().mockResolvedValue({});
  Object.assign(deploymentDiscovery, { refresh });
  open();
  const button = await screen.findByRole("button", {
    name: "Refresh discovery",
  });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  await waitFor(() => expect(refresh).toHaveBeenCalledWith("MIG-demo", 6));
  expect(api.discover).not.toHaveBeenCalled();
});

it("keeps platform findings available separately from application findings", async () => {
  api.assessment.mockResolvedValue({
    assessment: {
      ...assessment,
      findings: [
        {
          code: "APP",
          message: "Application concern",
          namespace: "retailflow",
          severity: "WARNING",
          category: "WORKLOAD",
        },
        {
          code: "PLATFORM",
          message: "Platform concern",
          namespace: "calico-system",
          severity: "WARNING",
          category: "WORKLOAD",
        },
      ],
    },
  });
  open();
  await openDiagnostics();
  await screen.findByText("Application concern", { selector: "strong" });
  fireEvent.click(screen.getByRole("button", { name: /^Assessment/ }));
  expect(
    screen.getByText("Application concern", { selector: "strong" }),
  ).toBeVisible();
  expect(
    screen.getByText("Platform concern", { selector: "strong" }),
  ).toBeVisible();
  expect(screen.getByRole("combobox", { name: "Findings view" })).toHaveValue(
    "all",
  );
  fireEvent.change(screen.getByRole("combobox", { name: "Findings view" }), {
    target: { value: "application" },
  });
  expect(
    screen.queryByText("Platform concern", { selector: "strong" }),
  ).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox", { name: "Findings view" }), {
    target: { value: "platform" },
  });
  expect(
    screen.getByText("Platform concern", { selector: "strong" }),
  ).toBeVisible();
  expect(
    screen.queryByText("Application concern", { selector: "strong" }),
  ).not.toBeInTheDocument();
});

it("groups repeated observations and retains every resource-specific recommendation", async () => {
  api.assessment.mockResolvedValue({
    assessment: {
      ...assessment,
      findings: [
        {
          code: "ACCESS_REVIEW",
          severity: "WARNING",
          category: "IDENTITY",
          namespace: "orders",
          resourceKind: "Role",
          resourceName: "reader",
          message: "Review reader access",
          remediation: "Check reader subjects",
        },
        {
          code: "ACCESS_REVIEW",
          severity: "WARNING",
          category: "IDENTITY",
          namespace: "orders",
          resourceKind: "Role",
          resourceName: "writer",
          message: "Review writer access",
          remediation: "Check writer subjects",
        },
      ],
    },
  });
  open();
  await openDiagnostics();
  await screen.findByText("Review reader access", { selector: "strong" });
  fireEvent.click(screen.getByRole("button", { name: /^Assessment/ }));
  expect(screen.getByRole("combobox", { name: "Findings view" })).toHaveValue(
    "all",
  );
  expect(screen.getByText(/2 observations in this view/)).toBeVisible();
  expect(screen.getByText(/2 resource references/)).toBeVisible();
  fireEvent.click(
    screen.getByText("Review reader access", { selector: "strong" }),
  );
  expect(screen.getByText("Check reader subjects")).toBeVisible();
  expect(screen.getByText("Check writer subjects")).toBeVisible();
  expect(api.assess).not.toHaveBeenCalled();
});

it("keeps discovery free of source connection setup and artifact work", async () => {
  open();
  await screen.findByRole("link", { name: "Continue to migration scope" });
  expect(deploymentDiscovery.evidence).not.toHaveBeenCalled();
  expect(
    screen.queryByText("Migration files & images"),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", {
      name: /Resolve Helm|Resolve deployment|Create workspace/,
    }),
  ).not.toBeInTheDocument();
  expect(screen.queryByText("Source connections")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Manage connections" }),
  ).not.toBeInTheDocument();
  const flow = screen.getByRole("list", { name: "Migration workflow" });
  expect(within(flow).getAllByRole("listitem")).toHaveLength(5);
  expect(
    within(flow).queryByRole("button", { name: /Source connection/ }),
  ).not.toBeInTheDocument();
  expect(
    within(flow).getByRole("button", { name: "1 Discovery & assessment" }),
  ).toBeDisabled();
  expect(
    screen.queryByRole("button", { name: "Review access" }),
  ).not.toBeInTheDocument();
});
