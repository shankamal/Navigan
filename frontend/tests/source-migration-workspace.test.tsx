import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { SourceMigrationWorkspace } from "@/modules/migration-management/source-migration-workspace";
const api = vi.hoisted(() => ({
  update: vi.fn(),
  source: vi.fn(),
  targets: vi.fn(),
  analyzeTarget: vi.fn(),
  compatibility: vi.fn(),
  canEdit: true,
}));
vi.mock("@/shared/auth/auth-provider", () => ({
  useAuth: () => ({ identity: {} }),
}));
vi.mock("@/shared/auth/permissions", () => ({
  hasPermission: () => api.canEdit,
}));
vi.mock("@/modules/cluster-management/service", () => ({
  clusters: { list: api.targets },
}));
vi.mock("@/modules/migration-management/service", () => ({
  sourceClusters: { get: api.source },
  migrations: {
    update: api.update,
    analyzeTarget: api.analyzeTarget,
    targetCompatibility: api.compatibility,
  },
}));
const workload = (name: string) => ({
  apiVersion: "apps/v1",
  kind: "Deployment",
  name,
  namespace: "payments",
  dependencyReferences: [{ kind: "ConfigMap", name: `${name}-config` }],
});
const migration = {
  migrationId: "MIG-db",
  customerId: "CUS-db",
  customerName: "DB Schenker",
  name: "DBS_Migration_Assessment",
  version: 6,
  status: "ASSESSMENT_READY",
  sourceConfiguration: { sourceClusterId: "SRC-db" },
  targetConfiguration: {},
  migrationScope: { namespaces: ["payments"] },
  planningDraft: {},
};
const assessment = {
  assessmentVersion: 1,
  migrationVersion: 4,
  inventoryDigest: "a".repeat(64),
  findings: [],
  inventorySummary: {},
};
const inventory = {
  inventoryVersion: 1,
  inventoryDigest: "a".repeat(64),
  sourceKubernetesVersion: "v1.37.1",
  resources: [
    workload("payment-api"),
    workload("payment-worker"),
    {
      apiVersion: "v1",
      kind: "ConfigMap",
      namespace: "payments",
      name: "payment-api-config",
    },
    {
      apiVersion: "v1",
      kind: "ConfigMap",
      namespace: "payments",
      name: "payment-worker-config",
    },
  ],
};
function open() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <SourceMigrationWorkspace
        migration={migration as never}
        assessment={assessment as never}
        inventory={inventory as never}
      />
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  api.canEdit = true;
  api.source.mockResolvedValue({
    name: "navigan-migration-lab",
    distribution: "kubeadm",
  });
  api.targets.mockResolvedValue({ items: [], pagination: { totalPages: 1 } });
  api.update.mockImplementation(async (_id, body) => ({
    ...migration,
    version: 7,
    planningDraft:
      body.planningDraft ?? api.update.mock.calls[0]?.[1].planningDraft ?? {},
    targetConfiguration: body.target ?? {},
  }));
});
it("uses the six-stage application migration flow and never auto-selects all workloads in a namespace", async () => {
  open();
  const flow = screen.getByRole("list", { name: "Migration workflow" });
  expect(within(flow).getAllByRole("listitem")).toHaveLength(6);
  expect(screen.queryByText("Migration Plan")).not.toBeInTheDocument();
  const save = screen.getByRole("button", {
    name: "Save & continue to target",
  });
  expect(save).toBeDisabled();
  fireEvent.click(
    within(screen.getByLabelText("Source namespaces")).getByRole("checkbox"),
  );
  expect(
    screen.getByRole("checkbox", { name: "Migrate payments/payment-api" }),
  ).not.toBeChecked();
  expect(
    screen.getByRole("checkbox", { name: "Migrate payments/payment-worker" }),
  ).not.toBeChecked();
  expect(save).toBeDisabled();
  expect(api.targets).not.toHaveBeenCalled();
});
it("saves only the selected workload, its dependencies and supplied Helm metadata before target selection", async () => {
  open();
  fireEvent.click(
    within(screen.getByLabelText("Source namespaces")).getByRole("checkbox"),
  );
  fireEvent.click(
    screen.getByRole("checkbox", { name: "Migrate payments/payment-api" }),
  );
  fireEvent.change(screen.getByLabelText("Deployment method for payment-api"), {
    target: { value: "HELM" },
  });
  fireEvent.change(screen.getByLabelText("Bundle name for payment-api"), {
    target: { value: "payments-chart" },
  });
  fireEvent.change(
    screen.getByLabelText("Artifact reference for payment-api"),
    { target: { value: "https://example.test/payments.git/charts" } },
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Save & continue to target" }),
  );
  await waitFor(() => expect(api.update).toHaveBeenCalled());
  const draft = api.update.mock.calls[0][1].planningDraft;
  expect(draft.workflow).toBe("SOURCE_FIRST");
  expect(draft.resources.map((r: { name: string }) => r.name)).toEqual([
    "payment-api",
    "payment-api-config",
  ]);
  expect(draft.selectedNamespaces).toEqual(["payments"]);
  expect(draft.deploymentSources[0].method).toBe("HELM");
  expect(draft.deploymentSources[0].bundleName).toBe("payments-chart");
  await screen.findByRole("heading", {
    name: "Choose a Navigan-managed destination",
  });
  expect(api.analyzeTarget).not.toHaveBeenCalled();
  expect(
    screen.getByRole("button", { name: "Assess target compatibility" }),
  ).toBeDisabled();
});
it("does not advance to target selection after a failed scope save", async () => {
  api.update.mockRejectedValue(new Error("Save failed"));
  open();
  fireEvent.click(
    within(screen.getByLabelText("Source namespaces")).getByRole("checkbox"),
  );
  fireEvent.click(
    screen.getByRole("checkbox", { name: "Migrate payments/payment-api" }),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Save & continue to target" }),
  );
  await screen.findByRole("alert");
  expect(
    screen.queryByRole("heading", {
      name: "Choose a Navigan-managed destination",
    }),
  ).not.toBeInTheDocument();
  expect(api.targets).not.toHaveBeenCalled();
});
it("keeps evidence read-only without migration edit permission", () => {
  api.canEdit = false;
  open();
  expect(
    within(screen.getByLabelText("Source namespaces")).getByRole("checkbox"),
  ).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Save scope draft" }),
  ).toBeDisabled();
});

it("checks only the saved scope against a customer target and keeps approval and execution gated", async () => {
  api.targets.mockResolvedValue({
    items: [
      {
        clusterId: "CLU-db",
        customerId: "CUS-db",
        clusterName: "dbs-target",
        environmentId: "ENV-db",
        environmentApprovedVersion: 8,
        status: "ACTIVE",
        platform: "EKS",
      },
      {
        clusterId: "CLU-other",
        customerId: "CUS-other",
        clusterName: "other-target",
        status: "ACTIVE",
        platform: "EKS",
      },
    ],
    pagination: { totalPages: 1 },
  });
  api.analyzeTarget.mockResolvedValue({ assessment: {} });
  api.compatibility.mockResolvedValue({
    coverageComplete: false,
    decision: { path: "PENDING_EVIDENCE", reason: "Missing target coverage" },
    resourceEvaluations: [],
  });
  open();
  fireEvent.click(
    within(screen.getByLabelText("Source namespaces")).getByRole("checkbox"),
  );
  fireEvent.click(
    screen.getByRole("checkbox", { name: "Migrate payments/payment-api" }),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Save & continue to target" }),
  );
  const target = await screen.findByLabelText("Target cluster *");
  await screen.findByRole("option", { name: /dbs-target/ });
  expect(
    screen.queryByRole("option", { name: /other-target/ }),
  ).not.toBeInTheDocument();
  fireEvent.change(target, { target: { value: "CLU-db" } });
  fireEvent.click(
    screen.getByRole("button", { name: "Assess target compatibility" }),
  );
  await screen.findByRole("heading", { name: /PENDING_EVIDENCE/ });
  expect(api.update.mock.calls[1][1].target.clusterId).toBe("CLU-db");
  expect(api.analyzeTarget).toHaveBeenCalledWith("MIG-db");
  fireEvent.click(
    screen.getByRole("button", { name: "Review scope & readiness" }),
  );
  expect(
    screen.getByRole("button", { name: "Submit for migration approval" }),
  ).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Execute migration" }),
  ).toBeDisabled();
});
