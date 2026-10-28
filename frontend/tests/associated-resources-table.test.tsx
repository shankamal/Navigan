import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { AssociatedResourcesTable } from "../src/modules/migration-management/associated-resources-table";

const resources = Array.from({ length: 125 }, (_, i) => ({
  apiVersion: "v1",
  kind: i % 2 ? "Service" : "ConfigMap",
  namespace: "shop",
  name: `resource-${i}`,
}));
it("keeps large dependency sets paginated and searchable without rendering a card per resource", () => {
  render(<AssociatedResourcesTable resources={resources} />);
  const table = screen.getByRole("table", { name: "Associated resources" });
  expect(within(table).getAllByRole("row")).toHaveLength(11);
  expect(screen.getByText("1–10 of 125 resources")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Next resources" }));
  expect(screen.getByText("11–20 of 125 resources")).toBeVisible();
  fireEvent.change(screen.getByRole("searchbox"), {
    target: { value: "resource-124" },
  });
  expect(screen.getByText("resource-124")).toBeVisible();
  expect(screen.getByText("1–1 of 1 resources")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Next resources" }),
  ).not.toBeInTheDocument();
});
it("filters by resource kind and gives a clear empty result", () => {
  render(<AssociatedResourcesTable resources={resources} />);
  fireEvent.change(screen.getByRole("combobox", { name: "Resource kind" }), {
    target: { value: "Service" },
  });
  const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
  expect(rows.every((row) => within(row).getByText("Service"))).toBe(true);
  fireEvent.change(screen.getByRole("searchbox"), {
    target: { value: "not-found" },
  });
  expect(screen.getByText(/No associated resources match/)).toBeVisible();
});
