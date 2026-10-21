import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { EvidenceCoverageRing } from "@/modules/migration-management/evidence-coverage-ring";

it("reports coverage and handles empty discovery without claiming zero-percent readiness", () => {
  const { rerender } = render(<EvidenceCoverageRing value={9} total={35} label="Repository coverage" />);
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuetext", "9 of 35 workloads (26%)");
  rerender(<EvidenceCoverageRing value={0} total={0} label="Repository coverage" />);
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuetext", "No workloads discovered");
  expect(screen.queryByText("NaN%")).not.toBeInTheDocument();
});
