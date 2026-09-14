import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "@/shared/components/app-shell";
import { PublicShell } from "@/shared/components/public-shell";
import { architect, engineer } from "./fixtures";

const signOut = vi.fn();
let identity = engineer;
let pathname = "/customers";

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

  it("places sign out inside the top-right account menu", () => {
    render(<AppShell>Content</AppShell>);
    fireEvent.click(
      screen.getByRole("button", { name: /Open account menu/i }),
    );
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

  it("selects only Cluster Operations on its dedicated route", () => {
    identity = architect;
    pathname = "/clusters/operations";
    render(<AppShell>Content</AppShell>);

    expect(
      screen.getByRole("link", { name: "Cluster Operations" }),
    ).toHaveAttribute("aria-current", "page");
    expect(
      screen.getByRole("link", { name: "Cluster Directory" }),
    ).not.toHaveAttribute("aria-current");
    expect(
      screen.getByRole("link", { name: "Cluster Reviews" }),
    ).not.toHaveAttribute("aria-current");
  });

  it("renders the public shell without workspace navigation", () => {
    render(<PublicShell>Sign in form</PublicShell>);
    expect(screen.getByText("Sign in form")).toBeInTheDocument();
    expect(
      screen.queryByRole("navigation", { name: "Platform modules" }),
    ).not.toBeInTheDocument();
  });
});
