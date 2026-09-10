"use client";
import { useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ChevronRight,
  LogOut,
  Menu,
  PlusCircle,
  Settings2,
  ShieldCheck,
  X,
} from "lucide-react";
import { platformModules } from "@/shared/config/modules";
import { useAuth } from "@/shared/auth/auth-provider";
import { signOut } from "@/shared/auth/session";
import { Button } from "./ui";

const environmentChildren = [
  { href: "/clusters/new", label: "New Container Env", icon: PlusCircle },
  { href: "/clusters", label: "Environment Admin", icon: Settings2 },
] as const;

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { identity } = useAuth();
  const [expanded, setExpanded] = useState(false);
  const current = platformModules.find((item) =>
    pathname.startsWith(item.href),
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
        <Link href="/customers" className="brand" aria-label="Navigan home">
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
          {identity && (
            <span className="avatar" aria-label={identity.displayName}>
              {identity.displayName.slice(0, 2).toUpperCase()}
            </span>
          )}
        </div>
      </header>
      <div className="shell-body">
        <aside
          id="platform-navigation"
          className={`sidebar ${expanded ? "expanded" : ""}`}
        >
          <div>
            <p className="nav-section">WORKSPACE</p>
            <nav aria-label="Platform modules">
              {platformModules
                .filter((item) => item.id !== "clusters")
                .map((item) => {
                  const selected =
                    pathname.startsWith(item.href) ||
                    (item.id === "environments" && pathname.startsWith("/clusters"));
                  return (
                    <div className="nav-group" key={item.id}>
                      <Link
                        href={item.href}
                        className={`nav-item ${selected ? "selected" : ""}`}
                        aria-current={pathname.startsWith(item.href) ? "page" : undefined}
                        onClick={() => setExpanded(false)}
                      >
                        <item.icon size={20} aria-hidden="true" />
                        <span>{item.shortTitle}</span>
                        {!item.available && <span className="soon">Soon</span>}
                      </Link>
                      {item.id === "environments" && (
                        <div className="nav-submenu" aria-label="Environment tools">
                          {environmentChildren.map((child) => {
                            const childSelected =
                              child.href === "/clusters"
                                ? pathname === child.href
                                : pathname.startsWith(child.href);
                            return (
                              <Link
                                key={child.href}
                                href={child.href}
                                className={`nav-subitem ${childSelected ? "selected" : ""}`}
                                aria-current={childSelected ? "page" : undefined}
                                onClick={() => setExpanded(false)}
                              >
                                <child.icon size={16} aria-hidden="true" />
                                <span>{child.label}</span>
                              </Link>
                            );
                          })}
                        </div>
                      )}
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
            {identity && (
              <div className="profile">
                <p>{identity.displayName}</p>
                <span>
                  {identity.roles
                    .map((role) => role.replaceAll("_", " ").toLowerCase())
                    .join(" · ") || "No platform role"}
                </span>
                <Button variant="ghost" onClick={() => void signOut()}>
                  <LogOut size={16} />
                  Sign out
                </Button>
              </div>
            )}
          </div>
        </aside>
        <div className="content-column">
          <div className="breadcrumb">
            <span>Workspace</span>
            <ChevronRight size={14} />
            <span>{pathname.startsWith("/clusters") ? "Environments" : current?.shortTitle ?? "Access"}</span>
            {pathname.startsWith("/clusters") && (
              <>
                <ChevronRight size={14} />
                <span>{pathname.startsWith("/clusters/new") ? "New Container Env" : "Environment Admin"}</span>
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
