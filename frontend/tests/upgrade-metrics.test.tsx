import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { UpgradeMetrics } from "../src/modules/upgrade-management/upgrade-metrics";
import type { EksUpgradePlan } from "../src/modules/cluster-management/model";
describe("upgrade doughnut metrics", () => {
  it("renders both charts and separates overdue requests from awaiting approval", () => {
    const plan = {
      status: "SUBMITTED",
      scheduledFor: "2020-01-01T08:15:00Z",
    } as EksUpgradePlan;
    render(
      <UpgradeMetrics
        ready={2}
        blocked={1}
        review={0}
        unknown={1}
        plans={[plan]}
        loading={false}
      />,
    );
    expect(screen.getAllByRole("img")).toHaveLength(2);
    expect(
      screen.getByRole("img", { name: /clusters.*Ready: 2, Blocked: 1/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", {
        name: /requests.*Awaiting approval: 0.*Overdue \/ inactive: 1/,
      }),
    ).toBeInTheDocument();
  });
  it("shows empty data without inventing a positive segment", () => {
    const { container } = render(
      <UpgradeMetrics
        ready={0}
        blocked={0}
        review={0}
        unknown={0}
        plans={[]}
        loading={false}
      />,
    );
    expect(container.querySelectorAll("circle[stroke-dasharray]")).toHaveLength(
      0,
    );
  });
});
