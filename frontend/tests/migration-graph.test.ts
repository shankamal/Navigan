import { describe, expect, it } from "vitest";
import { graphFromSanitizedInventory, migrationResourceCategory } from "@/modules/migration-management/migration-graph";

describe("migration intelligence portable graph", () => {
  it("resolves namespaced Kubernetes dependencies from sanitized evidence", () => {
    const graph = graphFromSanitizedInventory([
      {kind:"Deployment",name:"api",namespace:"retailflow",dependencyReferences:[
        {kind:"Service",name:"api-service"},
        {kind:"PersistentVolumeClaim",name:"missing-data"},
      ]},
      {kind:"Service",name:"api-service",namespace:"retailflow"},
      {kind:"Service",name:"api-service",namespace:"other"},
      {kind:"Ingress",name:"edge",namespace:"retailflow",backendServiceReferences:[
        {kind:"Service",name:"api-service"},
      ]},
    ]);
    expect(graph.coverage).toBe("REFERENCES_AVAILABLE");
    expect(graph.edges).toHaveLength(3);
    expect(graph.edges.filter(e=>e.resolution === "IN_INVENTORY")).toHaveLength(2);
    expect(graph.edges.find(e=>e.name === "missing-data")?.resolution).toBe("NOT_IN_INVENTORY");
    expect(graph.nodes.find(n=>n.name==="api")?.category).toBe("WORKLOAD");
  });
  it("does not claim absent dependencies when the adapter has not collected references", () => {
    const graph = graphFromSanitizedInventory([{kind:"Deployment",name:"api",namespace:"ns"}]);
    expect(graph.coverage).toBe("REFERENCES_NOT_COLLECTED");
    expect(graph.edges).toEqual([]);
  });
  it("accepts normalized ECS and OpenShift shapes without changing the graph contract", () => {
    const ecs = graphFromSanitizedInventory([
      {kind:"TaskDefinition",name:"orders",dependencyReferences:[{kind:"EfsVolume",name:"orders-data"}]},
      {kind:"EfsVolume",name:"orders-data"},
    ],"ECS");
    const openshift = graphFromSanitizedInventory([
      {kind:"DeploymentConfig",name:"orders",namespace:"app",dependencyReferences:[{kind:"Service",name:"orders-svc"}]},
      {kind:"Service",name:"orders-svc",namespace:"app"},
    ],"OPENSHIFT");
    expect(ecs.edges[0].resolution).toBe("IN_INVENTORY");
    expect(ecs.nodes[0].platform).toBe("ECS");
    expect(openshift.edges[0].resolution).toBe("IN_INVENTORY");
    expect(migrationResourceCategory("DeploymentConfig")).toBe("WORKLOAD");
  });
});
