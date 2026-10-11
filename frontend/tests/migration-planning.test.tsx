import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type {
  Assessment,
  Migration,
  SourceInventory,
} from "@/modules/migration-management/model";
import { PlanningEditor } from "@/modules/migration-management/planning-workspace";

const mock = vi.hoisted(() => ({ update: vi.fn(), canEdit: true }));
vi.mock("@/shared/auth/auth-provider", () => ({
  useAuth: () => ({ identity: {} }),
}));
vi.mock("@/shared/auth/permissions", () => ({
  hasPermission: () => mock.canEdit,
}));
vi.mock("@/modules/migration-management/service", () => ({
  migrations: { update: mock.update },
}));

const migration = {
  migrationId: "MIG-demo",
  customerId: "CUS-demo",
  name: "RetailFlow pilot",
  status: "APPROVED",
  version: 7,
  sourceConfiguration: { clusterName: "Self-managed" },
  targetConfiguration: { clusterId: "CLU-demo" },
  migrationScope: { namespaces: ["retailflow"] },
} as Migration;
const assessment = {
  assessmentVersion: 2,
  inventoryDigest: "a".repeat(64),
  findings: [
    {
      code: "STORAGE_MAPPING",
      message: "Map persistent storage",
      severity: "BLOCKER",
      category: "Storage",
      resourceName: "postgres",
    },
  ],
  inventorySummary: { target: { clusterName: "DEV2-CLUS2-DEMO" } },
} as Assessment;
const inventory = {
  inventoryDigest: "a".repeat(64),
  resources: [
    {
      apiVersion: "apps/v1",
      kind: "Deployment",
      name: "retailflow-api",
      namespace: "retailflow",
    },
    {
      apiVersion: "apps/v1",
      kind: "StatefulSet",
      name: "postgres",
      namespace: "retailflow",
    },
    { apiVersion: "v1", kind: "Node", name: "source-node" },
  ],
} as SourceInventory;

function open(overrides: Partial<Migration> = {}, inventoryOverride: SourceInventory = inventory) {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <PlanningEditor
        migration={{ ...migration, ...overrides }}
        assessment={assessment}
        inventory={inventoryOverride}
      />
    </QueryClientProvider>,
  );
}

describe("migration planning", () => {
  beforeEach(() => {
    mock.canEdit = true;
    mock.update.mockReset();
    mock.update.mockResolvedValue({ ...migration, version: 8 });
  });
  it("persists resource selection and dependency confirmation without altering assessment scope", async () => {
    open();
    fireEvent.click(
      screen.getByLabelText("Include Deployment retailflow/retailflow-api"),
    );
    fireEvent.click(
      screen.getByLabelText("Include StatefulSet retailflow/postgres"),
    );
    fireEvent.click(screen.getByLabelText("Required dependency postgres"));
    fireEvent.change(screen.getByLabelText("Data strategy"), {
      target: { value: "BACKUP_RESTORE" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    await waitFor(() => expect(mock.update).toHaveBeenCalled());
    const input = mock.update.mock.calls[0][1];
    expect(input.version).toBe(7);
    expect(input.scope).toBeUndefined();
    expect(input.planningDraft.resources).toHaveLength(2);
    expect(input.planningDraft.resources[1].dependency).toBe(true);
    expect(input.planningDraft.dataStrategy).toBe("BACKUP_RESTORE");
    expect(
      (
        await screen.findAllByText(
          "Planning draft saved. No cluster changes were applied.",
        )
      )[0],
    ).toBeVisible();
  });
  it("shows namespace recommendations before selection and applies only the filtered recommendations", () => {
    open();
    fireEvent.change(screen.getByLabelText("Namespace"), { target: { value: "retailflow" } });
    expect(screen.getByText(/Navigan analysis/)).toBeVisible();
    expect(screen.getByLabelText("Scope readiness assessment")).toHaveTextContent("Scope readiness");
    expect(screen.getByLabelText("Scope readiness assessment")).toHaveTextContent("COVERAGE UNKNOWN");
    expect(screen.getByText(/2 inventoried resources in view/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Add 1 recommended resource to draft" }));
    expect(screen.getByLabelText("Include Deployment retailflow/retailflow-api")).toBeChecked();
    expect(screen.getByLabelText("Include StatefulSet retailflow/postgres")).not.toBeChecked();
    expect(screen.queryByRole("button", { name: /explicitly referenced dependencies/i })).toBeNull();
    const review = screen.getByRole("button", { name: "Review selected scope" });
    expect(review).toBeEnabled();
    fireEvent.click(review);
    const reviewPanel = screen.getByRole("region", { name: "Selected migration scope review" });
    expect(reviewPanel).toHaveTextContent("retailflow-api");
    expect(reviewPanel).toHaveTextContent("Decision required");
    fireEvent.click(screen.getByRole("button", { name: "Hide scope review" }));
    expect(screen.queryByRole("region", { name: "Selected migration scope review" })).toBeNull();
  });
  it("scopes remediation findings to the chosen namespace and resets the detail selection", () => {
    const scoped = {
      ...assessment,
      findings: [
        { ...assessment.findings[0], namespace: "retailflow", resourceKind: "StatefulSet", message: "Mutable image references", code: "IMAGE_TAG" },
        { ...assessment.findings[0], namespace: "payments", resourceName: "other", message: "Other namespace warning", code: "OTHER" },
      ],
    } as Assessment;
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <PlanningEditor migration={migration} assessment={scoped} inventory={inventory} />
      </QueryClientProvider>,
    );
    fireEvent.change(screen.getByLabelText("Namespace"), { target: { value: "retailflow" } });
    fireEvent.click(screen.getByLabelText("Include StatefulSet retailflow/postgres"));
    fireEvent.click(screen.getByRole("button", { name: "Remediate" }));
    expect(screen.getAllByText("Mutable image references").length).toBeGreaterThan(0);
    expect(screen.queryByText("Other namespace warning")).toBeNull();
    expect(screen.getByLabelText("Remediation namespace")).toHaveValue("retailflow");
  });
  it("previews and acknowledges an accepted remediation recommendation", () => {
    open();
    fireEvent.click(screen.getByRole("button", { name: "Remediate" }));
    fireEvent.change(screen.getByLabelText("Findings view"), { target: { value: "SHARED" } });
    expect(screen.getByText("Navigan suggested remediation")).toBeVisible();
    expect(screen.getByLabelText("Source to target remediation comparison")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Apply recommendation to draft" }));
    expect(screen.getByText(/Remediation added to draft/)).toBeVisible();
    expect(screen.getByLabelText("Target mapping")).not.toHaveValue("");
  });
  it("supports selecting findings and accepting eligible recommendations into the draft", () => {
    open();
    fireEvent.click(screen.getByRole("button", {name:"Remediate"}));
    fireEvent.change(screen.getByLabelText("Findings view"), {target:{value:"SHARED"}});
    const selectAll = screen.getByRole("checkbox", {name:"Select all visible remediation findings"});
    fireEvent.click(selectAll);
    const bulk = screen.getByRole("button", {name:"Accept selected recommendations"});
    expect(bulk).toBeEnabled();
    fireEvent.click(bulk);
    expect(screen.getByText(/resources in draft/)).toBeVisible();
  });
  it("navigates actionable remediation views without leaving the draft", () => {
    open();
    fireEvent.click(screen.getByRole("button",{name:"Remediate"}));
    expect(screen.getByRole("navigation",{name:"Remediation workspace views"})).toBeVisible();
    fireEvent.click(screen.getByRole("button",{name:/Target mappings/}));
    expect(screen.getByLabelText("Target mapping workspace")).toBeVisible();
    fireEvent.click(screen.getByRole("button",{name:/Remediation plan/}));
    expect(screen.getByLabelText("Consolidated remediation plan")).toBeVisible();
    fireEvent.click(screen.getByRole("button",{name:/Recommended fixes/}));
    expect(screen.getByLabelText("Remediation bulk actions")).toBeVisible();
    expect(screen.getByLabelText("Remediation findings list")).toBeVisible();
  });
  it("captures remediation evidence without exposing verification or execution actions", () => {
    open();
    fireEvent.click(screen.getByRole("button", { name: "Remediate" }));
    fireEvent.change(screen.getByLabelText("Findings view"), { target: { value: "SHARED" } });
    fireEvent.change(screen.getByLabelText("Owner"), {
      target: { value: "Application owner" },
    });
    fireEvent.change(screen.getByLabelText("Evidence reference"), {
      target: { value: "artifact:restore-test" },
    });
    expect(screen.queryByRole("button", { name: "Apply change" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Verify remediation" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save remediation decision" })).toBeEnabled();
    expect(
      screen.getByText(
        "Evidence attachment is not verification. Target preparation requires a separate authorized action.",
      ),
    ).toBeVisible();
  });
  it("blocks stale evidence and supports an explicit draft reset", () => {
    open({
      planningDraft: {
        schemaVersion: 1,
        mode: "SELECTED_WORKLOADS",
        assessmentVersion: 1,
        inventoryDigest: "b".repeat(64),
        resources: [],
        remediations: [],
        dataStrategy: "UNDECIDED",
        notes: "",
      },
    });
    expect(screen.getByRole("button", { name: "Save draft" })).toBeDisabled();
    expect(
      screen.getByLabelText("Include Deployment retailflow/retailflow-api"),
    ).toBeDisabled();
    fireEvent.click(
      screen.getByRole("button", {
        name: "Start a new draft from current evidence",
      }),
    );
    expect(
      screen.getByLabelText("Include Deployment retailflow/retailflow-api"),
    ).toBeEnabled();
  });
  it("does not imply full-cluster coverage or allow source node migration", () => {
    open();
    fireEvent.click(screen.getByRole("radio", { name: /Full cluster/ }));
    expect(
      screen.getByText(/Inventory coverage is not yet certified/),
    ).toBeVisible();
    fireEvent.change(screen.getByLabelText("Namespace"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: /All resources.*Technical view/ }));
    fireEvent.click(screen.getByLabelText("Include Node cluster/source-node"));
    const treatment = screen.getByLabelText("Treatment source-node");
    expect(treatment.querySelector('option[value="MIGRATE"]')).toBeNull();
  });
  it("selects and clears only filtered resources", () => {
    open();
    fireEvent.change(screen.getByLabelText("Search resources"), {
      target: { value: "postgres" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Select all filtered resources (manual override)" }),
    );
    expect(
      screen.getByLabelText("Include StatefulSet retailflow/postgres"),
    ).toBeChecked();
    fireEvent.change(screen.getByLabelText("Search resources"), {
      target: { value: "" },
    });
    expect(
      screen.getByLabelText("Include Deployment retailflow/retailflow-api"),
    ).not.toBeChecked();
    fireEvent.click(
      screen.getByRole("button", { name: "Clear filtered selection" }),
    );
    expect(
      screen.getByLabelText("Include StatefulSet retailflow/postgres"),
    ).not.toBeChecked();
    expect(screen.queryByRole("link", { name: "Assess" })).toBeNull();
  });
  it("navigates consistently between scope, remediation and review using footer actions", () => {
    open();
    expect(screen.getByRole("button", { name: "Previous step" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Continue to remediation" }));
    expect(screen.getByLabelText("Remediation overview")).toHaveTextContent("Migration remediation workspace");
    expect(screen.getByLabelText("Planning readiness issues for remediation")).toHaveTextContent("COVERAGE UNKNOWN");
    expect(screen.getByLabelText("Remediation decision coverage")).toBeVisible();
    expect(screen.getByLabelText("Finding category")).toHaveValue("ALL");
    expect(screen.getByRole("combobox", { name: "Finding category" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Back to scope" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Continue to review draft" }));
    expect(screen.getByRole("button", { name: "Back to remediation" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Back to remediation" }));
    expect(screen.getByRole("button", { name: "Continue to review draft" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Back to scope" }));
    expect(screen.getByRole("button", { name: "Continue to remediation" })).toBeEnabled();
  });
  it("defaults storage discovery to the migration namespace and excludes other namespace PVCs", () => {
    open({}, {...inventory, resources: [...inventory.resources,
      {apiVersion:"v1",kind:"PersistentVolumeClaim",name:"data-postgres-0",namespace:"retailflow",requestedStorage:"8Gi"},
      {apiVersion:"v1",kind:"PersistentVolumeClaim",name:"other-data",namespace:"migration-demo",requestedStorage:"4Gi"},
    ]} as SourceInventory);
    fireEvent.click(screen.getByRole("button",{name:"Data & Storage"}));
    const table = screen.getByLabelText("Storage discovery and mapping");
    expect(table).toHaveTextContent("retailflow/data-postgres-0");
    expect(table).not.toHaveTextContent("migration-demo/other-data");
  });
  it("shows compact prefilled EKS storage mappings after adding a discovered PVC", () => {
    open({targetConfiguration:{platform:"EKS",clusterId:"CLU-demo"}} as Partial<Migration>,{
      ...inventory,
      resources: [...inventory.resources, {
        apiVersion:"v1",kind:"PersistentVolumeClaim",name:"data-postgres-0",namespace:"retailflow",
        requestedStorage:"8Gi",storageClassName:"navigan-ebs-gp3",accessModes:["ReadWriteOnce"],
      }],
    } as SourceInventory);
    fireEvent.click(screen.getByRole("button",{name:"Data & Storage"}));
    fireEvent.click(screen.getByRole("button",{name:"Include PVC"}));
    expect(screen.getByLabelText("Storage discovery and mapping")).toHaveTextContent("data-postgres-0");
    expect(screen.getByLabelText("Storage class for data-postgres-0")).toHaveValue("gp3");
    expect(screen.getByLabelText("Target capacity for data-postgres-0")).toHaveValue("8Gi");
    expect(screen.getByLabelText("Target access mode for data-postgres-0")).toHaveValue("ReadWriteOnce");
    expect(screen.getByLabelText("Mapping status for data-postgres-0")).toHaveValue("PROPOSED");
  });
  it("switches between workloads, dependencies, configuration and storage without modifying selections", () => {
    open();
    expect(screen.getByRole("button", { name: "Workloads" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByLabelText("Application workload dependency map")).toHaveTextContent("retailflow-api");
    expect(screen.getByLabelText("Application workload dependency map")).toHaveTextContent("Reference evidence unavailable in this snapshot");
    fireEvent.click(screen.getByRole("button", { name: "Workloads" }));
    expect(screen.getByLabelText("Include Deployment retailflow/retailflow-api")).toBeInTheDocument();
    expect(screen.queryByLabelText("Include StatefulSet retailflow/postgres")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Data & Storage" }));
    expect(screen.getByText("PVC consumer references", { selector: "strong" })).toBeVisible();
    expect(screen.getByText(/Discovered PVC inventory/)).toBeVisible();
    expect(screen.getByLabelText("Storage discovery and mapping")).toBeVisible();
    expect(screen.getByText(/PVC metadata does not include volume data/)).toBeVisible();
    expect(screen.queryByLabelText("Include Deployment retailflow/retailflow-api")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Dependencies" }));
    expect(screen.getByText(/Source reference evidence/i)).toBeVisible();
    expect(screen.getByText(/references from selected primary resources/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Configuration" }));
    expect(screen.getByText(/Configuration resources are metadata-only inventory/i)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /All resources.*Technical view/ }));
    expect(screen.getByLabelText("Include Deployment retailflow/retailflow-api")).toBeInTheDocument();
  });
  it("shows save failures prominently and retains edits", async () => {
    mock.update.mockRejectedValue(new Error("Dev backend unavailable"));
    open();
    fireEvent.click(
      screen.getByLabelText("Include Deployment retailflow/retailflow-api"),
    );
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "An unexpected response was received. Please try again.",
    );
    expect(
      screen.getByLabelText("Include Deployment retailflow/retailflow-api"),
    ).toBeChecked();
  });
  it("keeps users without edit permission read-only", () => {
    mock.canEdit = false;
    open();
    expect(
      screen.getByLabelText("Include Deployment retailflow/retailflow-api"),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save draft" })).toBeDisabled();
  });
});
