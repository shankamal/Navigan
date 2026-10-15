import { describe, expect, it, vi } from "vitest";
import type { MigrationPlanningDraft } from "../src/modules/migration-management/model";
import { confirmAndClearDraft, saveAndContinueToTarget } from "../src/modules/migration-management/planning-draft-actions";
import { restorePlanningNamespaces } from "../src/modules/migration-management/planning-draft-scope";

const draft: MigrationPlanningDraft = {
  schemaVersion:1,mode:"SELECTED_WORKLOADS",assessmentVersion:2,
  inventoryDigest:"a".repeat(64),selectedNamespaces:["headlamp"],
  resources:[{apiVersion:"apps/v1",kind:"Deployment",namespace:"headlamp",name:"headlamp",treatment:"MIGRATE",dependency:false}],
  remediations:[],storageMappings:[],dataStrategy:"UNDECIDED",notes:"",
};
describe("Source draft action workflow",()=>{
  it("persists selection before navigating to Target",async()=>{
    const order:string[]=[];
    const persist=vi.fn(async(saved:MigrationPlanningDraft)=>{expect(saved.selectedNamespaces).toEqual(["headlamp"]);order.push("saved");});
    const navigate=vi.fn(()=>order.push("target"));
    expect(await saveAndContinueToTarget(draft,["headlamp"],persist,navigate)).toBe(true);
    expect(order).toEqual(["saved","target"]);
  });
  it("never navigates if save fails",async()=>{
    const navigate=vi.fn();
    await expect(saveAndContinueToTarget(draft,["headlamp"],async()=>{throw Error("API failed")},navigate)).rejects.toThrow("API failed");
    expect(navigate).not.toHaveBeenCalled();
  });
  it("cannot advance with empty or unselected scope",async()=>{
    const persist=vi.fn();const navigate=vi.fn();
    expect(await saveAndContinueToTarget(draft,[],persist,navigate)).toBe(false);
    expect(await saveAndContinueToTarget(draft,["default"],persist,navigate)).toBe(false);
    expect(persist).not.toHaveBeenCalled();expect(navigate).not.toHaveBeenCalled();
  });
  it("canceling Clear Draft does not send a save",async()=>{
    const persist=vi.fn();
    expect(await confirmAndClearDraft(draft,()=>false,persist)).toBeNull();
    expect(persist).not.toHaveBeenCalled();
  });
  it("Clear Draft persists empty selections, and reload restores none",async()=>{
    let saved:MigrationPlanningDraft | null=null;
    const cleared=await confirmAndClearDraft(draft,()=>true,async(next)=>{saved=next;});
    expect(cleared?.resources).toEqual([]);
    expect(cleared?.selectedNamespaces).toEqual([]);
    expect(restorePlanningNamespaces(["headlamp","retailflow"],saved)).toEqual([]);
    expect(draft.resources).toHaveLength(1);
  });
  it("failed Clear Draft retains existing local draft state",async()=>{
    await expect(confirmAndClearDraft(draft,()=>true,async()=>{throw Error("save failed")})).rejects.toThrow("save failed");
    expect(draft.selectedNamespaces).toEqual(["headlamp"]);
    expect(draft.resources).toHaveLength(1);
  });
});
