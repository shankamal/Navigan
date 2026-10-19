import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { SourceConnectionsPanel } from "@/modules/migration-management/source-connections-panel";
const api = vi.hoisted(() => ({
  settings: vi.fn(),
  saveSettings: vi.fn(),
  canEdit: true,
}));
vi.mock("@/modules/migration-management/deployment-evidence-service", () => ({
  deploymentDiscovery: api,
}));
vi.mock("@/shared/auth/auth-provider", () => ({
  useAuth: () => ({ identity: {} }),
}));
vi.mock("@/shared/auth/permissions", () => ({
  hasPermission: () => api.canEdit,
}));
const settings = {
  sourceClusterId: "SRC-db",
  version: 2,
  configuration: {
    repositories: [
      { repository: "customer/app", revision: "main", directory: "deploy" },
    ],
    registries: ["905418045935.dkr.ecr.ap-south-1.amazonaws.com"],
  },
  githubOrganizations: [],
  authentication: {},
  readyForDiscovery: false,
};
function open() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <SourceConnectionsPanel sourceId="SRC-db" />
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  api.canEdit = true;
  api.settings.mockResolvedValue(structuredClone(settings));
  api.saveSettings.mockResolvedValue({
    ...settings,
    readyForDiscovery: true,
    authentication: {
      "github:customer/app": {
        mode: "TOKEN",
        secretConfigured: true,
        status: "CONNECTED",
      },
      "registry:905418045935.dkr.ecr.ap-south-1.amazonaws.com": {
        mode: "AWS_IAM",
        status: "CONNECTED",
      },
    },
  });
});
it("offers editable source settings and sends write-only credentials with verification", async () => {
  open();
  const mode = await screen.findByLabelText(
    "Authentication for github:customer/app",
  );
  expect(mode).not.toBeDisabled();
  fireEvent.change(mode, { target: { value: "TOKEN" } });
  fireEvent.change(screen.getByLabelText(/^GitHub token \*/), {
    target: { value: "read-only-secret" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Save and verify access" }),
  );
  await waitFor(() =>
    expect(api.saveSettings).toHaveBeenCalledWith(
      "SRC-db",
      2,
      expect.objectContaining({
        registries: settings.configuration.registries,
      }),
      expect.arrayContaining([
        {
          key: "github:customer/app",
          mode: "TOKEN",
          token: "read-only-secret",
          username: "",
        },
        {
          key: "registry:" + settings.configuration.registries[0],
          mode: "AWS_IAM",
        },
      ]),
      true,
    ),
  );
  await screen.findByText(
    "Source connections are ready. You can start discovery below.",
  );
  expect(screen.getByLabelText(/GitHub token \(saved securely/)).toHaveValue(
    "",
  );
});
it("shows a retry control when settings fail", async () => {
  api.settings.mockRejectedValueOnce(new Error("Unavailable"));
  open();
  fireEvent.click(
    await screen.findByRole("button", { name: "Retry source settings" }),
  );
  expect(
    await screen.findByLabelText("Authentication for github:customer/app"),
  ).toBeEnabled();
});
it("validates missing tokens before submitting", async () => {
  open();
  fireEvent.change(
    await screen.findByLabelText("Authentication for github:customer/app"),
    { target: { value: "TOKEN" } },
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Save and verify access" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "mandatory read-only token",
  );
  expect(api.saveSettings).not.toHaveBeenCalled();
});
it("allows explicit inventory-only discovery without credentials", async () => {
  api.settings.mockResolvedValue({
    ...settings,
    configuration: { repositories: [], registries: [] },
  });
  open();
  fireEvent.click(await screen.findByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Save connections" }));
  await waitFor(() =>
    expect(api.saveSettings).toHaveBeenCalledWith(
      "SRC-db",
      2,
      { repositories: [], registries: [], inventoryOnly: true },
      [],
      false,
    ),
  );
});
it("explains missing permission and prevents mutation", async () => {
  api.canEdit = false;
  open();
  await screen.findByLabelText("Authentication for github:customer/app");
  expect(
    screen.getByRole("button", { name: "Save and verify access" }),
  ).toBeDisabled();
  expect(screen.getByText(/migration.edit permission/)).toBeVisible();
});
it("normalizes GitHub URLs and clears credentials after failure", async () => {
  api.saveSettings.mockRejectedValue(new Error("Failed"));
  open();
  fireEvent.change(
    await screen.findByLabelText("Repository URL or owner/repository *"),
    { target: { value: "https://github.com/customer/app.git" } },
  );
  fireEvent.change(
    screen.getByLabelText(
      "Authentication for github:https://github.com/customer/app.git",
    ),
    { target: { value: "TOKEN" } },
  );
  fireEvent.change(screen.getByLabelText(/^GitHub token \*/), {
    target: { value: "temporary" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Save and verify access" }),
  );
  await screen.findByRole("alert");
  expect(api.saveSettings.mock.calls[0][2].repositories[0].repository).toBe(
    "customer/app",
  );
  expect(screen.queryByDisplayValue("temporary")).toBeNull();
});
