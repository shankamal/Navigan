import { describe, expect, it } from "vitest";
import type { MigrationPlanningDraft } from "../src/modules/migration-management/model";
import { hasSelectedWorkload, preparePlanningDraft, restorePlanningNamespaces } from "../src/modules/migration-management/planning-draft-scope";

const draft: MigrationPlanningDraft = {
  schemaVersion: 1, mode: "SELECTED_WORKLOADS", assessmentVersion: 2,
  inventoryDigest: "a".repeat(64), resources: [
    {apiVersion:"apps/v1",kind:"Deployment",namespace:"headlamp",name:"headlamp",treatment:"MIGRATE",dependency:false},
    {apiVersion:"apps/v1",kind:"Deployment",namespace:"retailflow",name:"api",treatment:"MIGRATE",dependency:false},
    {apiVersion:"v1",kind:"ServiceAccount",namespace:"retailflow",name:"api-sa",treatment:"MIGRATE",dependency:true},
  ], remediations: [], dataStrategy: "UNDECIDED", notes: "",
};
const assessed = ["calico-system", "default", "headlamp", "ingress-nginx", "migration-demo", "navigan-migration", "retailflow", "tigera-operator"];

describe("Migration Source planning scope", () => {
  it("starts with no namespaces selected for a new draft", () => {
    expect(restorePlanningNamespaces(assessed, null)).toEqual([]);
    expect(restorePlanningNamespaces(assessed, {...draft,resources:[]})).toEqual([]);
  });
  it("restores only legacy draft namespaces, never the whole source inventory", () => {
    expect(restorePlanningNamespaces(assessed, draft)).toEqual(["headlamp","retailflow"]);
  });
  it("restores exactly an explicitly saved selection, including an empty draft", () => {
    expect(restorePlanningNamespaces(assessed,{...draft,selectedNamespaces:["retailflow"]})).toEqual(["retailflow"]);
    expect(restorePlanningNamespaces(assessed,{...draft,selectedNamespaces:[]})).toEqual([]);
  });
  it("does not restore namespaces outside the assessed source", () => {
    expect(restorePlanningNamespaces(assessed,{...draft,selectedNamespaces:["retailflow","unknown"]})).toEqual(["retailflow"]);
  });
  it("persists a unique namespace selection without mutating the saved draft", () => {
    const next=preparePlanningDraft(draft,["retailflow","retailflow","headlamp"]);
    expect(next.selectedNamespaces).toEqual(["retailflow","headlamp"]);
    expect(draft.selectedNamespaces).toBeUndefined();
    expect(next.resources).toHaveLength(3);
  });
  it("gates Continue to Target on a primary workload in the current selected scope", () => {
    expect(hasSelectedWorkload(draft,["retailflow"])).toBe(true);
    expect(hasSelectedWorkload(draft,["default"])).toBe(false);
    expect(hasSelectedWorkload({...draft,resources:[draft.resources[2]]},["retailflow"])).toBe(false);
  });
  it("cleared drafts restore no namespace selection on reload", () => {
    const cleared:MigrationPlanningDraft={...draft,resources:[],remediations:[],selectedNamespaces:[]};
    expect(restorePlanningNamespaces(assessed,cleared)).toEqual([]);
  });
});
