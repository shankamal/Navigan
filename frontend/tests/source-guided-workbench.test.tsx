import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Assessment, Migration, SourceInventory } from "@/modules/migration-management/model";
import { PlanningEditor } from "@/modules/migration-management/planning-workspace";
import { ApiError } from "@/shared/api/client";

const api = vi.hoisted(() => ({
  update: vi.fn(), sourceInventory: vi.fn(), assessment: vi.fn(),
  targetAssessment: vi.fn(), targetCompatibility: vi.fn(), analyzeTarget: vi.fn(), canEdit: true,
}));
vi.mock("@/shared/auth/auth-provider", () => ({ useAuth: () => ({identity: {}}) }));
vi.mock("@/shared/auth/permissions", () => ({hasPermission: () => api.canEdit}));
vi.mock("@/modules/migration-management/service", () => ({migrations: api}));

const migration = {
  migrationId: "MIG-guided", customerId: "customer", name: "Source demo",
  status: "APPROVED", version: 7, sourceConfiguration: {clusterName: "source-east"},
  targetConfiguration: {clusterId: "target-west"},
  migrationScope: {namespaces: ["orders", "payments"]},
} as Migration;
const assessment = {
  assessmentVersion: 3, inventoryDigest: "a".repeat(64), findings: [],
  inventorySummary: {target: {clusterName: "target-west"}},
} as unknown as Assessment;
const inventory = {
  inventoryDigest: "a".repeat(64), inventoryVersion: 1, resources: [
    {apiVersion: "apps/v1",kind: "Deployment",namespace: "orders",name: "orders-api"},
    {apiVersion: "v1",kind: "PersistentVolumeClaim",namespace: "orders",name: "orders-data",requestedStorage: "5Gi"},
    {apiVersion: "apps/v1",kind: "StatefulSet",namespace: "payments",name: "payments-db"},
    {apiVersion: "v1",kind: "Service",namespace: "payments",name: "payments-api"},
  ],
} as SourceInventory;

function open(overrides: Partial<Migration> = {}) {
  const queryClient = new QueryClient({defaultOptions: {queries: {retry: false}, mutations: {retry: false}}});
  return render(<QueryClientProvider client={queryClient}><PlanningEditor migration={{...migration,...overrides}} assessment={assessment} inventory={inventory}/></QueryClientProvider>);
}

describe("guided Source planning", () => {
  beforeEach(() => {
    api.canEdit = true;
    for (const fn of [api.update,api.sourceInventory,api.assessment,api.targetAssessment,api.targetCompatibility,api.analyzeTarget]) fn.mockReset();
    api.sourceInventory.mockResolvedValue({inventory});
    api.assessment.mockResolvedValue({assessment});
    api.targetAssessment.mockResolvedValue({assessment: null});
    api.targetCompatibility.mockResolvedValue({resourceEvaluations: []});
    api.analyzeTarget.mockResolvedValue({assessment: null});
    api.update.mockImplementation(async (_id: string,input: {planningDraft: unknown}) => ({...migration,version: 8,planningDraft: input.planningDraft}));
  });

  it("starts at Choose namespaces with selected-scope only", () => {
    open();
    const planning = screen.getByRole("region", {name: "Source migration planning"});
    expect(within(planning).getByRole("heading", {name: "Choose namespaces"})).toBeInTheDocument();
    expect(within(planning).getByText("Full cluster migration")).toBeInTheDocument();
    expect(within(planning).getByText("Not available yet")).toBeInTheDocument();
    expect(within(planning).getByRole("button", {name: /Analyze selected namespaces/})).toBeDisabled();
    fireEvent.click(within(planning).getByRole("button", {name: "Select all namespaces"}));
    expect(within(planning).getByRole("button", {name: /Analyze selected namespaces/})).toBeEnabled();
  });

  it("refreshes Source evidence and includes discovered workloads and PVCs", async () => {
    open();
    fireEvent.click(screen.getByRole("button", {name: "Select all namespaces"}));
    fireEvent.click(screen.getByRole("button", {name: /Analyze selected namespaces/}));
    await waitFor(() => expect(api.sourceInventory).toHaveBeenCalledWith("MIG-guided"));
    await waitFor(() => expect(screen.getByRole("heading", {name: "Review workloads & dependencies"})).toBeInTheDocument());
    const planning = screen.getByRole("region", {name: "Source migration planning"});
    expect(within(planning).getByText("orders-api")).toBeInTheDocument();
    expect(within(planning).getByText("orders-data")).toBeInTheDocument();
    expect(within(planning).getByText("payments-db")).toBeInTheDocument();
    expect(within(planning).getByText(/External databases, storage transfer/)).toBeInTheDocument();
    fireEvent.click(within(planning).getByRole("button", {name: /Review source scope/}));
    expect(within(planning).getByRole("heading", {name: "Review & save source scope"})).toBeInTheDocument();
  });

  it("saves the reviewed Source draft and advances to Target compatibility", async () => {
    open();
    fireEvent.click(screen.getByRole("button", {name: "Select all namespaces"}));
    fireEvent.click(screen.getByRole("button", {name: /Analyze selected namespaces/}));
    await screen.findByRole("heading", {name: "Review workloads & dependencies"});
    fireEvent.click(screen.getByRole("button", {name: /Review source scope/}));
    fireEvent.click(screen.getByRole("button", {name: /Save scope & continue to Target/}));
    await waitFor(() => expect(api.update).toHaveBeenCalledTimes(1));
    const payload = api.update.mock.calls[0][1].planningDraft;
    expect(payload.selectedNamespaces).toEqual(["orders", "payments"]);
    expect(payload.resources.some((item: {kind: string;name: string}) => item.kind === "PersistentVolumeClaim" && item.name === "orders-data")).toBe(true);
    expect(payload.mode).toBe("SELECTED_WORKLOADS");
    await waitFor(() => expect(screen.getByRole("button", {name: /Target & Compatibility/})).toHaveAttribute("aria-current", "step"));
  });

  it("supports selecting all namespaces after clearing the selection", async () => {
    open();
    const planning = screen.getByRole("region", {name: "Source migration planning"});
    fireEvent.click(within(planning).getByRole("button", {name: "Select all namespaces"}));
    fireEvent.click(within(planning).getByRole("button", {name: "Clear selection"}));
    expect(within(planning).getByRole("button", {name: /Analyze selected namespaces/})).toBeDisabled();
    fireEvent.click(within(planning).getByRole("button", {name: "Select all namespaces"}));
    expect(within(planning).getByRole("button", {name: /Analyze selected namespaces/})).toBeEnabled();
  });

  it("keeps Source planning read-only without migration edit permission", () => {
    api.canEdit = false;
    open();
    expect(screen.getByRole("button", {name: /Analyze selected namespaces/})).toBeDisabled();
    expect(screen.getByRole("button", {name: /Clear draft/})).toBeDisabled();
  });

  it("retries empty Clear Draft against older backends that reject selectedNamespaces", async () => {
    const prior = {...migration,planningDraft: {schemaVersion:1,mode:"SELECTED_WORKLOADS",assessmentVersion:3,inventoryDigest: "a".repeat(64),selectedNamespaces:["orders"],resources:[],remediations:[],dataStrategy:"UNDECIDED",notes:""}} as Migration;
    api.update.mockRejectedValueOnce(new ApiError("Check the highlighted request fields.",400,"VALIDATION_ERROR",undefined,{fields:[{field:"planningDraft.selectedNamespaces",message:"Extra inputs are not permitted"}]}));
    open(prior);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", {name: "Clear draft"}));
    await waitFor(() => expect(api.update).toHaveBeenCalledTimes(2));
    expect(api.update.mock.calls[1][1].planningDraft.selectedNamespaces).toBeUndefined();
    confirm.mockRestore();
  });
});
