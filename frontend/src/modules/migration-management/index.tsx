"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import {
  ArrowRight,
  Boxes,
  CheckCircle2,
  CircleAlert,
  Clock3,
  Copy,
  FileText,
  FileChartColumn,
  ListChecks,
  MoreVertical,
  Plus,
  Search,
  Users,
  XCircle,
} from "lucide-react";

import { useAuth } from "@/shared/auth/auth-provider";
import {
  hasPermission,
  isMigrationPreviewEnabled,
} from "@/shared/auth/permissions";
import { PageHeading } from "@/shared/components/ui";
import { AssessmentWizard } from "./assessment-wizard";
import { useCancelMigration, useMigrations } from "./hooks";
import styles from "./migration-management.module.css";
import { PlatformIcon } from "./platform-icon";

const lifecycle = [
  {
    label: "Draft",
    statuses: ["DRAFT", "SOURCE_ENROLLMENT_PENDING"],
    icon: FileText,
    tone: "draft",
  },
  {
    label: "Discovering",
    statuses: ["INVENTORY_DISCOVERING", "INVENTORY_READY", "DISCOVERING"],
    icon: Search,
    tone: "discovery",
  },
  {
    label: "Assessing",
    statuses: ["DISCOVERY_PENDING", "ASSESSING", "ASSESSMENT_READY"],
    icon: ListChecks,
    tone: "assessment",
  },
  {
    label: "Review",
    statuses: ["SUBMITTED", "UNDER_REVIEW"],
    icon: Users,
    tone: "review",
  },
  {
    label: "Approved",
    statuses: ["APPROVED"],
    icon: CheckCircle2,
    tone: "approved",
  },
  {
    label: "Blocked",
    statuses: ["REJECTED", "CANCELLED"],
    icon: CircleAlert,
    tone: "blocked",
  },
];

function platformLabel(platform: string) {
  return platform.replaceAll("_", " ").toLowerCase();
}

function statusLabel(status: string) {
  return status.replaceAll("_", " ").toLowerCase();
}

function statusTone(status: string) {
  if (["APPROVED"].includes(status)) return styles.stageApproved;
  if (["REJECTED", "CANCELLED"].includes(status)) return styles.stageBlocked;
  if (["SUBMITTED", "UNDER_REVIEW"].includes(status)) return styles.stageReview;
  if (["DISCOVERY_PENDING", "ASSESSING", "ASSESSMENT_READY"].includes(status))
    return styles.stageAssessment;
  if (
    ["INVENTORY_DISCOVERING", "INVENTORY_READY", "DISCOVERING"].includes(status)
  )
    return styles.stageDiscovery;
  return styles.stageDraft;
}

function formatUpdated(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? value
    : new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
}

export function MigrationManagementPage() {
  const { identity } = useAuth();
  const migrationsQuery = useMigrations();
  const migrationItems = migrationsQuery.data?.items ?? [];
  const [search, setSearch] = useState("");
  const [stage, setStage] = useState("ACTIVE");
  const [source, setSource] = useState("ALL");
  const [target, setTarget] = useState("ALL");
  const canCreate =
    hasPermission(identity, "migration.create") || isMigrationPreviewEnabled();
  const canEdit =
    hasPermission(identity, "migration.edit") || isMigrationPreviewEnabled();
  const cancelMigration = useCancelMigration();
  const sourcePlatforms = [
    ...new Set(migrationItems.map((item) => item.sourcePlatform)),
  ];
  const targetPlatforms = [
    ...new Set(migrationItems.map((item) => item.targetPlatform)),
  ];
  const filteredMigrations = useMemo(() => {
    const term = search.trim().toLowerCase();
    return migrationItems.filter((migration) => {
      const isArchived = ["CANCELLED"].includes(migration.status);
      const stageMatches =
        stage === "ALL" ||
        (stage === "ACTIVE" && !isArchived) ||
        migration.status === stage;
      const searchMatches =
        !term ||
        migration.name.toLowerCase().includes(term) ||
        migration.migrationId.toLowerCase().includes(term) ||
        migration.customerName.toLowerCase().includes(term);
      return (
        stageMatches &&
        searchMatches &&
        (source === "ALL" || migration.sourcePlatform === source) &&
        (target === "ALL" || migration.targetPlatform === target)
      );
    });
  }, [migrationItems, search, source, stage, target]);
  const awaitingReview = migrationItems.filter((migration) =>
    ["ASSESSMENT_READY", "SUBMITTED", "UNDER_REVIEW"].includes(
      migration.status,
    ),
  );
  const blocked = migrationItems.filter((migration) =>
    ["REJECTED"].includes(migration.status),
  );

  return (
    <>
      <PageHeading
        eyebrow="MIGRATION"
        title="Migration portfolio"
        description={
          "Discover workloads, assess compatibility, and govern migration " +
          "approval across Kubernetes and cloud platforms."
        }
        action={
          canCreate && (
            <Link href="/migrations/new" className="button button-primary">
              <Plus size={18} />
              New migration assessment
            </Link>
          )
        }
      />

      <section className={styles.lifecycle} aria-label="Migration lifecycle">
        {lifecycle.map((step, index) => {
          const Icon = step.icon;
          const count = migrationItems.filter((migration) =>
            step.statuses.includes(migration.status),
          ).length;
          return (
            <div className={styles.lifecycleStep} key={step.label}>
              <div
                className={`${styles.lifecycleIcon} ${styles[step.tone]}`}
                aria-hidden="true"
              >
                <Icon size={20} />
              </div>
              <div>
                <span>{step.label}</span>
                <strong>{count}</strong>
              </div>
              {index < lifecycle.length - 1 && (
                <span className={styles.lifecycleLine} aria-hidden="true" />
              )}
            </div>
          );
        })}
      </section>

      <div className={styles.portfolioLayout}>
        <section className={`panel ${styles.portfolioPanel}`}>
          <div className={styles.portfolioHeading}>
            <div>
              <h2>Migration assessments</h2>
              <p>
                Track source discovery, compatibility analysis and approval.
              </p>
            </div>
            <span className="status-badge">Assessment only</span>
          </div>

          <div className={styles.filters}>
            <label className={styles.search}>
              <span>Search migrations</span>
              <div>
                <Search size={17} aria-hidden="true" />
                <input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Migration, customer or ID"
                />
              </div>
            </label>
            <label>
              <span>Stage</span>
              <select
                value={stage}
                onChange={(event) => setStage(event.target.value)}
              >
                <option value="ACTIVE">Active assessments</option>
                <option value="ALL">All stages</option>
                {lifecycle.flatMap((item) =>
                  item.statuses.map((status) => (
                    <option value={status} key={status}>
                      {statusLabel(status)}
                    </option>
                  )),
                )}
              </select>
            </label>
            <label>
              <span>Source platform</span>
              <select
                value={source}
                onChange={(event) => setSource(event.target.value)}
              >
                <option value="ALL">All sources</option>
                {sourcePlatforms.map((platform) => (
                  <option value={platform} key={platform}>
                    {platformLabel(platform)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Target platform</span>
              <select
                value={target}
                onChange={(event) => setTarget(event.target.value)}
              >
                <option value="ALL">All targets</option>
                {targetPlatforms.map((platform) => (
                  <option value={platform} key={platform}>
                    {platformLabel(platform)}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {migrationsQuery.isPending && (
            <div className="empty-state">Loading migration assessments…</div>
          )}
          {migrationsQuery.isError && (
            <div className="empty-state" role="alert">
              Unable to load migration assessments.
            </div>
          )}
          {!migrationsQuery.isPending &&
            !migrationsQuery.isError &&
            migrationItems.length === 0 && (
              <div className="empty-state">
                <Boxes size={32} aria-hidden="true" />
                <h3>No migration assessments yet</h3>
                <p>
                  Create an assessment to connect a source cluster, discover
                  workloads and evaluate target compatibility.
                </p>
              </div>
            )}
          {migrationItems.length > 0 && filteredMigrations.length === 0 && (
            <div className="empty-state">
              <Search size={28} aria-hidden="true" />
              <h3>No matching migrations</h3>
              <p>Clear or change the filters to see other assessments.</p>
            </div>
          )}
          {filteredMigrations.length > 0 && (
            <div className={styles.tableScroller}>
              <table className={styles.portfolioTable}>
                <thead>
                  <tr>
                    <th>Migration</th>
                    <th>Customer</th>
                    <th>Migration path</th>
                    <th>Stage</th>
                    <th>Updated</th>
                    <th aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {filteredMigrations.map((migration) => (
                    <tr key={migration.migrationId}>
                      <td>
                        <Link href={`/migrations/${migration.migrationId}`}>
                          <strong>{migration.name}</strong>
                          <span>{migration.migrationId}</span>
                        </Link>
                      </td>
                      <td>{migration.customerName}</td>
                      <td>
                        <div className={styles.platformPath}>
                          <span className={styles.sourcePlatform}>
                            <PlatformIcon platform={migration.sourcePlatform} />
                            {platformLabel(migration.sourcePlatform)}
                          </span>
                          <ArrowRight size={14} aria-hidden="true" />
                          <span className={styles.targetPlatform}>
                            <PlatformIcon platform={migration.targetPlatform} />
                            {platformLabel(migration.targetPlatform)}
                          </span>
                        </div>
                      </td>
                      <td>
                        <span
                          className={`${styles.stageBadge} ${statusTone(
                            migration.status,
                          )}`}
                        >
                          {statusLabel(migration.status)}
                        </span>
                      </td>
                      <td>
                        <span className={styles.updated}>
                          <Clock3 size={14} aria-hidden="true" />
                          {formatUpdated(migration.updatedAt)}
                        </span>
                      </td>
                      <td>
                        <details className={styles.rowMenu}>
                          <summary aria-label={`Actions for ${migration.name}`}>
                            <MoreVertical size={18} />
                          </summary>
                          <div>
                            <Link href={`/migrations/${migration.migrationId}`}>
                              <ArrowRight size={15} />
                              {[
                                "DRAFT",
                                "SOURCE_ENROLLMENT_PENDING",
                                "INVENTORY_DISCOVERING",
                                "INVENTORY_READY",
                                "DISCOVERY_PENDING",
                                "DISCOVERING",
                                "ASSESSING",
                              ].includes(migration.status)
                                ? "Continue assessment"
                                : "Open assessment"}
                            </Link>
                            {[
                              "ASSESSMENT_READY",
                              "SUBMITTED",
                              "UNDER_REVIEW",
                              "APPROVED",
                              "REJECTED",
                            ].includes(migration.status) && (
                              <Link
                                href={`/migrations/${migration.migrationId}#assessment-report-title`}
                              >
                                <FileChartColumn size={15} />
                                View feasibility report
                              </Link>
                            )}
                            <button
                              type="button"
                              onClick={() =>
                                navigator.clipboard.writeText(
                                  migration.migrationId,
                                )
                              }
                            >
                              <Copy size={15} />
                              Copy migration ID
                            </button>
                            {canEdit &&
                              [
                                "DRAFT",
                                "REJECTED",
                                "DISCOVERY_PENDING",
                                "DISCOVERING",
                                "ASSESSMENT_READY",
                                "SUBMITTED",
                              ].includes(migration.status) && (
                                <button
                                  type="button"
                                  className={styles.cancelAction}
                                  disabled={cancelMigration.isPending}
                                  onClick={() => {
                                    if (
                                      window.confirm(
                                        `Cancel and remove "${migration.name}" from the active list? Its audit evidence will be retained.`,
                                      )
                                    ) {
                                      cancelMigration.mutate({
                                        migrationId: migration.migrationId,
                                        version: migration.version,
                                      });
                                    }
                                  }}
                                >
                                  <XCircle size={15} />
                                  Cancel and archive
                                </button>
                              )}
                          </div>
                        </details>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <aside className={styles.attentionPanel}>
          <div className={styles.attentionHeading}>
            <CircleAlert size={20} aria-hidden="true" />
            <div>
              <h2>Attention required</h2>
              <p>Items waiting for action</p>
            </div>
          </div>

          <section className={styles.attentionCard}>
            <header className={styles.attentionReview}>
              <Users size={18} aria-hidden="true" />
              <div>
                <strong>Reports awaiting review</strong>
                <span>{awaitingReview.length}</span>
              </div>
            </header>
            {awaitingReview.length === 0 ? (
              <p className={styles.attentionEmpty}>No reports waiting.</p>
            ) : (
              awaitingReview.slice(0, 4).map((migration) => (
                <Link
                  href={`/migrations/${migration.migrationId}`}
                  key={migration.migrationId}
                >
                  <strong>{migration.name}</strong>
                  <span>{statusLabel(migration.status)}</span>
                </Link>
              ))
            )}
          </section>

          <section className={styles.attentionCard}>
            <header className={styles.attentionBlocked}>
              <CircleAlert size={18} aria-hidden="true" />
              <div>
                <strong>Blocked assessments</strong>
                <span>{blocked.length}</span>
              </div>
            </header>
            {blocked.length === 0 ? (
              <p className={styles.attentionEmpty}>No blocked assessments.</p>
            ) : (
              blocked.slice(0, 4).map((migration) => (
                <Link
                  href={`/migrations/${migration.migrationId}`}
                  key={migration.migrationId}
                >
                  <strong>{migration.name}</strong>
                  <span>Needs remediation</span>
                </Link>
              ))
            )}
          </section>
        </aside>
      </div>
    </>
  );
}

export function MigrationCreatePage() {
  return <AssessmentWizard />;
}

export { AssessmentReportCard } from "./assessment-report";
