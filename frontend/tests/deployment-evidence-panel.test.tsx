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
const inventoryApi = vi.hoisted(() => ({ sourceInventory: vi.fn() }));
vi.mock("@/modules/migration-management/service", () => ({
  migrations: inventoryApi,
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
it("keeps repository matches separate from image availability in the summary", async () => {
  open();
  const summary = await screen.findByRole("region", {
    name: "Discovery evidence summary",
  });
  expect(
    within(summary).getByRole("progressbar", {
      name: "Repository definitions matched",
    }),
  ).toHaveAttribute("aria-valuenow", "1");
  expect(
    within(summary).getByRole("progressbar", {
      name: "All container images available",
    }),
  ).toHaveAttribute("aria-valuenow", "0");
  expect(
    within(summary).getByText(/do not verify the deployed Git revision/),
  ).toBeVisible();
});
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
  expect(await screen.findByText("GitHub candidate")).toBeVisible();
  expect(screen.queryByLabelText(/deployment method/i)).not.toBeInTheDocument();
  expect(api.analyze).not.toHaveBeenCalled();
  expect(api.saveSettings).not.toHaveBeenCalled();
  expect(api.refresh).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: "Inspect api in payments" }),
  );
  fireEvent.click(
    within(screen.getByRole("dialog")).getByText("api-container"),
  );
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
it("keeps one Check sources action before and after analysis without refreshing discovery", async () => {
  api.analyze.mockResolvedValue({
    ...report,
    analyzedAt: "2026-10-31T11:30:00Z",
  });
  open();
  const button = await screen.findByRole("button", {
    name: "Check sources",
  });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  await waitFor(() => expect(api.analyze).toHaveBeenCalledWith("MIG-db", 5));
  expect(api.refresh).not.toHaveBeenCalled();
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Check sources" })).toBeEnabled(),
  );
  expect(screen.getAllByRole("button", { name: "Check sources" })).toHaveLength(
    1,
  );
  expect(
    screen.queryByRole("button", { name: "Recheck sources" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Analyze deployment sources" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Check sources" }));
  await waitFor(() => expect(api.analyze).toHaveBeenCalledTimes(2));
  expect(await screen.findByText(/Analysis finished/)).toHaveAttribute(
    "role",
    "status",
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
it("scope summary includes only selected workload identities and checks sources in place", async () => {
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
    screen.queryByRole("link", { name: /resolve deployment sources/ }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", {
      name: /Check sources/,
    }),
  ).toBeVisible();
});
it("marks explicit user confirmation without claiming a verified deployed commit", async () => {
  open();
  fireEvent.click(
    await screen.findByRole("button", { name: "Inspect api in payments" }),
  );
  const button = screen.getByRole("button", { name: "Confirm source" });
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
  expect(
    await screen.findByText(/does not independently verify/),
  ).toHaveAttribute("role", "status");
});
it("viewer cannot mutate connections, analysis, refresh or confirmation", async () => {
  api.canEdit = false;
  open();
  await screen.findByText("GitHub candidate");
  for (const name of [
    "Manage deployment sources",
    "Check sources",
    "Refresh cluster evidence",
  ])
    expect(screen.getByRole("button", { name })).toBeDisabled();
  fireEvent.click(
    screen.getByRole("button", { name: "Inspect api in payments" }),
  );
  expect(screen.getByRole("button", { name: "Confirm source" })).toBeDisabled();
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
    await screen.findByRole("button", { name: "Source diagnostics" }),
  );
  fireEvent.click(screen.getByText("Repository artifact index"));
  fireEvent.click(screen.getByText("api.yaml", { selector: "summary" }));
  fireEvent.click(
    screen.getByText(".github/workflows/build.yml", { selector: "summary" }),
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
    await screen.findByRole("button", { name: "Source diagnostics" }),
  );
  fireEvent.click(
    screen.getByLabelText("Inspect registry image customer/api:1.2"),
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
  fireEvent.click(
    await screen.findByRole("button", { name: "Inspect api in payments" }),
  );
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
  expect(
    await screen.findByText("No original repository mapping."),
  ).toBeVisible();
  expect(screen.getByText("No active Pod")).toBeVisible();
  fireEvent.click(
    screen.getByRole("button", { name: "Inspect api in payments" }),
  );
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
  expect(
    screen.getByRole("button", { name: /^api\s*Deployment$/ }),
  ).toBeVisible();
  expect(screen.queryByText("operator")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Source diagnostics" }));
  fireEvent.click(
    screen.getByLabelText("Inspect registry image customer/api:1.2"),
  );
  expect(
    within(screen.getByRole("dialog")).getByText("customer/api:1.2"),
  ).toBeVisible();
  expect(screen.queryByText("quay.io/operator:v1")).not.toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Close workload evidence" }),
  );
  fireEvent.change(filter, { target: { value: "platform" } });
  fireEvent.click(screen.getByRole("button", { name: "Source diagnostics" }));
  expect(screen.getByText("Registry not configured")).toBeVisible();
  fireEvent.click(
    screen.getByLabelText("Inspect registry image quay.io/operator:v1"),
  );
  expect(screen.getByText(/Image availability is unknown/)).toBeVisible();
});

it("shows all discovered workloads by default with evidence completeness and read-only snapshots", async () => {
  api.evidence.mockResolvedValue({
    ...report,
    coverage: {
      status: "WITH_GAPS",
      namespaceCount: 2,
      workloadCount: 2,
      repositoryMappedCount: 0,
      registryVerifiedWorkloadCount: 1,
      runtimeObservedCount: 2,
      inventorySnapshotCount: 2,
      limitations: ["Deployment package review required"],
    },
    workloads: [
      {
        ...row,
        candidates: [],
        mappingStatus: "UNRESOLVED",
        clusterSnapshot: {
          resource: { kind: "Deployment", name: "api" },
          deployable: false,
          inventoryDigest: digest,
          observedAt: "2026-10-19T10:00:00Z",
        },
      },
      { ...row, workload: { ...workload, namespace: "other", name: "worker" } },
    ],
  });
  open();
  expect(
    await screen.findByRole("heading", { name: "Source workload explorer" }),
  ).toBeVisible();
  expect(
    screen.getByRole("button", { name: /^api\s*Deployment$/ }),
  ).toBeVisible();
  expect(screen.getByText("worker")).toBeInTheDocument();
  expect(
    screen.getByRole("combobox", { name: "Evidence namespace" }),
  ).toHaveValue("");
  fireEvent.click(
    screen.getByRole("button", { name: "Inspect api in payments" }),
  );
  fireEvent.click(screen.getByText("Review captured cluster inventory"));
  expect(screen.getByText(/This is not a deployable manifest/)).toBeVisible();
  expect(screen.getByText(/"kind": "Deployment"/)).toBeVisible();
});

it("continues pending registry checks within an explicit analysis action", async () => {
  api.analyze
    .mockResolvedValueOnce({
      ...report,
      images: [{ image: "customer/api:1.2", status: "PENDING" }],
    })
    .mockResolvedValue(report);
  open();
  const button = await screen.findByRole("button", {
    name: "Check sources",
  });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  await waitFor(() => expect(api.analyze).toHaveBeenCalledTimes(2));
  expect(api.analyze).toHaveBeenNthCalledWith(1, "MIG-db", 5);
  expect(api.analyze).toHaveBeenNthCalledWith(2, "MIG-db", 5, true);
});

it("loads a digest-matching snapshot on demand and refuses stale inventory", async () => {
  api.evidence.mockResolvedValue({
    ...report,
    workloads: [
      {
        ...row,
        clusterSnapshot: {
          inventoryDigest: digest,
          observedAt: "2026-10-19T10:00:00Z",
          resourceIdentity: workload,
          deployable: false,
        },
      },
    ],
  });
  inventoryApi.sourceInventory.mockResolvedValue({
    inventory: { inventoryDigest: "different", resources: [] },
  });
  open();
  fireEvent.click(
    await screen.findByRole("button", { name: "Inspect api in payments" }),
  );
  const summary = await screen.findByText("Review captured cluster inventory");
  expect(inventoryApi.sourceInventory).not.toHaveBeenCalled();
  fireEvent.click(summary);
  await waitFor(() =>
    expect(inventoryApi.sourceInventory).toHaveBeenCalledWith("MIG-db"),
  );
  expect(
    await screen.findByText(/Inventory changed. Refresh the discovery view/),
  ).toBeVisible();
});

it("opens evidence on demand and restores focus when Escape closes the drawer", async () => {
  open();
  const trigger = await screen.findByRole("button", {
    name: "Inspect api in payments",
  });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  trigger.focus();
  fireEvent.click(trigger);
  const drawer = screen.getByRole("dialog", { name: "api" });
  expect(drawer).toHaveFocus();
  expect(
    within(drawer).getByText("Deployed Git revision not verified."),
  ).toBeVisible();
  expect(document.body.style.overflow).toBe("hidden");
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(document.body.style.overflow).not.toBe("hidden");
  expect(trigger).toHaveFocus();
});

it("searches names and images without changing migration scope or running analysis", async () => {
  open();
  const search = await screen.findByRole("searchbox", {
    name: "Search workloads",
  });
  fireEvent.change(search, { target: { value: "missing" } });
  expect(screen.getByText(/No workloads match these filters/)).toBeVisible();
  fireEvent.change(search, { target: { value: "customer/api:1.2" } });
  expect(
    screen.getByRole("button", { name: "Inspect api in payments" }),
  ).toBeVisible();
  expect(api.analyze).not.toHaveBeenCalled();
  expect(api.saveSettings).not.toHaveBeenCalled();
});

it("does not repeat namespace confirmation instructions after a mapping is confirmed", async () => {
  api.evidence.mockResolvedValue({
    ...report,
    workloads: [
      {
        ...row,
        mappingStatus: "CONFIRMED",
        candidates: [{ ...row.candidates[0], match: "NAMESPACE_UNSPECIFIED" }],
      },
    ],
  });
  open();
  fireEvent.click(
    await screen.findByRole("button", { name: "Inspect api in payments" }),
  );
  expect(
    screen.queryByText(/Manifest namespace unspecified/),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Confirm source" }),
  ).not.toBeInTheDocument();
  expect(screen.getByText("Deployed Git revision not verified.")).toBeVisible();
});

it("keeps empty discovered namespaces selectable and moves raw evidence behind diagnostics", async () => {
  api.evidence.mockResolvedValue({
    ...report,
    namespaces: [
      { name: "empty", workloadCount: 0 },
      { name: "payments", workloadCount: 1 },
    ],
  });
  open();
  const filter = await screen.findByRole("combobox", {
    name: "Evidence namespace",
  });
  expect(
    screen.queryByRole("button", { name: "Container registry" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByText("Repository artifact index"),
  ).not.toBeInTheDocument();
  fireEvent.change(filter, { target: { value: "empty" } });
  expect(screen.getByText(/No workloads match these filters/)).toBeVisible();
  expect(api.refresh).not.toHaveBeenCalled();
});

it("analyzes a fresh inventory once after collection when source connections are ready", async () => {
  api.settings.mockResolvedValue({ ...settings, readyForDiscovery: true });
  api.evidence.mockResolvedValue({ ...report, analysisCurrent: false });
  api.analyze.mockResolvedValue({
    ...report,
    analysisCurrent: true,
    analyzedAt: "2026-10-20T07:00:00Z",
  });
  open({ hideConnections: true });
  await waitFor(() => expect(api.analyze).toHaveBeenCalledTimes(1));
  expect(api.analyze).toHaveBeenCalledWith("MIG-db", 5);
  expect(api.refresh).not.toHaveBeenCalled();
});

it("puts source analysis and diagnostics in the discovery more-options disclosure", async () => {
  open({ hideConnections: true });
  const summary = await screen.findByLabelText("More options");
  const menu = summary.closest("details")!;
  expect(menu.open).toBe(false);
  fireEvent.click(summary);
  expect(menu.open).toBe(true);
  fireEvent.click(
    within(menu).getByRole("button", { name: "Source diagnostics" }),
  );
  expect(menu.open).toBe(false);
  expect(await screen.findByRole("dialog")).toBeVisible();
});

it("separates overview from workload inspection and preserves explorer filters across navigation", async () => {
  open({ hideConnections: true });
  const nav = screen.getByRole("navigation", {
    name: "Source discovery views",
  });
  const overview = within(nav).getByRole("button", {
    name: "Review discovery",
  });
  expect(overview).toHaveAttribute("aria-pressed", "true");
  await screen.findByRole("heading", { name: "Source review & next actions" });
  expect(
    screen.queryByRole("combobox", { name: "Evidence namespace" }),
  ).not.toBeInTheDocument();
  fireEvent.click(
    within(nav).getByRole("button", { name: "Inspect workloads" }),
  );
  const search = screen.getByRole("searchbox", { name: "Search workloads" });
  fireEvent.change(search, { target: { value: "payments" } });
  expect(
    screen.getByRole("button", { name: "Inspect api in payments" }),
  ).toBeVisible();
  fireEvent.click(overview);
  expect(
    screen.queryByRole("button", { name: "Inspect api in payments" }),
  ).not.toBeInTheDocument();
  fireEvent.click(
    within(nav).getByRole("button", { name: "Inspect workloads" }),
  );
  expect(
    screen.getByRole("searchbox", { name: "Search workloads" }),
  ).toHaveValue("payments");
  expect(api.refresh).not.toHaveBeenCalled();
});

it("labels unchecked source evidence without interpreting zero counts as missing artifacts", async () => {
  open({ hideConnections: true });
  await screen.findByText(/Deployment source checks have not completed/);
  expect(
    within(
      screen.getByRole("region", { name: "Discovery evidence summary" }),
    ).getAllByText("Not checked").length,
  ).toBeGreaterThanOrEqual(2);
  expect(
    screen.queryByRole("progressbar", {
      name: "All container images available",
    }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", {
      name: "Check sources",
      hidden: false,
    }),
  ).toBeVisible();
});

it("opens namespace evidence from the review table without changing migration scope", async () => {
  const manage = vi.fn();
  open({ hideConnections: true, onManageConnections: manage });
  fireEvent.click(await screen.findByRole("button", { name: "Review access" }));
  expect(manage).toHaveBeenCalledTimes(1);
  fireEvent.click(
    screen.getByRole("button", { name: "Inspect namespace payments" }),
  );
  expect(
    screen.getByRole("combobox", { name: "Evidence namespace" }),
  ).toHaveValue("payments");
  expect(
    within(
      screen.getByRole("navigation", { name: "Source discovery views" }),
    ).getByRole("button", { name: "Inspect workloads" }),
  ).toHaveAttribute("aria-pressed", "true");
  expect(api.saveSettings).not.toHaveBeenCalled();
  expect(api.refresh).not.toHaveBeenCalled();
});

it("allows candidate confirmation inside the selected scope without returning to discovery", async () => {
  open({ selectedKeys: new Set([scopeKey(workload)]) });
  fireEvent.click(
    await screen.findByRole("button", { name: "Inspect api in payments" }),
  );
  const confirm = screen.getByRole("button", { name: "Confirm source" });
  await waitFor(() => expect(confirm).toBeEnabled());
  fireEvent.click(confirm);
  await waitFor(() => expect(api.saveSettings).toHaveBeenCalled());
});

it("keeps source analysis visible when selected workload details are collapsed", async () => {
  open({
    selectedKeys: new Set([scopeKey(workload)]),
    collapseWorkloads: true,
  });
  expect(
    await screen.findByRole("button", {
      name: /Check sources/,
    }),
  ).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Inspect api in payments" }),
  ).not.toBeInTheDocument();
  fireEvent.click(
    await screen.findByText("Inspect selected workload evidence (1)"),
  );
  expect(
    screen.getByRole("button", { name: "Inspect api in payments" }),
  ).toBeVisible();
});
