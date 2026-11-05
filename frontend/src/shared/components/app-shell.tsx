"use client";
import "./workspace-navigation.css";
import "./workspace-backdrop.css";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import { IntentLink as Link } from "@/shared/components/intent-link";
import {
  WorkspacePageProvider,
  useWorkspacePage,
} from "./workspace-page-context";
import { usePathname } from "next/navigation";
import { NaviganMark } from "./navigan-mark";
import {
  ArrowRightLeft,
  Building2,
  ChevronRight,
  ChevronDown,
  CircleArrowUp,
  ClipboardCheck,
  Gauge,
  Info,
  Layers3,
  LogOut,
  Menu,
  Network,
  PlugZap,
  Rocket,
  Settings2,
  ShieldAlert,
  ShieldCheck,
  Workflow,
  X,
} from "lucide-react";
import { useAuth } from "@/shared/auth/auth-provider";
import {
  hasPermission,
  isMigrationPreviewEnabled,
  type PlatformPermission,
} from "@/shared/auth/permissions";
import { signOut } from "@/shared/auth/session";
import { runtimeConfig } from "@/shared/config/runtime-config";
import { Button } from "./ui";
import { prefetchWorkspaceData } from "@/shared/performance/prefetch-workspace-data";

interface NavigationItem {
  href: string;
  label: string;
  icon: typeof Gauge;
  permission: PlatformPermission;
}

const DEFAULT_SIDEBAR_WIDTH = 232;
const MIN_SIDEBAR_WIDTH = 220;
const MAX_SIDEBAR_WIDTH = 300;
const SIDEBAR_WIDTH_STORAGE_KEY = "navigan.sidebarWidth";

// These informational landing pages use the existing platform overview entitlement.
// Individual workflow permissions will be added with each capability's implementation.
const platformArchitectNavigationGroups: ReadonlyArray<{
  label: string;
  items: readonly NavigationItem[];
}> = [
  {
    label: "Overview",
    items: [
      {
        href: "/dashboard",
        label: "Platform Overview",
        icon: Gauge,
        permission: "dashboard.platform.view",
      },
    ],
  },
  {
    label: "Govern",
    items: [
      {
        href: "/customers",
        label: "Customer Portfolio",
        icon: Building2,
        permission: "customer.view",
      },
      {
        href: "/clusters/reviews",
        label: "Cluster Reviews",
        icon: Settings2,
        permission: "cluster.review",
      },
      {
        href: "/environments",
        label: "Environment Portfolio",
        icon: Layers3,
        permission: "environment.view",
      },
      {
        href: "/environments/reviews",
        label: "Environment Reviews",
        icon: ClipboardCheck,
        permission: "environment.review",
      },
      {
        href: "/environments/remediations",
        label: "Bootstrap Approvals",
        icon: ShieldAlert,
        permission: "remediation.review",
      },
    ],
  },
  {
    label: "Build & Onboard",
    items: [
      {
        href: "/clusters",
        label: "Cluster Portfolio",
        icon: Network,
        permission: "cluster.view",
      },
      {
        href: "/onboarding",
        label: "Cluster Onboarding",
        icon: PlugZap,
        permission: "dashboard.platform.view",
      },
    ],
  },
  {
    label: "Migrate & Modernize",
    items: [
      {
        href: "/migrations",
        label: "Migration Portfolio",
        icon: ArrowRightLeft,
        permission: "migration.view",
      },
      {
        href: "/app-transformation",
        label: "Application Modernization",
        icon: Workflow,
        permission: "dashboard.platform.view",
      },
    ],
  },
  {
    label: "Operate & Evolve",
    items: [
      {
        href: "/upgrades",
        label: "Upgrade Center",
        icon: CircleArrowUp,
        permission: "dashboard.platform.view",
      },
    ],
  },
];

const cloudEngineerNavigationGroups: ReadonlyArray<{
  label: string;
  items: readonly NavigationItem[];
}> = [
  {
    label: "Overview",
    items: [
      {
        href: "/dashboard",
        label: "Platform Dashboard",
        icon: Gauge,
        permission: "dashboard.platform.view",
      },
    ],
  },
  {
    label: "Manage",
    items: [
      {
        href: "/customers",
        label: "Customers",
        icon: Building2,
        permission: "customer.view",
      },
      {
        href: "/environments",
        label: "Environments",
        icon: Layers3,
        permission: "environment.view",
      },
      {
        href: "/clusters",
        label: "Clusters",
        icon: Network,
        permission: "cluster.view",
      },
    ],
  },
  {
    label: "Build & Onboard",
    items: [
      {
        href: "/clusters/new",
        label: "Create Cluster",
        icon: Rocket,
        permission: "cluster.create",
      },
      {
        href: "/onboarding",
        label: "Import Cluster",
        icon: PlugZap,
        permission: "dashboard.platform.view",
      },
    ],
  },
  {
    label: "Migrate & Modernize",
    items: [
      {
        href: "/migrations",
        label: "Migration Assessments",
        icon: ArrowRightLeft,
        permission: "migration.view",
      },
      {
        href: "/app-transformation",
        label: "Application Modernization",
        icon: Workflow,
        permission: "dashboard.platform.view",
      },
    ],
  },
  {
    label: "Operate & Evolve",
    items: [
      {
        href: "/upgrades",
        label: "Upgrade Center",
        icon: CircleArrowUp,
        permission: "dashboard.platform.view",
      },
    ],
  },
];

function isCloudEngineerOnly(identity: ReturnType<typeof useAuth>["identity"]) {
  const humanRoles = identity?.roles.filter((role) => role !== "SERVICE") ?? [];
  return humanRoles.length === 1 && humanRoles[0] === "CLOUD_ENGINEER";
}

function canViewNavigation(
  identity: ReturnType<typeof useAuth>["identity"],
  permission: PlatformPermission,
) {
  return (
    hasPermission(identity, permission) ||
    (permission === "migration.view" && isMigrationPreviewEnabled())
  );
}

function AccountMenu() {
  const { identity } = useAuth();
  const [open, setOpen] = useState(false);
  const menu = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (event: MouseEvent) => {
      if (!menu.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  if (!identity) return null;
  return (
    <div className="account-menu" ref={menu}>
      <button
        type="button"
        className="account-trigger"
        aria-label={`Open account menu for ${identity.displayName}`}
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => setOpen((current) => !current)}
      >
        <span className="avatar" aria-hidden="true">
          {identity.displayName.slice(0, 2).toUpperCase()}
        </span>
        <ChevronDown size={15} aria-hidden="true" />
      </button>
      {open && (
        <div className="account-popover" role="menu">
          <div className="account-identity">
            <strong>{identity.displayName}</strong>
            <span>
              {identity.roles
                .filter((role) => role !== "SERVICE")
                .map((role) => role.replaceAll("_", " ").toLowerCase())
                .join(" · ") || "No platform role"}
            </span>
          </div>
          <button
            type="button"
            role="menuitem"
            className="account-action"
            onClick={() => void signOut()}
          >
            <LogOut size={16} />
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <WorkspacePageProvider>
      <AppShellContent>{children}</AppShellContent>
    </WorkspacePageProvider>
  );
}
function AppShellContent({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const { label: pageLabel } = useWorkspacePage();
  const pathname = usePathname();
  const { identity } = useAuth();
  const [expanded, setExpanded] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [resizingSidebar, setResizingSidebar] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(DEFAULT_SIDEBAR_WIDTH);
  const activeNavigationGroups = isCloudEngineerOnly(identity)
    ? cloudEngineerNavigationGroups
    : platformArchitectNavigationGroups;
  const current = activeNavigationGroups
    .flatMap((group) => group.items)
    .filter((item) => canViewNavigation(identity, item.permission))
    .toSorted((left, right) => right.href.length - left.href.length)
    .find(
      (item) =>
        pathname === item.href ||
        (item.href !== "/" && pathname.startsWith(item.href + "/")),
    );
  const [isLocalDev, setIsLocalDev] = useState(false);
  const warmWorkspace = useCallback(
    (href: string) => {
      void prefetchWorkspaceData(queryClient, href);
    },
    [queryClient],
  );
  const updateSidebarWidth = useCallback((width: number) => {
    const next = Math.min(
      MAX_SIDEBAR_WIDTH,
      Math.max(MIN_SIDEBAR_WIDTH, Math.round(width)),
    );
    setSidebarWidth(next);
    window.localStorage.setItem(SIDEBAR_WIDTH_STORAGE_KEY, String(next));
  }, []);
  useEffect(() => {
    const saved = Number(
      window.localStorage.getItem(SIDEBAR_WIDTH_STORAGE_KEY),
    );
    if (Number.isFinite(saved) && saved >= MIN_SIDEBAR_WIDTH) {
      setSidebarWidth(Math.min(MAX_SIDEBAR_WIDTH, saved));
    }
  }, []);
  useEffect(() => {
    if (!resizingSidebar) return;
    const resize = (event: PointerEvent) => updateSidebarWidth(event.clientX);
    const finish = () => setResizingSidebar(false);
    const previousCursor = document.body.style.cursor;
    const previousSelection = document.body.style.userSelect;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", resize);
    window.addEventListener("pointerup", finish, { once: true });
    return () => {
      window.removeEventListener("pointermove", resize);
      window.removeEventListener("pointerup", finish);
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousSelection;
    };
  }, [resizingSidebar, updateSidebarWidth]);
  useEffect(() => {
    if (
      pathname.startsWith("/migrations") ||
      !canViewNavigation(identity, "migration.view")
    )
      return;
    const timeout = window.setTimeout(
      () => warmWorkspace("/migrations"),
      4_000,
    );
    return () => window.clearTimeout(timeout);
  }, [identity, pathname, warmWorkspace]);
  useEffect(() => {
    setIsLocalDev(
      ["localhost", "127.0.0.1"].includes(window.location.hostname),
    );
  }, []);
  const logo = runtimeConfig().corporateLogoUrl;
  useEffect(() => {
    const header = document.querySelector<HTMLElement>(
      ".app-shell > header.topbar",
    );
    const shell = header?.parentElement;
    if (!header || !shell) return;
    const updateHeight = () => {
      shell.style.setProperty(
        "--workspace-topbar-height",
        `${header.getBoundingClientRect().height}px`,
      );
    };
    updateHeight();
    const observer =
      typeof ResizeObserver !== "undefined"
        ? new ResizeObserver(updateHeight)
        : undefined;
    observer?.observe(header);
    window.addEventListener("resize", updateHeight);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", updateHeight);
      shell.style.removeProperty("--workspace-topbar-height");
    };
  }, []);
  return (
    <div
      className={`app-shell ${pathname === "/about" ? "about-shell" : ""} ${pathname === "/dashboard" ? "dashboard-shell" : ""} ${collapsed ? "navigation-collapsed" : ""} ${resizingSidebar ? "navigation-resizing" : ""}`}
      style={
        {
          "--workspace-sidebar-width": `${sidebarWidth}px`,
        } as CSSProperties
      }
    >
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="topbar">
        <Button
          variant="ghost"
          className="mobile-menu"
          aria-label={expanded ? "Close navigation" : "Open navigation"}
          aria-expanded={expanded}
          aria-controls="platform-navigation"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? <X /> : <Menu />}
        </Button>
        <Link href="/dashboard" className="brand" aria-label="Deloitte home">
          {logo ? (
            <img src={logo} alt="Corporate logo" className="corporate-logo" />
          ) : (
            <span className="corporate-wordmark" aria-label="Deloitte">
              Deloitte<span aria-hidden="true">.</span>
            </span>
          )}
        </Link>
        <span className="brand-divider" />
        <span className="platform-title">Container Management Platform</span>
        <div className="topbar-account">
          <div className="signed-in-user">
            <strong>{identity?.displayName ?? "Secure access"}</strong>
            {identity && (
              <span>
                {identity.roles
                  .filter((role) => role !== "SERVICE")
                  .map((role) =>
                    role
                      .replaceAll("_", " ")
                      .toLowerCase()
                      .replace(/\b\w/g, (letter) => letter.toUpperCase()),
                  )
                  .join(" · ") || "No platform role"}
              </span>
            )}
          </div>
          {isLocalDev && <span className="workspace-environment">DEV</span>}
          <AccountMenu />
        </div>
      </header>
      <div className="shell-body">
        <aside
          id="platform-navigation"
          className={`sidebar ${expanded ? "expanded" : ""}`}
        >
          <div
            className="sidebar-resize-handle"
            role="separator"
            aria-label="Resize navigation"
            aria-orientation="vertical"
            aria-valuemin={MIN_SIDEBAR_WIDTH}
            aria-valuemax={MAX_SIDEBAR_WIDTH}
            aria-valuenow={sidebarWidth}
            tabIndex={collapsed ? -1 : 0}
            onPointerDown={(event) => {
              if (collapsed) return;
              event.preventDefault();
              setResizingSidebar(true);
            }}
            onDoubleClick={() => updateSidebarWidth(DEFAULT_SIDEBAR_WIDTH)}
            onKeyDown={(event) => {
              const next =
                event.key === "ArrowLeft"
                  ? sidebarWidth - 8
                  : event.key === "ArrowRight"
                    ? sidebarWidth + 8
                    : event.key === "Home"
                      ? MIN_SIDEBAR_WIDTH
                      : event.key === "End"
                        ? MAX_SIDEBAR_WIDTH
                        : undefined;
              if (next === undefined) return;
              event.preventDefault();
              updateSidebarWidth(next);
            }}
          />
          <div>
            <div className="sidebar-brand-panel">
              <Link
                href="/dashboard"
                className="sidebar-brand"
                aria-label="Navigan home"
                title="Navigan home"
              >
                <NaviganMark compact />
                <span className="sidebar-brand-name">Navigan</span>
              </Link>
              <button
                type="button"
                className="sidebar-collapse"
                aria-label={
                  collapsed ? "Expand navigation" : "Collapse navigation"
                }
                aria-expanded={!collapsed}
                onClick={() => setCollapsed(!collapsed)}
              >
                <Menu size={18} />
              </button>
            </div>
            <nav aria-label="Platform modules">
              {activeNavigationGroups.map((group) => {
                const items = group.items.filter((item) =>
                  canViewNavigation(identity, item.permission),
                );
                if (!items.length) return null;
                return (
                  <div className="clustered-nav-group" key={group.label}>
                    <p className="nav-section">{group.label}</p>
                    {items.map((item) => {
                      const selected = current === item;
                      return (
                        <Link
                          key={`${group.label}-${item.label}`}
                          href={item.href}
                          className={`nav-item ${selected ? "selected" : ""}`}
                          title={item.label}
                          aria-current={selected ? "page" : undefined}
                          onClick={() => setExpanded(false)}
                          onMouseEnter={() => warmWorkspace(item.href)}
                          onFocus={() => warmWorkspace(item.href)}
                          onTouchStart={() => warmWorkspace(item.href)}
                        >
                          <item.icon size={19} aria-hidden="true" />
                          <span>{item.label}</span>
                        </Link>
                      );
                    })}
                  </div>
                );
              })}
            </nav>
          </div>
          <div className="sidebar-footer sidebar-utilities">
            <Link
              href="/about"
              className="sidebar-about"
              aria-label="About Navigan"
              title="About Navigan"
              aria-current={pathname === "/about" ? "page" : undefined}
              onClick={() => setExpanded(false)}
            >
              <Info size={20} aria-hidden="true" />
            </Link>
          </div>
        </aside>
        <div className="content-column">
          {pathname !== "/about" && (
            <nav className="breadcrumb" aria-label="Breadcrumb">
              <Link href="/dashboard">Home</Link>
              <ChevronRight size={14} />
              <Link
                aria-label={`Back to ${(pathname === "/about" ? "About Navigan" : current?.label) ?? "dashboard"}`}
                href={
                  pathname === "/about"
                    ? "/about"
                    : (current?.href ?? "/dashboard")
                }
              >
                {pathname === "/about"
                  ? "About Navigan"
                  : (current?.label ?? "Access")}
              </Link>
              {pathname.endsWith("/plan") && pageLabel && (
                <>
                  <ChevronRight size={14} />
                  <span aria-current="page">{pageLabel}</span>
                </>
              )}
              {/^\/clusters\/CLU-[A-Za-z0-9-]+$/.test(pathname) && (
                <>
                  <ChevronRight size={14} />
                  <span>Cluster request details</span>
                </>
              )}
              {pathname.includes("/customers/") && (
                <>
                  <ChevronRight size={14} />
                  <span>
                    {pathname.endsWith("/new")
                      ? "New customer"
                      : pathname.endsWith("/edit")
                        ? "Edit customer"
                        : "Customer details"}
                  </span>
                </>
              )}
            </nav>
          )}
          <main id="main-content" tabIndex={-1}>
            {children}
          </main>
          {pathname !== "/about" && (
            <footer className="app-footer">
              <span>Navigan</span>
              <span>Customer identity and governance</span>
            </footer>
          )}
        </div>
      </div>
    </div>
  );
}
