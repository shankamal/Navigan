import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { CloudProviderChart } from "@/shared/components/summary-donut";
import { CustomerMetrics } from "@/modules/customer-management/components/customer-metrics";
import { EnvironmentRing } from "@/modules/environment-management/components/environment-metrics";
import { chartColors, cloudColors } from "@/shared/components/chart-palette";
it("keeps provider donut arcs and legend swatches in the same provider order", () => {
  const { container } = render(
    <CloudProviderChart
      counts={[3, 1, 1, 1]}
      label="Cloud mix"
      caption="Environments"
      legendLabel="Providers"
    />,
  );
  const arcs = screen
    .getByRole("img", { name: "Cloud mix" })
    .querySelectorAll("circle[stroke-dasharray]");
  expect(Array.from(arcs).map((c) => c.getAttribute("stroke"))).toEqual(
    cloudColors,
  );
  expect(container.querySelectorAll(".summary-chart-dot")).toHaveLength(4);
  expect(screen.getByLabelText("Providers")).toHaveTextContent("AWS");
});
it("uses the same active/remainder treatment for customer coverage and environment rings", () => {
  render(
    <>
      <CustomerMetrics
        total={3}
        active={1}
        draft={1}
        submitted={1}
        review={0}
        failed={false}
        providerCounts={[3, 0, 0, 0]}
      />
      <EnvironmentRing
        values={[1, 2]}
        total={3}
        center="1"
        label="Environment coverage"
        palette={[chartColors.active, chartColors.remainder]}
      />
    </>,
  );
  const customer = screen.getByRole("img", {
    name: "Active customer coverage: 1 of 3",
  });
  const environment = screen.getByRole("img", { name: "Environment coverage" });
  const colors = (el: HTMLElement) =>
    Array.from(el.querySelectorAll("circle[stroke-dasharray]")).map((c) =>
      c.getAttribute("stroke"),
    );
  expect(colors(customer)).toEqual(colors(environment));
});
