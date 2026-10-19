import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { DeploymentEvidencePanel } from "@/modules/migration-management/deployment-evidence-panel";
import { isAllowedRoute } from "@/shared/api/proxy";
import { scopeKey } from "@/modules/migration-management/source-migration-scope";
import type { Migration } from "@/modules/migration-management/model";
const api = vi.hoisted(() => ({
  evidence: vi.fn(),
  settings: vi.fn(),
  saveSettings: vi.fn(),
  analyze: vi.fn(),
  refresh: vi.fn(),
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
const migration = {
  migrationId: "MIG-db",
  sourceConfiguration: { sourceClusterId: "SRC-db" },
  version: 5,
  status: "ASSESSMENT_READY",
} as unknown as Migration;
const digest = "a".repeat(64);
const workload = {
  apiVersion: "apps/v1",
  kind: "Deployment",
  namespace: "payments",
  name: "api",
};
const row = {
  workload,
  applicationVersion: "1.2",
  artifactFormat: "Helm",
  deliveryTool: "Helm",
  helmChart: "payments-1.0",
  helmRelease: "payments",
  mappingStatus: "CANDIDATE",
  runtimeStatus: "NOT_COLLECTED",
  candidates: [
    {
      repository: "customer/payments",
      commit: "b".repeat(40),
      filePath: "charts/Chart.yaml",
      format: "HELM",
      match: "CHART_METADATA",
    },
  ],
  containers: [
    {
      name: "api-container",
      containerType: "APPLICATION",
      configuredImage: "customer/api:1.2",
      runningImageIDs: [],
      observedDigests: [],
      runningImages: [],
      runningPodCount: 0,
      multipleRunningVersions: false,
      digestComparison: "UNVERIFIED",
      registryEvidence: null,
    },
  ],
  gaps: ["Running container image evidence is not collected."],
};
const report = {
  inventoryDigest: digest,
  workloads: [row],
  repositories: [],
  images: [],
  limitations: [],
  observedAt: "2026-10-19T10:00:00Z",
  analyzedAt: null,
};
const settings = {
  version: 2,
  configuration: { repositories: [], registries: [] },
  githubOrganizations: ["customer"],
  registryAdapters: ["AWS_ECR", "PUBLIC_DOCKER_HUB"],
};
function open(
  props: Partial<React.ComponentProps<typeof DeploymentEvidencePanel>> = {},
) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <DeploymentEvidencePanel
        migration={migration}
        inventoryDigest={digest}
        {...props}
      />
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  api.canEdit = true;
  api.evidence.mockResolvedValue(report);
  api.settings.mockResolvedValue(settings);
  api.saveSettings.mockResolvedValue({ ...settings, version: 3 });
  api.analyze.mockResolvedValue(report);
  api.refresh.mockResolvedValue({ refreshRequested: true });
});
it("shows discovered evidence without running analysis or asking for a deployment method", async () => {
  open();
  expect(
    await screen.findByText("Candidate · needs confirmation"),
  ).toBeVisible();
  expect(screen.queryByLabelText(/deployment method/i)).not.toBeInTheDocument();
  expect(api.analyze).not.toHaveBeenCalled();
  expect(api.saveSettings).not.toHaveBeenCalled();
  expect(api.refresh).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("api-container"));
  expect(screen.getByText("Running digest not reported")).toBeVisible();
});
it("saves source connections once with version protection and required-field validation", async () => {
  open();
  const manage = await screen.findByRole("button", {
    name: "Manage deployment sources",
  });
  await waitFor(() => expect(manage).toBeEnabled());
  fireEvent.click(manage);
  fireEvent.click(screen.getByRole("button", { name: "Add repository" }));
  fireEvent.submit(
    screen
      .getByRole("button", { name: "Save source connections" })
      .closest("form")!,
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Enter owner/repository",
  );
  expect(api.saveSettings).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("GitHub repository *"), {
    target: { value: "customer/payments" },
  });
  fireEvent.change(screen.getByLabelText("Deployment directory"), {
    target: { value: "deploy/production" },
  });
  fireEvent.change(screen.getByLabelText("Container registry hosts"), {
    target: { value: "docker.io" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Save source connections" }),
  );
  await waitFor(() =>
    expect(api.saveSettings).toHaveBeenCalledWith("SRC-db", 2, {
      repositories: [
        {
          repository: "customer/payments",
          revision: "main",
          directory: "deploy/production",
        },
      ],
      registries: ["docker.io"],
      confirmations: [],
    }),
  );
  expect(api.analyze).not.toHaveBeenCalled();
});
it("explicit analysis persists no implicit refresh or workflow transition", async () => {
  open();
  const button = await screen.findByRole("button", {
    name: "Analyze deployment sources",
  });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  await waitFor(() => expect(api.analyze).toHaveBeenCalledWith("MIG-db", 5));
  expect(api.refresh).not.toHaveBeenCalled();
  expect(await screen.findByRole("status")).toHaveTextContent(
    "Analysis finished",
  );
});
it("requests cluster evidence refresh using the migration version", async () => {
  const onRefresh = vi.fn();
  open({ onRefresh });
  fireEvent.click(
    await screen.findByRole("button", { name: "Refresh cluster evidence" }),
  );
  await waitFor(() => expect(api.refresh).toHaveBeenCalledWith("MIG-db", 5));
  await waitFor(() => expect(onRefresh).toHaveBeenCalled());
});
it("scope summary includes only selected workload identities and links to discovery", async () => {
  api.evidence.mockResolvedValue({
    ...report,
    workloads: [row, { ...row, workload: { ...workload, name: "unselected" } }],
  });
  open({ selectedKeys: new Set([scopeKey(workload)]) });
  expect(await screen.findByText("api")).toBeVisible();
  expect(screen.queryByText("unselected")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Manage deployment sources" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: /resolve deployment sources/ }),
  ).toHaveAttribute("href", "/migrations/MIG-db/discovery#deployment-evidence");
});
it("marks explicit user confirmation without claiming a verified deployed commit", async () => {
  open();
  const button = await screen.findByRole("button", {
    name: "Confirm unique source mappings",
  });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  await waitFor(() => expect(api.saveSettings).toHaveBeenCalled());
  const body = api.saveSettings.mock.calls[0][2];
  expect(body.confirmations[0]).toEqual({
    ...workload,
    repository: "customer/payments",
    commit: "b".repeat(40),
    filePath: "charts/Chart.yaml",
  });
  expect(await screen.findByRole("status")).toHaveTextContent(
    "does not independently verify",
  );
});
it("viewer cannot mutate connections, analysis, refresh or confirmation", async () => {
  api.canEdit = false;
  open();
  await screen.findByText("Candidate · needs confirmation");
  for (const name of [
    "Manage deployment sources",
    "Analyze deployment sources",
    "Refresh cluster evidence",
    "Confirm unique source mappings",
  ])
    expect(screen.getByRole("button", { name })).toBeDisabled();
});
it("a stale inventory response does not present mappings as current", async () => {
  api.evidence.mockResolvedValue({
    ...report,
    inventoryDigest: "c".repeat(64),
  });
  open();
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "another inventory snapshot",
  );
  expect(
    screen.queryByText("Candidate · needs confirmation"),
  ).not.toBeInTheDocument();
});
it("only permits intended authenticated proxy methods", () => {
  const mig = "MIG-" + "a".repeat(32);
  const source = "SRC-" + "a".repeat(32);
  expect(
    isAllowedRoute("GET", ["migrations", mig, "deployment-evidence"]),
  ).toBe(true);
  expect(
    isAllowedRoute("POST", ["migrations", mig, "deployment-evidence"]),
  ).toBe(true);
  expect(
    isAllowedRoute("PUT", ["source-clusters", source, "deployment-sources"]),
  ).toBe(true);
  expect(
    isAllowedRoute("DELETE", ["source-clusters", source, "deployment-sources"]),
  ).toBe(false);
});

it("distinguishes resources in a multi-document manifest and labels workflows", async () => {
  api.evidence.mockResolvedValue({
    ...report,
    repositories: [
      {
        repository: "customer/payments",
        status: "ANALYZED",
        commit: "b".repeat(40),
        gaps: [],
        artifacts: [
          {
            filePath: "api.yaml",
            format: "MANIFESTS",
            resource: {
              kind: "Deployment",
              name: "api",
              namespace: "payments",
            },
          },
          {
            filePath: "api.yaml",
            format: "MANIFESTS",
            resource: {
              kind: "Service",
              name: "api-service",
              namespace: "payments",
            },
          },
          { filePath: ".github/workflows/build.yml", format: "GITHUB_ACTIONS" },
        ],
      },
    ],
  });
  open();
  fireEvent.click(
    await screen.findByRole("button", { name: "Deployment structure" }),
  );
  expect(screen.getByText("Deployment · payments · api")).toBeVisible();
  expect(screen.getByText("Service · payments · api-service")).toBeVisible();
  expect(screen.getByText("GitHub Actions workflow")).toBeVisible();
});

it("shows which workload references each registry image", async () => {
  api.evidence.mockResolvedValue({
    ...report,
    images: [{ image: "customer/api:1.2", status: "NOT_CONNECTED" }],
  });
  open();
  fireEvent.click(
    await screen.findByRole("button", { name: "Container registry" }),
  );
  expect(screen.getByText("payments · Deployment / api")).toBeVisible();
  expect(
    screen.getByText(
      /Connecting a registry does not change source workload images/,
    ),
  ).toBeVisible();
});

it("requires individual namespace review for manifests without namespace", async () => {
  api.evidence.mockResolvedValue({
    ...report,
    workloads: [
      {
        ...row,
        artifactFormat: "Kubernetes manifests (candidate)",
        deliveryTool: "Unresolved",
        candidates: [
          {
            ...row.candidates[0],
            format: "MANIFESTS",
            match: "NAMESPACE_UNSPECIFIED",
            filePath: "base/api.yaml",
          },
        ],
      },
    ],
  });
  open();
  expect(
    await screen.findByText(/Manifest namespace unspecified/),
  ).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Confirm unique source mappings" }),
  ).not.toBeInTheDocument();
  const confirm = screen.getByRole("button", { name: "Confirm source" });
  await waitFor(() => expect(confirm).toBeEnabled());
  fireEvent.click(confirm);
  await waitFor(() => expect(api.saveSettings).toHaveBeenCalled());
  expect(api.saveSettings.mock.calls[0][2].confirmations[0].namespace).toBe(
    "payments",
  );
});

it("separates missing repository mapping from runtime evidence", async () => {
  api.evidence.mockResolvedValue({
    ...report,
    workloads: [
      {
        ...row,
        workload: { ...workload, kind: "CronJob" },
        candidates: [],
        mappingStatus: "UNRESOLVED",
        runtimeStatus: "NO_RUNNING_EVIDENCE",
      },
    ],
  });
  open();
  expect(await screen.findByText("Repository not mapped")).toBeVisible();
  expect(screen.getByText(/No running Pod observed/)).toBeVisible();
  expect(
    screen.getByText(/Scheduled or completed Jobs may have no running Pods/),
  ).toBeVisible();
});

it("filters Git workload mapping and registry evidence by the same namespace", async () => {
  api.evidence.mockResolvedValue({
    ...report,
    workloads: [
      row,
      {
        ...row,
        workload: { ...workload, namespace: "platform", name: "operator" },
        containers: [
          { ...row.containers[0], configuredImage: "quay.io/operator:v1" },
        ],
      },
    ],
    images: [
      { image: "customer/api:1.2", status: "AVAILABLE" },
      { image: "quay.io/operator:v1", status: "NOT_CONNECTED" },
    ],
  });
  open();
  const filter = await screen.findByRole("combobox", {
    name: "Evidence namespace",
  });
  fireEvent.change(filter, { target: { value: "payments" } });
  expect(screen.getByText("api")).toBeVisible();
  expect(screen.queryByText("operator")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Container registry" }));
  expect(screen.getByText("customer/api:1.2")).toBeVisible();
  expect(screen.queryByText("quay.io/operator:v1")).not.toBeInTheDocument();
  fireEvent.change(filter, { target: { value: "platform" } });
  expect(screen.getByText("Registry not configured")).toBeVisible();
  expect(screen.getByText(/Image availability is unknown/)).toBeVisible();
});
