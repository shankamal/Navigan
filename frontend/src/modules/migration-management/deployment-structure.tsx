"use client";
import { useEffect, useState } from "react";
import {
  Box,
  GitBranch,
  FileCode2,
  Database,
  Copy,
  Check,
  AlertTriangle,
  ChevronRight,
  Download,
  LoaderCircle,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import {
  deploymentDiscovery,
  type DeploymentWorkloadEvidence,
  type RecoveryJob,
  type RecoveryRequest,
} from "./deployment-evidence-service";
import { normalizeApiError } from "@/shared/api/client";
import { scopeKey } from "./source-migration-scope";
import { EvidenceDrawer } from "./evidence-drawer";
import styles from "./deployment-evidence-panel.module.css";

type Workload = DeploymentWorkloadEvidence;
function imageLabel(reference: string) {
  const [name, digest] = reference.split("@");
  const shortName = name.split("/").slice(-2).join("/");
  return digest ? `${shortName}@${digest.slice(0, 19)}…` : shortName;
}
function CopyValue({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);
  return (
    <>
      <button
        type="button"
        className={styles.copyValue}
        aria-label={`Copy ${value}`}
        title="Copy full value"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(value);
            setCopied(true);
            setFailed(false);
          } catch {
            setFailed(true);
          }
        }}
      >
        {copied ? <Check size={14} /> : <Copy size={14} />}
      </button>
      {failed && (
        <small role="status">
          Copy unavailable; select the displayed value.
        </small>
      )}
    </>
  );
}
export function ContainerImages({
  workload,
  onResolve,
}: {
  workload: Workload;
  onResolve?: (c: Workload["containers"][number]) => void;
}) {
  return (
    <div className={styles.imageEvidence}>
      <h4>
        Container images <span>({workload.containers.length})</span>
      </h4>
      <p>
        Declared references and observed Pod digests are separate evidence.
        Expand for full values.
      </p>
      {!workload.containers.length && (
        <p>No container image evidence was collected.</p>
      )}
      {workload.containers.map((c) => (
        <details
          key={`${c.containerType}/${c.name}`}
          className={styles.containerImage}
        >
          <summary>
            <Box size={17} />
            <span>
              <strong>{c.name}</strong>
              <small>
                {c.containerType === "INIT" || c.containerType === "init"
                  ? "Init container"
                  : "Container"}
              </small>
            </span>
            <span className={styles.imageReference} title={c.configuredImage}>
              {imageLabel(c.configuredImage)}
            </span>
            <span>
              <small>Runtime digest</small>
              {c.observedDigests.length
                ? `${c.observedDigests.length} observed`
                : "Not reported"}
            </span>
            <span>
              <small>Source registry</small>
              {c.registryEvidence?.status?.toLowerCase().replaceAll("_", " ") ||
                "Not checked"}
            </span>
            <ChevronRight size={16} />
          </summary>
          <dl className={styles.imageFacts}>
            <div>
              <dt>Declared image reference</dt>
              <dd>
                <code>{c.configuredImage}</code>
                <CopyValue value={c.configuredImage} />
              </dd>
            </div>
            <div>
              <dt>Declared digest</dt>
              <dd>
                <code>
                  {c.configuredImage.includes("@")
                    ? c.configuredImage.split("@")[1]
                    : "Tag reference — digest not declared"}
                </code>
              </dd>
            </div>
            <div>
              <dt>Observed runtime digests</dt>
              <dd>
                {c.observedDigests.length
                  ? c.observedDigests.map((d) => (
                      <p key={d}>
                        <code>{d}</code>
                        <CopyValue value={d} />
                      </p>
                    ))
                  : "Not reported by the collected runtime evidence"}
              </dd>
            </div>
            <div>
              <dt>Registry result</dt>
              <dd>
                {c.registryEvidence?.reason ||
                  (c.registryEvidence
                    ? `Registry metadata status: ${c.registryEvidence.status.toLowerCase().replaceAll("_", " ")}. This does not verify target pull access.`
                    : "Registry metadata has not been checked.")}
              </dd>
            </div>
          </dl>
          <p>
            {c.runningPodCount} observed Pods ·{" "}
            {c.multipleRunningVersions
              ? "Multiple runtime versions — choose the digest to recover."
              : "Image availability does not verify runtime health or target pull access."}
          </p>
          {onResolve && (
            <button onClick={() => onResolve(c)}>
              <Database size={14} />
              Resolve image artifact
            </button>
          )}
        </details>
      ))}
    </div>
  );
}
export function DeploymentStructure({
  workloads,
  onInspect,
  onResolve,
}: {
  workloads: Workload[];
  onInspect: (w: Workload) => void;
  onResolve: (w: Workload, container?: Workload["containers"][number]) => void;
}) {
  const [selected, setSelected] = useState("");
  const active =
    workloads.find((w) => scopeKey(w.workload) === selected) ??
    workloads.find((w) => w.candidates.length > 0) ??
    workloads[0];
  const namespaces = [
    ...new Set(workloads.map((w) => w.workload.namespace || "Cluster-scoped")),
  ].sort();
  return (
    <div className={styles.structureLayout}>
      <aside
        className={styles.workloadNavigator}
        aria-label="Deployment structure workloads"
      >
        <h3>Namespaces & workloads</h3>
        <small>{workloads.length} matching workload controllers</small>
        {namespaces.map((ns) => (
          <details
            key={ns}
            open={ns === (active?.workload.namespace || "Cluster-scoped")}
          >
            <summary>
              {ns}
              <small>
                {
                  workloads.filter(
                    (w) => (w.workload.namespace || "Cluster-scoped") === ns,
                  ).length
                }
              </small>
            </summary>
            {workloads
              .filter((w) => (w.workload.namespace || "Cluster-scoped") === ns)
              .map((w) => (
                <button
                  key={scopeKey(w.workload)}
                  aria-pressed={w === active}
                  onClick={() => setSelected(scopeKey(w.workload))}
                >
                  <Box size={17} />
                  <span>
                    {w.workload.name}
                    <small>{w.workload.kind}</small>
                  </span>
                </button>
              ))}
          </details>
        ))}
      </aside>
      {!active ? (
        <p>No workloads match these filters.</p>
      ) : (
        <article className={styles.structureStory}>
          <header>
            <Box size={25} />
            <div>
              <h3>How {active.workload.name} is defined</h3>
              <p>
                {active.workload.kind} ·{" "}
                {active.workload.namespace || "Cluster-scoped"}
              </p>
            </div>
          </header>
          <section>
            <h4>
              <Database size={18} />
              Observed workload
            </h4>
            <dl className={styles.evidenceFacts}>
              <div>
                <dt>Cluster snapshot</dt>
                <dd>
                  {active.clusterSnapshot
                    ? "Captured inventory available"
                    : "Not collected"}
                </dd>
              </div>
              <div>
                <dt>Runtime evidence</dt>
                <dd>{active.runtimeStatus.replaceAll("_", " ")}</dd>
              </div>
              <div>
                <dt>Reported application version</dt>
                <dd>{active.applicationVersion || "Not reported"}</dd>
              </div>
            </dl>
          </section>
          <section>
            <ContainerImages
              workload={active}
              onResolve={(c) => onResolve(active, c)}
            />
          </section>
          <section>
            <h4>
              <GitBranch size={18} />
              Deployment source
            </h4>
            <p className={styles.provenanceNote}>
              <AlertTriangle size={15} />
              Deployed Git revision unverified
            </p>
            {active.candidates.length ? (
              active.candidates.map((c) => (
                <div
                  className={styles.sourceCandidate}
                  key={`${c.repository}/${c.filePath}/${c.commit}`}
                >
                  <small>
                    {c.match === "USER_CONFIRMED"
                      ? "User-confirmed candidate"
                      : "Repository candidate"}
                  </small>
                  <strong>
                    <FileCode2 size={16} />
                    {c.filePath}
                  </strong>
                  <p>
                    {c.repository} · inspected commit{" "}
                    <code title={c.commit}>{c.commit.slice(0, 12)}</code>
                  </p>
                  {c.match === "NAMESPACE_UNSPECIFIED" && (
                    <small>
                      Namespace not specified in file. Runtime namespace is
                      shown above.
                    </small>
                  )}
                </div>
              ))
            ) : (
              <p>
                No original repository mapping.{" "}
                {active.clusterSnapshot
                  ? "A sanitized cluster snapshot is available for review."
                  : "Connect a repository or refresh source evidence."}
              </p>
            )}
            <dl className={styles.evidenceFacts}>
              <div>
                <dt>Artifact type</dt>
                <dd>
                  {active.artifactFormat === "Unresolved"
                    ? "Not detected"
                    : active.artifactFormat}
                </dd>
              </div>
              <div>
                <dt>Delivery tool</dt>
                <dd>
                  {active.deliveryTool === "Unresolved"
                    ? "Not detected"
                    : active.deliveryTool}
                </dd>
              </div>
              {active.helmRelease && (
                <div>
                  <dt>Helm release</dt>
                  <dd>
                    {active.helmRelease} ·{" "}
                    {active.helmChart || "Chart version not reported"}
                  </dd>
                </div>
              )}
            </dl>
            {active.helmRelease && (
              <button onClick={() => onResolve(active)}>
                Resolve Helm release artifact
              </button>
            )}
          </section>
          <footer>
            <button
              className={styles.primary}
              onClick={() => onInspect(active)}
            >
              Inspect evidence
            </button>
          </footer>
        </article>
      )}
    </div>
  );
}

export function ArtifactResolution({
  migrationId,
  version,
  inventoryDigest,
  workload,
  container,
  jobs,
  canEdit,
  onClose,
}: {
  migrationId: string;
  version: number;
  inventoryDigest?: string;
  workload: Workload;
  container?: Workload["containers"][number];
  jobs: RecoveryJob[];
  canEdit: boolean;
  onClose: () => void;
}) {
  const cache = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const matchingJobs = jobs.filter(
    (j) =>
      j.inventoryDigest === inventoryDigest &&
      scopeKey(j.workload) === scopeKey(workload.workload) &&
      j.kind === (container ? "IMAGE" : "HELM_RELEASE") &&
      (!container || j.containerName === container.name),
  );
  const [job, setJob] = useState<RecoveryJob | undefined>(matchingJobs.at(-1));
  const digests = container
    ? [
        ...new Set([
          ...container.observedDigests,
          ...(container.configuredImage.includes("@sha256:")
            ? [container.configuredImage.split("@")[1]]
            : []),
        ]),
      ]
    : [];
  const [digest, setDigest] = useState(digests.length === 1 ? digests[0] : "");
  async function request(operation: "START" | "POLL" | "DOWNLOAD") {
    setBusy(true);
    setError("");
    try {
      const action: RecoveryRequest =
        operation === "START"
          ? {
              operation,
              artifactKind: container ? "IMAGE" : "HELM_RELEASE",
              ...workload.workload,
              ...(container
                ? {
                    containerName: container.name,
                    containerType: container.containerType,
                    digest,
                  }
                : {}),
            }
          : { operation, jobId: job?.jobId };
      const result = await deploymentDiscovery.recover(
        migrationId,
        version,
        action,
      );
      setJob(result.job);
      if (result.downloadUrl) {
        const link = document.createElement("a");
        link.href = result.downloadUrl;
        link.rel = "noopener noreferrer";
        link.click();
      }
      if (result.job.status !== "RECOVERING")
        await cache.invalidateQueries({
          queryKey: ["deployment-evidence", migrationId],
        });
    } catch (failure) {
      setError(
        normalizeApiError(failure).message || "Recovery request failed.",
      );
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    if (job?.status !== "RECOVERING" || error) return;
    const timeout = setTimeout(() => {
      void request("POLL");
    }, 5000);
    return () => clearTimeout(timeout);
    // Each response schedules the next bounded status check; failed checks require an explicit retry.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job, error]);
  return (
    <EvidenceDrawer
      title="Resolve source artifact"
      subtitle={`${workload.workload.namespace} / ${workload.workload.name}${container ? " / " + container.name : " / Helm release"}`}
      onClose={onClose}
      closeLabel="Close artifact recovery"
    >
      <section className={styles.drawerSection}>
        <h3>Source availability</h3>
        <p>
          {container
            ? container.registryEvidence?.reason ||
              `Registry metadata result: ${container.registryEvidence?.status || "Not checked"}. This does not establish cache recoverability.`
            : "A detected Helm release does not establish whether the original chart package remains available."}
        </p>
        <p>
          Authentication errors and unreachable sources do not prove deletion.
          Check source access first.
        </p>
      </section>
      <section className={styles.drawerSection}>
        <h3>Recover retained artifacts</h3>
        <p>
          {container
            ? "Checks the configured source SSM host’s local containerd cache only. Exports an OCI archive only if the selected digest and every required blob validate. Other nodes need separately approved access."
            : "Checks retained deployed Helm release Secrets on the configured SSM host. Recovers release data for review; original chart archives, signatures and dependency completeness remain unverified."}
        </p>
        {container && (
          <label>
            Image digest *
            <select
              aria-label="Recovery image digest"
              value={digest}
              onChange={(e) => setDigest(e.target.value)}
            >
              <option value="">Choose observed or declared digest</option>
              {digests.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </label>
        )}
        {container && !digests.length && (
          <p role="status">
            No recoverable digest identity was collected. Refresh runtime
            evidence or supply the original image artifact.
          </p>
        )}
        <p>
          Recovery uses the approved SSM delivery role. Artifacts are stored
          privately for this customer and assessment. Source workloads and
          target registries are not changed. Helm bundles can contain sensitive
          configuration.
        </p>
        <button
          className={styles.primary}
          disabled={
            !canEdit ||
            busy ||
            job?.status === "RECOVERING" ||
            Boolean(container && !digest)
          }
          onClick={() => void request("START")}
        >
          {busy && <LoaderCircle size={14} className={styles.spin} />}Check
          cache and recover
        </button>
      </section>
      {job && (
        <section className={styles.drawerSection} aria-live="polite">
          <h3>{job.status.replaceAll("_", " ")}</h3>
          <p>{job.message}</p>
          {job.sha256 && (
            <p>
              Archive checksum: <code>{job.sha256}</code>
            </p>
          )}
          {job.platform && <p>Recovered platform: {job.platform}</p>}
          {job.sizeBytes && (
            <p>
              {(job.sizeBytes / 1024 ** 2).toFixed(1)} MiB · Original source
              availability unchanged
            </p>
          )}
          {job.status === "RECOVERING" && (
            <button disabled={busy} onClick={() => void request("POLL")}>
              Refresh recovery status
            </button>
          )}
          {["RECOVERED", "PARTIAL_RECOVERY"].includes(job.status) && (
            <button
              disabled={busy || !canEdit}
              onClick={() => void request("DOWNLOAD")}
            >
              <Download size={15} />
              Download recovered artifact
            </button>
          )}
        </section>
      )}
      {matchingJobs.length > 1 && (
        <details className={styles.drawerSection}>
          <summary>Previous recovery attempts ({matchingJobs.length})</summary>
          {matchingJobs.map((item) => (
            <button
              key={item.jobId}
              disabled={busy}
              onClick={() => setJob(item)}
            >
              {item.jobId.slice(-8)} · {item.status.replaceAll("_", " ")}
            </button>
          ))}
        </details>
      )}
      {error && (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      )}
    </EvidenceDrawer>
  );
}
