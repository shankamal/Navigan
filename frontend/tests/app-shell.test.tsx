import { fireEvent, render, screen, within } from "@testing-library/react";
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
vi.mock("@/modules/customer-management/hooks/queries", () => ({
  useCustomers: () => ({
    data: {
      items: [
        {
          customerId: "CUS-dbs",
          name: "DB Schenker",
          status: "ACTIVE",
          version: 1,
          cloudProviders: ["AWS"],
        },
      ],
    },
  }),
}));
vi.mock("@/modules/environment-management/hooks/queries", () => ({
  useEnvironments: () => ({
    data: {
      items: [
        {
          environmentId: "ENV-dbs",
          customerId: "CUS-dbs",
          customerName: "DB Schenker",
          cloudProvider: "AWS",
          kubernetesDistribution: "EKS",
          environmentName: "DEV2-DBS-LCO",
          environmentType: "DEV",
          status: "ACTIVE",
          version: 1,
          createdAt: "2026-11-01T00:00:00Z",
        },
      ],
    },
  }),
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

  it("renders the approved single-line Navigan global top bar", () => {
    const { container } = render(<AppShell>Content</AppShell>);

    const header = container.querySelector("header.navigan-global-topbar");
    expect(header).toBeInTheDocument();
    expect(
      within(header as HTMLElement).getByRole("link", { name: "Navigan home" }),
    ).toHaveTextContent("Navigan");
    expect(
      within(header as HTMLElement).getByRole("combobox", {
        name: "Global customer scope",
      }),
    ).toHaveValue("all");
    expect(
      within(header as HTMLElement).getByRole("combobox", {
        name: "Global environment scope",
      }),
    ).toHaveValue("all");
    expect(
      within(header as HTMLElement).getByRole("searchbox", {
        name: "Search Navigan",
      }),
    ).toBeInTheDocument();
    expect(
      within(header as HTMLElement).getByRole("button", {
        name: "Collapse navigation",
      }),
    ).toBeInTheDocument();
    expect(
      container.querySelector(".sidebar-brand-panel"),
    ).not.toBeInTheDocument();
  });

  it("allows a desktop user to resize and reset the navigation width", () => {
    render(<AppShell>Content</AppShell>);
    const resize = screen.getByRole("separator", {
      name: "Resize navigation",
    });
    const shell = resize.closest<HTMLElement>(".app-shell");

    fireEvent.keyDown(resize, { key: "ArrowRight" });
    expect(shell?.style.getPropertyValue("--workspace-sidebar-width")).toBe(
      "256px",
    );
    expect(window.localStorage.getItem("navigan.sidebarWidth")).toBe("256");

    fireEvent.doubleClick(resize);
    expect(shell?.style.getPropertyValue("--workspace-sidebar-width")).toBe(
      "248px",
    );
  });

  it("keeps About outside the scrolling module menu", () => {
    const { container } = render(<AppShell>Content</AppShell>);
    const menuScroller = container.querySelector(".sidebar-menu-scroll");
    const about = screen.getByRole("link", { name: "About Navigan" });

    expect(menuScroller).toBeInTheDocument();
    expect(menuScroller).not.toContainElement(about);
    expect(about.closest(".sidebar-footer")).toBeInTheDocument();
  });

  it("shows capability-based working routes to a Cloud Engineer", () => {
    const { container } = render(<AppShell>Content</AppShell>);
    expect(
      Array.from(container.querySelectorAll(".nav-section")).map(
        (section) => section.textContent,
      ),
    ).toEqual([
      "Resource Management",
      "Migration & Modernization",
      "Platform Maintenance",
      "Operations & Observability",
      "Settings",
    ]);
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
      screen.queryByRole("link", { name: "Create Cluster" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Import Cluster" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "My Work" })).toHaveAttribute(
      "href",
      "/my-work",
    );
    expect(
      screen.getByRole("link", { name: "System Utilities" }),
    ).toHaveAttribute("href", "/upgrades/utilities");
    expect(screen.getByRole("link", { name: "Migration" })).toHaveAttribute(
      "href",
      "/migrations",
    );
    expect(
      screen.getByRole("link", { name: "Application Modernization" }),
    ).toHaveAttribute("href", "/app-transformation");
    expect(
      screen.getByRole("link", { name: "Upgrades & Patching" }),
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

    const navigation = screen.getByRole("navigation", {
      name: "Platform modules",
    });
    expect(
      within(navigation).getByRole("link", { name: "Environments" }),
    ).toHaveAttribute("aria-current", "page");
    expect(
      within(navigation).getByRole("link", { name: "Customers" }),
    ).not.toHaveAttribute("aria-current");
    expect(
      within(navigation).getByRole("link", { name: "Clusters" }),
    ).not.toHaveAttribute("aria-current");
  });

  it("shows review tools and hides create tools for a Platform Architect", () => {
    identity = architect;
    const { container } = render(<AppShell>Content</AppShell>);
    expect(
      Array.from(container.querySelectorAll(".nav-section")).map(
        (section) => section.textContent,
      ),
    ).toEqual([
      "Resource Management",
      "Migration & Modernization",
      "Platform Maintenance",
      "Operations & Observability",
      "Settings",
    ]);
    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute(
      "href",
      "/dashboard",
    );
    expect(screen.getByRole("link", { name: "Customers" })).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Environments" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Clusters" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Migration" })).toHaveAttribute(
      "href",
      "/migrations",
    );
    expect(
      screen.getByRole("link", { name: "Application Modernization" }),
    ).toHaveAttribute("href", "/app-transformation");
    expect(screen.getByRole("link", { name: "My Work" })).toHaveAttribute(
      "href",
      "/my-work",
    );
    expect(
      screen.getByRole("link", { name: "Upgrades & Patching" }),
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
    expect(screen.queryByText("Cluster Reviews")).not.toBeInTheDocument();
    expect(screen.queryByText("Bootstrap Approvals")).not.toBeInTheDocument();
  });

  it("warms workspace data when a user approaches a navigation item", () => {
    identity = architect;
    render(<AppShell>Content</AppShell>);

    fireEvent.mouseEnter(screen.getByRole("link", { name: "Migration" }));

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
    expect(screen.getByRole("link", { name: "Customers" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "My Work" })).toBeInTheDocument();
    expect(screen.queryByText("Create Environment")).not.toBeInTheDocument();
    expect(screen.queryByText("Clusters")).not.toBeInTheDocument();
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
        name: "Migration",
      }),
    ).toHaveAttribute("href", "/migrations");
  });

  it("places sign out inside the top-right account menu", () => {
    render(<AppShell>Content</AppShell>);
    fireEvent.click(screen.getByRole("button", { name: /Open account menu/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Sign out" }));
    expect(signOut).toHaveBeenCalledOnce();
  });

  it("shows route-aware breadcrumbs for deep capability workflows", () => {
    pathname = "/migrations/MIG-123/discovery";
    render(<AppShell>Content</AppShell>);

    const breadcrumb = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(
      within(breadcrumb).getByRole("link", { name: "Home" }),
    ).toHaveAttribute("href", "/dashboard");
    expect(
      within(breadcrumb).getByRole("link", { name: "Migrations" }),
    ).toHaveAttribute("href", "/migrations");
    expect(
      within(breadcrumb).getByRole("link", { name: "Assessment MIG-123" }),
    ).toHaveAttribute("href", "/migrations/MIG-123");
    expect(within(breadcrumb).getByText("Source Discovery")).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("shows explicit creation breadcrumbs instead of generic module labels", () => {
    pathname = "/clusters/new";
    render(<AppShell>Content</AppShell>);

    const breadcrumb = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(
      within(breadcrumb).getByRole("link", { name: "Clusters" }),
    ).toHaveAttribute("href", "/clusters");
    expect(within(breadcrumb).getByText("Create Cluster")).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("keeps Environments selected on its review route", () => {
    identity = architect;
    pathname = "/environments/reviews";
    render(<AppShell>Content</AppShell>);
    const nav = screen.getByRole("navigation", { name: "Platform modules" });
    expect(
      within(nav).getByRole("link", { name: "Environments" }),
    ).toHaveAttribute("aria-current", "page");
    expect(
      within(nav).queryByRole("link", { name: "Environment Reviews" }),
    ).not.toBeInTheDocument();
  });

  it("selects System Utilities without also selecting Upgrades & Patching", () => {
    pathname = "/upgrades/utilities";
    render(<AppShell>Content</AppShell>);
    const nav = screen.getByRole("navigation", { name: "Platform modules" });
    expect(
      within(nav).getByRole("link", { name: "System Utilities" }),
    ).toHaveAttribute("aria-current", "page");
    expect(
      within(nav).getByRole("link", { name: "Upgrades & Patching" }),
    ).not.toHaveAttribute("aria-current");
    expect(
      within(nav).queryByRole("link", { name: "Monitoring & Health" }),
    ).not.toBeInTheDocument();
    expect(
      within(nav)
        .getByText("Monitoring & Health")
        .closest('[aria-disabled="true"]'),
    ).toBeInTheDocument();
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
    expect(about).toHaveTextContent("Navigan · v");
    expect(
      screen.getByText("Workspace").closest(".sidebar-heading"),
    ).toBeInTheDocument();
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
