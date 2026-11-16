import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { WorkspaceShortcuts } from "@/shared/components/workspace-shortcuts";
import { architect, engineer } from "./fixtures";
let identity = engineer;
vi.mock("@/shared/auth/auth-provider", () => ({
  useAuth: () => ({ identity }),
}));
beforeEach(() => {
  identity = engineer;
});
it("keeps architect review entry points accessible through My Work", () => {
  identity = architect;
  render(<WorkspaceShortcuts />);
  expect(
    screen.getByRole("link", { name: "Environment Reviews" }),
  ).toHaveAttribute("href", "/environments/reviews");
  expect(screen.getByRole("link", { name: "Cluster Reviews" })).toHaveAttribute(
    "href",
    "/clusters/reviews",
  );
});
it("does not show architect review shortcuts to engineers", () => {
  render(<WorkspaceShortcuts />);
  expect(
    screen.queryByRole("link", { name: "Environment Reviews" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("link", { name: "Cluster Reviews" }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Clusters" })).toHaveAttribute(
    "href",
    "/clusters",
  );
});
it("provides About Navigan in Settings & Help", () => {
  render(<WorkspaceShortcuts help />);
  expect(screen.getByRole("link", { name: "About Navigan" })).toHaveAttribute(
    "href",
    "/about",
  );
});
