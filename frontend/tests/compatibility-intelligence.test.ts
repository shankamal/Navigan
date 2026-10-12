import {describe,it,expect} from "vitest";
import {evaluateTargetCompatibility} from "@/modules/migration-management/compatibility-intelligence";
import type {TargetCapabilitySnapshot} from "@/modules/migration-management/target-capabilities";
const now=Date.parse("2026-10-12T10:00:00Z");
const snapshot:TargetCapabilitySnapshot={schemaVersion:1,platform:"EKS",targetId:"target-a",observedAt:"2026-10-12T09:30:00Z",source:"READ_ONLY_ADAPTER",storageClasses:[{name:"observed-class",provisioner:"example.csi",accessModes:["ReadWriteOnce"],verified:true}]};
const base={platform:"EKS",targetId:"target-a",requirements:[],claims:[{namespace:"retailflow",name:"postgres",requestedStorage:"8Gi"}],mappings:[{namespace:"retailflow",sourceClaim:"postgres",targetStorageClass:"observed-class",targetCapacity:"8Gi",targetAccessMode:"ReadWriteOnce"}],now};
describe("target compatibility intelligence",()=>{
it("keeps missing read-only target evidence unknown",()=>{const r=evaluateTargetCompatibility({...base,snapshot:null});expect(r.evidenceStatus).toBe("UNAVAILABLE");expect(r.findings.some(f=>f.capability==="Target discovery"&&f.status==="UNKNOWN")).toBe(true);});
it("rejects snapshots for a different target",()=>{const r=evaluateTargetCompatibility({...base,snapshot:{...snapshot,targetId:"other"}});expect(r.evidenceStatus).toBe("INVALID");});
it("flags storage smaller than source as incompatible",()=>{const r=evaluateTargetCompatibility({...base,snapshot,mappings:[{...base.mappings[0],targetCapacity:"4Gi"}]});expect(r.findings.some(f=>f.status==="INCOMPATIBLE")).toBe(true);});
it("avoids inferring verified workload identity from target platform",()=>{const r=evaluateTargetCompatibility({...base,snapshot,requirements:[{kind:"Deployment",namespace:"retailflow",name:"api",serviceAccountName:"retailflow-api"}]});expect(r.findings.some(f=>f.capability==="Workload identity"&&f.status==="REVIEW_REQUIRED")).toBe(true);});
it("does not invent compatibility issues from an observed storage class",()=>{const r=evaluateTargetCompatibility({...base,snapshot});expect(r.evidenceStatus).toBe("CURRENT");expect(r.findings).toHaveLength(0);});
});