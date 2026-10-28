import { expect, it } from "vitest";
import {
  restoredWorkloadKeys,
  scopeKey,
  selectedApplicationScope,
} from "@/modules/migration-management/source-migration-scope";
const item = (kind: string, name: string, extra = {}) => ({
  apiVersion: "v1",
  kind,
  name,
  namespace: "payments",
  ...extra,
});
const api = item("Deployment", "api", {
  dependencyReferences: [
    { kind: "Service", name: "api-service" },
    { kind: "Secret", name: "api-secret" },
  ],
});
const worker = item("Deployment", "worker", {
  dependencyReferences: [{ kind: "Secret", name: "worker-secret" }],
});
const resources = [
  api,
  worker,
  item("Service", "api-service"),
  item("Secret", "api-secret"),
  item("Secret", "worker-secret"),
  item("Namespace", "payments"),
  item("Ingress", "shared", {
    backendServiceReferences: [
      { kind: "Service", name: "api-service" },
      { kind: "Service", name: "unrelated" },
    ],
  }),
  item("Service", "unrelated"),
];
it("starts without workload selection and does not treat a namespace as a workload", () => {
  expect(selectedApplicationScope(resources, new Set()).resources).toEqual([]);
  expect(
    selectedApplicationScope(
      resources,
      new Set([scopeKey(item("Namespace", "payments"))]),
    ).resources,
  ).toEqual([]);
});
it("includes only selected applications and observed dependencies without unrelated shared-ingress backends", () => {
  const scope = selectedApplicationScope(resources, new Set([scopeKey(api)]));
  expect(scope.workloads.map((r) => r.name)).toEqual(["api"]);
  expect(scope.dependencies.map((r) => r.name)).toEqual([
    "api-service",
    "api-secret",
    "payments",
    "shared",
  ]);
  expect(
    scope.resources.some(
      (r) =>
        r.name === "worker" ||
        r.name === "worker-secret" ||
        r.name === "unrelated",
    ),
  ).toBe(false);
  expect(scope.resources.find((r) => r.name === "api")?.dependency).toBe(false);
});
it("preserves missing dependency evidence without inventing resources", () => {
  const scope = selectedApplicationScope([api], new Set([scopeKey(api)]));
  expect(scope.missing).toHaveLength(2);
  expect(scope.resources).toHaveLength(1);
});
it("restores saved application selection without retired resources or dependencies", () => {
  const scope = selectedApplicationScope(resources, new Set([scopeKey(api)]));
  expect([
    ...restoredWorkloadKeys(resources, {
      resources: [
        ...scope.resources,
        {
          ...worker,
          namespace: "payments",
          treatment: "RETIRE",
          dependency: false,
        },
      ],
    } as never),
  ]).toEqual([scopeKey(api)]);
});
