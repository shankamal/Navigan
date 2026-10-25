import {
  QueryClient,
  QueryClientProvider,
  useQueryClient,
} from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { within } from "@testing-library/react";
import { SourceAccessSetup } from "@/modules/migration-management/source-access-setup";

const api = vi.hoisted(() => ({
  migration: vi.fn(),
  source: vi.fn(),
  settings: vi.fn(),
}));
vi.mock("@/modules/migration-management/service", () => ({
  migrations: { get: api.migration },
  sourceClusters: { get: api.source },
}));
vi.mock("@/modules/migration-management/deployment-evidence-service", () => ({
  deploymentDiscovery: { settings: api.settings },
}));
vi.mock("@/modules/migration-management/source-connections-panel", () => ({
  SourceConnectionsPanel: ({
    sourceId,
    showConnector,
  }: {
    sourceId: string;
    showConnector: boolean;
  }) => {
    const cache = useQueryClient();
    return (
      <section aria-label="Source access editor">
        <p>{sourceId}</p>
        <p>{String(showConnector)}</p>
        <button
          onClick={() =>
            cache.setQueryData(["deployment-sources", sourceId], {
              readyForDiscovery: true,
            })
          }
        >
          Save verified access
        </button>
      </section>
    );
  },
}));
function open() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <SourceAccessSetup migrationId="MIG-test" />
    </QueryClientProvider>,
  );
}
it("keeps Back and Continue together in one navigation bar", async () => {
  api.settings.mockResolvedValue({ readyForDiscovery: true });
  open();
  await screen.findByRole("link", { name: "Continue to discovery" });
  const actions = screen.getByRole("navigation", {
    name: "Migration step actions",
  });
  expect(
    within(actions).getByRole("link", { name: "Back to discovery status" }),
  ).toBeVisible();
  expect(
    within(actions).getByRole("link", { name: "Continue to discovery" }),
  ).toBeVisible();
});
beforeEach(() => {
  vi.resetAllMocks();
  api.migration.mockResolvedValue({
    migrationId: "MIG-test",
    name: "PROD assessment",
    customerId: "CUS-db",
    status: "INVENTORY_READY",
    sourceConfiguration: { sourceClusterId: "SRC-db" },
  });
  api.source.mockResolvedValue({
    sourceClusterId: "SRC-db",
    name: "Source lab",
    customerId: "CUS-db",
  });
  api.settings.mockResolvedValue({ readyForDiscovery: false });
});
it("loads setup for an inventory-ready assessment without requiring an editable draft", async () => {
  open();
  expect(
    await screen.findByRole("region", { name: "Source access editor" }),
  ).toHaveTextContent("SRC-db");
  expect(
    screen.getByRole("button", { name: "Continue to discovery" }),
  ).toBeDisabled();
  expect(
    screen.getByRole("link", { name: "Back to discovery status" }),
  ).toHaveAttribute("href", "/migrations/MIG-test/discovery");
  fireEvent.click(screen.getByRole("button", { name: "Save verified access" }));
  expect(
    await screen.findByRole("link", { name: "Continue to discovery" }),
  ).toHaveAttribute("href", "/migrations/MIG-test/discovery");
});
it.each([
  { customerId: "CUS-other" },
  { status: "REVOKED" },
  { sourceClusterId: "SRC-other" },
])("rejects an unavailable or mismatched registration: %j", async (change) => {
  api.source.mockResolvedValue({
    sourceClusterId: "SRC-db",
    customerId: "CUS-db",
    ...change,
  });
  open();
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "authorized source registration",
  );
  expect(
    screen.queryByRole("region", { name: "Source access editor" }),
  ).not.toBeInTheDocument();
  expect(api.settings).not.toHaveBeenCalled();
});
it("handles missing assessment source without requesting an empty source ID", async () => {
  api.migration.mockResolvedValue({
    customerId: "CUS-db",
    sourceConfiguration: {},
  });
  open();
  await screen.findByRole("alert");
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await waitFor(() => expect(api.migration).toHaveBeenCalledTimes(2));
  expect(api.source).not.toHaveBeenCalled();
});
it("blocks continuation when readiness cannot be checked and allows retry", async () => {
  api.settings.mockRejectedValue(new Error("Unavailable"));
  open();
  await screen.findByRole("button", { name: "Check readiness again" });
  expect(
    screen.getByRole("button", { name: "Continue to discovery" }),
  ).toBeDisabled();
  api.settings.mockResolvedValue({ readyForDiscovery: true });
  fireEvent.click(
    screen.getByRole("button", { name: "Check readiness again" }),
  );
  await screen.findByRole("link", { name: "Continue to discovery" });
});
