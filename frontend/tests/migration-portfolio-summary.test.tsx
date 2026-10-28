import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MigrationPortfolioSummary } from "@/modules/migration-management/migration-portfolio-summary";

const props = {
  total: 4,
  lifecycle: [
    { label: "Draft", tone: "draft", count: 1 },
    { label: "Approved", tone: "approved", count: 2 },
  ],
  approved: 2,
  paths: [
    {
      path: "KUBERNETES|EKS",
      sourcePlatform: "KUBERNETES",
      targetPlatform: "EKS",
      count: 4,
    },
  ],
  pending: false,
  error: false,
};

describe("Migration portfolio summary", () => {
  it("includes ungrouped statuses so lifecycle segments account for the full total", () => {
    render(<MigrationPortfolioSummary {...props} />);
    expect(
      screen.getByRole("img", {
        name: /Assessment lifecycle.*Draft: 1.*Approved: 2.*Other statuses: 1.*Total: 4/,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", {
        name: "Approval coverage. Approved: 2, Not approved: 2. Total: 4",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("50%")).toBeInTheDocument();
    expect(
      screen.getByRole("progressbar", {
        name: "KUBERNETES to EKS: 4 assessments",
      }),
    ).toHaveAttribute("value", "4");
  });

  it.each([
    { pending: true, error: false },
    { pending: false, error: true },
  ])(
    "does not present empty charts as real data while unavailable: %j",
    (state) => {
      render(<MigrationPortfolioSummary {...props} {...state} />);
      expect(screen.queryByRole("img")).not.toBeInTheDocument();
      expect(screen.queryByText("50%")).not.toBeInTheDocument();
    },
  );

  it("renders an empty portfolio without a NaN percentage", () => {
    render(
      <MigrationPortfolioSummary
        {...props}
        total={0}
        approved={0}
        lifecycle={[]}
        paths={[]}
      />,
    );
    expect(screen.getByText("0%")).toBeInTheDocument();
    expect(screen.getByText("No assessments yet")).toBeInTheDocument();
    expect(screen.getByText("No migration paths yet.")).toBeInTheDocument();
  });
});
