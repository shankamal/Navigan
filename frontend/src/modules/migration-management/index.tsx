"use client";

import Link from "next/link";
import {
  ArrowRightLeft,
  ClipboardCheck,
  Plus,
  Radar,
  ShieldCheck,
} from "lucide-react";

import { useAuth } from "@/shared/auth/auth-provider";
import {
  hasPermission,
  isMigrationPreviewEnabled,
} from "@/shared/auth/permissions";
import { PageHeading } from "@/shared/components/ui";
import { AssessmentWizard } from "./assessment-wizard";

const capabilities = [
  {
    label: "Source discovery",
    value: "Read-only",
    note: "Outbound connector with sanitized inventory",
    icon: Radar,
  },
  {
    label: "Compatibility",
    value: "Policy checked",
    note: "Target-specific findings and remediation",
    icon: ShieldCheck,
  },
  {
    label: "Approval",
    value: "Required",
    note: "Independent review before future execution",
    icon: ClipboardCheck,
  },
  {
    label: "Execution",
    value: "Disabled",
    note: "The current release is assessment-only",
    icon: ArrowRightLeft,
  },
];

export function MigrationManagementPage() {
  const { identity } = useAuth();
  const canCreate =
    hasPermission(identity, "migration.create") ||
    isMigrationPreviewEnabled();

  return (
    <>
      <PageHeading
        eyebrow="MIGRATION"
        title="Migrations"
        description={
          "Assess workload portability across Kubernetes and cloud " +
          "platforms through a governed, security-first workflow."
        }
        action={
          canCreate && (
            <Link
              href="/migrations/new"
              className="button button-primary"
            >
              <Plus size={18} />
              New migration assessment
            </Link>
          )
        }
      />

      <div className="metrics-grid">
        {capabilities.map((capability) => (
          <div className="metric" key={capability.label}>
            <div className="metric-label">
              {capability.label}
              <capability.icon size={20} aria-hidden="true" />
            </div>
            <strong>{capability.value}</strong>
            <p>{capability.note}</p>
          </div>
        ))}
      </div>

      <section className="panel">
        <div className="list-heading">
          <div>
            <h2>Migration requests</h2>
            <p className="muted">
              Discover source workloads, review compatibility findings,
              and govern migration approval.
            </p>
          </div>
          <span className="status-badge">Assessment only</span>
        </div>

        <div className="empty-state">
          <Radar size={32} aria-hidden="true" />
          <h3>No migration requests loaded yet</h3>
          <p>
            Create a migration assessment to select source and target
            platforms and define the discovery scope.
          </p>
          <p>
            Execution remains disabled until dry-run, validation,
            rollback, and approval controls are implemented.
          </p>
        </div>
      </section>
    </>
  );
}

export function MigrationCreatePage() {
  return <AssessmentWizard />;
}
