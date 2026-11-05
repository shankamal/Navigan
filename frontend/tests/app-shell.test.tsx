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
    window.localStorage.clear();
    installRuntimeConfig({ ...runtimeConfig(), migrationUiPreview: false });
  });

  it("allows a desktop user to resize and reset the navigation width", () => {
    render(<AppShell>Content</AppShell>);
    const resize = screen.getByRole("separator", {
      name: "Resize navigation",
    });
    const shell = resize.closest<HTMLElement>(".app-shell");

    fireEvent.keyDown(resize, { key: "ArrowRight" });
    expect(shell?.style.getPropertyValue("--workspace-sidebar-width")).toBe(
      "240px",
    );
    expect(window.localStorage.getItem("navigan.sidebarWidth")).toBe("240");

    fireEvent.doubleClick(resize);
    expect(shell?.style.getPropertyValue("--workspace-sidebar-width")).toBe(
      "232px",
    );
  });

  it("shows capability-based working routes to a Cloud Engineer", () => {
    render(<AppShell>Content</AppShell>);
    expect(screen.getByText("Manage")).toBeInTheDocument();
    expect(screen.getByText("Build & Onboard")).toBeInTheDocument();
    expect(screen.getByText("Migrate & Modernize")).toBeInTheDocument();
    expect(screen.getByText("Operate & Evolve")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Customers" })).toHaveAttribute(
      "href",
      "/customers",
    );
    expect(screen.getByRole("link", { name: "Environments" })).toHaveAttribute(
      "href",
      "/environments",
    );
    expect(screen.getByRole("link", { name: "Clusters" })).toHaveAttribute(
      "href",
      "/clusters",
    );
    expect(
      screen.getByRole("link", { name: "Create Cluster" }),
    ).toHaveAttribute("href", "/clusters/new");
    expect(
      screen.getByRole("link", { name: "Import Cluster" }),
    ).toHaveAttribute("href", "/onboarding");
    expect(
      screen.getByRole("link", { name: "Migration Assessments" }),
    ).toHaveAttribute("href", "/migrations");
    expect(
      screen.getByRole("link", { name: "Application Modernization" }),
    ).toHaveAttribute("href", "/app-transformation");
    expect(
      screen.getByRole("link", { name: "Upgrade Center" }),
    ).toHaveAttribute("href", "/upgrades");
    expect(screen.queryByText("Customer Directory")).not.toBeInTheDocument();
    expect(screen.queryByText("Create Environment")).not.toBeInTheDocument();
    expect(screen.queryByText("New Cluster Request")).not.toBeInTheDocument();
    expect(screen.queryByText("Cluster Reviews")).not.toBeInTheDocument();
    expect(screen.queryByText("Sign out")).not.toBeInTheDocument();
  });

  it("keeps the owning management module selected on a nested engineer route", () => {
    pathname = "/environments/new";
    render(<AppShell>Content</AppShell>);

    expect(screen.getByRole("link", { name: "Environments" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Customers" })).not.toHaveAttribute(
      "aria-current",
    );
    expect(screen.getByRole("link", { name: "Clusters" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("shows review tools and hides create tools for a Platform Architect", () => {
    identity = architect;
    render(<AppShell>Content</AppShell>);
    expect(screen.getByText("Govern")).toBeInTheDocument();
    expect(screen.getByText("Build & Onboard")).toBeInTheDocument();
    expect(screen.getByText("Migrate & Modernize")).toBeInTheDocument();
    expect(screen.getByText("Operate & Evolve")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Platform Overview" }),
    ).toHaveAttribute("href", "/dashboard");
    expect(
      screen.getByRole("link", { name: "Customer Portfolio" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Environment Portfolio" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Cluster Portfolio" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Migration Portfolio" }),
    ).toHaveAttribute("href", "/migrations");
    expect(
      screen.getByRole("link", { name: "Application Modernization" }),
    ).toHaveAttribute("href", "/app-transformation");
    expect(
      screen.getByRole("link", { name: "Cluster Onboarding" }),
    ).toHaveAttribute("href", "/onboarding");
    expect(
      screen.getByRole("link", { name: "Upgrade Center" }),
    ).toHaveAttribute("href", "/upgrades");
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
      screen.getByRole("link", { name: "Migration Portfolio" }),
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
      screen.getByRole("link", { name: "Customer Portfolio" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Environment Reviews")).toBeInTheDocument();
    expect(screen.queryByText("Create Environment")).not.toBeInTheDocument();
    expect(screen.queryByText("Cluster Portfolio")).not.toBeInTheDocument();
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
        name: "Migration Portfolio",
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
      screen.getByRole("link", { name: "Environment Portfolio" }),
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
