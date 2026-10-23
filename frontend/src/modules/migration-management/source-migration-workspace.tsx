"use client";

import Link from "next/link";
import { PageHeading } from "@/shared/components/ui";
import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowRight,
  Boxes,
  CheckCircle2,
  Info,
  LockKeyhole,
  Network,
  Save,
  Search,
} from "lucide-react";
import { useAuth } from "@/shared/auth/auth-provider";
import { hasPermission } from "@/shared/auth/permissions";
import { normalizeApiError } from "@/shared/api/client";
import { clusters } from "@/modules/cluster-management/service";
import type { Cluster } from "@/modules/cluster-management/model";
import type {
  Assessment,
  Migration,
  MigrationDeploymentSource,
  MigrationPlanningDraft,
  SourceInventory,
} from "./model";
import {
  migrations,
  sourceClusters,
  type TargetCompatibilityResponse,
} from "./service";
import { ArtifactWorkspacePanel } from "./artifact-workspace-panel";
import { SourceConnectionsPanel } from "./source-connections-panel";
import { DeploymentEvidencePanel } from "./deployment-evidence-panel";
import { MigrationWorkflow } from "./migration-workflow";
import {
  applicationKinds,
  namedResources,
  restoredWorkloadKeys,
  scopeKey,
  selectedApplicationScope,
} from "./source-migration-scope";
import styles from "./source-migration-workspace.module.css";

function statusLabel(value: string) {
  const text = value.replaceAll("_", " ").toLowerCase();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function SourceMigrationWorkspace({
  migration: initial,
  assessment,
  inventory,
}: {
  migration: Migration;
  assessment: Assessment;
  inventory: SourceInventory;
}) {
  const { identity } = useAuth();
  const cache = useQueryClient();
  const [migration, setMigration] = useState(initial);
  const saved = (
    migration.planningDraft?.schemaVersion === 1
      ? migration.planningDraft
      : undefined
  ) as MigrationPlanningDraft | undefined;
  const [step, setStep] = useState(3);
  const [scopeView, setScopeView] = useState<"selection" | "artifacts">(
    "selection",
  );
  const [manageRequest, setManageRequest] = useState(0);
  const [filesStage, setFilesStage] = useState(1);
  const [selected, setSelected] = useState(() =>
    restoredWorkloadKeys(inventory.resources, saved),
  );
  const [browsingNamespaces, setBrowsingNamespaces] = useState<string[]>(
    saved?.selectedNamespaces ?? [],
  );
  const [search, setSearch] = useState("");
  const [deploymentSources] = useState<MigrationDeploymentSource[]>(
    saved?.deploymentSources ?? [],
  );
  const [dataStrategy, setDataStrategy] = useState<
    MigrationPlanningDraft["dataStrategy"]
  >(saved?.dataStrategy ?? "UNDECIDED");
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [targetId, setTargetId] = useState(
    String(migration.targetConfiguration.clusterId ?? ""),
  );
  const [compatibility, setCompatibility] =
    useState<TargetCompatibilityResponse | null>(null);
  const canEdit =
    hasPermission(identity, "migration.edit") &&
    ["ASSESSMENT_READY", "REJECTED"].includes(migration.status);
  const scope = useMemo(
    () => selectedApplicationScope(inventory.resources, selected),
    [inventory.resources, selected],
  );
  const resources = namedResources(inventory.resources);
  const namespaces = [
    ...new Set(
      resources.flatMap((r) =>
        r.kind === "Namespace" ? [r.name] : r.namespace ? [r.namespace] : [],
      ),
    ),
  ].sort();
  const workloads = resources.filter(
    (r) =>
      applicationKinds.has(r.kind) &&
      browsingNamespaces.includes(r.namespace ?? "") &&
      `${r.name} ${r.kind}`.toLowerCase().includes(search.toLowerCase()),
  );
  const visibleSelectedCount = workloads.filter((r) =>
    selected.has(scopeKey(r)),
  ).length;
  function selectVisibleWorkloads(include: boolean) {
    if (busy || !canEdit || !workloads.length) return;
    setSelected((current) => {
      const next = new Set(current);
      for (const resource of workloads) {
        if (include) next.add(scopeKey(resource));
        else next.delete(scopeKey(resource));
      }
      return next;
    });
    markDirty();
  }
  const pvcs = scope.dependencies.filter(
    (r) => r.kind === "PersistentVolumeClaim",
  );
  const savedScope =
    saved?.workflow === "SOURCE_FIRST" &&
    saved.inventoryDigest === inventory.inventoryDigest &&
    saved.assessmentVersion === assessment.assessmentVersion &&
    saved.resources.some((r) => !r.dependency && applicationKinds.has(r.kind));
  const source = useQuery({
    queryKey: [
      "workspace-source",
      migration.sourceConfiguration.sourceClusterId,
    ],
    queryFn: () =>
      sourceClusters.get(String(migration.sourceConfiguration.sourceClusterId)),
    enabled: Boolean(migration.sourceConfiguration.sourceClusterId),
    retry: false,
  });
  const targets = useQuery({
    queryKey: ["migration-targets", migration.customerId],
    enabled: step >= 4,
    retry: false,
    queryFn: async () => {
      const first = await clusters.list({
        page: 0,
        pageSize: 100,
        status: "ACTIVE",
      });
      const items: Cluster[] = [...first.items];
      for (let page = 1; page < first.pagination.totalPages; page++)
        items.push(
          ...(await clusters.list({ page, pageSize: 100, status: "ACTIVE" }))
            .items,
        );
      return items.filter(
        (c) =>
          c.customerId === migration.customerId &&
          c.status === "ACTIVE" &&
          c.platform === "EKS" &&
          c.workflow?.ownershipStatus !== "ARCHIVED",
      );
    },
  });
  const storedCompatibility = useQuery({
    queryKey: [
      "source-first-compatibility",
      migration.migrationId,
      migration.version,
      targetId,
    ],
    queryFn: () => migrations.targetCompatibility(migration.migrationId),
    enabled:
      step >= 4 &&
      Boolean(savedScope) &&
      !dirty &&
      Boolean(targetId) &&
      targetId === migration.targetConfiguration.clusterId,
    retry: false,
  });
  const currentCompatibility =
    !dirty && targetId === migration.targetConfiguration.clusterId
      ? (compatibility ?? storedCompatibility.data ?? null)
      : null;
  const markDirty = () => {
    setDirty(true);
    setCompatibility(null);
    setNotice("");
  };
  function browseNamespace(ns: string, included: boolean) {
    setBrowsingNamespaces((current) =>
      included ? [...current, ns] : current.filter((n) => n !== ns),
    );
    if (!included) {
      setSelected(
        (current) =>
          new Set(
            [...current].filter(
              (key) =>
                !resources.some(
                  (r) => r.namespace === ns && scopeKey(r) === key,
                ),
            ),
          ),
      );
      markDirty();
    }
  }
  async function saveScope(continueToTarget = false) {
    if (!scope.workloads.length) {
      setError(
        "Select at least one application workload. Selecting a namespace does not select its workloads.",
      );
      return;
    }
    setBusy(true);
    setError("");
    try {
      const draft: MigrationPlanningDraft = {
        schemaVersion: 1,
        workflow: "SOURCE_FIRST",
        mode: "SELECTED_WORKLOADS",
        assessmentVersion: assessment.assessmentVersion,
        inventoryDigest: inventory.inventoryDigest,
        selectedNamespaces: scope.namespaces,
        resources: scope.resources,
        deploymentSources: deploymentSources.filter((s) =>
          selected.has(scopeKey(s.workload)),
        ),
        remediations: saved?.remediations ?? [],
        storageMappings:
          saved?.storageMappings?.filter((m) =>
            pvcs.some(
              (p) => p.namespace === m.namespace && p.name === m.sourceClaim,
            ),
          ) ?? [],
        dataStrategy: pvcs.length ? dataStrategy : "NO_PERSISTENT_DATA",
        notes: saved?.notes ?? "",
      };
      const result = await migrations.update(migration.migrationId, {
        version: migration.version,
        planningDraft: draft,
        changeReason:
          "Save selected application scope and deployment source metadata",
      });
      setMigration(result);
      setDirty(false);
      setCompatibility(null);
      setNotice(
        "Migration scope saved. Only selected application workloads and observed dependencies are included.",
      );
      void cache.invalidateQueries({ queryKey: ["migrations"] });
      if (continueToTarget) setStep(4);
    } catch (e) {
      setError(normalizeApiError(e).message);
    } finally {
      setBusy(false);
    }
  }
  async function assessTarget() {
    if (!savedScope || dirty || !targetId) return;
    const target = targets.data?.find((c) => c.clusterId === targetId);
    if (!target) {
      setError(
        "Select an available target cluster belonging to this customer.",
      );
      return;
    }
    setBusy(true);
    setError("");
    setCompatibility(null);
    try {
      const result = await migrations.update(migration.migrationId, {
        version: migration.version,
        changeReason: "Select target for the saved application migration scope",
        target: {
          platform: "EKS",
          targetType: "EXISTING_CLUSTER",
          clusterId: target.clusterId,
          clusterName: target.clusterName,
          environmentId: target.environmentId,
          environmentApprovedVersion: target.environmentApprovedVersion,
          endpointAccess: "PRIVATE",
        },
      });
      setMigration(result);
      await migrations.analyzeTarget(migration.migrationId);
      setCompatibility(
        await migrations.targetCompatibility(migration.migrationId),
      );
      setNotice(
        "Target evidence collected. Review compatibility for the saved application scope.",
      );
    } catch (e) {
      setError(normalizeApiError(e).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className={styles.workspace}>
      <PageHeading
        title={
          step === 3
            ? "Migration scope"
            : step === 4
              ? "Target & compatibility"
              : "Review migration"
        }
        description="Choose applications, prepare source artifacts, then assess the destination."
        icon={<Boxes size={20} />}
        action={
          <Link
            href={`/migrations/${migration.migrationId}/discovery`}
            className="button button-secondary"
          >
            <ArrowLeft size={16} /> Source assessment
          </Link>
        }
      />
      <MigrationWorkflow
        active={step}
        hideConnection
        completed={[1, 2, ...(savedScope && !dirty ? [3] : [])]}
        available={
          busy
            ? []
            : [
                3,
                ...(savedScope && !dirty ? [4] : []),
                ...(currentCompatibility && !dirty ? [5] : []),
              ]
        }
        onSelect={setStep}
      />
      <section className={styles.context} aria-label="Migration context">
        <div>
          <small>ASSESSMENT</small>
          <strong>{migration.name}</strong>
        </div>
        <div>
          <small>CUSTOMER</small>
          <strong>
            {String(
              migration.customerName ??
                source.data?.customerName ??
                migration.customerId,
            )}
          </strong>
        </div>
        <div>
          <small>SOURCE CLUSTER</small>
          <strong>
            {source.data?.name ??
              String(
                migration.sourceConfiguration.sourceClusterId ??
                  "Source cluster",
              )}
          </strong>
          <span>
            {source.data?.distribution ?? "Kubernetes"} ·{" "}
            {inventory.sourceKubernetesVersion}
          </span>
        </div>
        <div>
          <small>MIGRATION SCOPE</small>
          <strong>
            {scope.workloads.length} workloads · {scope.namespaces.length}{" "}
            namespaces
          </strong>
          <span>{scope.dependencies.length} associated resources</span>
        </div>
      </section>
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      {source.isError && (
        <p className={styles.error} role="alert">
          Unable to load source cluster details.{" "}
          <button onClick={() => void source.refetch()}>
            Retry source details
          </button>
        </p>
      )}
      {notice && (
        <p className={styles.notice} role="status">
          {notice}
        </p>
      )}
      {!canEdit && (
        <p className={styles.info}>
          This assessment is read-only for your account or workflow status.
        </p>
      )}
      {step === 3 && (
        <>
          <nav className={styles.scopeTabs} aria-label="Migration scope views">
            <button
              aria-pressed={scopeView === "selection"}
              onClick={() => setScopeView("selection")}
            >
              1. Choose scope
            </button>
            <button
              aria-pressed={scopeView === "artifacts"}
              onClick={() => setScopeView("artifacts")}
            >
              2. Files &amp; images
            </button>
          </nav>
          <div hidden={scopeView !== "selection"}>
            <section className={styles.panel}>
              <div className={styles.sectionHeading}>
                <div>
                  <span className={styles.eyebrow}>
                    STEP 2 · MIGRATION SCOPE
                  </span>
                  <h2>Select application workloads</h2>
                  <p>
                    Choose namespaces to browse, then select individual
                    workloads. No application is selected automatically.
                  </p>
                </div>
                <span className={styles.badge}>Selected applications only</span>
              </div>
              <div className={styles.scopeGrid}>
                <aside
                  className={styles.namespaces}
                  aria-label="Source namespaces"
                >
                  <h3>1. Namespaces</h3>
                  <p>Browse applications by namespace.</p>
                  {namespaces.map((ns) => (
                    <label key={ns}>
                      <input
                        type="checkbox"
                        checked={browsingNamespaces.includes(ns)}
                        disabled={busy || !canEdit}
                        onChange={(e) => browseNamespace(ns, e.target.checked)}
                      />
                      <span>
                        <strong>{ns}</strong>
                        <small>
                          {
                            resources.filter(
                              (r) =>
                                r.namespace === ns &&
                                applicationKinds.has(r.kind),
                            ).length
                          }{" "}
                          workloads
                        </small>
                      </span>
                    </label>
                  ))}
                </aside>
                <div className={styles.workloads}>
                  <div className={styles.sectionHeading}>
                    <h3>2. Application workloads</h3>
                    <label className={styles.search}>
                      <Search size={16} />
                      <input
                        aria-label="Find workload"
                        value={search}
                        placeholder="Find a workload"
                        onChange={(e) => setSearch(e.target.value)}
                      />
                    </label>
                  </div>
                  <div
                    className={styles.bulkActions}
                    aria-label="Bulk workload selection"
                  >
                    <button
                      type="button"
                      disabled={
                        busy ||
                        !canEdit ||
                        !workloads.length ||
                        visibleSelectedCount === workloads.length
                      }
                      onClick={() => selectVisibleWorkloads(true)}
                    >
                      Select all
                    </button>
                    <button
                      type="button"
                      disabled={busy || !canEdit || !visibleSelectedCount}
                      onClick={() => selectVisibleWorkloads(false)}
                    >
                      Deselect all
                    </button>
                    <small aria-live="polite">
                      {visibleSelectedCount} of {workloads.length} shown
                      selected · Applies to current namespace and search filters
                    </small>
                  </div>
                  {!browsingNamespaces.length ? (
                    <div className={styles.empty}>
                      <Boxes size={30} />
                      <strong>
                        Choose a namespace to see its applications
                      </strong>
                      <p>
                        Selecting a namespace does not add its workloads to
                        migration scope.
                      </p>
                    </div>
                  ) : (
                    <div className={styles.tableScroll}>
                      <table>
                        <thead>
                          <tr>
                            <th>Select</th>
                            <th>Workload</th>
                            <th>Namespace</th>
                            <th>Kind</th>
                          </tr>
                        </thead>
                        <tbody>
                          {workloads.map((r) => (
                            <tr key={scopeKey(r)}>
                              <td>
                                <input
                                  type="checkbox"
                                  aria-label={`Migrate ${r.namespace}/${r.name}`}
                                  title="Include this application workload and its observed resource dependencies."
                                  checked={selected.has(scopeKey(r))}
                                  disabled={busy || !canEdit}
                                  onChange={(e) => {
                                    const checked = e.target.checked;
                                    setSelected((current) => {
                                      const next = new Set(current);
                                      if (checked) next.add(scopeKey(r));
                                      else next.delete(scopeKey(r));
                                      return next;
                                    });
                                    markDirty();
                                  }}
                                />
                              </td>
                              <td>
                                <strong>{r.name}</strong>
                              </td>
                              <td>{r.namespace}</td>
                              <td>{r.kind}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      {!workloads.length && (
                        <p>No matching application workloads.</p>
                      )}
                    </div>
                  )}
                  <p className={styles.hint}>
                    Application controllers are available in the current
                    inventory. Standalone Pod selection requires Pod discovery
                    evidence, which this connector has not collected.
                  </p>
                </div>
                <aside
                  className={styles.summary}
                  aria-label="Selected application scope"
                >
                  <h3>Selected for migration</h3>
                  <strong className={styles.metric}>
                    {scope.workloads.length}
                  </strong>
                  <span>application workloads</span>
                  <dl>
                    <div>
                      <dt>Namespaces</dt>
                      <dd>{scope.namespaces.length}</dd>
                    </div>
                    <div>
                      <dt>Associated resources</dt>
                      <dd>{scope.dependencies.length}</dd>
                    </div>
                    <div>
                      <dt>Persistent volume claims</dt>
                      <dd>{pvcs.length}</dd>
                    </div>
                  </dl>
                  {scope.workloads.map((r) => (
                    <p key={scopeKey(r)}>
                      <CheckCircle2 size={14} />
                      <span>
                        {r.name}
                        <small>{r.namespace}</small>
                      </span>
                    </p>
                  ))}
                </aside>
              </div>
            </section>
            <section
              className={styles.panel}
              aria-label="Observed dependencies"
              hidden={!scope.workloads.length}
            >
              <div className={styles.sectionHeading}>
                <div>
                  <h2>
                    <Network size={20} />
                    3. Review associated resources
                  </h2>
                  <p>
                    Included from observed workload references, ingress backends
                    and StatefulSet claim ownership. Unrelated workloads are
                    excluded.
                  </p>
                </div>
                <span className={styles.badge}>
                  {scope.dependencies.length} resources
                </span>
              </div>
              <div className={styles.chips}>
                {scope.dependencies.map((r) => (
                  <span key={scopeKey(r)}>
                    <strong>{r.name}</strong>
                    <small>
                      {r.namespace ?? "Cluster"} · {r.kind}
                    </small>
                  </span>
                ))}
              </div>
              {scope.missing.length > 0 && (
                <p role="status" className={styles.warning}>
                  Referenced resources missing from inventory:{" "}
                  {scope.missing.map((r) => `${r.kind}/${r.name}`).join(", ")}.
                  Review before migration approval.
                </p>
              )}
              <p className={styles.hint}>
                <Info size={15} />
                Observed references are not proof of complete dependencies.
                Network policies, operators, external services and
                controller-specific relationships require review.
              </p>
              {pvcs.length > 0 && (
                <label className={styles.field}>
                  Persistent data strategy
                  <select
                    value={dataStrategy}
                    disabled={busy || !canEdit}
                    onChange={(e) => {
                      setDataStrategy(e.target.value as typeof dataStrategy);
                      markDirty();
                    }}
                  >
                    <option value="UNDECIDED">Choose during planning</option>
                    <option value="BACKUP_RESTORE">Backup and restore</option>
                    <option value="REPLICATION">Replication</option>
                  </select>
                  <small>
                    PVC selection records storage requirements; it does not
                    transfer persistent data.
                  </small>
                </label>
              )}
            </section>
          </div>
          {scopeView === "artifacts" &&
            (!savedScope || dirty ? (
              <section
                className={styles.panel}
                aria-label="Save scope before collection"
              >
                <h2>Save your scope before collecting artifacts</h2>
                <p>
                  Files and images use the namespaces from your saved workload
                  selection. Save the current selection to continue.
                </p>
                <button
                  className={styles.secondary}
                  onClick={() => setScopeView("selection")}
                >
                  Back to scope selection
                </button>
              </section>
            ) : (
              <div className={styles.artifacts}>
                <nav
                  className={styles.filesNavigation}
                  aria-label="Files and images preparation"
                >
                  <div className={styles.filesSteps}>
                    {[
                      "Check sources",
                      "Collect artifacts",
                      "Review & export",
                    ].map((label, index) => (
                      <button
                        key={label}
                        type="button"
                        aria-current={
                          filesStage === index + 1 ? "step" : undefined
                        }
                        onClick={() => setFilesStage(index + 1)}
                      >
                        <span>{index + 1}</span> {label}
                      </button>
                    ))}
                  </div>
                  <div className={styles.filesActions}>
                    <button
                      className={styles.secondary}
                      onClick={() =>
                        filesStage === 1
                          ? setScopeView("selection")
                          : setFilesStage(filesStage - 1)
                      }
                    >
                      {filesStage === 1 ? "Back to scope" : "Previous"}
                    </button>
                    {filesStage < 3 ? (
                      <button
                        className={styles.primary}
                        onClick={() => setFilesStage(filesStage + 1)}
                      >
                        {filesStage === 1
                          ? "Continue to collection"
                          : "Review saved artifacts"}
                        <ArrowRight size={16} />
                      </button>
                    ) : (
                      <button
                        className={styles.primary}
                        disabled={busy}
                        onClick={() => setStep(4)}
                      >
                        Continue to target
                        <ArrowRight size={16} />
                      </button>
                    )}
                  </div>
                </nav>
                <div hidden={filesStage !== 1} className={styles.artifacts}>
                  <section
                    className={styles.panel}
                    aria-label="Artifact source access"
                  >
                    <h2>Repository &amp; registry access</h2>
                    <SourceConnectionsPanel
                      sourceId={String(
                        migration.sourceConfiguration.sourceClusterId ?? "",
                      )}
                      assessmentComplete
                      showConnector={false}
                      compact
                      openRequest={manageRequest}
                    />
                  </section>
                  <DeploymentEvidencePanel
                    migration={migration}
                    selectedKeys={selected}
                    inventoryDigest={inventory.inventoryDigest}
                    collapseWorkloads
                  />
                </div>
                <div hidden={filesStage === 1}>
                  <ArtifactWorkspacePanel
                    key={`${inventory.inventoryDigest}/${scope.namespaces.slice().sort().join(",")}`}
                    migrationId={migration.migrationId}
                    version={migration.version}
                    inventoryDigest={inventory.inventoryDigest}
                    namespaces={scope.namespaces}
                    canEdit={canEdit}
                    guided
                    active
                    fixedScope
                    stage={filesStage === 3 ? "review" : "collect"}
                    onReviewAccess={() => {
                      setFilesStage(1);
                      setManageRequest((n) => n + 1);
                    }}
                  />
                </div>
              </div>
            ))}
          {(scopeView === "selection" || !savedScope || dirty) && (
            <footer className={styles.actions}>
              <span>
                {scope.workloads.length} workloads selected ·{" "}
                {dirty
                  ? "Unsaved changes"
                  : savedScope
                    ? "Scope saved"
                    : "Save scope to continue"}
              </span>
              <button
                className={styles.secondary}
                disabled={busy || !canEdit || !scope.workloads.length}
                onClick={() => void saveScope()}
              >
                <Save size={16} />
                Save scope draft
              </button>

              <button
                className={styles.primary}
                disabled={busy || !canEdit || !scope.workloads.length}
                onClick={() => void saveScope(true)}
              >
                {busy ? "Saving…" : "Save & continue to target"}
                <ArrowRight size={16} />
              </button>
            </footer>
          )}
        </>
      )}
      {step === 4 && (
        <section className={styles.panel}>
          <span className={styles.eyebrow}>
            STEP 3 · TARGET & COMPATIBILITY
          </span>
          <h2>Choose a Navigan-managed destination</h2>
          <p>
            Compare only the saved application scope: {scope.workloads.length}{" "}
            workloads and {scope.dependencies.length} associated resources.
          </p>
          <div className={styles.providers}>
            <span>EKS · Available</span>
            <span>AKS · Adapter pending</span>
            <span>GKE · Adapter pending</span>
            <span>OpenShift · Adapter pending</span>
          </div>
          <label className={styles.field}>
            Target cluster *
            <select
              value={targetId}
              disabled={
                busy || !canEdit || targets.isPending || targets.isError
              }
              onChange={(e) => {
                setTargetId(e.target.value);
                setCompatibility(null);
                setNotice("");
              }}
            >
              <option value="">
                Select an active cluster for this customer
              </option>
              {targets.data?.map((c) => (
                <option key={c.clusterId} value={c.clusterId}>
                  {c.clusterName} · {c.environmentName ?? c.environmentId}
                </option>
              ))}
            </select>
          </label>
          {targets.isPending && (
            <p role="status">Loading active customer clusters…</p>
          )}
          {targets.isError && (
            <p role="alert">
              Unable to load target clusters.{" "}
              <button onClick={() => void targets.refetch()}>
                Retry targets
              </button>
            </p>
          )}
          {targets.data?.length === 0 && (
            <p>No active EKS targets are registered for this customer.</p>
          )}
          <button
            className={styles.primary}
            disabled={
              !canEdit ||
              busy ||
              !targetId ||
              !savedScope ||
              dirty ||
              !targets.data?.some((c) => c.clusterId === targetId)
            }
            onClick={() => void assessTarget()}
          >
            {busy ? "Assessing selected scope…" : "Assess target compatibility"}
          </button>
          {storedCompatibility.isError && !compatibility && (
            <p role="alert" className={styles.error}>
              Unable to load saved target checks.{" "}
              <button onClick={() => void storedCompatibility.refetch()}>
                Retry target checks
              </button>
            </p>
          )}
          {currentCompatibility && (
            <div
              className={styles.compatibility}
              aria-label="Selected scope compatibility"
            >
              <h3>
                {statusLabel(currentCompatibility.decision.path)}
                {currentCompatibility.decision.reason ? " · " : ""}
                {currentCompatibility.decision.reason}
              </h3>
              <p>
                {currentCompatibility.coverageComplete
                  ? "Reported coverage complete"
                  : "Evidence coverage is incomplete; migration readiness has not been established."}
              </p>
              <div className={styles.tableScroll}>
                <table>
                  <thead>
                    <tr>
                      <th>Selected resource</th>
                      <th>Kind</th>
                      <th>Status</th>
                      <th>Required checks</th>
                    </tr>
                  </thead>
                  <tbody>
                    {currentCompatibility.resourceEvaluations?.map((r) => (
                      <tr key={scopeKey(r.resource)}>
                        <td>
                          {r.resource.namespace}/{r.resource.name}
                        </td>
                        <td>{r.resource.kind}</td>
                        <td>{r.status}</td>
                        <td>
                          {r.checks
                            .map(
                              (c) =>
                                `${c.capability}: ${c.status} — ${c.reason}`,
                            )
                            .join("; ")}
                        </td>
                      </tr>
                    ))}
                    {!currentCompatibility.resourceEvaluations?.length && (
                      <tr>
                        <td colSpan={4}>
                          No per-resource checks were returned. Review evidence
                          coverage before approval.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              <button className={styles.secondary} onClick={() => setStep(5)}>
                Review scope & readiness <ArrowRight size={16} />
              </button>
            </div>
          )}
          <div className={styles.actions}>
            <button className={styles.secondary} onClick={() => setStep(3)}>
              <ArrowLeft size={16} />
              Back to migration scope
            </button>
          </div>
        </section>
      )}
      {step === 5 && (
        <section className={styles.panel}>
          <span className={styles.eyebrow}>STEP 4 · REVIEW & APPROVAL</span>
          <h2>Review the application migration scope</h2>
          <p>
            {scope.workloads.length} workloads · {scope.namespaces.length}{" "}
            namespaces · {scope.dependencies.length} associated resources
          </p>
          <ul className={styles.readiness}>
            <li>Source assessment: completed</li>
            <li>
              Migration scope:{" "}
              {savedScope && !dirty ? "saved" : "requires saving"}
            </li>
            <li>
              Target compatibility:{" "}
              {currentCompatibility
                ? statusLabel(currentCompatibility.decision.path)
                : "not evaluated"}
            </li>
            <li>
              Source files &amp; images: review the S3 collection and export in
              Migration scope. An export does not verify target readiness.
            </li>
            <li>Rendered deployment package validation: pending</li>
            <li>Adapted deployment package and validation: pending</li>
            <li>
              Persistent data strategy:{" "}
              {pvcs.length ? dataStrategy : "no selected PVCs"}
            </li>
          </ul>
          <p className={styles.warning}>
            Review is available. Migration approval requires analyzed artifacts,
            a validated selected-workload package and resolved compatibility
            checks. These capabilities are not yet connected in this workflow.
          </p>
          <div className={styles.actions}>
            <button
              className={styles.secondary}
              onClick={() => {
                setScopeView("artifacts");
                setFilesStage(3);
                setStep(3);
              }}
            >
              Review files &amp; images
            </button>
            <button className={styles.secondary} onClick={() => setStep(4)}>
              Back to target & compatibility
            </button>
            <button className={styles.primary} disabled>
              <LockKeyhole size={16} />
              Submit for migration approval
            </button>
            <button disabled>
              <LockKeyhole size={16} />
              Execute migration
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
