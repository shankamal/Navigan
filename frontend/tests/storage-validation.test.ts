import { describe, expect, it } from "vitest";
import { evaluateStorageCompatibility } from "@/modules/migration-management/storage-validation";

const claims = [{namespace:"retailflow",name:"data-postgres-0",requestedStorage:"8Gi"}];
const mapping = {namespace:"retailflow",sourceClaim:"data-postgres-0",targetStorageClass:"gp3",targetCapacity:"8Gi",targetAccessMode:"ReadWriteOnce"};

describe("target storage compatibility", () => {
  it("flags target classes that have not been verified instead of trusting a suggestion", () => {
    const issues = evaluateStorageCompatibility(claims,[mapping],null);
    expect(issues.map(i => i.type)).toEqual(["CLASS_UNVERIFIED"]);
  });
  it("detects insufficient target capacity using Kubernetes binary and decimal quantities", () => {
    const issues = evaluateStorageCompatibility(claims,[{...mapping,targetCapacity:"8000M"}],null);
    expect(issues.map(i => i.type)).toContain("CAPACITY_TOO_SMALL");
  });
  it("uses independently verified class capabilities for access mode checks", () => {
    const evidence = {platform:"EKS",storageClasses:[{name:"gp3",verified:true,accessModes:["ReadWriteOnce"]}]};
    expect(evaluateStorageCompatibility(claims,[mapping],evidence)).toEqual([]);
    expect(evaluateStorageCompatibility(claims,[{...mapping,targetAccessMode:"ReadWriteMany"}],evidence)
      .map(i => i.type)).toContain("ACCESS_MODE_UNSUPPORTED");
  });
  it("does not treat unverified class metadata as confirmed capabilities", () => {
    const evidence = {platform:"EKS",storageClasses:[{name:"gp3",verified:false,accessModes:["ReadWriteOnce"]}]};
    expect(evaluateStorageCompatibility(claims,[mapping],evidence).map(i => i.type)).toContain("CLASS_UNVERIFIED");
  });
});
