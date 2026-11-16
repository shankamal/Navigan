"use client";

import { IntentLink as Link } from "./intent-link";
import { PageHeading } from "./ui";
import { useAuth } from "@/shared/auth/auth-provider";
import {
  hasPermission,
  type PlatformPermission,
} from "@/shared/auth/permissions";

const workLinks: {
  href: string;
  label: string;
  detail: string;
  permission: PlatformPermission;
}[] = [
  {
    href: "/customers",
    label: "Customers",
    detail: "Open customer records and available lifecycle actions.",
    permission: "customer.view",
  },
  {
    href: "/environments",
    label: "Environments",
    detail: "Open environment requests and available lifecycle actions.",
    permission: "environment.view",
  },
  {
    href: "/clusters",
    label: "Clusters",
    detail: "Open cluster requests and available lifecycle actions.",
    permission: "cluster.view",
  },
  {
    href: "/environments/reviews",
    label: "Environment Reviews",
    detail: "Review submitted environment requests.",
    permission: "environment.review",
  },
  {
    href: "/environments/remediations",
    label: "Bootstrap Approvals",
    detail: "Review environment bootstrap remediation requests.",
    permission: "remediation.review",
  },
  {
    href: "/clusters/reviews",
    label: "Cluster Reviews",
    detail: "Review submitted cluster requests.",
    permission: "cluster.review",
  },
  {
    href: "/upgrades",
    label: "Upgrade Plans",
    detail: "Open plans, approvals and execution evidence.",
    permission: "dashboard.platform.view",
  },
  {
    href: "/onboarding",
    label: "Cluster Onboarding",
    detail: "View the planned cluster onboarding capability.",
    permission: "dashboard.platform.view",
  },
];

export function WorkspaceShortcuts({ help = false }: { help?: boolean }) {
  const { identity } = useAuth();
  return (
    <>
      <PageHeading
        title={help ? "Settings & Help" : "My Work"}
        description={
          help
            ? "Product information and workspace preferences."
            : "Open the workspaces and review actions available to your role."
        }
      />
      <section
        className="panel"
        aria-label={help ? "Settings and help links" : "Work shortcuts"}
      >
        {help ? (
          <>
            <h2>Workspace preferences</h2>
            <p>
              Use the top bar to choose Customer and Environment. Resize or
              collapse the sidebar using its controls.
            </p>
            <p>
              <Link href="/about">About Navigan</Link>
            </p>
            <p className="muted">
              Additional platform settings are not available on this page yet.
            </p>
          </>
        ) : (
          <>
            <p className="muted">
              These shortcuts open existing workspaces. Assignment and status
              filters remain inside each capability.
            </p>
            <ul>
              {workLinks
                .filter((item) => hasPermission(identity, item.permission))
                .map((item) => (
                  <li key={item.href}>
                    <Link href={item.href}>{item.label}</Link>
                    <p className="muted">{item.detail}</p>
                  </li>
                ))}
            </ul>
          </>
        )}
      </section>
    </>
  );
}
