"use client";
import { useState } from "react";
import { ChevronDown, Database, Search, ShieldCheck } from "lucide-react";
import {
  apiClient,
  normalizeApiError,
  writeHeaders,
} from "@/shared/api/client";
import styles from "./artifact-workspace-panel.module.css";
type Recovery = { jobId: string; status: string; message?: string };
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
  jobs?: {
    jobId: string;
    status: string;
    attempts: number;
    errorCode?: string;
  }[];
  artifacts: {
    artifactId: string;
    kind: string;
    status: string;
    workloads?: Workload[];
    source?: {
      reference?: string;
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
}: {
  migrationId: string;
  version: number;
  inventoryDigest?: string;
  namespaces: string[];
  canEdit: boolean;
}) {
  const [query, setQuery] = useState("");
  const [historicalReviews, setHistoricalReviews] = useState<
    Record<string, { parent: string; confirmed: boolean }>
  >({});
  const [selected, setSelected] = useState<string[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [recoveryFeedback, setRecoveryFeedback] = useState<{
    workspaceId: string;
    artifactId: string;
    pending: boolean;
    failed: boolean;
    message: string;
  } | null>(null);
  async function run(create: boolean) {
    setBusy(true);
    setError("");
    try {
      if (create) {
        const { data } = await apiClient.post(
          `/migrations/${migrationId}/artifact-workspaces`,
          {
            version,
            inventoryDigest,
            namespaces: selected.filter((ns) => namespaces.includes(ns)),
          },
          { headers: writeHeaders({ key: crypto.randomUUID(), version }) },
        );
        setWorkspaces((items) => [data, ...items]);
      } else {
        const { data } = await apiClient.get(
          `/migrations/${migrationId}/artifact-workspaces`,
        );
        setWorkspaces(data.workspaces);
      }
      setLoaded(true);
    } catch (e) {
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
  const scope = selected.filter((ns) => namespaces.includes(ns));
  const visibleNamespaces = namespaces.filter((ns) =>
    ns.toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <details className={styles.panel}>
      <summary>
        <Database size={19} aria-hidden="true" />
        <div className={styles.heading}>
          <strong>Migration files &amp; images</strong>
          <small>
            Choose namespaces, collect artifacts, resolve missing items.
          </small>
        </div>
        <span className={styles.storage}>
          <ShieldCheck size={14} aria-hidden="true" /> Private S3 workspace
        </span>
        <ChevronDown className={styles.chevron} size={18} aria-hidden="true" />
      </summary>
      <div className={styles.content}>
        <div className={styles.intro}>
          <div>
            <strong>Choose what to migrate</strong>
            <p>
              Select namespaces to list their required deployment files and
              container images.
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
                  selected.includes(ns) ? styles.selectedNamespace : undefined
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
          <button type="button" disabled={busy} onClick={() => run(false)}>
            {loaded ? "Refresh workspaces" : "Load workspaces"}
          </button>
          <span className={styles.hint}>
            Creates an artifact list. Collection starts separately.
          </span>
          {busy && <span role="status">Saving or loading workspace…</span>}
        </div>
        {!inventoryDigest && (
          <p>Complete source discovery before creating a workspace.</p>
        )}
        {error && <p role="alert">{error}</p>}
        {loaded && !workspaces.length && (
          <p className={styles.empty}>
            No saved workspaces yet. Select namespaces above to create one.
          </p>
        )}
        {workspaces.map((w) => {
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
          return (
            <div className={styles.workspace} key={w.workspaceId}>
              <div className={styles.workspaceHeading}>
                <strong>{w.namespaces.join(", ")}</strong>
                <span className={styles.badge}>
                  {w.stale
                    ? "Older inventory snapshot · Create a new workspace"
                    : saved > 0 && saved === required
                      ? "All required artifacts saved · Review before deployment"
                      : w.status === "COLLECTING"
                        ? "Artifact collection queued or running"
                        : w.status === "FAILED"
                          ? "Collection failed · Review details"
                          : w.status === "PARTIAL"
                            ? "Partially collected"
                            : w.status === "COLLECTED" ||
                                w.status === "VALIDATED"
                              ? "Collection complete"
                              : "Workspace index created"}
                </span>
              </div>
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
              <small>
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
              <div className={styles.actions}>
                <button
                  type="button"
                  disabled={
                    busy ||
                    !canEdit ||
                    w.stale ||
                    w.status === "COLLECTING" ||
                    !w.artifacts.some(
                      (a) =>
                        a.kind === "REPOSITORY_DEFINITION" &&
                        a.status !== "COLLECTED",
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
                      (a) =>
                        a.kind === "IMAGE" && a.status === "PENDING_COLLECTION",
                    )
                  }
                  onClick={() => collect(w.workspaceId, "IMAGE")}
                >
                  Collect / retry available images
                </button>
              </div>
              {(w.jobs ?? []).map((job) => (
                <small key={job.jobId}>
                  {job.status.toLowerCase()} · Attempt {job.attempts}
                  {job.errorCode
                    ? ` · ${job.errorCode.toLowerCase().replaceAll("_", " ")}`
                    : ""}
                </small>
              ))}
              <details>
                <summary>View required files, images &amp; status</summary>
                <div className={styles.tableScroll}>
                  <table className={styles.artifactTable}>
                    <thead>
                      <tr>
                        <th scope="col">Artifact</th>
                        <th scope="col">Type</th>
                        <th scope="col">Next step / status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {w.artifacts.map((a) => (
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
                          </td>
                          <td>{artifactKind(a.kind)}</td>
                          <td>
                            {artifactStatus(a.status)}
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
                            {a.validation?.historicalReview && (
                              <small>
                                {" "}
                                · Reviewed parent:{" "}
                                {
                                  a.validation.historicalReview.parent.namespace
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
                                    deleted and identifying its parent CronJob.
                                    Your review excludes this historical run
                                    from replay and keeps the failed-export
                                    evidence.
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
                                                  a.source?.resource?.namespace,
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
                                    I checked that this is a deleted historical
                                    run of the selected CronJob.
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
                            {recoveryFeedback?.workspaceId === w.workspaceId &&
                              recoveryFeedback.artifactId === a.artifactId && (
                                <p
                                  role={
                                    recoveryFeedback.failed ? "alert" : "status"
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
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            </div>
          );
        })}
        <p className={styles.footer}>
          Collection jobs run in the background and require a running collector.
          Refresh workspaces to check progress. Missing items need recovery
          before migration. Live definitions and retained Helm data use the
          approved source SSM host. They may contain sensitive configuration and
          require review. Use Check recovery progress until the file is saved to
          S3.
        </p>
      </div>
    </details>
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
