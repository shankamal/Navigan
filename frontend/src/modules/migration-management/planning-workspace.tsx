"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowRight,
  Boxes,
  ClipboardCheck,
  Database,
  LockKeyhole,
  Search,
  ShieldCheck,
  Wrench,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { normalizeApiError } from "@/shared/api/client";
import { useAuth } from "@/shared/auth/auth-provider";
import { hasPermission } from "@/shared/auth/permissions";
import { PageHeading } from "@/shared/components/ui";
import {
  useMigration,
  useMigrationAssessment,
  useSourceInventory,
} from "./hooks";
import type {
  Assessment,
  Migration,
  MigrationPlanningDraft,
  PlannedResource,
  RemediationDraft,
  SourceInventory,
  SourceInventoryResource,
} from "./model";
import { PlatformIcon } from "./platform-icon";
import { migrations } from "./service";
import styles from "./planning-workspace.module.css";

export function resourceKey(
  resource: Pick<PlannedResource, "apiVersion" | "kind" | "namespace" | "name">,
) {
  return JSON.stringify([
    resource.apiVersion,
    resource.kind,
    resource.namespace ?? null,
    resource.name,
  ]);
}

function emptyDraft(assessment: Assessment): MigrationPlanningDraft {
  return {
    schemaVersion: 1,
    mode: "SELECTED_WORKLOADS",
    assessmentVersion: assessment.assessmentVersion,
    inventoryDigest: assessment.inventoryDigest,
    resources: [],
    remediations: [],
    dataStrategy: "UNDECIDED",
    notes: "",
  };
}

export function MigrationPlanningWorkspace({
  migrationId,
}: {
  migrationId: string;
}) {
  const migration = useMigration(migrationId);
  const assessment = useMigrationAssessment(migrationId, true);
  const inventory = useSourceInventory(
    migrationId,
    Boolean(assessment.data?.assessment),
  );
  if (migration.isError || assessment.isError || inventory.isError)
    return (
      <section className="panel" role="alert">
        Unable to load planning evidence.{" "}
        <Link href={`/migrations/${migrationId}`}>Back to assessment</Link>
      </section>
    );
  if (migration.isPending || assessment.isPending || inventory.isPending)
    return <section className="panel">Loading migration evidence…</section>;
  if (
    !migration.data ||
    !assessment.data?.assessment ||
    !inventory.data?.inventory
  )
    return (
      <section className="panel">
        Complete the source inventory and assessment before planning.{" "}
        <Link href={`/migrations/${migrationId}`}>Open assessment</Link>
      </section>
    );
  return (
    <PlanningEditor
      migration={migration.data}
      assessment={assessment.data.assessment}
      inventory={inventory.data.inventory}
    />
  );
}

export function PlanningEditor({
  migration,
  assessment,
  inventory,
}: {
  migration: Migration;
  assessment: Assessment;
  inventory: SourceInventory;
}) {
  const { identity } = useAuth();
  const cache = useQueryClient();
  const canEdit =
    hasPermission(identity, "migration.edit") &&
    [
      "ASSESSMENT_READY",
      "SUBMITTED",
      "UNDER_REVIEW",
      "APPROVED",
      "REJECTED",
    ].includes(migration.status);
  const [draft, setDraft] = useState<MigrationPlanningDraft>(() =>
    migration.planningDraft?.schemaVersion === 1
      ? (migration.planningDraft as unknown as MigrationPlanningDraft)
      : emptyDraft(assessment),
  );
  const [tab, setTab] = useState<"scope" | "remediate" | "review">("scope");
  const [namespace, setNamespace] = useState("");
  const [search, setSearch] = useState("");
  const [severity, setSeverity] = useState("ALL");
  const [findingIndex, setFindingIndex] = useState(0);
  const [message, setMessage] = useState("");
  const [dirty, setDirty] = useState(false);
  const stale =
    draft.assessmentVersion !== assessment.assessmentVersion ||
    draft.inventoryDigest !== assessment.inventoryDigest ||
    inventory.inventoryDigest !== assessment.inventoryDigest;
  const resources = inventory.resources.filter(
    (r): r is SourceInventoryResource & { name: string } => Boolean(r.name),
  );
  const namespaces = [
    ...new Set(
      resources.map((r) => r.namespace).filter((n): n is string => Boolean(n)),
    ),
  ].sort();
  const filtered = resources.filter(
    (r) =>
      (!namespace || r.namespace === namespace) &&
      `${r.name} ${r.kind}`.toLowerCase().includes(search.toLowerCase()),
  );
  const selected = new Map(draft.resources.map((r) => [resourceKey(r), r]));
  const unaccounted = resources.filter(
    (r) =>
      !selected.has(resourceKey({ ...r, namespace: r.namespace ?? null })) ||
      selected.get(resourceKey({ ...r, namespace: r.namespace ?? null }))
        ?.treatment === "REVIEW",
  ).length;
  const dependencies = draft.resources.filter((r) => r.dependency).length;
  const blockers = assessment.findings.filter(
    (f) => f.severity === "BLOCKER",
  ).length;
  const findings = assessment.findings
    .map((finding, index) => ({ finding, index }))
    .filter(
      ({ finding }) => severity === "ALL" || finding.severity === severity,
    );
  const finding = assessment.findings[findingIndex];
  const remediation =
    draft.remediations.find((r) => r.findingIndex === findingIndex) ??
    ({
      findingIndex,
      treatment: "REVIEW",
      owner: "",
      targetMapping: "",
      evidenceReference: "",
      status: "PLANNED",
    } satisfies RemediationDraft);
  function change(next: MigrationPlanningDraft) {
    setDraft(next);
    setDirty(true);
    setMessage("");
  }
  function changeRemediation(patch: Partial<RemediationDraft>) {
    change({
      ...draft,
      remediations: [
        ...draft.remediations.filter((r) => r.findingIndex !== findingIndex),
        { ...remediation, ...patch },
      ],
    });
  }
  function toggle(resource: SourceInventoryResource & { name: string }) {
    const item: PlannedResource = {
      apiVersion: resource.apiVersion,
      kind: resource.kind,
      namespace: resource.namespace ?? null,
      name: resource.name,
      treatment: resource.kind === "Node" ? "REVIEW" : "MIGRATE",
      dependency: false,
    };
    change({
      ...draft,
      resources: selected.has(resourceKey(item))
        ? draft.resources.filter((r) => resourceKey(r) !== resourceKey(item))
        : [...draft.resources, item],
    });
  }
  const save = useMutation({
    mutationFn: () =>
      migrations.update(migration.migrationId, {
        version: migration.version,
        planningDraft: draft,
        changeReason: "Update migration scope and remediation planning draft",
      }),
    onSuccess: async (value) => {
      cache.setQueryData(["migrations", migration.migrationId], value);
      setDirty(false);
      setMessage("Planning draft saved. No cluster changes were applied.");
      await cache.invalidateQueries({ queryKey: ["migrations"], exact: true });
    },
    onError: (error) => setMessage(normalizeApiError(error).message),
  });
  return (
    <div className={styles.workspace}>
      <PageHeading
        eyebrow="MIGRATION PLANNING"
        title={
          tab === "remediate"
            ? "Remediation & target mapping"
            : tab === "review"
              ? "Review migration draft"
              : "Plan your migration"
        }
        description={`${migration.name} · Self-managed Kubernetes → Amazon EKS`}
        action={
          <Link
            className="button button-secondary"
            href={`/migrations/${migration.migrationId}`}
          >
            <ArrowLeft size={16} /> Assessment report
          </Link>
        }
      />
      <nav className={styles.steps} aria-label="Migration workflow">
        <button
          aria-current={tab === "scope" ? "step" : undefined}
          onClick={() => setTab("scope")}
        >
          <Boxes size={17} />
          Scope & target
        </button>
        <Link href={`/migrations/${migration.migrationId}`}>
          <ClipboardCheck size={17} />
          Assess
        </Link>
        <button
          aria-current={tab === "remediate" ? "step" : undefined}
          onClick={() => setTab("remediate")}
        >
          <Wrench size={17} />
          Remediate
        </button>
        <button disabled title="Execution plan generation is not available yet">
          Plan
        </button>
        <button
          aria-current={tab === "review" ? "step" : undefined}
          onClick={() => setTab("review")}
        >
          <ShieldCheck size={17} />
          Review draft
        </button>
      </nav>
      {stale && (
        <div className={styles.warning} role="alert">
          Assessment evidence has changed. This draft cannot be saved.{" "}
          <button
            onClick={() => {
              change(emptyDraft(assessment));
              setFindingIndex(0);
            }}
          >
            Start a new draft from current evidence
          </button>
        </div>
      )}
      {!canEdit && (
        <div className={styles.notice}>
          Read-only planning view. Editing requires migration permission and a
          completed assessment.
        </div>
      )}
      {tab === "scope" && (
        <div className={styles.columns}>
          <section className={styles.surface}>
            <div className={styles.context}>
              <div>
                <span>Migration name</span>
                <strong>{migration.name}</strong>
              </div>
              <div>
                <span>Customer</span>
                <strong>
                  {String(migration.customerName ?? migration.customerId)}
                </strong>
              </div>
              <div>
                <span>Assessment snapshot</span>
                <strong>Version {assessment.assessmentVersion}</strong>
              </div>
            </div>
            <fieldset
              disabled={!canEdit || stale || save.isPending}
              className={styles.fields}
            >
              <legend>Migration mode</legend>
              <div className={styles.modes}>
                {(["SELECTED_WORKLOADS", "FULL_CLUSTER"] as const).map(
                  (mode) => (
                    <label
                      className={draft.mode === mode ? styles.selectedMode : ""}
                      key={mode}
                    >
                      <input
                        type="radio"
                        name="migration-mode"
                        checked={draft.mode === mode}
                        onChange={() => change({ ...draft, mode })}
                      />
                      <Boxes size={21} />
                      <span>
                        <strong>
                          {mode === "FULL_CLUSTER"
                            ? "Full cluster"
                            : "Selected workloads"}
                        </strong>
                        <small>
                          {mode === "FULL_CLUSTER"
                            ? "Account for the estate; replace platform services as needed."
                            : "Choose applications and explicitly confirm dependencies."}
                        </small>
                      </span>
                    </label>
                  ),
                )}
              </div>
            </fieldset>
            <div className={styles.target}>
              <PlatformIcon platform="SELF_MANAGED_KUBERNETES" size="medium" />
              <div>
                <span>Assessed source</span>
                <strong>
                  {String(
                    migration.sourceConfiguration.clusterName ??
                      "Self-managed Kubernetes",
                  )}
                </strong>
              </div>
              <ArrowRight size={18} />
              <PlatformIcon platform="EKS" size="medium" />
              <div>
                <span>Assessed target</span>
                <strong>
                  {assessment.inventorySummary.target.clusterName ??
                    "Target not selected"}
                </strong>
                <small>
                  {String(migration.targetConfiguration.environmentId ?? "")} ·{" "}
                  {String(migration.targetConfiguration.awsRegion ?? "")}
                </small>
              </div>
            </div>
            <p className={styles.caption}>
              Target changes require a fresh assessment.{" "}
              <Link href="/clusters/new">
                Create a cluster through Cluster Management
              </Link>
            </p>
            <div className={styles.sectionHeading}>
              <h2>
                {draft.mode === "FULL_CLUSTER"
                  ? "Resource accounting"
                  : "Choose workloads & dependencies"}
              </h2>
              <span>{draft.resources.length} selected</span>
            </div>
            <p className={styles.caption}>
              {draft.mode === "FULL_CLUSTER"
                ? "This inventory may exclude system namespaces or cluster-scoped resources. Full-estate coverage must be confirmed before execution planning."
                : "Inventory contains sanitized metadata, not deployment manifests or data. Dependency names are incomplete; confirm them with the application owner."}
            </p>
            <div className={styles.filters}>
              <label>
                Namespace
                <select
                  value={namespace}
                  onChange={(e) => setNamespace(e.target.value)}
                >
                  <option value="">All assessed namespaces</option>
                  {namespaces.map((n) => (
                    <option key={n}>{n}</option>
                  ))}
                </select>
              </label>
              <label>
                Search resources
                <div className={styles.search}>
                  <Search size={16} />
                  <input
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Name or kind"
                  />
                </div>
              </label>
            </div>
            <div className={styles.tableScroll}>
              <table>
                <thead>
                  <tr>
                    <th>Include</th>
                    <th>Name / kind</th>
                    <th>Namespace</th>
                    <th>Treatment</th>
                    <th>Dependency</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((r) => {
                    const key = resourceKey({
                      ...r,
                      namespace: r.namespace ?? null,
                    });
                    const chosen = selected.get(key);
                    return (
                      <tr key={key}>
                        <td>
                          <input
                            aria-label={`Include ${r.kind} ${r.namespace ?? "cluster"}/${r.name}`}
                            type="checkbox"
                            checked={Boolean(chosen)}
                            disabled={!canEdit || stale || save.isPending}
                            onChange={() => toggle(r)}
                          />
                        </td>
                        <td>
                          <strong>{r.name}</strong>
                          <small>{r.kind}</small>
                        </td>
                        <td>{r.namespace ?? "Cluster scoped"}</td>
                        <td>
                          {chosen ? (
                            <select
                              aria-label={`Treatment ${r.name}`}
                              value={chosen.treatment}
                              disabled={!canEdit || stale || save.isPending}
                              onChange={(e) =>
                                change({
                                  ...draft,
                                  resources: draft.resources.map((item) =>
                                    resourceKey(item) === key
                                      ? {
                                          ...item,
                                          treatment: e.target
                                            .value as PlannedResource["treatment"],
                                        }
                                      : item,
                                  ),
                                })
                              }
                            >
                              {[
                                "MIGRATE",
                                "RECREATE",
                                "REPLACE",
                                "RETIRE",
                                "REVIEW",
                              ]
                                .filter(
                                  (t) => r.kind !== "Node" || t !== "MIGRATE",
                                )
                                .map((t) => (
                                  <option key={t} value={t}>
                                    {t.toLowerCase()}
                                  </option>
                                ))}
                            </select>
                          ) : (
                            "Not selected"
                          )}
                        </td>
                        <td>
                          <input
                            aria-label={`Required dependency ${r.name}`}
                            type="checkbox"
                            checked={chosen?.dependency ?? false}
                            disabled={
                              !chosen || !canEdit || stale || save.isPending
                            }
                            onChange={(e) =>
                              change({
                                ...draft,
                                resources: draft.resources.map((item) =>
                                  resourceKey(item) === key
                                    ? { ...item, dependency: e.target.checked }
                                    : item,
                                ),
                              })
                            }
                          />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {filtered.length === 0 && (
                <p className={styles.caption}>No matching resources.</p>
              )}
            </div>
            <p className={styles.caption}>
              Showing {filtered.length} of {resources.length} inventoried
              resources. Historical Jobs and node agents need explicit treatment
              decisions.
            </p>
          </section>
          <aside className={styles.surface}>
            <h2>Scope summary</h2>
            <div className={styles.summaryItem}>
              <Boxes size={22} />
              <div>
                <strong>
                  {draft.resources.length - dependencies} selected resources
                </strong>
                <small>Explicitly selected by you</small>
              </div>
            </div>
            <div className={styles.summaryItem}>
              <ClipboardCheck size={22} />
              <div>
                <strong>{dependencies} confirmed dependencies</strong>
                <small>Manual confirmation; discovery is not complete</small>
              </div>
            </div>
            <div className={styles.summaryItem}>
              <Database size={22} />
              <div>
                <strong>Data migration</strong>
                <label>
                  Strategy
                  <select
                    aria-label="Data strategy"
                    value={draft.dataStrategy}
                    disabled={!canEdit || stale || save.isPending}
                    onChange={(e) =>
                      change({
                        ...draft,
                        dataStrategy: e.target
                          .value as MigrationPlanningDraft["dataStrategy"],
                      })
                    }
                  >
                    {(
                      [
                        "UNDECIDED",
                        "BACKUP_RESTORE",
                        "REPLICATION",
                        "NO_PERSISTENT_DATA",
                      ] as const
                    ).map((s) => (
                      <option value={s} key={s}>
                        {s.replaceAll("_", " ").toLowerCase()}
                      </option>
                    ))}
                  </select>
                </label>
                <small>A choice records intent; it does not move data.</small>
              </div>
            </div>
            <div className={styles.summaryItem}>
              <ShieldCheck size={22} />
              <div>
                <strong>Source remains unchanged</strong>
                <small>No workload, data, or traffic changes</small>
              </div>
            </div>
            <div className={styles.summaryItem}>
              <LockKeyhole size={22} />
              <div>
                <strong>Execution not enabled</strong>
                <small>Separate plan approval and cutover gates required</small>
              </div>
            </div>
            {draft.mode === "FULL_CLUSTER" && (
              <p className={styles.warning}>
                {unaccounted} resources need a treatment decision. Inventory
                coverage is not yet certified for full-cluster migration.
              </p>
            )}
          </aside>
        </div>
      )}
      {tab === "remediate" && (
        <section className={styles.surface}>
          <div className={styles.toolbar}>
            <strong>{blockers} assessment blockers</strong>
            <span>
              {draft.remediations.filter((r) => r.evidenceReference).length}{" "}
              evidence references · verification pending
            </span>
            <label>
              Severity
              <select
                aria-label="Finding severity"
                value={severity}
                onChange={(e) => setSeverity(e.target.value)}
              >
                <option value="ALL">All findings</option>
                <option value="BLOCKER">Blockers</option>
                <option value="WARNING">Warnings</option>
                <option value="INFO">Information</option>
              </select>
            </label>
          </div>
          <div className={styles.remediationColumns}>
            <div className={styles.tableScroll}>
              <table>
                <thead>
                  <tr>
                    <th>Finding</th>
                    <th>Affected resource</th>
                    <th>Owner</th>
                    <th>Evidence status</th>
                  </tr>
                </thead>
                <tbody>
                  {findings.map(({ finding: f, index }) => {
                    const item = draft.remediations.find(
                      (r) => r.findingIndex === index,
                    );
                    return (
                      <tr
                        key={index}
                        className={
                          index === findingIndex ? styles.selectedRow : ""
                        }
                      >
                        <td>
                          <button
                            className={styles.findingButton}
                            onClick={() => setFindingIndex(index)}
                          >
                            <span
                              className={
                                f.severity === "BLOCKER"
                                  ? styles.blocker
                                  : styles.severity
                              }
                            >
                              {f.severity}
                            </span>
                            {f.message}
                          </button>
                        </td>
                        <td>
                          {f.resourceName ?? "Assessment-wide"}
                          <small>
                            {f.namespace ?? "Cluster"} ·{" "}
                            {f.resourceKind ?? f.category}
                          </small>
                        </td>
                        <td>{item?.owner || "Unassigned"}</td>
                        <td>
                          {item?.evidenceReference
                            ? "Evidence attached; not verified"
                            : "Not verified"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <aside className={styles.detail}>
              {finding ? (
                <>
                  <h2>
                    <Wrench size={20} />
                    {finding.code.replaceAll("_", " ")}
                  </h2>
                  <p>{finding.message}</p>
                  <p className={styles.caption}>
                    {finding.remediation ??
                      "Review this finding with the application owner."}
                  </p>
                  <fieldset
                    className={styles.fields}
                    disabled={!canEdit || stale || save.isPending}
                  >
                    <label>
                      Treatment
                      <select
                        value={remediation.treatment}
                        onChange={(e) =>
                          changeRemediation({
                            treatment: e.target
                              .value as RemediationDraft["treatment"],
                          })
                        }
                      >
                        {[
                          "REVIEW",
                          "RECONFIGURE",
                          "RECREATE",
                          "REPLACE",
                          "RETIRE",
                        ].map((t) => (
                          <option value={t} key={t}>
                            {t.toLowerCase()}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Owner
                      <input
                        value={remediation.owner}
                        maxLength={150}
                        onChange={(e) =>
                          changeRemediation({ owner: e.target.value })
                        }
                        placeholder="Application or platform owner"
                      />
                    </label>
                    <label>
                      Target mapping
                      <textarea
                        value={remediation.targetMapping}
                        maxLength={1000}
                        rows={3}
                        onChange={(e) =>
                          changeRemediation({ targetMapping: e.target.value })
                        }
                        placeholder="Target storage class, ingress, identity, or replacement decision"
                      />
                    </label>
                    <label>
                      Evidence reference
                      <input
                        value={remediation.evidenceReference}
                        maxLength={1000}
                        onChange={(e) =>
                          changeRemediation({
                            evidenceReference: e.target.value,
                          })
                        }
                        placeholder="Artifact ID or reference; no credentials"
                      />
                    </label>
                    <label>
                      Work status
                      <select
                        value={remediation.status}
                        onChange={(e) =>
                          changeRemediation({
                            status: e.target
                              .value as RemediationDraft["status"],
                          })
                        }
                      >
                        <option value="PLANNED">Planned</option>
                        <option value="IN_PROGRESS">In progress</option>
                        <option value="EVIDENCE_ATTACHED">
                          Evidence attached
                        </option>
                      </select>
                    </label>
                  </fieldset>
                  <p className={styles.notice}>
                    Evidence attachment is not verification. Target preparation
                    requires a separate authorized action.
                  </p>
                  <div className={styles.detailActions}>
                    <button
                      disabled
                      title="Target action runner not implemented"
                    >
                      Apply change
                    </button>
                    <button
                      disabled
                      title="Target verification runner not implemented"
                    >
                      Verify remediation
                    </button>
                  </div>
                </>
              ) : (
                <p>No findings in this assessment.</p>
              )}
            </aside>
          </div>
        </section>
      )}
      {tab === "review" && (
        <section className={styles.surface}>
          <h2>Draft readiness</h2>
          <div className={styles.context}>
            <div>
              <span>Migration mode</span>
              <strong>{draft.mode.replaceAll("_", " ")}</strong>
            </div>
            <div>
              <span>Resources / dependencies</span>
              <strong>
                {draft.resources.length} / {dependencies}
              </strong>
            </div>
            <div>
              <span>Assessment evidence</span>
              <strong>
                {stale
                  ? "Changed; reload required"
                  : `Version ${draft.assessmentVersion}`}
              </strong>
            </div>
          </div>
          <p>
            {blockers} assessment blockers remain unverified. No execution plan
            has been generated or approved.
          </p>
          <label>
            Planning notes
            <textarea
              rows={3}
              maxLength={2000}
              value={draft.notes}
              disabled={!canEdit || stale || save.isPending}
              onChange={(e) => change({ ...draft, notes: e.target.value })}
            />
          </label>
          <p className={styles.notice}>
            Next: confirm dependencies and data consistency requirements,
            implement target verification, then generate a versioned execution
            plan with validation and rollback checkpoints.
          </p>
          <button
            disabled
            title="Execution engine and plan approval are not implemented"
          >
            Approve & execute migration
          </button>
        </section>
      )}
      <footer className={styles.footer}>
        <button
          className="button button-secondary"
          onClick={() => setTab(tab === "review" ? "remediate" : "scope")}
        >
          <ArrowLeft size={16} />
          Back
        </button>
        <p role={save.isError ? "alert" : "status"}>
          {message ||
            (dirty
              ? "Unsaved planning changes"
              : `Assessment v${assessment.assessmentVersion} · Draft only`)}
        </p>
        <button
          className="button button-secondary"
          disabled={!canEdit || stale || !dirty || save.isPending}
          onClick={() => save.mutate()}
        >
          {save.isPending ? "Saving…" : "Save draft"}
        </button>
        <button
          className="button button-primary"
          onClick={() => setTab(tab === "scope" ? "remediate" : "review")}
          disabled={tab === "review"}
        >
          {tab === "scope" ? "Review remediation" : "Review draft"}
          <ArrowRight size={16} />
        </button>
      </footer>
    </div>
  );
}
