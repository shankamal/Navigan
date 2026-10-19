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
        expect.objectContaining({
          key: "registry:" + settings.configuration.registries[0],
          mode: "AWS_ROLE",
          provider: "AWS_ECR",
          roleArn:
            "arn:aws:iam::905418045935:role/navigan-source-discovery/NaviganRegistryReadOnly",
        }),
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

it("lets a separate registry account use a customer role and displays generated trust setup", async () => {
  const host = "111111111111.dkr.ecr.us-west-2.amazonaws.com";
  const roleArn =
    "arn:aws:iam::111111111111:role/navigan-source-discovery/ReadOnly";
  api.settings.mockResolvedValue({
    ...settings,
    configuration: { repositories: [], registries: [host] },
  });
  api.saveSettings.mockResolvedValue({
    ...settings,
    configuration: { repositories: [], registries: [host] },
    readyForDiscovery: false,
    registryPrincipalArn: "arn:aws:iam::905418045935:role/NaviganBackend",
    authentication: {
      ["registry:" + host]: {
        mode: "AWS_ROLE",
        roleArn,
        externalId: "navigan-generated-id",
        status: "NOT_VERIFIED",
      },
    },
  });
  open();
  fireEvent.change(
    await screen.findByLabelText("Authentication for registry:" + host),
    { target: { value: "AWS_ROLE" } },
  );
  fireEvent.change(screen.getByLabelText("Registry read-only role ARN *"), {
    target: { value: roleArn },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save connections" }));
  await waitFor(() =>
    expect(api.saveSettings).toHaveBeenCalledWith(
      "SRC-db",
      2,
      expect.objectContaining({ registries: [host] }),
      expect.arrayContaining([
        expect.objectContaining({
          key: "registry:" + host,
          mode: "AWS_ROLE",
          roleArn,
        }),
      ]),
      false,
    ),
  );
  expect(
    await screen.findByLabelText("Navigan-generated External ID"),
  ).toHaveValue("navigan-generated-id");
  fireEvent.click(screen.getByText("Customer role trust and permissions"));
  expect(
    (screen.getByLabelText("Trust policy") as HTMLTextAreaElement).value,
  ).toContain("navigan-generated-id");
  expect(
    (
      screen.getByLabelText(
        "Read-only ECR permission policy",
      ) as HTMLTextAreaElement
    ).value,
  ).toContain("arn:aws:ecr:us-west-2:111111111111:repository/*");
});

it("recognizes a non-AWS registry without offering an ECR role", async () => {
  api.settings.mockResolvedValue({
    ...settings,
    configuration: { repositories: [], registries: ["customer.azurecr.io"] },
  });
  open();
  expect(
    await screen.findByLabelText(
      "Registry provider for registry:customer.azurecr.io",
    ),
  ).toHaveValue("AZURE_ACR");
  expect(
    screen.queryByRole("option", { name: /Customer IAM role/ }),
  ).toBeNull();
  expect(
    screen.getByRole("option", {
      name: "Service principal or ACR repository token",
    }),
  ).toBeVisible();
});

it("offers explicit providers and removes the platform IAM option", async () => {
  open();
  const host = settings.configuration.registries[0];
  expect(
    await screen.findByLabelText("Registry provider for registry:" + host),
  ).toHaveValue("AWS_ECR");
  expect(
    screen.queryByRole("option", { name: "AWS ECR · Navigan IAM role" }),
  ).toBeNull();
  expect(screen.getByLabelText("Registry read-only role ARN *")).toHaveValue(
    "arn:aws:iam::905418045935:role/navigan-source-discovery/NaviganRegistryReadOnly",
  );
  for (const name of [
    "Azure Container Registry",
    "Google Artifact Registry / GCR",
    "Docker Hub",
    "GitHub Container Registry",
    "Harbor",
    "Other OCI / Docker registry",
  ])
    expect(screen.getByRole("option", { name })).toBeInTheDocument();
});

it("keeps a provider selected before entering the registry hostname", async () => {
  api.settings.mockResolvedValue({
    ...settings,
    configuration: { repositories: [], registries: [""] },
  });
  open();
  fireEvent.change(
    await screen.findByLabelText("Registry provider for registry:"),
    { target: { value: "GOOGLE_AR" } },
  );
  fireEvent.change(screen.getByLabelText("Registry hostname *"), {
    target: { value: "asia-south1-docker.pkg.dev" },
  });
  expect(
    screen.getByLabelText(
      "Registry provider for registry:asia-south1-docker.pkg.dev",
    ),
  ).toHaveValue("GOOGLE_AR");
  expect(screen.getByLabelText("Google token username")).toHaveValue(
    "oauth2accesstoken",
  );
  expect(
    screen.getByRole("option", { name: "Google OAuth access token" }),
  ).toBeVisible();
  fireEvent.change(screen.getByLabelText(/^Google access token/), {
    target: { value: "short-lived-token" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save connections" }));
  await waitFor(() =>
    expect(api.saveSettings).toHaveBeenCalledWith(
      "SRC-db",
      2,
      expect.anything(),
      expect.arrayContaining([
        expect.objectContaining({
          provider: "GOOGLE_AR",
          mode: "TOKEN",
          username: "oauth2accesstoken",
          token: "short-lived-token",
        }),
      ]),
      false,
    ),
  );
});

it("generates an AWS role template with the exact path, External ID and read-only permissions", async () => {
  const { registryRoleTemplate } =
    await import("@/modules/migration-management/registry-connection-options");
  const template = registryRoleTemplate(
    "905418045935.dkr.ecr.ap-south-1.amazonaws.com",
    "arn:aws:iam::905418045935:role/navigan-source-discovery/NaviganRegistryReadOnly",
    "arn:aws:iam::999999999999:role/Backend",
    "navigan-generated-id",
  );
  const role = template.Resources.RegistryDiscoveryRole.Properties;
  expect(role.RoleName).toBe("NaviganRegistryReadOnly");
  expect(role.Path).toBe("/navigan-source-discovery/");
  expect(
    role.AssumeRolePolicyDocument.Statement[0].Condition.StringEquals[
      "sts:ExternalId"
    ],
  ).toBe("navigan-generated-id");
  expect(
    role.Policies[0].PolicyDocument.Statement.flatMap((s) => s.Action),
  ).toEqual(["ecr:GetAuthorizationToken", "ecr:DescribeImages"]);
  expect(role.Policies[0].PolicyDocument.Statement[1].Resource).toBe(
    "arn:aws:ecr:ap-south-1:905418045935:repository/*",
  );
  expect(() =>
    registryRoleTemplate(
      "905418045935.dkr.ecr.ap-south-1.amazonaws.com",
      "arn:aws:iam::111111111111:role/navigan-source-discovery/Role",
      "principal",
      "id",
    ),
  ).toThrow();
});

it("allows an existing IAM role without offering role creation downloads", async () => {
  const host = settings.configuration.registries[0];
  const arn = "arn:aws:iam::905418045935:role/team/ExistingEcrRole";
  api.saveSettings.mockResolvedValue({
    ...settings,
    registryPrincipalArn: "arn:aws:iam::905418045935:role/Backend",
    readyForDiscovery: false,
    authentication: {
      ["registry:" + host]: {
        mode: "AWS_EXISTING_ROLE",
        provider: "AWS_ECR",
        roleArn: arn,
        externalId: "navigan-existing-id",
        status: "NOT_VERIFIED",
      },
    },
  });
  open();
  const method = await screen.findByLabelText(
    "Authentication for registry:" + host,
  );
  expect(
    screen.getByRole("option", { name: "Existing IAM role" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("option", { name: "Create new IAM role" }),
  ).toBeInTheDocument();
  fireEvent.change(method, { target: { value: "AWS_EXISTING_ROLE" } });
  fireEvent.change(screen.getByLabelText("Existing IAM role ARN *"), {
    target: { value: arn },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save connections" }));
  await waitFor(() =>
    expect(api.saveSettings).toHaveBeenCalledWith(
      "SRC-db",
      2,
      expect.anything(),
      expect.arrayContaining([
        expect.objectContaining({ mode: "AWS_EXISTING_ROLE", roleArn: arn }),
      ]),
      false,
    ),
  );
  expect(
    await screen.findByLabelText("Navigan-generated External ID"),
  ).toHaveValue("navigan-existing-id");
  fireEvent.click(screen.getByText("Customer role trust and permissions"));
  expect(
    screen.queryByRole("button", { name: "Download AWS role setup" }),
  ).toBeNull();
  expect(screen.getByText(/Merge the displayed trust statement/)).toBeVisible();
});
