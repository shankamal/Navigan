import { describe, expect, it } from "vitest";
import type { Assessment, SourceInventoryResource } from "@/modules/migration-management/model";
import { recommendDependencies, recommendFinding, recommendResource } from "@/modules/migration-management/planning-recommendations";

const resource = (kind: string, name: string, extras: Record<string, unknown> = {}): SourceInventoryResource & { name: string } => ({
  apiVersion: "v1", kind, name, namespace: "demo", ...extras,
});

describe("migration planning recommendations", () => {
  it("never recommends direct migration of source nodes or unreviewed storage", () => {
    expect(recommendResource(resource("Node", "worker")).resource.treatment).toBe("REVIEW");
    expect(recommendResource(resource("PersistentVolumeClaim", "db")).resource.treatment).toBe("REVIEW");
    expect(recommendResource(resource("StatefulSet", "db")).resource.treatment).toBe("REVIEW");
  });
  it("recommends target recreation for identity and secrets, without claiming execution", () => {
    expect(recommendResource(resource("Secret", "credentials")).resource.treatment).toBe("RECREATE");
    expect(recommendResource(resource("ServiceAccount", "api")).resource.treatment).toBe("RECREATE");
  });
  it("only adds explicit same-namespace references as dependencies", () => {
    const workload = resource("Deployment", "api", {
      pod: { serviceAccountName: "api-sa", containers: [{
        environment: [{source: "ConfigMap", name: "app-config"}],
        envFrom: [{configMapRef: { name: "app-config" }}],
      }] },
    });
    const selected = recommendDependencies(workload, [
      resource("ConfigMap", "app-config"),
      resource("ServiceAccount", "api-sa"),
      resource("Secret", "unrelated"),
      resource("ConfigMap", "app-config", {namespace: "other"}),
    ]);
    expect(selected.map((x) => x.resource.name).sort()).toEqual(["api-sa", "app-config"]);
    expect(selected.every((x) => x.resource.dependency)).toBe(true);
  });
  it("provides planned remediation with no fictitious evidence or verification", () => {
    const assessment = {findings:[{category:"Storage",code:"STORAGE_MAPPING",message:"Map persistent storage"}]} as Assessment;
    expect(recommendFinding(assessment,0)).toMatchObject({
      treatment:"REVIEW", owner:"", evidenceReference:"", status:"PLANNED",
    });
  });
});
