import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { SourceDiscoveryScreen } from "@/modules/migration-management/source-discovery-screen";
import { sourceWorkspaceReady } from "@/modules/migration-management/source-discovery-state";
const api = vi.hoisted(() => ({
  get: vi.fn(),
  catalogue: vi.fn(),
  inventory: vi.fn(),
  assessment: vi.fn(),
  source: vi.fn(),
  customer: vi.fn(),
  discover: vi.fn(),
  assess: vi.fn(),
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
  sourceClusters: { get: api.source },
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
beforeEach(() => {
  vi.clearAllMocks();
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
    customerId: "CUS-db",
    distribution: "kubeadm",
    region: "ap-south-1",
  });
});
it("enables workspace only for completed matching evidence and shows source facts without a target score", async () => {
  open();
  const link = await screen.findByRole("link", {
    name: "Open Migration Workspace",
  });
  expect(link).toHaveAttribute("href", "/migrations/MIG-demo/plan");
  expect(await screen.findByText("DB Schenker")).toBeVisible();
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
    await screen.findByRole("button", { name: "Open Migration Workspace" }),
  ).toBeDisabled();
  expect(
    screen.queryByRole("link", { name: "Open Migration Workspace" }),
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
