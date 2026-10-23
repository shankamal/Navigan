"use client";
import { useEffect, useRef, useState } from "react";
import {
  ChevronDown,
  Database,
  Search,
  ShieldCheck,
  Github,
  Container,
  FileCode2,
  Layers,
  CheckCircle2,
  LoaderCircle,
  RefreshCw,
} from "lucide-react";
import {
  apiClient,
  normalizeApiError,
  writeHeaders,
} from "@/shared/api/client";
import styles from "./artifact-workspace-panel.module.css";
import journey from "./discovery-journey.module.css";
type Recovery = { jobId: string; status: string; message?: string };
type WorkspaceExport = {
  exportId: string;
  downloadUrl: string;
  expiresInSeconds: number;
  collectedArtifactCount: number;
  excludedArtifactCount: number;
  storage: { versionId: string; sha256: string; bucket?: string; key?: string };
};
type Workload = {
  apiVersion?: string;
  kind: string;
  namespace: string;
  name: string;
};
type Workspace = {
  workspaceId: string;
  namespaces: string[];
  stale: boolean;
  status?: string;
  collectedArtifactCount?: number;
  storage?: { bucket?: string; key?: string; prefix?: string };
  jobs?: {
    jobId: string;
    status: string;
    attempts: number;
    artifactId?: string;
    errorCode?: string;
  }[];
  artifacts: {
    artifactId: string;
    kind: string;
    status: string;
    workloads?: Workload[];
    storage?: { bucket?: string; key?: string; versionId?: string };
    source?: {
      reference?: string;
      repository?: string;
      filePath?: string;
      namespace?: string;
      release?: string;
      resource?: { namespace: string; kind: string; name: string };
    };
    validation?: {
      platforms?: string[];
      reviewRequired?: boolean;
      recovery?: Recovery;
      historicalReview?: { parent: Workload; reviewedAt: string };
    };
  }[];
};
export function ArtifactWorkspacePanel({
  migrationId,
  version,
  inventoryDigest,
  namespaces,
  canEdit,
  guided = false,
  active = false,
  onReviewAccess,
  fixedScope = false,
  stage,
}: {
  migrationId: string;
  version: number;
  inventoryDigest?: string;
  namespaces: string[];
  canEdit: boolean;
  guided?: boolean;
  active?: boolean;
  onReviewAccess?: () => void;
  fixedScope?: boolean;
  stage?: "collect" | "review";
}) {
  const [query, setQuery] = useState("");
  const [exports, setExports] = useState<
    Record<
      string,
      {
        pending: boolean;
        error?: string;
        result?: WorkspaceExport;
        expiresAt?: number;
      }
    >
  >({});
  const [historicalReviews, setHistoricalReviews] = useState<
    Record<string, { parent: string; confirmed: boolean }>
  >({});
  const [selected, setSelected] = useState<string[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [activeWorkspaceId, setActiveWorkspaceId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [showCompleted, setShowCompleted] = useState<
    Record<string, "all" | "remaining" | "saved">
  >({});
  const [refreshWarning, setRefreshWarning] = useState("");
  const [recoveryFeedback, setRecoveryFeedback] = useState<{
    workspaceId: string;
    artifactId: string;
    pending: boolean;
    failed: boolean;
    message: string;
  } | null>(null);
  const loadAttempt = useRef("");
  const previousStage = useRef(stage);
  useEffect(() => {
    if (stage === "review" && previousStage.current !== "review") {
      setShowCompleted(
        Object.fromEntries(workspaces.map((w) => [w.workspaceId, "saved"])),
      );
    }
    previousStage.current = stage;
  }, [stage, workspaces]);
  useEffect(() => {
    if (!active || loadAttempt.current === migrationId) return;
    const controller = new AbortController();
    setBusy(true);
    apiClient
      .get(`/migrations/${migrationId}/artifact-workspaces`, {
        signal: controller.signal,
      })
      .then(({ data }) => {
        if (controller.signal.aborted) return;
        loadAttempt.current = migrationId;
        if (!Array.isArray(data.workspaces))
          throw new Error(
            "Workspace list could not be read. Refresh workspaces to retry.",
          );
        setWorkspaces(data.workspaces);
        setLoaded(true);
        setError("");
      })
      .catch((failure) => {
        if (!controller.signal.aborted) {
          loadAttempt.current = migrationId;
          setError(normalizeApiError(failure).message);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setBusy(false);
      });
    return () => controller.abort();
  }, [active, migrationId]);

  async function run(create: boolean) {
    if (
      create &&
      fixedScope &&
      (!loaded ||
        busy ||
        workspaces.some(
          (w) =>
            !w.stale &&
            w.namespaces.length === namespaces.length &&
            w.namespaces.every((ns) => namespaces.includes(ns)),
        ))
    )
      return;
    setBusy(true);
    setError("");
    setRefreshWarning("");
    try {
      if (create) {
        const { data } = await apiClient.post(
          `/migrations/${migrationId}/artifact-workspaces`,
          {
            version,
            inventoryDigest,
            namespaces: fixedScope
              ? namespaces
              : selected.filter((ns) => namespaces.includes(ns)),
          },
          { headers: writeHeaders({ key: crypto.randomUUID(), version }) },
        );
        setWorkspaces((items) => [data, ...items]);
        if (fixedScope) setActiveWorkspaceId(data.workspaceId);
      } else {
        const { data } = await apiClient.get(
          `/migrations/${migrationId}/artifact-workspaces`,
        );
        if (!Array.isArray(data.workspaces))
          throw new Error(
            "Workspace list could not be read. Refresh workspaces to retry.",
          );
        setWorkspaces(data.workspaces);
      }
      setLoaded(true);
    } catch (e) {
      if (fixedScope) setLoaded(false);
      setError(normalizeApiError(e).message);
    } finally {
      setBusy(false);
    }
  }
  async function collect(
    workspaceId: string,
    artifactKind = "REPOSITORY_DEFINITION",
  ) {
    setBusy(true);
    setError("");
    try {
      const { data } = await apiClient.post(
        `/migrations/${migrationId}/artifact-workspaces/${workspaceId}/collection-jobs`,
        { version, ...(artifactKind === "IMAGE" ? { artifactKind } : {}) },
        { headers: writeHeaders({ key: crypto.randomUUID(), version }) },
      );
      setWorkspaces((items) =>
        items.map((item) => (item.workspaceId === workspaceId ? data : item)),
      );
    } catch (e) {
      setError(normalizeApiError(e).message);
    } finally {
      setBusy(false);
    }
  }
  async function recover(
    workspaceId: string,
    artifactId: string,
    job?: Recovery,
  ) {
    setBusy(true);
    setError("");
    const checking = job?.status === "RECOVERING";
    const identity = { workspaceId, artifactId };
    setRecoveryFeedback({
      ...identity,
      pending: true,
      failed: false,
      message: checking
        ? "Checking recovery progress…"
        : "Starting source recovery…",
    });
    let accepted = false;
    try {
      const response = await apiClient.post<{ job: Recovery }>(
        `/migrations/${migrationId}/deployment-evidence`,
        {
          version,
          recovery: {
            operation: checking ? "POLL" : "START",
            workspaceId,
            artifactId,
            ...(checking ? { jobId: job.jobId } : {}),
          },
        },
        { headers: writeHeaders({ key: crypto.randomUUID(), version }) },
      );
      const recovery = response.data.job;
      accepted = true;
      const collected = ["RECOVERED", "PARTIAL_RECOVERY"].includes(
        recovery.status,
      );
      // Keep the accepted job handle even if the subsequent refresh fails.
      setWorkspaces((items) =>
        items.map((item) =>
          item.workspaceId !== workspaceId
            ? item
            : {
                ...item,
                artifacts: item.artifacts.map((artifact) =>
                  artifact.artifactId !== artifactId
                    ? artifact
                    : {
                        ...artifact,
                        status: collected
                          ? "COLLECTED"
                          : recovery.status === "RECOVERING"
                            ? "RECOVERING"
                            : "RECOVERY_REQUIRED",
                        validation: {
                          ...artifact.validation,
                          recovery,
                          ...(collected ? { reviewRequired: true } : {}),
                        },
                      },
                ),
              },
        ),
      );
      setRecoveryFeedback({
        ...identity,
        pending: false,
        failed: recovery.status === "CUSTOMER_INPUT_REQUIRED",
        message:
          recovery.message ||
          (collected
            ? "Recovered copy saved to S3. Review before deployment."
            : recovery.status === "RECOVERING"
              ? "Recovery started. Use Check recovery progress to continue."
              : "Recovery needs attention. Retry after checking source access."),
      });
      const { data } = await apiClient.get(
        `/migrations/${migrationId}/artifact-workspaces`,
      );
      setWorkspaces(data.workspaces);
    } catch (e) {
      const problem = normalizeApiError(e);
      const detail = `${problem.message}${problem.code ? ` (${problem.code})` : ""}`;
      setRecoveryFeedback({
        ...identity,
        pending: false,
        failed: true,
        message: accepted
          ? `Recovery response received, but the workspace could not refresh. ${detail} Use Check recovery progress for a running job.`
          : detail,
      });
    } finally {
      setBusy(false);
    }
  }
  async function excludeHistoricalJob(workspaceId: string, artifactId: string) {
    const selectedReview = historicalReviews[`${workspaceId}/${artifactId}`];
    if (!selectedReview?.confirmed || !selectedReview.parent) return;
    const parent = JSON.parse(selectedReview.parent) as {
      artifactId: string;
      name: string;
    };
    setBusy(true);
    setRecoveryFeedback({
      workspaceId,
      artifactId,
      pending: true,
      failed: false,
      message: "Saving historical run review…",
    });
    try {
      const { data } = await apiClient.post<{ workspace: Workspace }>(
        `/migrations/${migrationId}/deployment-evidence`,
        {
          version,
          recovery: {
            operation: "EXCLUDE_HISTORICAL_JOB",
            workspaceId,
            artifactId,
            parentArtifactId: parent.artifactId,
            parentCronJobName: parent.name,
            confirmHistoricalRun: true,
          },
        },
        { headers: writeHeaders({ key: crypto.randomUUID(), version }) },
      );
      setWorkspaces((items) =>
        items.map((item) =>
          item.workspaceId === workspaceId ? data.workspace : item,
        ),
      );
      setRecoveryFeedback({
        workspaceId,
        artifactId,
        pending: false,
        failed: false,
        message:
          "Historical exclusion recorded. The review receipt is saved to S3; this Job will not be replayed.",
      });
    } catch (e) {
      const problem = normalizeApiError(e);
      setRecoveryFeedback({
        workspaceId,
        artifactId,
        pending: false,
        failed: true,
        message: `${problem.message}${problem.code ? ` (${problem.code})` : ""}`,
      });
    } finally {
      setBusy(false);
    }
  }
  async function createExport(workspaceId: string) {
    setBusy(true);
    setExports((items) => ({ ...items, [workspaceId]: { pending: true } }));
    try {
      const { data } = await apiClient.post<WorkspaceExport>(
        `/migrations/${migrationId}/artifact-workspaces/${workspaceId}/exports`,
        { version },
        { headers: writeHeaders({ key: crypto.randomUUID(), version }) },
      );
      if (
        !data?.exportId ||
        !data.downloadUrl ||
        !data.storage?.sha256 ||
        !Number.isFinite(data.expiresInSeconds) ||
        data.expiresInSeconds <= 0
      ) {
        setExports((items) => ({
          ...items,
          [workspaceId]: {
            pending: false,
            error:
              "The export service returned an incomplete response. Refresh workspaces and try again.",
          },
        }));
        return;
      }
      setExports((items) => ({
        ...items,
        [workspaceId]: {
          pending: false,
          result: data,
          expiresAt: Date.now() + data.expiresInSeconds * 1000,
        },
      }));
    } catch (e) {
      const problem = normalizeApiError(e);
      setExports((items) => ({
        ...items,
        [workspaceId]: {
          pending: false,
          error: `${problem.message}${problem.code ? ` (${problem.code})` : ""}`,
        },
      }));
    } finally {
      setBusy(false);
    }
  }
  function collectionButtons(w: Workspace) {
    return (
      <>
        {" "}
        <button
          type="button"
          disabled={
            busy ||
            !canEdit ||
            w.stale ||
            w.status === "COLLECTING" ||
            !w.artifacts.some(
              (a) =>
                a.kind === "REPOSITORY_DEFINITION" && a.status !== "COLLECTED",
            )
          }
          onClick={() => collect(w.workspaceId)}
        >
          Collect / retry repository files
        </button>
        <button
          type="button"
          disabled={
            busy ||
            !canEdit ||
            w.stale ||
            !w.artifacts.some(
              (a) => a.kind === "IMAGE" && a.status === "PENDING_COLLECTION",
            )
          }
          onClick={() => collect(w.workspaceId, "IMAGE")}
        >
          Collect / retry available images
        </button>
      </>
    );
  }
  function exportButton(w: Workspace) {
    const { attention, available, required } = workspaceCounts(w);
    return (
      <button
        className={styles.primary}
        type="button"
        disabled={
          busy ||
          !canEdit ||
          w.stale ||
          attention > 0 ||
          available > 0 ||
          required < 1 ||
          (w.jobs ?? []).some((job) =>
            ["QUEUED", "RUNNING"].includes(job.status),
          )
        }
        aria-describedby={`export-help-${w.workspaceId}`}
        onClick={() => createExport(w.workspaceId)}
      >
        {exports[w.workspaceId]?.pending && (
          <LoaderCircle
            size={13}
            className={styles.spinning}
            aria-hidden="true"
          />
        )}
        {exports[w.workspaceId]?.pending
          ? "Verifying files and creating export…"
          : "Create workspace export"}
      </button>
    );
  }
  function downloadExport(w: Workspace) {
    return exports[w.workspaceId]?.result ? (
      <a
        className={styles.downloadExport}
        href={exports[w.workspaceId].result!.downloadUrl}
        download
        rel="noopener noreferrer"
        onClick={(event) => {
          if (Date.now() >= (exports[w.workspaceId].expiresAt ?? 0)) {
            event.preventDefault();
            setExports((items) => ({
              ...items,
              [w.workspaceId]: {
                ...items[w.workspaceId],
                error:
                  "The download link expired. Create another export for a fresh link.",
              },
            }));
          }
        }}
      >
        Download export manifest
      </a>
    ) : null;
  }
  function exportFeedback(w: Workspace) {
    const { attention, available, required } = workspaceCounts(w);
    return (
      <div
        aria-live="polite"
        aria-label="Workspace export feedback"
        className={`${styles.exportResult} ${guided ? journey.collectionExport : ""}`}
        data-empty={
          !exports[w.workspaceId]?.pending &&
          !exports[w.workspaceId]?.error &&
          !exports[w.workspaceId]?.result
        }
      >
        <p id={`export-help-${w.workspaceId}`}>
          {w.stale
            ? "Create a workspace from the current inventory before exporting."
            : attention > 0
              ? `Resolve ${attention} artifact${attention === 1 ? "" : "s"} needing attention before exporting.`
              : available > 0
                ? `Collect ${available} remaining artifact${available === 1 ? "" : "s"} before exporting.`
                : required < 1
                  ? "The workspace needs at least one required artifact to export."
                  : (w.jobs ?? []).some((job) =>
                        ["QUEUED", "RUNNING"].includes(job.status),
                      )
                    ? "Wait for the current collection jobs to finish before exporting."
                    : !canEdit
                      ? "Your role can review this workspace but cannot create an export."
                      : "Create an export manifest referencing the exact files and images saved to S3. Target validation follows."}
        </p>
        {exports[w.workspaceId]?.pending && (
          <p role="status">
            Checking stored object versions and review receipts…
          </p>
        )}
        {exports[w.workspaceId]?.error && (
          <p role="alert">{exports[w.workspaceId].error}</p>
        )}
        {exports[w.workspaceId]?.result && (
          <div>
            <p role="status">
              Export saved to S3 ·{" "}
              {exports[w.workspaceId].result!.collectedArtifactCount} collected
              artifacts · {exports[w.workspaceId].result!.excludedArtifactCount}{" "}
              historical exclusions · Target readiness not verified
            </p>
            <small>
              {exports[w.workspaceId].result!.storage.bucket &&
                exports[w.workspaceId].result!.storage.key && (
                  <code>{`s3://${exports[w.workspaceId].result!.storage.bucket}/${exports[w.workspaceId].result!.storage.key}`}</code>
                )}
              {exports[w.workspaceId].result!.exportId} · SHA-256:{" "}
              {exports[w.workspaceId].result!.storage.sha256}
            </small>
            <small>
              Download link valid for five minutes. Files and images remain in
              private S3 storage.
            </small>
          </div>
        )}
      </div>
    );
  }
  const NamespaceChooser = guided ? "details" : "div";
  const scope = fixedScope
    ? namespaces
    : selected.filter((ns) => namespaces.includes(ns));
  const scopedWorkspaces = fixedScope
    ? workspaces.filter(
        (w) =>
          w.namespaces.length === namespaces.length &&
          w.namespaces.every((ns) => namespaces.includes(ns)),
      )
    : workspaces;
  const activeWorkspace =
    scopedWorkspaces.find((w) => w.workspaceId === activeWorkspaceId) ??
    scopedWorkspaces.find((w) => !w.stale) ??
    scopedWorkspaces[0];
  const visibleWorkspaces = fixedScope
    ? activeWorkspace
      ? [activeWorkspace]
      : []
    : scopedWorkspaces;
  const existingWorkspace = scopedWorkspaces.find((w) => !w.stale);
  const visibleNamespaces = namespaces.filter((ns) =>
    ns.toLowerCase().includes(query.toLowerCase()),
  );
  useEffect(() => {
    if (
      !active ||
      busy ||
      !(fixedScope ? visibleWorkspaces : workspaces).some(collectionInProgress)
    )
      return;
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        const { data } = await apiClient.get(
          `/migrations/${migrationId}/artifact-workspaces`,
          { signal: controller.signal },
        );
        if (controller.signal.aborted) return;
        if (!Array.isArray(data.workspaces))
          throw new Error("Invalid workspace response");
        setRefreshWarning("");
        setWorkspaces(data.workspaces);
      } catch {
        if (!controller.signal.aborted)
          setRefreshWarning(
            "Automatic progress updates paused. Refresh workspaces to check the latest status.",
          );
      }
    }, 5000);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [
    active,
    busy,
    migrationId,
    workspaces,
    fixedScope,
    activeWorkspaceId,
    namespaces,
  ]);
  return (
    <details
      className={`${styles.panel} ${guided ? `${styles.guided} ${journey.collection}` : ""}`}
      open={guided || undefined}
    >
      <summary>
        <Database size={19} aria-hidden="true" />
        <div className={styles.heading}>
          <strong>Migration files &amp; images</strong>
          <small>
            {fixedScope
              ? "Collect files and images for the saved namespace scope."
              : "Choose namespaces, collect artifacts, resolve missing items."}
          </small>
        </div>
        <span className={styles.storage}>
          <ShieldCheck size={14} aria-hidden="true" /> Private S3 workspace
        </span>
        <ChevronDown className={styles.chevron} size={18} aria-hidden="true" />
      </summary>
      <div className={styles.content}>
        {guided && !fixedScope && !workspaces.length && (
          <ol
            className={styles.collectionSteps}
            aria-label="Artifact preparation sequence"
          >
            <li>
              <b>1. Choose namespaces</b>
              <span>Collection scope only</span>
            </li>
            <li>
              <b>2. Create workspace</b>
              <span>Build the artifact index</span>
            </li>
            <li>
              <b>3. Collect & resolve</b>
              <span>Save files and images to S3</span>
            </li>
            <li>
              <b>4. Review & export</b>
              <span>Create the versioned manifest</span>
            </li>
          </ol>
        )}
        {!fixedScope && (
          <NamespaceChooser
            className={
              guided
                ? `${styles.namespaceChooser} ${journey.workspaceChooser}`
                : undefined
            }
            {...(guided ? { open: !workspaces.length || undefined } : {})}
          >
            {guided && (
              <summary>
                {workspaces.length
                  ? "Create another workspace"
                  : "Choose namespaces to collect"}
              </summary>
            )}
            <div className={styles.intro}>
              <div>
                <strong>Namespaces to collect</strong>
                <p>
                  Select namespaces to list their required deployment files and
                  container images. This does not select the migration execution
                  scope.
                </p>
              </div>
              <span className={styles.selectionCount} role="status">
                {scope.length} of {namespaces.length} selected
              </span>
            </div>
            <fieldset disabled={busy || !canEdit} className={styles.scope}>
              <legend>Namespaces to include</legend>
              <div className={styles.scopeToolbar}>
                <label className={styles.search}>
                  <Search size={15} aria-hidden="true" />
                  <input
                    type="search"
                    aria-label="Search namespaces"
                    placeholder="Find a namespace…"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                </label>
                <button type="button" onClick={() => setSelected(namespaces)}>
                  Select all
                </button>
                <button
                  type="button"
                  disabled={!scope.length}
                  onClick={() => setSelected([])}
                >
                  Clear selection
                </button>
              </div>
              <div className={styles.namespaces}>
                {visibleNamespaces.map((ns) => (
                  <label
                    key={ns}
                    className={
                      selected.includes(ns)
                        ? styles.selectedNamespace
                        : undefined
                    }
                  >
                    <input
                      type="checkbox"
                      checked={selected.includes(ns)}
                      onChange={(e) =>
                        setSelected((items) =>
                          e.target.checked
                            ? [...items, ns]
                            : items.filter((item) => item !== ns),
                        )
                      }
                    />
                    <span>{ns}</span>
                  </label>
                ))}
              </div>
              {!visibleNamespaces.length && (
                <p className={styles.hint}>
                  {namespaces.length
                    ? "No namespaces match your search."
                    : "No namespaces discovered yet."}
                </p>
              )}
            </fieldset>
            <div className={styles.actions}>
              <button
                className={styles.primary}
                type="button"
                disabled={busy || !canEdit || !inventoryDigest || !scope.length}
                onClick={() => run(true)}
              >
                Create workspace
              </button>

              <span className={styles.hint}>
                Creates an artifact list. Collection starts separately.
              </span>
              {busy && <span role="status">Saving or loading workspace…</span>}
            </div>
            {guided && !scope.length && (
              <p className={styles.hint}>
                Select at least one namespace to enable Create workspace.
              </p>
            )}
          </NamespaceChooser>
        )}
        {fixedScope ? (
          <section
            className={styles.workspaceToolbar}
            aria-label="Artifact workspace controls"
          >
            <div className={styles.toolbarHeading}>
              <Database size={18} aria-hidden="true" />
              <div>
                <h3>Artifact workspace</h3>
                <p>Saved namespaces: {namespaces.join(", ") || "None"}</p>
              </div>
            </div>
            <div
              className={styles.toolbarActions}
              role="toolbar"
              aria-label="Workspace actions"
            >
              {stage !== "review" && (
                <button
                  className={styles.primary}
                  type="button"
                  disabled={
                    busy ||
                    !loaded ||
                    !canEdit ||
                    !inventoryDigest ||
                    !scope.length ||
                    Boolean(existingWorkspace)
                  }
                  onClick={() => run(true)}
                >
                  Create workspace
                </button>
              )}
              <button type="button" disabled={busy} onClick={() => run(false)}>
                <RefreshCw size={13} aria-hidden="true" />
                {loaded ? "Refresh workspaces" : "Load workspaces"}
              </button>
              {activeWorkspace &&
                stage !== "review" &&
                collectionButtons(activeWorkspace)}
              {activeWorkspace && exportButton(activeWorkspace)}
              {activeWorkspace && downloadExport(activeWorkspace)}
            </div>
            {activeWorkspace && exportFeedback(activeWorkspace)}
            <p className={styles.toolbarHint}>
              {existingWorkspace
                ? "Workspace already created for this assessment and saved namespace scope."
                : !loaded
                  ? "Checking existing workspaces before creation…"
                  : "Create the workspace, then collect available files and images."}
            </p>
          </section>
        ) : (
          <div
            className={`${styles.savedHeading} ${guided ? journey.collectionHeading : ""}`}
          >
            <h3>Saved workspaces</h3>
            <button type="button" disabled={busy} onClick={() => run(false)}>
              {loaded ? "Refresh workspaces" : "Load workspaces"}
            </button>
          </div>
        )}
        {refreshWarning && (
          <p role="status" className={styles.hint}>
            {refreshWarning}
          </p>
        )}
        {fixedScope && scopedWorkspaces.length > 1 && (
          <label className={styles.hint}>
            Workspace snapshot{" "}
            <select
              aria-label="Workspace snapshot"
              value={activeWorkspace?.workspaceId ?? ""}
              onChange={(e) => setActiveWorkspaceId(e.target.value)}
            >
              {scopedWorkspaces.map((w) => (
                <option key={w.workspaceId} value={w.workspaceId}>
                  {w.workspaceId} ·{" "}
                  {w.stale ? "Older inventory" : "Current inventory"}
                </option>
              ))}
            </select>
          </label>
        )}
        {!inventoryDigest && (
          <p>Complete source discovery before creating a workspace.</p>
        )}
        {error && <p role="alert">{error}</p>}
        {loaded && !visibleWorkspaces.length && (
          <p className={styles.empty}>
            {fixedScope
              ? "No workspace for this saved namespace scope. Create one to start collection."
              : "No saved workspaces yet. Select namespaces above to create one."}
          </p>
        )}
        {visibleWorkspaces.map((w) => {
          const artifactView =
            showCompleted[w.workspaceId] ??
            (stage === "review" ? "saved" : "all");
          const saved = w.artifacts.filter(
            (a) => a.status === "COLLECTED",
          ).length;
          const available = w.artifacts.filter(
            (a) => a.status === "PENDING_COLLECTION",
          ).length;
          const historical = w.artifacts.filter(
            (a) => a.status === "EXCLUDED_FROM_REPLAY",
          ).length;
          const required = w.artifacts.length - historical;
          const attention = required - saved - available;
          const pendingJobs = (w.jobs ?? []).some((job) =>
            ["QUEUED", "RUNNING"].includes(job.status),
          );
          const exportReady =
            required > 0 && saved === required && !pendingJobs && !w.stale;
          return (
            <div
              className={`${styles.workspace} ${guided ? journey.collectionWorkspace : ""}`}
              key={w.workspaceId}
            >
              <div className={styles.workspaceHeading}>
                <strong>{w.namespaces.join(", ")}</strong>
                <span className={styles.badge}>
                  {w.stale
                    ? "Older inventory snapshot · Create a new workspace"
                    : pendingJobs || collectionInProgress(w)
                      ? "Artifact collection queued or running"
                      : saved > 0 && saved === required
                        ? "All required artifacts saved · Review before deployment"
                        : w.status === "COLLECTING"
                          ? "Artifact collection queued or running"
                          : w.status === "FAILED"
                            ? "Collection failed · Review details"
                            : w.status === "PARTIAL"
                              ? "Partially collected"
                              : "Workspace index created"}
                </span>
              </div>
              {guided && (
                <>
                  <ol
                    hidden={Boolean(stage)}
                    className={journey.collectionPipeline}
                    aria-label="Workspace preparation progress"
                  >
                    <li data-state="done">
                      1. Workspace<small>Index created</small>
                    </li>
                    <li
                      data-state={
                        pendingJobs || available > 0
                          ? "active"
                          : saved > 0 && saved === required
                            ? "done"
                            : "pending"
                      }
                    >
                      2. Collect
                      <small>
                        {pendingJobs ? "Jobs in progress" : `${saved} saved`}
                      </small>
                    </li>
                    <li data-state={attention > 0 ? "attention" : "pending"}>
                      3. Resolve<small>{attention} need attention</small>
                    </li>
                    <li data-state={exportReady ? "active" : "pending"}>
                      4. Export
                      <small>{exportReady ? "Available" : "Not ready"}</small>
                    </li>
                  </ol>
                  <div className={journey.collectionProgress}>
                    <span>
                      {required ? Math.floor((saved / required) * 100) : 0}%
                      complete · {saved} of {required} required artifacts saved
                    </span>
                    <progress
                      value={saved}
                      max={Math.max(required, 1)}
                      aria-label={`Collection progress for ${w.namespaces.join(", ")}`}
                      title="Percentage of required artifacts saved to S3, not bytes transferred."
                    />
                    <small>Target readiness not verified</small>
                    {collectionInProgress(w) && (
                      <small className={styles.liveStatus}>
                        <LoaderCircle
                          size={13}
                          className={styles.spinning}
                          aria-hidden="true"
                        />{" "}
                        Copying or queued · updates every 5 seconds
                      </small>
                    )}
                  </div>
                </>
              )}
              <div
                className={styles.metrics}
                aria-label="Artifact collection progress"
              >
                <div>
                  <strong>{required}</strong>
                  <span>Required artifacts</span>
                </div>
                <div>
                  <strong>{saved}</strong>
                  <span>Saved to S3</span>
                </div>
                <div>
                  <strong>{available}</strong>
                  <span>Awaiting collection</span>
                </div>
                <div>
                  <strong>{attention}</strong>
                  <span>Needs attention</span>
                </div>
              </div>
              <small hidden={guided}>
                {saved} / {required} artifacts collected · Target readiness not
                verified
              </small>
              {historical > 0 && (
                <p>
                  {historical} historical Job run{historical === 1 ? "" : "s"}{" "}
                  excluded from replay · {w.artifacts.length} artifacts
                  originally listed. Review receipts are retained in S3.
                </p>
              )}
              <h3 hidden={stage === "review"} className={styles.stageHeading}>
                Collect files & images
              </h3>
              {!fixedScope && stage !== "review" && (
                <div className={styles.actions}>{collectionButtons(w)}</div>
              )}
              {!fixedScope && (
                <>
                  {exportButton(w)}
                  {downloadExport(w)}
                  {exportFeedback(w)}
                </>
              )}
              <details
                open={guided || undefined}
                className={guided ? journey.artifactList : undefined}
              >
                <summary>
                  {guided
                    ? "Files, images & copy progress"
                    : "View required files, images & status"}
                </summary>
                {guided &&
                  (artifactView === "saved" ||
                    Boolean(
                      workspaceLocation(w, exports[w.workspaceId]?.result),
                    )) && (
                    <div className={styles.s3Summary}>
                      <strong>Workspace S3 folder</strong>
                      {workspaceLocation(w, exports[w.workspaceId]?.result) ? (
                        <code>
                          {workspaceLocation(w, exports[w.workspaceId]?.result)}
                        </code>
                      ) : (
                        <small>
                          Create an export manifest to display the workspace
                          location.
                        </small>
                      )}
                      <small>
                        The export manifest lists exact object paths and
                        historical review receipts.
                      </small>
                    </div>
                  )}
                {guided && (
                  <div className={journey.artifactFilters}>
                    <button
                      type="button"
                      aria-pressed={artifactView === "all"}
                      onClick={() =>
                        setShowCompleted((v) => ({
                          ...v,
                          [w.workspaceId]: "all",
                        }))
                      }
                    >
                      All artifacts ({w.artifacts.length})
                    </button>
                    <button
                      type="button"
                      aria-pressed={artifactView === "remaining"}
                      onClick={() =>
                        setShowCompleted((v) => ({
                          ...v,
                          [w.workspaceId]: "remaining",
                        }))
                      }
                    >
                      Remaining ({required - saved})
                    </button>
                    <button
                      type="button"
                      aria-pressed={artifactView === "saved"}
                      onClick={() =>
                        setShowCompleted((v) => ({
                          ...v,
                          [w.workspaceId]: "saved",
                        }))
                      }
                    >
                      Saved / excluded ({saved + historical})
                    </button>
                  </div>
                )}
                <div className={styles.tableScroll}>
                  <table className={styles.artifactTable}>
                    <thead>
                      <tr>
                        <th scope="col">Artifact</th>
                        <th scope="col">Source</th>
                        <th scope="col">Copy progress</th>
                        <th scope="col">Next step / status</th>
                        <th scope="col">S3 location</th>
                      </tr>
                    </thead>
                    <tbody>
                      {w.artifacts
                        .filter(
                          (a) =>
                            !guided ||
                            artifactView === "all" ||
                            (artifactView === "saved"
                              ? ["COLLECTED", "EXCLUDED_FROM_REPLAY"].includes(
                                  a.status,
                                )
                              : !["COLLECTED", "EXCLUDED_FROM_REPLAY"].includes(
                                  a.status,
                                )),
                        )
                        .map((a) => (
                          <tr key={a.artifactId}>
                            <td>
                              {a.source?.reference ||
                                a.source?.filePath ||
                                (a.source?.resource
                                  ? `${a.source.resource.namespace} / ${a.source.resource.kind} / ${a.source.resource.name}`
                                  : "") ||
                                (a.source?.release
                                  ? `${a.source.namespace} / ${a.source.release}`
                                  : "") ||
                                artifactKind(a.kind)}
                              {a.source?.repository && (
                                <small className={styles.artifactMeta}>
                                  {a.source.repository}
                                </small>
                              )}
                            </td>
                            <td>
                              <ArtifactOrigin artifact={a} />
                            </td>
                            <td>
                              <TransferProgress
                                artifact={a}
                                job={(w.jobs ?? []).find(
                                  (job) => job.artifactId === a.artifactId,
                                )}
                              />
                            </td>
                            <td>
                              {collectionStatus(
                                a,
                                (w.jobs ?? []).find(
                                  (job) => job.artifactId === a.artifactId,
                                ),
                              )}
                              {a.validation?.reviewRequired &&
                                a.status === "COLLECTED" && (
                                  <small>
                                    {" "}
                                    · Recovered copy: review configuration and
                                    dependencies before deployment.
                                  </small>
                                )}
                              {a.validation?.recovery?.message &&
                                a.status !== "COLLECTED" && (
                                  <small>
                                    {" "}
                                    · {a.validation.recovery.message}
                                  </small>
                                )}
                              {["LIVE_DEFINITION", "HELM_RELEASE"].includes(
                                a.kind,
                              ) &&
                                !["COLLECTED", "EXCLUDED_FROM_REPLAY"].includes(
                                  a.status,
                                ) && (
                                  <button
                                    type="button"
                                    disabled={busy || !canEdit || w.stale}
                                    onClick={() =>
                                      recover(
                                        w.workspaceId,
                                        a.artifactId,
                                        a.validation?.recovery,
                                      )
                                    }
                                  >
                                    {busy &&
                                    recoveryFeedback?.workspaceId ===
                                      w.workspaceId &&
                                    recoveryFeedback.artifactId === a.artifactId
                                      ? "Contacting recovery service…"
                                      : a.validation?.recovery?.status ===
                                          "RECOVERING"
                                        ? "Check recovery progress"
                                        : a.kind === "LIVE_DEFINITION"
                                          ? "Export live definition"
                                          : "Recover Helm release"}
                                  </button>
                                )}
                              {a.kind === "IMAGE" &&
                                a.status === "ACCESS_REQUIRED" &&
                                onReviewAccess && (
                                  <button
                                    type="button"
                                    disabled={busy}
                                    onClick={onReviewAccess}
                                  >
                                    Review registry access
                                  </button>
                                )}
                              {a.validation?.historicalReview && (
                                <small>
                                  {" "}
                                  · Reviewed parent:{" "}
                                  {
                                    a.validation.historicalReview.parent
                                      .namespace
                                  }{" "}
                                  / {a.validation.historicalReview.parent.name}.
                                  Former ownership is operator-confirmed; target
                                  readiness is not verified.
                                </small>
                              )}
                              {a.kind === "LIVE_DEFINITION" &&
                                a.source?.resource?.kind === "Job" &&
                                a.status === "RECOVERY_REQUIRED" &&
                                a.validation?.recovery?.status ===
                                  "CUSTOMER_INPUT_REQUIRED" && (
                                  <details>
                                    <summary>Review deleted Job run</summary>
                                    <p>
                                      Use this after checking that the Job was
                                      deleted and identifying its parent
                                      CronJob. Your review excludes this
                                      historical run from replay and keeps the
                                      failed-export evidence.
                                    </p>
                                    <label>
                                      Saved parent CronJob
                                      <select
                                        disabled={busy || !canEdit || w.stale}
                                        value={
                                          historicalReviews[
                                            `${w.workspaceId}/${a.artifactId}`
                                          ]?.parent ?? ""
                                        }
                                        onChange={(event) =>
                                          setHistoricalReviews((items) => ({
                                            ...items,
                                            [`${w.workspaceId}/${a.artifactId}`]:
                                              {
                                                parent: event.target.value,
                                                confirmed: false,
                                              },
                                          }))
                                        }
                                      >
                                        <option value="">
                                          Select the saved CronJob definition
                                        </option>
                                        {w.artifacts
                                          .filter(
                                            (candidate) =>
                                              [
                                                "REPOSITORY_DEFINITION",
                                                "LIVE_DEFINITION",
                                              ].includes(candidate.kind) &&
                                              candidate.status === "COLLECTED",
                                          )
                                          .flatMap((candidate) =>
                                            (candidate.workloads ?? [])
                                              .filter(
                                                (link) =>
                                                  link.kind === "CronJob" &&
                                                  link.namespace ===
                                                    a.source?.resource
                                                      ?.namespace,
                                              )
                                              .map((link) => (
                                                <option
                                                  key={`${candidate.artifactId}/${link.name}`}
                                                  value={JSON.stringify({
                                                    artifactId:
                                                      candidate.artifactId,
                                                    name: link.name,
                                                  })}
                                                >
                                                  {link.name} ·{" "}
                                                  {candidate.source?.filePath ??
                                                    "Live definition"}
                                                </option>
                                              )),
                                          )}
                                      </select>
                                    </label>
                                    <label>
                                      <input
                                        type="checkbox"
                                        disabled={
                                          busy ||
                                          !canEdit ||
                                          w.stale ||
                                          !historicalReviews[
                                            `${w.workspaceId}/${a.artifactId}`
                                          ]?.parent
                                        }
                                        checked={
                                          historicalReviews[
                                            `${w.workspaceId}/${a.artifactId}`
                                          ]?.confirmed ?? false
                                        }
                                        onChange={(event) =>
                                          setHistoricalReviews((items) => ({
                                            ...items,
                                            [`${w.workspaceId}/${a.artifactId}`]:
                                              {
                                                ...items[
                                                  `${w.workspaceId}/${a.artifactId}`
                                                ],
                                                confirmed: event.target.checked,
                                              },
                                          }))
                                        }
                                      />
                                      I checked that this is a deleted
                                      historical run of the selected CronJob.
                                    </label>
                                    <button
                                      type="button"
                                      disabled={
                                        busy ||
                                        !canEdit ||
                                        w.stale ||
                                        !historicalReviews[
                                          `${w.workspaceId}/${a.artifactId}`
                                        ]?.confirmed
                                      }
                                      onClick={() =>
                                        excludeHistoricalJob(
                                          w.workspaceId,
                                          a.artifactId,
                                        )
                                      }
                                    >
                                      Record historical exclusion
                                    </button>
                                  </details>
                                )}
                              {recoveryFeedback?.workspaceId ===
                                w.workspaceId &&
                                recoveryFeedback.artifactId ===
                                  a.artifactId && (
                                  <p
                                    role={
                                      recoveryFeedback.failed
                                        ? "alert"
                                        : "status"
                                    }
                                    aria-live="polite"
                                  >
                                    {recoveryFeedback.message}
                                  </p>
                                )}
                              {a.validation?.platforms?.length ? (
                                <small>
                                  {" "}
                                  · Available platforms:{" "}
                                  {a.validation.platforms.join(", ")} · Target
                                  compatibility not verified
                                </small>
                              ) : null}
                            </td>
                            <td className={styles.s3Location}>
                              {["COLLECTED", "EXCLUDED_FROM_REPLAY"].includes(
                                a.status,
                              ) ? (
                                <>
                                  {a.storage?.bucket && a.storage.key ? (
                                    <code>{`s3://${a.storage.bucket}/${a.storage.key}`}</code>
                                  ) : (
                                    <small>
                                      {workspaceLocation(
                                        w,
                                        exports[w.workspaceId]?.result,
                                      )
                                        ? "In workspace folder · exact path in export manifest"
                                        : "Create export to view location"}
                                    </small>
                                  )}
                                </>
                              ) : (
                                <small>Not saved to S3 yet</small>
                              )}
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                  {guided &&
                    artifactView === "remaining" &&
                    required === saved && (
                      <p className={styles.hint}>
                        All required artifacts are saved. Review saved items
                        before exporting.
                      </p>
                    )}
                </div>
              </details>
            </div>
          );
        })}
        <details className={styles.collectionHelp}>
          <summary>How collection and recovery work</summary>
          <p>
            Collection includes artifacts across these namespaces. Migration
            execution remains limited to your saved workloads.
          </p>
          <p className={styles.footer}>
            Collection jobs run in the background and require a running
            collector. Active jobs update automatically; Refresh workspaces
            checks manually. Missing items need recovery before migration. Live
            definitions and retained Helm data use the approved source SSM host.
            They may contain sensitive configuration and require review. Use
            Check recovery progress until the file is saved to S3.
          </p>
        </details>
      </div>
    </details>
  );
}

type Artifact = Workspace["artifacts"][number];
type CollectionJob = NonNullable<Workspace["jobs"]>[number];

function collectionStatus(artifact: Artifact, job?: CollectionJob) {
  if (["COLLECTED", "EXCLUDED_FROM_REPLAY"].includes(artifact.status))
    return artifactStatus(artifact.status);
  if (job?.status === "RUNNING") return "Copy in progress";
  if (job?.status === "QUEUED") return "Waiting for collector";
  if (job?.status === "FAILED") return "Retry collection";
  if (job?.status === "SUCCEEDED") return "Verifying saved copy";
  return artifactStatus(artifact.status);
}

function collectionInProgress(workspace: Workspace) {
  return (
    (workspace.jobs ?? []).some((job) =>
      ["QUEUED", "RUNNING"].includes(job.status),
    ) ||
    workspace.artifacts.some(
      (artifact) =>
        artifact.status === "RECOVERING" ||
        ["QUEUED", "RUNNING"].includes(
          artifact.validation?.recovery?.status ?? "",
        ),
    )
  );
}

function workspaceCounts(workspace: Workspace) {
  const saved = workspace.artifacts.filter(
    (a) => a.status === "COLLECTED",
  ).length;
  const available = workspace.artifacts.filter(
    (a) => a.status === "PENDING_COLLECTION",
  ).length;
  const required = workspace.artifacts.filter(
    (a) => a.status !== "EXCLUDED_FROM_REPLAY",
  ).length;
  return {
    saved,
    available,
    required,
    attention: required - saved - available,
  };
}

function ArtifactOrigin({ artifact }: { artifact: Artifact }) {
  const origin =
    artifact.kind === "REPOSITORY_DEFINITION"
      ? { label: "GitHub", Icon: Github, tone: "github" }
      : artifact.kind === "IMAGE"
        ? { label: "Container registry", Icon: Container, tone: "registry" }
        : artifact.kind === "HELM_RELEASE"
          ? { label: "Source cluster · Helm", Icon: Layers, tone: "cluster" }
          : {
              label: "Source cluster · Live export",
              Icon: FileCode2,
              tone: "cluster",
            };
  return (
    <span className={styles.origin} data-source={origin.tone}>
      <origin.Icon size={15} aria-hidden="true" />
      {origin.label}
    </span>
  );
}

function TransferProgress({
  artifact,
  job,
}: {
  artifact: Artifact;
  job?: CollectionJob;
}) {
  const saved = artifact.status === "COLLECTED";
  const excluded = artifact.status === "EXCLUDED_FROM_REPLAY";
  const recovery = artifact.validation?.recovery?.status;
  const running =
    !saved &&
    !excluded &&
    (job?.status === "RUNNING" ||
      artifact.status === "RECOVERING" ||
      ["QUEUED", "RUNNING"].includes(recovery ?? ""));
  const verifying =
    !saved && !excluded && !running && job?.status === "SUCCEEDED";
  const failed = !saved && !excluded && !running && job?.status === "FAILED";
  const queued = !saved && !excluded && !running && job?.status === "QUEUED";
  const label = saved
    ? "100% · Saved to S3"
    : excluded
      ? "Excluded from replay"
      : running
        ? artifact.kind === "IMAGE"
          ? "Copying image to S3"
          : "Copying definition to S3"
        : verifying
          ? "Verifying saved copy"
          : failed
            ? "Copy failed · Retry required"
            : queued
              ? "Queued · Waiting for collector"
              : artifact.status === "PENDING_COLLECTION"
                ? "Ready to copy"
                : "Source action required";
  return (
    <div
      className={styles.transfer}
      data-state={saved ? "saved" : failed ? "failed" : "pending"}
    >
      <span>
        {saved ? (
          <CheckCircle2 size={13} aria-hidden="true" />
        ) : running || verifying ? (
          <LoaderCircle
            size={13}
            className={styles.spinning}
            aria-hidden="true"
          />
        ) : null}
        {label}
      </span>
      {!excluded && (
        <progress
          className={styles.transferBar}
          max={100}
          value={running || verifying ? undefined : saved ? 100 : 0}
          aria-label={`Copy progress for ${artifact.source?.reference || artifact.source?.filePath || artifact.source?.resource?.name || artifact.source?.release || artifact.artifactId}`}
          aria-valuetext={label}
        />
      )}
      {failed && job?.errorCode && (
        <small>{job.errorCode.toLowerCase().replaceAll("_", " ")}</small>
      )}
    </div>
  );
}

function artifactKind(kind: string) {
  return (
    (
      {
        IMAGE: "Container image",
        REPOSITORY_DEFINITION: "Repository file",
        LIVE_DEFINITION: "Cluster definition",
        HELM_RELEASE: "Helm release",
      } as Record<string, string>
    )[kind] ?? kind.toLowerCase().replaceAll("_", " ")
  );
}
function artifactStatus(status: string) {
  return (
    (
      {
        COLLECTED: "Saved to S3",
        PENDING_COLLECTION: "Ready to collect",
        EXPORT_REQUIRED: "Export definition from source cluster",
        RECOVERY_REQUIRED: "Missing at source · Recovery required",
        RECOVERY_REVIEW_REQUIRED: "Recover retained Helm data",
        RECOVERING: "Recovery in progress",
        EXCLUDED_FROM_REPLAY: "Historical run · Excluded from replay",
        ACCESS_REQUIRED: "Connect source or check permissions",
        DIGEST_REQUIRED: "Identify the running image version",
        CHECK_REQUIRED: "Check source availability",
      } as Record<string, string>
    )[status] ?? status.toLowerCase().replaceAll("_", " ")
  );
}

function workspaceLocation(workspace: Workspace, exported?: WorkspaceExport) {
  if (
    workspace.storage?.bucket &&
    (workspace.storage.prefix || workspace.storage.key)
  )
    return `s3://${workspace.storage.bucket}/${workspace.storage.prefix || workspace.storage.key}`;
  if (!exported?.storage.bucket || !exported.storage.key) return null;
  const marker = exported.storage.key.lastIndexOf("/exports/");
  return marker < 0
    ? null
    : `s3://${exported.storage.bucket}/${exported.storage.key.slice(0, marker + 1)}`;
}
