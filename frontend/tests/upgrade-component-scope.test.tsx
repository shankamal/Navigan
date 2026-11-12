import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { planScopes } from "../src/modules/upgrade-management/plan-scope";
import { ComponentPlanMetrics } from "../src/modules/upgrade-management/component-plan-metrics";
import type { EksUpgradePlan } from "../src/modules/cluster-management/model";
const plan = {
  kind: "CONTAINER",
  status: "DRAFT",
  currentVersion: "1.36",
  targetVersion: "1.37",
  readinessEvidence: {
    nodeGroups: [{ version: "1.36" }, { version: "1.36" }],
    addons: [
      { version: "v1", targetVersion: "v1" },
      { version: "v2", targetVersion: null },
    ],
  },
} as EksUpgradePlan;
describe("component upgrade scope", () => {
  it("counts affected plans once per scope and excludes kept or unknown addon versions", () => {
    expect(planScopes(plan)).toEqual(["cluster", "nodes"]);
    const select = vi.fn();
    render(
      <ComponentPlanMetrics
        plans={[plan]}
        loading={false}
        selected="all"
        onSelect={select}
      />,
    );
    expect(
      screen.getAllByRole("img", { name: /plans.*Draft: 1/ }),
    ).toHaveLength(2);
    expect(
      screen.getAllByRole("img", { name: /plans.*Draft: 0/ }),
    ).toHaveLength(2);
    fireEvent.click(
      screen.getByRole("button", { name: /Node group upgrades/ }),
    );
    expect(select).toHaveBeenCalledWith("nodes");
  });
  it("labels utility plans separately and includes only addons actually changing", () => {
    expect(planScopes({ ...plan, kind: "UTILITY" })).toEqual(["utilities"]);
    expect(
      planScopes({
        ...plan,
        readinessEvidence: {
          ...plan.readinessEvidence!,
          addons: [
            {
              name: "cni",
              version: "v1",
              targetVersion: "v2",
              status: "ACTIVE",
              healthIssues: [],
            },
          ],
        },
      }),
    ).toEqual(["cluster", "nodes", "addons"]);
  });
});
