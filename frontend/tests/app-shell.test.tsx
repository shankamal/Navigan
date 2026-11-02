import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "@/shared/components/app-shell";
import { PublicShell } from "@/shared/components/public-shell";
import { architect, engineer } from "./fixtures";
import {
  installRuntimeConfig,
  runtimeConfig,
} from "@/shared/config/runtime-config";

const signOut = vi.fn();
const prefetchQuery = vi.fn().mockResolvedValue(undefined);
let identity = engineer;
let pathname = "/customers";

vi.mock("@tanstack/react-query", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@tanstack/react-query")>()),
  useQueryClient: () => ({ prefetchQuery }),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
}));
vi.mock("@/shared/auth/auth-provider", () => ({
  useAuth: () => ({ identity, loading: false, configured: true }),
}));
vi.mock("@/shared/auth/session", () => ({
  signOut: () => signOut(),
}));

describe("Application shell permissions", () => {
  beforeEach(() => {
    identity = engineer;
    pathname = "/customers";
    signOut.mockReset();
    prefetchQuery.mockClear();
    installRuntimeConfig({ ...runtimeConfig(), migrationUiPreview: false });
  });

  it("shows one top-level management entry per domain to a Cloud Engineer", () => {
    render(<AppShell>Content</AppShell>);
    expect(
      screen.getByRole("link", { name: "Customer Management" }),
    ).toHaveAttribute("href", "/customers");
    expect(
      screen.getByRole("link", { name: "Environment Management" }),
    ).toHaveAttribute("href", "/environments");
    expect(
      screen.getByRole("link", { name: "Cluster Management" }),
    ).toHaveAttribute("href", "/clusters");
    expect(screen.getByRole("link", { name: "Migration" })).toHaveAttribute(
      "href",
      "/migrations",
    );
    expect(screen.queryByText("Customer Directory")).not.toBeInTheDocument();
    expect(screen.queryByText("Create Environment")).not.toBeInTheDocument();
    expect(screen.queryByText("New Cluster Request")).not.toBeInTheDocument();
    expect(screen.queryByText("Cluster Reviews")).not.toBeInTheDocument();
    expect(screen.queryByText("Sign out")).not.toBeInTheDocument();
  });

  it("keeps the owning management module selected on a nested engineer route", () => {
    pathname = "/environments/new";
    render(<AppShell>Content</AppShell>);

    expect(
      screen.getByRole("link", { name: "Environment Management" }),
    ).toHaveAttribute("aria-current", "page");
    expect(
      screen.getByRole("link", { name: "Customer Management" }),
    ).not.toHaveAttribute("aria-current");
    expect(
      screen.getByRole("link", { name: "Cluster Management" }),
    ).not.toHaveAttribute("aria-current");
  });

  it("shows review tools and hides create tools for a Platform Architect", () => {
    identity = architect;
    render(<AppShell>Content</AppShell>);
    expect(
      screen.getByRole("link", { name: "Customer Directory" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Environment Directory" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Cluster Directory" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Migration Requests" }),
    ).toHaveAttribute("href", "/migrations");
    expect(
      screen.queryByRole("link", { name: "Customer Management" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Environment Management" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Cluster Management" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Create Environment")).not.toBeInTheDocument();
    expect(screen.queryByText("New Cluster Setup")).not.toBeInTheDocument();
    expect(screen.getByText("Cluster Reviews")).toBeInTheDocument();
    expect(screen.getByText("Bootstrap Approvals")).toBeInTheDocument();
  });

  it("warms workspace data when a user approaches a navigation item", () => {
    identity = architect;
    render(<AppShell>Content</AppShell>);

    fireEvent.mouseEnter(
      screen.getByRole("link", { name: "Migration Requests" }),
    );

    expect(prefetchQuery).toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: ["migrations"] }),
    );
  });

  it("renders menus from dynamic privileges without a predefined role", () => {
    identity = {
      ...engineer,
      roles: [],
      privileges: [
        "dashboard.platform.view",
        "customer.view",
        "environment.view",
        "environment.review",
      ],
    };
    render(<AppShell>Content</AppShell>);
    expect(
      screen.getByRole("link", { name: "Customer Directory" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Environment Reviews")).toBeInTheDocument();
    expect(screen.queryByText("Create Environment")).not.toBeInTheDocument();
    expect(screen.queryByText("Cluster Directory")).not.toBeInTheDocument();
  });

  it("supports an explicit non-production migration preview", () => {
    installRuntimeConfig({ ...runtimeConfig(), migrationUiPreview: true });
    identity = {
      ...engineer,
      roles: [],
      privileges: ["dashboard.platform.view"],
    };

    render(<AppShell>Content</AppShell>);

    expect(
      screen.getByRole("link", {
        name: "Migration Requests",
      }),
    ).toHaveAttribute("href", "/migrations");
  });

  it("places sign out inside the top-right account menu", () => {
    render(<AppShell>Content</AppShell>);
    fireEvent.click(screen.getByRole("button", { name: /Open account menu/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Sign out" }));
    expect(signOut).toHaveBeenCalledOnce();
  });

  it("selects only Environment Reviews on its dedicated route", () => {
    identity = architect;
    pathname = "/environments/reviews";
    render(<AppShell>Content</AppShell>);

    expect(
      screen.getByRole("link", { name: "Environment Reviews" }),
    ).toHaveAttribute("aria-current", "page");
    expect(
      screen.getByRole("link", { name: "Environment Directory" }),
    ).not.toHaveAttribute("aria-current");
  });

  it("does not expose Cluster Operations in the sidebar", () => {
    identity = architect;
    pathname = "/clusters/operations";
    render(<AppShell>Content</AppShell>);

    expect(
      screen.queryByRole("link", { name: "Cluster Operations" }),
    ).not.toBeInTheDocument();
  });

  it("offers About Navigan in expanded and collapsed navigation", () => {
    pathname = "/about";
    render(<AppShell>Content</AppShell>);
    const about = screen.getByRole("link", {
      name: "About Navigan",
    });
    expect(about).toHaveAttribute("href", "/about");
    expect(about.closest(".sidebar-utilities")).not.toBeNull();
    expect(about.closest('nav[aria-label="Platform modules"]')).toBeNull();
    expect(about.textContent).toBe("");
    expect(
      screen.queryByRole("navigation", { name: "Breadcrumb" }),
    ).not.toBeInTheDocument();
    expect(about).toHaveAttribute("aria-current", "page");
    fireEvent.click(
      screen.getByRole("button", { name: "Collapse navigation" }),
    );
    expect(
      screen.getByRole("link", { name: "About Navigan" }),
    ).toBeInTheDocument();
  });

  it("renders the public shell without workspace navigation", () => {
    render(<PublicShell>Sign in form</PublicShell>);
    expect(screen.getByText("Sign in form")).toBeInTheDocument();
    expect(
      screen.queryByRole("navigation", { name: "Platform modules" }),
    ).not.toBeInTheDocument();
  });
});
