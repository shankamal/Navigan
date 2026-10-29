import { render, screen, within } from "@testing-library/react";
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
      screen.getByRole("img", {
        name: "Migration paths. KUBERNETES to EKS: 4. Total: 4",
      }),
    ).toBeInTheDocument();
    expect(
      within(
        screen.getByRole("list", { name: "Migration path counts" }),
      ).getByText("4"),
    ).toBeInTheDocument();
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
  it("keeps each source-to-target route and its count in the donut legend", () => {
    render(
      <MigrationPortfolioSummary
        {...props}
        paths={[
          { ...props.paths[0], count: 3 },
          {
            path: "AWS_EKS|EKS",
            sourcePlatform: "AWS_EKS",
            targetPlatform: "EKS",
            count: 1,
          },
        ]}
      />,
    );
    expect(
      screen.getByRole("img", {
        name: "Migration paths. KUBERNETES to EKS: 3, AWS_EKS to EKS: 1. Total: 4",
      }),
    ).toBeInTheDocument();
    const legend = within(
      screen.getByRole("list", { name: "Migration path counts" }),
    );
    expect(legend.getAllByRole("listitem")).toHaveLength(2);
    expect(legend.getByText("3")).toBeInTheDocument();
    expect(legend.getByText("1")).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });
});
