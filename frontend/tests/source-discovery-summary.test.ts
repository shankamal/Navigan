import { expect, it } from "vitest";
import {
  discoveryScope,
  groupSourceFindings,
  inventorySummary,
} from "@/modules/migration-management/source-discovery-summary";
import type { Assessment } from "@/modules/migration-management/model";
const finding = {
  code: "RBAC_REVIEW",
  severity: "WARNING",
  category: "IDENTITY",
  disposition: "MANUAL_CHANGE",
  message: "Review access",
  resourceKind: "Role",
  resourceName: "reader",
  namespace: "orders",
} as Assessment["findings"][number];
it("separates controllers from batch objects and accounts for platform and cluster records without discarding them", () => {
  const result = inventorySummary([
    {
      apiVersion: "apps/v1",
      kind: "Deployment",
      namespace: "orders",
      name: "api",
    },
    {
      apiVersion: "apps/v1",
      kind: "DaemonSet",
      namespace: "calico-system",
      name: "agent",
    },
    {
      apiVersion: "batch/v1",
      kind: "CronJob",
      namespace: "orders",
      name: "check",
    },
    {
      apiVersion: "batch/v1",
      kind: "Job",
      namespace: "orders",
      name: "check-1",
    },
    {
      apiVersion: "batch/v1",
      kind: "Job",
      namespace: "orders",
      name: "check-2",
    },
    {
      apiVersion: "rbac.authorization.k8s.io/v1",
      kind: "ClusterRole",
      name: "reader",
    },
  ]);
  expect(result.controllers).toBe(2);
  expect(result.batch).toBe(3);
  expect(result.workloads).toEqual({ application: 4, platform: 1, cluster: 0 });
  expect(result.kinds.reduce((sum, [, n]) => sum + n, 0)).toBe(6);
  expect(discoveryScope(undefined)).toBe("cluster");
});
it("groups repeated rules but retains every observation, severity and distinct resource reference", () => {
  const groups = groupSourceFindings([
    finding,
    { ...finding, message: "Review another access detail" },
    { ...finding, resourceName: "writer" },
    { ...finding, namespace: "payments" },
    { ...finding, severity: "BLOCKER" },
    { ...finding, resourceName: undefined },
  ]);
  expect(groups).toHaveLength(2);
  expect(groups[0].severity).toBe("BLOCKER");
  const warning = groups[1];
  expect(warning.observations).toHaveLength(5);
  expect(warning.resources.size).toBe(3);
  expect(warning.unlinked).toBe(1);
  expect(groups.flatMap((g) => g.observations)).toHaveLength(6);
});
it("reports repeated identities without silently reducing raw object counts", () => {
  const resource = {
    apiVersion: "apps/v1",
    kind: "Deployment",
    namespace: "orders",
    name: "api",
  };
  const result = inventorySummary([
    resource,
    { ...resource, apiVersion: "apps/v1beta1" },
    { ...resource, namespace: "other" },
  ]);
  expect(result.repeatedIdentities).toBe(1);
  expect(result.controllers).toBe(3);
  expect(result.kinds).toEqual([["Deployment", 3]]);
});
