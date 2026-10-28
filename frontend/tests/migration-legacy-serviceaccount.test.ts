import { describe, expect, it } from "vitest";
import {
  graphFromSanitizedInventory,
  migrationNodeId,
} from "../src/modules/migration-management/migration-graph";

describe("historical source inventory service-account evidence", () => {
  it("recovers exact observed ServiceAccount links without claiming reference coverage", () => {
    const graph = graphFromSanitizedInventory([
      {
        kind: "Deployment",
        name: "api",
        namespace: "retailflow",
        pod: {
          serviceAccountName: "api-sa",
          volumes: [{ name: "config", type: "configMap" }],
        },
      },
      { kind: "ServiceAccount", name: "api-sa", namespace: "retailflow" },
      { kind: "ConfigMap", name: "config", namespace: "retailflow" },
    ]);
    expect(graph.coverage).toBe("REFERENCES_NOT_COLLECTED");
    expect(graph.edges).toEqual([
      {
        from: migrationNodeId("Deployment", "retailflow", "api"),
        to: migrationNodeId("ServiceAccount", "retailflow", "api-sa"),
        kind: "ServiceAccount",
        name: "api-sa",
        evidence: "EXPLICIT_REFERENCE",
        resolution: "IN_INVENTORY",
      },
    ]);
  });

  it("does not duplicate an existing source dependency reference", () => {
    const graph = graphFromSanitizedInventory([
      {
        kind: "Deployment",
        name: "api",
        namespace: "retailflow",
        pod: { serviceAccountName: "api-sa" },
        dependencyReferences: [{ kind: "ServiceAccount", name: "api-sa" }],
      },
      { kind: "ServiceAccount", name: "api-sa", namespace: "retailflow" },
    ]);
    expect(graph.coverage).toBe("REFERENCES_AVAILABLE");
    expect(graph.edges).toHaveLength(1);
  });
});
