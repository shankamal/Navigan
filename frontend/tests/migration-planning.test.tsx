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

function open(overrides: Partial<Migration> = {}) {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <PlanningEditor
        migration={{ ...migration, ...overrides }}
        assessment={assessment}
        inventory={inventory}
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
    expect(screen.getByText(/2 inventoried resources in view/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Confirm recommended scope (1)" }));
    expect(screen.getByLabelText("Include Deployment retailflow/retailflow-api")).toBeChecked();
    expect(screen.getByLabelText("Include StatefulSet retailflow/postgres")).not.toBeChecked();
    expect(screen.queryByRole("button", { name: /explicitly referenced dependencies/i })).toBeNull();
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
    fireEvent.click(screen.getByRole("button", { name: "Apply recommendation to draft" }));
    expect(screen.getByText(/Remediation added to draft/)).toBeVisible();
    expect(screen.getByLabelText("Target mapping")).not.toHaveValue("");
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
    expect(screen.getByRole("button", { name: "Apply change" })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Verify remediation" }),
    ).toBeDisabled();
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
    expect(screen.getByRole("button", { name: "Back to scope" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Continue to review draft" }));
    expect(screen.getByRole("button", { name: "Back to remediation" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Back to remediation" }));
    expect(screen.getByRole("button", { name: "Continue to review draft" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Back to scope" }));
    expect(screen.getByRole("button", { name: "Continue to remediation" })).toBeEnabled();
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
