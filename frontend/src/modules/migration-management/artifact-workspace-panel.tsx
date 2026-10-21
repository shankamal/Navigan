"use client";
import { useState } from "react";
import { Database } from "lucide-react";
import {
  apiClient,
  normalizeApiError,
  writeHeaders,
} from "@/shared/api/client";
import styles from "./artifact-workspace-panel.module.css";
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
  artifacts: { artifactId: string; kind: string; status: string }[];
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
  const [selected, setSelected] = useState<string[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
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
  async function collect(workspaceId: string) {
    setBusy(true);
    setError("");
    try {
      const { data } = await apiClient.post(
        `/migrations/${migrationId}/artifact-workspaces/${workspaceId}/collection-jobs`,
        { version },
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
  return (
    <details className={styles.panel}>
      <summary>
        <Database size={16} /> Artifact workspace{" "}
        <span>Private S3 storage</span>
      </summary>
      <div className={styles.content}>
        <p>
          Create a workspace index for selected namespaces. The index records
          which deployment definitions and images are needed. Then collect
          repository files. Images and missing definitions require separate
          collection or recovery.
        </p>
        <fieldset disabled={busy || !canEdit}>
          <legend>Namespaces to include</legend>
          <div className={styles.namespaces}>
            {namespaces.map((ns) => (
              <label key={ns}>
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
                {ns}
              </label>
            ))}
          </div>
        </fieldset>
        <div className={styles.actions}>
          <button
            type="button"
            disabled={
              busy ||
              !canEdit ||
              !inventoryDigest ||
              !selected.some((ns) => namespaces.includes(ns))
            }
            onClick={() => run(true)}
          >
            Create workspace index
          </button>
          <button type="button" disabled={busy} onClick={() => run(false)}>
            {loaded ? "Refresh workspaces" : "Load workspaces"}
          </button>
          {busy && <span role="status">Saving or loading workspace…</span>}
        </div>
        {!inventoryDigest && (
          <p>Complete source discovery before creating a workspace.</p>
        )}
        {error && <p role="alert">{error}</p>}
        {loaded && !workspaces.length && (
          <p>No artifact workspaces have been created.</p>
        )}
        {workspaces.map((w) => (
          <div className={styles.workspace} key={w.workspaceId}>
            <strong>{w.namespaces.join(", ")}</strong>
            <span>
              {w.stale
                ? "Older inventory snapshot · Create a new workspace"
                : w.status === "COLLECTING"
                  ? "Repository collection queued or running"
                  : "Workspace index created"}
            </span>
            <small>
              {w.collectedArtifactCount ?? 0} / {w.artifacts.length} artifacts
              collected · Target readiness not verified
            </small>
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
              <summary>Artifact status</summary>
              <ul>
                {w.artifacts.map((a) => (
                  <li key={a.artifactId}>
                    {a.kind.toLowerCase().replaceAll("_", " ")} —{" "}
                    {a.status.toLowerCase().replaceAll("_", " ")}
                  </li>
                ))}
              </ul>
            </details>
          </div>
        ))}
      </div>
    </details>
  );
}
