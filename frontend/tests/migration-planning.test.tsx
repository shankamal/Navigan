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

// Current planning UI reveals resource controls after explicit scope analysis.
function analyzeScope() {
  fireEvent.click(screen.getByRole("button", { name: "Analyze selected scope" }));
}
function openTechnicalResources() {
  analyzeScope();
  fireEvent.click(screen.getByRole("button", { name: /All resources.*Technical view/ }));
}

describe("migration planning", () => {
  beforeEach(() => {
    mock.canEdit = true;
    mock.update.mockReset();
    mock.update.mockResolvedValue({ ...migration, version: 8 });
  });
  it("persists resource selection and dependency confirmation without altering assessment scope", async () => {
    open();
    openTechnicalResources();
    fireEvent.click(
      screen.getByLabelText("Include Deployment retailflow/retailflow-api"),
    );
    fireEvent.click(
      screen.getByLabelText("Include StatefulSet retailflow/postgres"),
    );
    fireEvent.click(screen.getByLabelText("Required dependency postgres"));
    fireEvent.click(screen.getByRole("button", { name: "Data & Storage" }));
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
  it("analyzes explicit namespace scope without silently adding unverified resources", () => {
    open();
    expect(screen.getByRole("button", {name:"Continue to target"})).toBeDisabled();
    expect(screen.getByRole("button", {name:"Analyze selected scope"})).toBeEnabled();
    analyzeScope();
    fireEvent.click(screen.getByRole("button", { name: /All resources.*Technical view/ }));
    fireEvent.click(screen.getByLabelText("Include Deployment retailflow/retailflow-api"));
    expect(screen.getByRole("button", {name:"Continue to target"})).toBeDisabled();
    analyzeScope();
    const reviewPanel = screen.getByRole("region",{name:"Selected migration scope review"});
    expect(reviewPanel).toHaveTextContent("retailflow-api");
    expect(reviewPanel).toHaveTextContent("Missing reference coverage is not confirmation of completeness");
    expect(screen.getByRole("button",{name:"Continue to target"})).toBeEnabled();
    expect(screen.getByRole("region",{name:"Selected migration scope review"})).toBeVisible();
  });
  it("supports analysis of multiple explicitly selected namespaces", () => {
    open({}, {...inventory,resources:[...inventory.resources,{
      apiVersion:"apps/v1",kind:"Deployment",namespace:"payments",name:"payments-api",
    }]} as SourceInventory);
    fireEvent.click(screen.getByText("Select namespaces · 1 selected"));
    fireEvent.click(screen.getByLabelText("Select namespace payments"));
    fireEvent.click(screen.getByRole("button",{name:"Analyze selected scope"}));
    const result=screen.getByRole("region",{name:"Selected migration scope review"});
    expect(result).toHaveTextContent("payments");
    expect(result).toHaveTextContent("retailflow-api");
    expect(result).toHaveTextContent("payments-api");
    expect(screen.getByRole("navigation", {name:"Migration workflow"})).toHaveTextContent("Source");
    expect(result).toHaveTextContent("Choose workloads for migration");
    expect(result).toHaveTextContent("Discovered");
    fireEvent.click(screen.getAllByRole("button",{name:"Add to Draft"}).at(-1)!);
    expect(screen.getByLabelText("Selected migration scope review")).toHaveTextContent("payments-api");
    expect(screen.getByText(/Choose workloads for migration/)).toBeInTheDocument();
    expect(result).toHaveTextContent("Missing reference coverage is not confirmation of completeness");
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
    
    openTechnicalResources();
    fireEvent.click(screen.getByLabelText("Include StatefulSet retailflow/postgres"));
    fireEvent.click(screen.getByRole("button", { name: "4 · Remediation" }));
    expect(screen.getAllByText("Mutable image references").length).toBeGreaterThan(0);
    expect(screen.queryByText("Other namespace warning")).toBeNull();
    expect(screen.getByLabelText("Findings view")).toHaveValue("SCOPE");
    expect(screen.getByLabelText("Remediation namespace")).toBeDisabled();
  });
  it("previews and acknowledges an accepted remediation recommendation", () => {
    open();
    fireEvent.click(screen.getByRole("button", { name: "4 · Remediation" }));
    fireEvent.change(screen.getByLabelText("Findings view"), { target: { value: "SHARED" } });
    expect(screen.getByText("Guided recommendation")).toBeVisible();
    expect(screen.getByLabelText("Remediation intelligence explanation")).toHaveTextContent("Storage equivalence");
    expect(screen.getByLabelText("Source to target remediation comparison")).toBeVisible();
    expect(screen.getByRole("button", {name:"Customize recommendation"})).toBeVisible();
    expect(screen.getByRole("button", { name: "Record for manual review" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Record for manual review" }));
    expect(screen.getByLabelText("Migration action")).toHaveValue("REVIEW");
    expect(screen.getByLabelText("Migration action")).toBeVisible();
    expect(screen.getByLabelText("Owner")).toBeVisible();
    expect(screen.getByLabelText("Work status")).toBeVisible();
    expect(screen.getByLabelText("Target mapping")).not.toHaveValue("");
    fireEvent.change(screen.getByLabelText("Target mapping"), {target:{value:"Review target CSI and data restore requirements"}});
    expect(screen.getByLabelText("Target mapping")).toHaveValue("Review target CSI and data restore requirements");
    expect(screen.getByRole("button", { name: "Decision in draft" })).toBeDisabled();
  });
  it("guides users between remediation findings and closes customization on navigation", () => {
    const scopedAssessment = {...assessment,findings:[
      {...assessment.findings[0],code:"STORAGE_MAPPING",message:"Storage mapping requires review"},
      {...assessment.findings[0],code:"IMAGE_DIGEST",category:"Security",message:"Container image is not pinned"},
    ]} as Assessment;
    const client = new QueryClient({defaultOptions:{mutations:{retry:false}}});
    render(<QueryClientProvider client={client}><PlanningEditor migration={migration} assessment={scopedAssessment} inventory={inventory}/></QueryClientProvider>);
    fireEvent.click(screen.getByRole("button",{name:"4 · Remediation"}));
    fireEvent.change(screen.getByLabelText("Findings view"),{target:{value:"SHARED"}});
    expect(screen.getByLabelText("Finding decision navigation")).toHaveTextContent("Finding 1 of 2");
    fireEvent.click(screen.getByRole("button",{name:"Customize recommendation"}));
    expect(screen.getByLabelText("Target mapping")).toBeVisible();
    fireEvent.click(screen.getByRole("button",{name:"Next finding"}));
    expect(screen.getByLabelText("Finding decision navigation")).toHaveTextContent("Finding 2 of 2");
    expect(screen.queryByLabelText("Target mapping")).not.toBeInTheDocument();
  });
  it("supports selecting findings and accepting eligible recommendations into the draft", () => {
    open();
    fireEvent.click(screen.getByRole("button", {name:"4 · Remediation"}));
    fireEvent.change(screen.getByLabelText("Findings view"), {target:{value:"SHARED"}});
    expect(screen.queryByLabelText("Remediation bulk actions")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", {name:"Select finding 0"}));
    expect(screen.getByLabelText("Remediation bulk actions")).toBeVisible();
    const bulk = screen.getByRole("button", {name:"Accept eligible selections"});
    expect(bulk).toBeEnabled();
    fireEvent.click(bulk);
    expect(screen.getByLabelText("Remediation overview")).toBeVisible();
  });
  it("navigates actionable remediation views without leaving the draft", () => {
    open();
    fireEvent.click(screen.getByRole("button",{name:"4 · Remediation"}));
    expect(screen.getByRole("navigation",{name:"Remediation workspace views"})).toBeVisible();
    fireEvent.click(screen.getByRole("button",{name:/Target mappings/}));
    expect(screen.getByLabelText("Target mapping workspace")).toBeVisible();
    fireEvent.click(screen.getByRole("button",{name:/Remediation plan/}));
    expect(screen.getByLabelText("Consolidated remediation plan")).toBeVisible();
    fireEvent.click(screen.getByRole("button",{name:/Recommended fixes/}));
    expect(screen.queryByLabelText("Remediation bulk actions")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Remediation findings list")).toBeVisible();
    expect(screen.getByText("Finding / resource")).toBeVisible();
    expect(screen.getByText("Recommended action")).toBeVisible();
  });
  it("opens a recorded decision directly in edit mode with clear next steps", () => {
    open();
    fireEvent.click(screen.getByRole("button",{name:"4 · Remediation"}));
    fireEvent.change(screen.getByLabelText("Findings view"),{target:{value:"SHARED"}});
    fireEvent.click(screen.getByRole("button",{name:"Customize recommendation"}));
    fireEvent.change(screen.getByLabelText("Owner"),{target:{value:"Platform team"}});
    fireEvent.click(screen.getByRole("button",{name:/Remediation plan/}));
    fireEvent.click(screen.getByRole("button",{name:"Edit decision"}));
    expect(screen.getByText("Editing recorded decision")).toBeVisible();
    expect(screen.getByLabelText("Owner")).toHaveValue("Platform team");
    expect(screen.getByRole("button",{name:"Save remediation decision"})).toBeEnabled();
    fireEvent.click(screen.getByRole("button",{name:"Back to remediation plan"}));
    expect(screen.getByLabelText("Consolidated remediation plan")).toBeVisible();
  });
  it("records a proposed PVC mapping through the target mapping workspace", () => {
    open({targetConfiguration:{platform:"EKS",clusterId:"CLU-demo"}} as Partial<Migration>,{
      ...inventory,resources:[...inventory.resources,{apiVersion:"v1",kind:"PersistentVolumeClaim",name:"data-postgres-0",namespace:"retailflow",requestedStorage:"8Gi",storageClassName:"navigan-ebs-gp3",accessModes:["ReadWriteOnce"]}],
    } as SourceInventory);
    analyzeScope();
    fireEvent.click(screen.getByRole("button",{name:"Data & Storage"}));
    fireEvent.click(screen.getByRole("button",{name:"Include PVC"}));
    fireEvent.click(screen.getByRole("button",{name:"4 · Remediation"}));
    fireEvent.click(screen.getByRole("button",{name:/Target mappings/}));
    expect(screen.getByLabelText("Target mapping workspace")).toBeVisible();
    expect(screen.getByRole("button",{name:"Add mapping to draft"})).toBeEnabled();
    fireEvent.click(screen.getByRole("button",{name:"Add mapping to draft"}));
    expect(screen.getByLabelText("Target mapping workspace")).toHaveTextContent("Mapping recorded in draft");
  });
  it("captures remediation evidence without exposing verification or execution actions", () => {
    open();
    fireEvent.click(screen.getByRole("button", { name: "4 · Remediation" }));
    fireEvent.change(screen.getByLabelText("Findings view"), { target: { value: "SHARED" } });
    fireEvent.click(screen.getByRole("button", {name:"Customize recommendation"}));
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
    openTechnicalResources();
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
      screen.getByText(/Full-estate coverage must be confirmed before execution planning/),
    ).toBeVisible();

    analyzeScope();
    fireEvent.click(screen.getByRole("button", { name: /All resources.*Technical view/ }));
    fireEvent.click(screen.getByLabelText("Include Node cluster/source-node"));
    const treatment = screen.getByLabelText("Migration action source-node");
    expect(treatment.querySelector('option[value="MIGRATE"]')).toBeNull();
  });
  it("selects and clears only filtered resources", () => {
    open();
    openTechnicalResources();
    fireEvent.change(screen.getByLabelText("Search selected resources"), {
      target: { value: "postgres" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Select all filtered resources (manual override)" }),
    );
    expect(
      screen.getByLabelText("Include StatefulSet retailflow/postgres"),
    ).toBeChecked();
    openTechnicalResources();
    fireEvent.change(screen.getByLabelText("Search selected resources"), {
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
    expect(screen.getByRole("button", { name: "Continue to target" })).toBeDisabled();
    expect(screen.getByLabelText("Required scope checks")).toHaveTextContent("Analyze selected scope");
    fireEvent.click(screen.getByRole("button", { name: "4 · Remediation" }));
    expect(screen.getByLabelText("Remediation overview")).toHaveTextContent("Resources in scope");
    expect(screen.getByRole("navigation", { name: "Remediation workspace views" })).toBeVisible();
    expect(screen.getByLabelText("Finding category")).toHaveValue("ALL");
    expect(screen.getByRole("combobox", { name: "Finding category" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Continue to migration plan" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Continue to migration plan" }));
    expect(screen.getByRole("button", { name: "5 · Migration Plan" })).toHaveAttribute("aria-current", "step");
    fireEvent.click(screen.getByRole("button", { name: "Continue to review" }));
    expect(screen.getByRole("button", { name: "6 · Review & Export" })).toHaveAttribute("aria-current", "step");
    fireEvent.click(screen.getByRole("button", { name: "Previous step" }));
    expect(screen.getByRole("button", { name: "5 · Migration Plan" })).toHaveAttribute("aria-current", "step");
    fireEvent.click(screen.getByRole("button", { name: "1 · Source" }));
    expect(screen.getByRole("button", { name: "Continue to target" })).toBeDisabled();
  });
  it("defaults storage discovery to the migration namespace and excludes other namespace PVCs", () => {
    open({}, {...inventory, resources: [...inventory.resources,
      {apiVersion:"v1",kind:"PersistentVolumeClaim",name:"data-postgres-0",namespace:"retailflow",requestedStorage:"8Gi"},
      {apiVersion:"v1",kind:"PersistentVolumeClaim",name:"other-data",namespace:"migration-demo",requestedStorage:"4Gi"},
    ]} as SourceInventory);
    analyzeScope();
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
    analyzeScope();
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
    analyzeScope();
    fireEvent.click(screen.getByRole("button", { name: "Workloads" }));
    expect(screen.getByRole("button", { name: "Workloads" })).toHaveAttribute("aria-current", "page");
    fireEvent.click(screen.getByLabelText("Include Deployment retailflow/retailflow-api"));
    analyzeScope();
    fireEvent.click(screen.getByRole("button", { name: "Dependencies" }));
    expect(screen.getByText(/Source reference evidence/i)).toBeVisible();
    expect(screen.getByText(/No references in this snapshot/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Workloads" }));
    expect(screen.getByLabelText("Include Deployment retailflow/retailflow-api")).toBeInTheDocument();
    expect(screen.queryByLabelText("Include StatefulSet retailflow/postgres")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Data & Storage" }));
    expect(screen.getByText("PVC consumer references", { selector: "strong" })).toBeVisible();
    expect(screen.getByText(/Discovered PVC inventory/)).toBeVisible();
    expect(screen.getByLabelText("Storage discovery and mapping")).toBeVisible();
    expect(screen.getByLabelText("Data strategy")).toHaveValue("UNDECIDED");
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
    openTechnicalResources();
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
  it("marks report evidence incomplete when dependencies and target verification are missing", () => {
    open();
    fireEvent.click(screen.getByRole("button", { name: "6 · Review & Export" }));
    expect(screen.getByRole("status")).toHaveTextContent("Report evidence: INCOMPLETE");
    expect(screen.getByRole("status")).toHaveTextContent("zero edges does not mean no dependencies");
    expect(screen.getByRole("status")).toHaveTextContent("Target capability inventory is unavailable");
    expect(screen.getByRole("status")).toHaveTextContent("Authoritative source-to-target resource checks are not current");
  });
  it("keeps users without edit permission read-only", () => {
    mock.canEdit = false;
    open();
    expect(screen.getByText(/does not have the migration.edit permission/)).toBeVisible();
    expect(screen.getByRole("radio", {name:/Full cluster/})).toBeDisabled();
    openTechnicalResources();
    expect(
      screen.getByLabelText("Include Deployment retailflow/retailflow-api"),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save draft" })).toBeDisabled();
  });
});
