import { describe, expect, it } from "vitest";
import { graphFromSanitizedInventory } from "@/modules/migration-management/migration-graph";
import { evaluateScopeReadiness } from "@/modules/migration-management/migration-readiness";
describe("migration scope readiness", () => {
  const inventory = graphFromSanitizedInventory([
    {kind:"Deployment",name:"api",namespace:"app",dependencyReferences:[
      {kind:"Service",name:"api-svc"}, {kind:"ConfigMap",name:"not-collected"}]},
    {kind:"Service",name:"api-svc",namespace:"app"},
  ]);
  const selected = [{kind:"Deployment",name:"api",namespace:"app"}];
  it("distinguishes missing inventory, unselected dependencies and pending storage strategy", () => {
    const value = evaluateScopeReadiness(inventory, selected, "UNDECIDED", true);
    expect(value.state).toBe("INCOMPLETE");
    expect(value.issues.map(i => i.type).sort()).toEqual(["DATA_STRATEGY_REQUIRED","MISSING_INVENTORY","NOT_SELECTED"]);
  });
  it("resolves selection gaps without certifying execution readiness", () => {
    const value = evaluateScopeReadiness(graphFromSanitizedInventory([
      {kind:"Deployment",name:"api",namespace:"app",dependencyReferences:[{kind:"Service",name:"api-svc"}]},
      {kind:"Service",name:"api-svc",namespace:"app"},
    ]), [...selected, {kind:"Service",name:"api-svc",namespace:"app",dependency:true}], "NO_PERSISTENT_DATA", false);
    expect(value.issues).toHaveLength(0);
    expect(value.state).toBe("REVIEW_REQUIRED");
  });
  it("flags unverified PVC ownership separately from data strategy", () => {
    const value = evaluateScopeReadiness(inventory, selected, "BACKUP_RESTORE", true, 2);
    expect(value.issues.map((issue) => issue.type)).toContain("PVC_OWNERSHIP_UNVERIFIED");
    expect(value.issues.map((issue) => issue.type)).not.toContain("DATA_STRATEGY_REQUIRED");
  });
  it("requires complete reviewed mappings and rejects no-data strategy for scoped PVCs", () => {
    const claims = [{namespace:"app",name:"data-api-0"}];
    const initial = evaluateScopeReadiness(inventory, selected, "NO_PERSISTENT_DATA", true, 0, claims, []);
    expect(initial.issues.map((issue) => issue.type)).toContain("STORAGE_MAPPING_REQUIRED");
    expect(initial.issues.map((issue) => issue.type)).toContain("DATA_STRATEGY_REQUIRED");
    const proposed = evaluateScopeReadiness(inventory, selected, "BACKUP_RESTORE", true, 0, claims, [{
      namespace:"app",sourceClaim:"data-api-0",targetStorageClass:"gp3",targetCapacity:"10Gi",targetAccessMode:"ReadWriteOnce",status:"PROPOSED"
    }]);
    expect(proposed.issues.map((issue) => issue.type)).toContain("STORAGE_MAPPING_REVIEW");
    const reviewed = evaluateScopeReadiness(inventory, selected, "BACKUP_RESTORE", true, 0, claims, [{
      namespace:"app",sourceClaim:"data-api-0",targetStorageClass:"gp3",targetCapacity:"10Gi",targetAccessMode:"ReadWriteOnce",status:"REVIEWED"
    }]);
    expect(reviewed.issues.some((issue) => issue.type.startsWith("STORAGE_MAPPING"))).toBe(false);
  });
  it("treats old inventories without references as incomplete evidence", () => {
    const value = evaluateScopeReadiness(graphFromSanitizedInventory([{kind:"Deployment",name:"api",namespace:"app"}]), selected, "UNDECIDED", false);
    expect(value.issues.map(i => i.type)).toContain("COVERAGE_UNKNOWN");
  });
});
