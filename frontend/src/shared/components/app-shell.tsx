"use client";
import { useEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Building2,
  ChevronRight,
  ChevronDown,
  ClipboardCheck,
  FileClock,
  FolderPlus,
  Gauge,
  Layers3,
  LogOut,
  Menu,
  Network,
  Rocket,
  Settings2,
  ShieldAlert,
  ShieldCheck,
  X,
} from "lucide-react";
import { useAuth } from "@/shared/auth/auth-provider";
import {
  hasPermission,
  type PlatformPermission,
} from "@/shared/auth/permissions";
import { signOut } from "@/shared/auth/session";
import { Button } from "./ui";

interface NavigationItem {
  href: string;
  label: string;
  icon: typeof FolderPlus;
  permission: PlatformPermission;
}

const navigationGroups: ReadonlyArray<{
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
    label: "Customer Management",
    items: [
      {
        href: "/customers",
        label: "Customer Directory",
        icon: Building2,
        permission: "customer.view",
      },
      {
        href: "/customers/new",
        label: "Create Customer",
        icon: FolderPlus,
        permission: "customer.create",
      },
    ],
  },
  {
    label: "Environment Management",
    items: [
      {
        href: "/environments",
        label: "Environment Directory",
        icon: Layers3,
        permission: "environment.view",
      },
      {
        href: "/environments/new",
        label: "Create Environment",
        icon: FolderPlus,
        permission: "environment.create",
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
    label: "Cluster Management",
    items: [
      {
        href: "/clusters",
        label: "Cluster Directory",
        icon: Network,
        permission: "cluster.view",
      },
      {
        href: "/clusters/new",
        label: "New Cluster Request",
        icon: Rocket,
        permission: "cluster.create",
      },
      {
        href: "/clusters/reviews",
        label: "Cluster Reviews",
        icon: Settings2,
        permission: "cluster.review",
      },
      {
        href: "/clusters/operations",
        label: "Cluster Operations",
        icon: FileClock,
        permission: "cluster.plan",
      },
    ],
  },
];

const cloudEngineerNavigationGroups: ReadonlyArray<{
  label: string;
  items: readonly NavigationItem[];
}> = [
  {
    label: "Workspace",
    items: [
      {
        href: "/dashboard",
        label: "Platform Dashboard",
        icon: Gauge,
        permission: "dashboard.platform.view",
      },
      {
        href: "/customers",
        label: "Customer Management",
        icon: Building2,
        permission: "customer.view",
      },
      {
        href: "/environments",
        label: "Environment Management",
        icon: Layers3,
        permission: "environment.view",
      },
      {
        href: "/clusters",
        label: "Cluster Management",
        icon: Network,
        permission: "cluster.view",
      },
    ],
  },
];

function isCloudEngineerOnly(identity: ReturnType<typeof useAuth>["identity"]) {
  const humanRoles =
    identity?.roles.filter((role) => role !== "SERVICE") ?? [];
  return humanRoles.length === 1 && humanRoles[0] === "CLOUD_ENGINEER";
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
  const pathname = usePathname();
  const { identity } = useAuth();
  const [expanded, setExpanded] = useState(false);
  const activeNavigationGroups = isCloudEngineerOnly(identity)
    ? cloudEngineerNavigationGroups
    : navigationGroups;
  const current = activeNavigationGroups
    .flatMap((group) => group.items)
    .filter((item) => hasPermission(identity, item.permission))
    .toSorted((left, right) => right.href.length - left.href.length)
    .find(
      (item) =>
        pathname === item.href ||
        (item.href !== "/" && pathname.startsWith(item.href + "/")),
    );
  const logo = process.env.NEXT_PUBLIC_CORPORATE_LOGO_URL;
  return (
    <div className="app-shell">
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
        <Link href="/dashboard" className="brand" aria-label="Navigan home">
          {logo && (
            <img src={logo} alt="Corporate logo" className="corporate-logo" />
          )}
          <span>Navigan</span>
        </Link>
        <span className="brand-divider" />
        <span className="platform-title">Container Management Platform</span>
        <div className="topbar-account">
          <ShieldCheck size={18} aria-hidden="true" />
          <span>{identity ? "Enterprise workspace" : "Secure access"}</span>
          <AccountMenu />
        </div>
      </header>
      <div className="shell-body">
        <aside
          id="platform-navigation"
          className={`sidebar ${expanded ? "expanded" : ""}`}
        >
          <div>
            <nav aria-label="Platform modules">
              {activeNavigationGroups.map((group) => {
                const items = group.items.filter((item) =>
                  hasPermission(identity, item.permission),
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
                          aria-current={selected ? "page" : undefined}
                          onClick={() => setExpanded(false)}
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
          <div className="sidebar-footer">
            <div className="workspace-card">
              <div className="workspace-symbol">
                <span aria-hidden="true">N</span>
              </div>
              <div>
                <strong>Multi-cloud platform</strong>
                <p>AWS · Azure · GCP · OCI</p>
              </div>
            </div>
          </div>
        </aside>
        <div className="content-column">
          <div className="breadcrumb">
            <span>Workspace</span>
            <ChevronRight size={14} />
            <span>{current?.label ?? "Access"}</span>
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
          </div>
          <main id="main-content" tabIndex={-1}>
            {children}
          </main>
          <footer className="app-footer">
            <span>Navigan</span>
            <span>Customer identity and governance</span>
          </footer>
        </div>
      </div>
    </div>
  );
}
