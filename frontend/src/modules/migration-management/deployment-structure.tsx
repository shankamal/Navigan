"use client";
import { Fragment, useEffect, useState } from "react";
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
  CheckCircle2,
  CircleMinus,
  Info,
  Server,
  Search,
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
import view from "./deployment-structure.module.css";

type Workload = DeploymentWorkloadEvidence;
import type { Assessment } from "./model";
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
function sourceStatus(status?: string) {
  if (status === "AVAILABLE")
    return { label: "Available", tone: view.good, Icon: CheckCircle2 };
  if (status === "NOT_FOUND")
    return { label: "Not found", tone: view.missing, Icon: AlertTriangle };
  if (status === "ACCESS_REQUIRED")
    return { label: "Access required", tone: view.review, Icon: AlertTriangle };
  if (status === "NOT_CONNECTED")
    return { label: "Not connected", tone: view.muted, Icon: CircleMinus };
  return {
    label: status ? status.toLowerCase().replaceAll("_", " ") : "Not checked",
    tone: view.muted,
    Icon: CircleMinus,
  };
}
function registryLabel(image: string) {
  const host = image.split("/")[0];
  return host.includes(".dkr.ecr.")
    ? "Source ECR"
    : host.includes(".") || (host.includes(":") && image.includes("/"))
      ? host
      : "Docker Hub";
}
export function ContainerImages({
  workload,
  onResolve,
  onConnect,
  recoveries = [],
}: {
  workload: Workload;
  recoveries?: RecoveryJob[];
  onConnect?: () => void;
  onResolve?: (c: Workload["containers"][number]) => void;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);
  return (
    <section className={view.images} aria-label="Workload container images">
      <div className={view.sectionTitle}>
        <Database size={22} />
        <div>
          <h3>
            Container images <span>({workload.containers.length})</span>
          </h3>
          <p>
            Declared images, observed runtime digests and source availability.
          </p>
        </div>
      </div>
      <div className={view.tableViewport}>
        <table className={view.imageTable}>
          <colgroup>
            <col style={{ width: "23%" }} />
            <col style={{ width: "26%" }} />
            <col style={{ width: "21%" }} />
            <col style={{ width: "18%" }} />
            <col style={{ width: "12%" }} />
          </colgroup>
          <thead>
            <tr>
              <th>Container</th>
              <th>
                Image{" "}
                <Info
                  size={12}
                  aria-label="Declared in the workload configuration"
                />
              </th>
              <th>
                Runtime evidence{" "}
                <Info
                  size={12}
                  aria-label="Digests reported by observed Pods"
                />
              </th>
              <th>
                Source availability{" "}
                <Info
                  size={12}
                  aria-label="Registry metadata only; target pull access is not verified"
                />
              </th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {workload.containers.map((c, index) => {
              const key = `${c.containerType}/${c.name}`;
              const open = expanded === key;
              const status = sourceStatus(c.registryEvidence?.status);
              const recovered =
                recoveries
                  .filter(
                    (job) =>
                      job.kind === "IMAGE" &&
                      scopeKey(job.workload) === scopeKey(workload.workload) &&
                      job.containerName === c.name,
                  )
                  .at(-1)?.status === "RECOVERED";
              const isInit = c.containerType.toUpperCase() === "INIT";
              const label = imageLabel(c.configuredImage);
              const [imageName, declaredDigest] = label.split("@");
              return (
                <Fragment key={key}>
                  <tr
                    className={
                      c.registryEvidence?.status === "NOT_FOUND"
                        ? view.missingRow
                        : undefined
                    }
                  >
                    <td>
                      <button
                        className={view.containerToggle}
                        aria-expanded={open}
                        aria-controls={`image-details-${index}`}
                        onClick={() => setExpanded(open ? null : key)}
                      >
                        <Box size={19} />
                        <span>
                          <strong>{c.name}</strong>
                          <small
                            className={
                              isInit ? view.initType : view.containerType
                            }
                          >
                            {isInit ? "Init" : "Container"}
                          </small>
                        </span>
                        <ChevronRight size={13} />
                      </button>
                    </td>
                    <td>
                      <div className={view.imageCell}>
                        <span>
                          <strong title={c.configuredImage}>{imageName}</strong>
                          {declaredDigest && <code>@{declaredDigest}</code>}
                          <small title={c.configuredImage.split("/")[0]}>
                            {registryLabel(c.configuredImage)}
                          </small>
                        </span>
                        <CopyValue value={c.configuredImage} />
                      </div>
                    </td>
                    <td>
                      <span
                        className={`${view.status} ${c.observedDigests.length ? view.good : view.muted}`}
                      >
                        {c.observedDigests.length ? (
                          <CheckCircle2 size={16} />
                        ) : (
                          <CircleMinus size={16} />
                        )}{" "}
                        {c.observedDigests.length
                          ? "Digest observed"
                          : "Not reported"}
                      </span>
                      {c.observedDigests.length > 0 && (
                        <small
                          className={view.runtimeDigest}
                          title={c.observedDigests.join(", ")}
                        >
                          {c.observedDigests[0].slice(0, 19)}…{" "}
                          {c.observedDigests.length > 1
                            ? `+${c.observedDigests.length - 1} more`
                            : ""}
                        </small>
                      )}
                    </td>
                    <td>
                      <span className={`${view.status} ${status.tone}`}>
                        <status.Icon size={16} />
                        {status.label}
                      </span>
                      <small className={view.registryCaption}>
                        {registryLabel(c.configuredImage)}
                      </small>
                      {recovered && (
                        <small className={view.good}>
                          Cached copy recovered
                        </small>
                      )}
                    </td>
                    <td>
                      {onResolve &&
                      (c.registryEvidence?.status !== "AVAILABLE" ||
                        recovered) ? (
                        <button
                          className={view.resolveButton}
                          aria-label={`${recovered ? "View recovered image" : ["NOT_CONNECTED", "ACCESS_REQUIRED"].includes(c.registryEvidence?.status ?? "") && onConnect ? "Review registry access for" : "Resolve image"} ${c.name}`}
                          onClick={() =>
                            !recovered &&
                            ["NOT_CONNECTED", "ACCESS_REQUIRED"].includes(
                              c.registryEvidence?.status ?? "",
                            ) &&
                            onConnect
                              ? onConnect()
                              : onResolve(c)
                          }
                        >
                          {recovered
                            ? "View copy"
                            : ["NOT_CONNECTED", "ACCESS_REQUIRED"].includes(
                                  c.registryEvidence?.status ?? "",
                                ) && onConnect
                              ? "Connect"
                              : "Resolve"}
                        </button>
                      ) : (
                        <span className={view.muted}>—</span>
                      )}
                    </td>
                  </tr>
                  {open && (
                    <tr className={view.expandedRow}>
                      <td colSpan={5}>
                        <div
                          id={`image-details-${index}`}
                          className={view.imageDetails}
                        >
                          <dl>
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
                                  {c.configuredImage.split("@")[1] ||
                                    "Tag reference — digest not declared"}
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
                                  `${status.label}. Registry availability and runtime evidence are checked independently.`}
                              </dd>
                            </div>
                          </dl>
                          <p>
                            {c.runningPodCount} observed Pods ·{" "}
                            {c.multipleRunningVersions
                              ? "Multiple runtime versions — select an exact digest for recovery."
                              : "Availability does not verify target pull access."}
                          </p>
                          {onResolve && (
                            <button onClick={() => onResolve(c)}>
                              Check recovery options
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      {!workload.containers.length && (
        <p className={view.empty}>No container image evidence was collected.</p>
      )}
    </section>
  );
}
export function DeploymentStructure({
  workloads,
  onInspect,
  onResolve,
  namespaces: knownNamespaces = [],
  recoveries = [],
  findings = [],
  onConnect,
}: {
  workloads: Workload[];
  namespaces?: string[];
  recoveries?: RecoveryJob[];
  findings?: Assessment["findings"];
  onConnect?: () => void;
  onInspect: (w: Workload) => void;
  onResolve: (w: Workload, c?: Workload["containers"][number]) => void;
}) {
  const [selected, setSelected] = useState("");
  const active =
    workloads.find((w) => scopeKey(w.workload) === selected) ?? workloads[0];
  const namespaces = [
    ...new Set([
      ...knownNamespaces,
      ...workloads.map((w) => w.workload.namespace || "Cluster-scoped"),
    ]),
  ].sort();
  const candidates =
    active?.candidates.filter(
      (c, i, all) =>
        all.findIndex(
          (other) =>
            other.repository === c.repository &&
            other.commit === c.commit &&
            other.filePath === c.filePath,
        ) === i,
    ) || [];
  const linkedFindings = active
    ? findings.filter(
        (f) =>
          f.namespace === active.workload.namespace &&
          ((f.resourceKind === active.workload.kind &&
            f.resourceName === active.workload.name) ||
            active.dependencies?.some(
              (d) => d.kind === f.resourceKind && d.name === f.resourceName,
            )),
      )
    : [];
  const groupedFindings = linkedFindings.filter(
    (f, i, all) =>
      all.findIndex((v) => v.code === f.code && v.severity === f.severity) ===
      i,
  );
  const additionalGaps = [...new Set(active?.gaps ?? [])].filter(
    (gap) =>
      !linkedFindings.some(
        (finding) =>
          finding.message.trim().toLowerCase() === gap.trim().toLowerCase(),
      ),
  );
  return (
    <div className={view.layout}>
      <aside
        className={view.navigator}
        aria-label="Deployment structure workloads"
      >
        <header>
          <h3>Namespaces & workloads</h3>
          <small>
            {namespaces.length} namespaces · {workloads.length} workloads
          </small>
        </header>
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
            {!workloads.some((w) => w.workload.namespace === ns) && (
              <p className={view.emptyNamespace}>
                No workload controllers captured.
              </p>
            )}
            {workloads
              .filter(
                (w) =>
                  (w.workload.namespace || "Cluster-scoped") === ns &&
                  w.workload.kind !== "Job",
              )
              .map((w) => (
                <button
                  key={scopeKey(w.workload)}
                  aria-pressed={w === active}
                  onClick={() => setSelected(scopeKey(w.workload))}
                >
                  <Box size={18} />
                  <span>
                    {w.workload.name}
                    <small>{w.workload.kind}</small>
                  </span>
                </button>
              ))}
            {workloads.some(
              (w) => w.workload.namespace === ns && w.workload.kind === "Job",
            ) && (
              <details
                className={view.jobGroup}
                open={
                  active?.workload.namespace === ns &&
                  active?.workload.kind === "Job"
                }
              >
                <summary>
                  Job executions{" "}
                  <small>
                    {
                      workloads.filter(
                        (w) =>
                          w.workload.namespace === ns &&
                          w.workload.kind === "Job",
                      ).length
                    }
                  </small>
                </summary>
                {workloads
                  .filter(
                    (w) =>
                      (w.workload.namespace || "Cluster-scoped") === ns &&
                      w.workload.kind === "Job",
                  )
                  .map((w) => (
                    <button
                      key={scopeKey(w.workload)}
                      aria-pressed={w === active}
                      onClick={() => setSelected(scopeKey(w.workload))}
                    >
                      <Box size={18} />
                      <span>
                        {w.workload.name}
                        <small>{w.workload.kind}</small>
                      </span>
                    </button>
                  ))}
              </details>
            )}
          </details>
        ))}
      </aside>
      {!active ? (
        <p className={view.empty}>
          No workloads match these filters. Empty namespaces remain listed;
          check Source diagnostics for collection limits.
        </p>
      ) : (
        <article className={view.card}>
          <header className={view.workloadTitle}>
            <Box size={29} />
            <div>
              <h3>{active.workload.name}</h3>
              <p>
                {active.workload.kind} ·{" "}
                {active.workload.namespace || "Cluster-scoped"}
                <span className={view.runtimeSummary}>
                  {active.runtimeStatus === "NO_RUNNING_EVIDENCE"
                    ? "No active Pod"
                    : active.runtimeStatus === "OBSERVED"
                      ? "Runtime observed"
                      : "Runtime evidence incomplete"}
                </span>
              </p>
            </div>
            <button
              className={view.inspectLink}
              aria-label={`Inspect ${active.workload.name} in ${active.workload.namespace || "cluster"}`}
              onClick={() => onInspect(active)}
            >
              Review details <ChevronRight size={14} />
            </button>
          </header>
          <div className={view.sectionTitle}>
            <FileCode2 size={20} />
            <div>
              <h3>Deployment definition</h3>
              <p>Files or Helm release associated with this workload.</p>
            </div>
          </div>
          {active.helmRelease && (
            <div className={view.helmRelease}>
              <span>
                <strong>Helm release: {active.helmRelease}</strong>
                <small>
                  {active.helmChart || "Chart version not reported"} · Original
                  package not checked
                </small>
              </span>
              <button onClick={() => onResolve(active)}>
                Resolve Helm artifact
              </button>
            </div>
          )}
          <section
            className={view.sourceStrip}
            aria-label="Source repository candidate"
          >
            {candidates.length ? (
              candidates.map((c) => (
                <div
                  key={`${c.repository}/${c.filePath}/${c.commit}`}
                  className={view.candidateStrip}
                >
                  <GitBranch size={23} />
                  <div>
                    <small>
                      {active.mappingStatus === "CONFIRMED"
                        ? "User-confirmed candidate"
                        : "GitHub candidate"}
                    </small>
                    <strong title={c.repository}>{c.repository}</strong>
                  </div>
                  <div className={view.filePath}>
                    <small>File path</small>
                    <strong title={c.filePath}>{c.filePath}</strong>
                    <CopyValue value={`${c.repository}/${c.filePath}`} />
                  </div>
                  <div>
                    <small>Type</small>
                    <strong>
                      {active.artifactFormat === "Unresolved"
                        ? "Not detected"
                        : active.artifactFormat.replace(" (candidate)", "")}
                    </strong>
                  </div>
                </div>
              ))
            ) : (
              <div className={view.unmapped}>
                <FileCode2 size={22} />
                <div>
                  <strong>No original repository mapping.</strong>
                  <p>
                    {active.clusterSnapshot
                      ? "Captured cluster evidence is available for review."
                      : "Connect a repository or refresh source evidence."}
                  </p>
                </div>
              </div>
            )}
            {candidates.length > 0 && (
              <div className={view.provenance}>
                <AlertTriangle size={14} />
                <span>Deployed Git revision unverified</span>
                <small>
                  Inspected commit {candidates[0].commit.slice(0, 12)}
                </small>
              </div>
            )}
            {candidates.some((c) => c.match === "NAMESPACE_UNSPECIFIED") && (
              <small className={view.namespaceNote}>
                Namespace not specified in the candidate file. Runtime namespace
                shown above.
              </small>
            )}
          </section>
          {(!candidates.length || active.mappingStatus !== "CONFIRMED") && (
            <div className={view.mappingAction}>
              <button onClick={() => onInspect(active)}>
                {candidates.length
                  ? "Review source mapping"
                  : "Resolve deployment source"}
              </button>
              <small>
                {candidates.length
                  ? "Review the candidate and confirm ownership."
                  : "Map an authorized repository or review captured configuration. Original files are not reconstructed automatically."}
              </small>
            </div>
          )}
          <ContainerImages
            key={scopeKey(active.workload)}
            workload={active}
            onResolve={(c) => onResolve(active, c)}
            onConnect={onConnect}
            recoveries={recoveries.filter(
              (job) => scopeKey(job.workload) === scopeKey(active.workload),
            )}
          />
          <section className={view.related} aria-label="Connected resources">
            <details>
              <summary>
                Connected resources{" "}
                <span>{active.dependencies?.length ?? "Not reported"}</span>
              </summary>
              <p>
                Resources this workload uses for networking, configuration,
                storage or access. Secret contents are not displayed.
              </p>
              {active.dependencies?.length ? (
                <div className={view.dependencyList}>
                  {active.dependencies.map((d) => (
                    <div key={`${d.kind}/${d.name}`}>
                      <strong>
                        {d.name}
                        <small>
                          {["Service", "Ingress", "NetworkPolicy"].includes(
                            d.kind,
                          )
                            ? "Networking"
                            : [
                                  "PersistentVolumeClaim",
                                  "PersistentVolume",
                                ].includes(d.kind)
                              ? "Storage"
                              : ["Secret", "ConfigMap"].includes(d.kind)
                                ? "Configuration"
                                : "Access / other"}{" "}
                          · {d.kind}
                        </small>
                      </strong>
                      <span
                        className={
                          d.status === "CAPTURED" ? view.good : view.review
                        }
                      >
                        {d.status === "CAPTURED"
                          ? "Found in discovery"
                          : "Not found in discovery"}
                      </span>
                      <span>
                        {d.sourceCandidates.length
                          ? "Candidate: " +
                            d.sourceCandidates.map((c) => c.filePath).join(", ")
                          : "Repository file not mapped"}
                        <small>{d.reason}</small>
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p>
                  {active.dependencies
                    ? "No dependency references were reported. This does not prove the application has no external dependencies."
                    : "Dependency evidence requires the latest backend analysis."}
                </p>
              )}
            </details>
          </section>
          <section className={view.related} aria-label="Checks and actions">
            <details
              open={groupedFindings.some((f) => f.severity === "BLOCKER")}
            >
              <summary>
                Checks &amp; actions{" "}
                <span>
                  {groupedFindings.length + additionalGaps.length} checks to
                  review
                </span>
              </summary>
              <p>
                Review the checks below to understand what needs attention.
                Image recovery and connection actions are beside each container
                above.
              </p>
              {!groupedFindings.length && !additionalGaps.length && (
                <p>
                  No resource-specific findings are linked to this workload in
                  the supplied assessment. Review cluster-wide findings
                  separately.
                </p>
              )}
              {groupedFindings.map((f) => (
                <div className={view.finding} key={`${f.code}/${f.severity}`}>
                  <strong
                    className={
                      f.severity === "BLOCKER" ? view.missing : view.review
                    }
                  >
                    {f.severity === "BLOCKER"
                      ? "Action required · Blocker"
                      : f.severity === "WARNING"
                        ? "Review needed"
                        : "Information"}
                  </strong>
                  <p>{f.message}</p>
                  {linkedFindings.filter(
                    (item) =>
                      item.code === f.code && item.severity === f.severity,
                  ).length > 1 && (
                    <details>
                      <summary>More observations in this issue group</summary>
                      {linkedFindings
                        .filter(
                          (item) =>
                            item.code === f.code &&
                            item.severity === f.severity,
                        )
                        .slice(1)
                        .map((item, index) => (
                          <p key={index}>
                            {item.resourceKind}/{item.resourceName}:{" "}
                            {item.message}
                            {item.remediation && (
                              <small>{item.remediation}</small>
                            )}
                          </p>
                        ))}
                    </details>
                  )}
                  {f.remediation && <small>Next step: {f.remediation}</small>}
                  <details>
                    <summary>Technical details</summary>
                    <p>
                      Check: {f.code} · Severity: {f.severity}
                    </p>
                  </details>
                </div>
              ))}
              {additionalGaps.map((gap) => (
                <div className={view.finding} key={gap}>
                  <strong className={view.review}>Review needed</strong>
                  <p>{gap}</p>
                  <button type="button" onClick={() => onInspect(active)}>
                    Review evidence
                  </button>
                </div>
              ))}
            </details>
          </section>
          <section className={view.deploymentFacts}>
            <div className={view.sectionTitle}>
              <FileCode2 size={21} />
              <div>
                <h3>Deployment context</h3>
                <p>Additional context from the collected source evidence.</p>
              </div>
            </div>
            <dl>
              <div>
                <dt>How this resource was updated</dt>
                <dd>
                  <Box size={17} />
                  {active.deliveryTool === "Unresolved"
                    ? "Not detected"
                    : active.deliveryTool.toLowerCase().includes("kubectl")
                      ? "Updated using kubectl"
                      : active.deliveryTool.replace(
                          /\s*\(field-manager evidence\)/i,
                          "",
                        )}
                </dd>
              </div>
              <div>
                <dt>Cluster snapshot</dt>
                <dd>
                  <Database size={17} />
                  {active.clusterSnapshot
                    ? "Captured inventory available"
                    : "Not collected"}
                </dd>
              </div>
              <div>
                <dt>Application version</dt>
                <dd>
                  <Info size={17} />
                  {active.applicationVersion || "Not reported"}
                </dd>
              </div>
            </dl>
            {(active.deliveryTool.toLowerCase().includes("kubectl") ||
              active.deliveryEvidenceBasis === "FIELD_MANAGER") && (
              <p className={view.namespaceNote}>
                kubectl is the command-line tool for managing Kubernetes. The
                cluster records which tool updated this resource; this does not
                confirm the original Git file or deployment pipeline.
              </p>
            )}
          </section>
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
  const availability = sourceStatus(container?.registryEvidence?.status);
  const recoverable =
    canEdit &&
    !busy &&
    job?.status !== "RECOVERING" &&
    (!container || Boolean(digest));
  const startButton = (
    <button
      className={view.recoverPrimary}
      disabled={!recoverable}
      onClick={() => void request("START")}
    >
      {busy ? (
        <LoaderCircle size={17} className={styles.spin} />
      ) : (
        <Search size={17} />
      )}
      Check cache and recover
    </button>
  );
  return (
    <EvidenceDrawer
      title={
        container
          ? container.registryEvidence?.status === "NOT_FOUND"
            ? "Resolve missing image"
            : "Resolve image artifact"
          : "Resolve Helm release"
      }
      subtitle={`${workload.workload.kind} · ${workload.workload.name} · ${workload.workload.namespace || "Cluster-scoped"}`}
      onClose={onClose}
      closeLabel="Close artifact recovery"
      variant="recovery"
      footer={
        <div className={view.recoveryFooter}>
          {!job || job.status === "CUSTOMER_INPUT_REQUIRED" ? (
            startButton
          ) : job.status === "RECOVERING" ? (
            <button
              className={view.recoverPrimary}
              disabled={busy}
              onClick={() => void request("POLL")}
            >
              <LoaderCircle size={16} className={styles.spin} />
              Refresh recovery status
            </button>
          ) : job.status === "RECOVERED" ||
            job.status === "PARTIAL_RECOVERY" ? (
            <button
              className={view.recoverPrimary}
              disabled={busy || !canEdit}
              onClick={() => void request("DOWNLOAD")}
            >
              <Download size={17} />
              Download recovered artifact
            </button>
          ) : (
            startButton
          )}
          <button className={view.recoverClose} onClick={onClose}>
            Close
          </button>
        </div>
      }
    >
      <div className={view.recoveryBody}>
        <div className={view.recoveryIdentity}>
          <Box size={25} />
          <div>
            <strong>
              {container?.name ||
                workload.helmRelease ||
                workload.workload.name}
            </strong>
            <span>
              {container?.containerType === "INIT"
                ? "Init container"
                : container
                  ? "Container image"
                  : "Helm release data"}
            </span>
          </div>
        </div>
        <div
          className={`${view.recoveryAvailability} ${container?.registryEvidence?.status === "NOT_FOUND" ? view.missingAvailability : ""}`}
        >
          <availability.Icon size={18} />
          <div>
            <strong>
              {container
                ? availability.label === "Not found"
                  ? "Missing at source registry"
                  : availability.label
                : "Original chart package unverified"}
            </strong>
            <small>
              {job
                ? job.status.toLowerCase().replaceAll("_", " ")
                : "Recovery not checked"}
            </small>
          </div>
        </div>
        {container && (
          <section>
            <h3>Declared image</h3>
            <div className={view.recoveryImage}>
              <strong>
                {imageLabel(container.configuredImage).split("@")[0]}
              </strong>
              <code>
                {container.configuredImage.includes("@")
                  ? "@" +
                    container.configuredImage.split("@")[1].slice(0, 23) +
                    "…"
                  : "Tag reference"}
              </code>
              <CopyValue value={container.configuredImage} />
            </div>
          </section>
        )}
        {container && (
          <section>
            <label className={view.digestLabel}>
              Recovery digest *{" "}
              <Info
                size={13}
                aria-label="Select an observed or declared digest; current registry tags are not used as deployed identity."
              />
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
            {!digests.length && (
              <p role="status">
                No recoverable digest identity was collected. Refresh runtime
                evidence or supply the original image artifact.
              </p>
            )}
          </section>
        )}
        <section>
          <h3>Recovery method</h3>
          <p className={view.method}>
            <Server size={19} />
            <span>
              Configured SSM host
              <small>
                {container
                  ? "containerd cache · selected platform"
                  : "Retained deployed Helm release"}
              </small>
            </span>
          </p>
          <div className={view.recoveryInfo}>
            <Info size={17} />
            <p>
              {container
                ? "Checks the exact image digest and required content. A cached copy is not guaranteed."
                : "Recovers retained release data, not a verified original chart package. Values and manifests may contain sensitive configuration."}
            </p>
          </div>
        </section>
        {job && (
          <section className={view.recoveryResult} aria-live="polite">
            <h3>{job.status.replaceAll("_", " ")}</h3>
            <p>{job.message}</p>
            {job.sha256 && (
              <small>
                Archive checksum <code>{job.sha256}</code>
              </small>
            )}
            {job.platform && <small>Platform: {job.platform}</small>}
            {job.sizeBytes ? (
              <small>
                {(job.sizeBytes / 1024 ** 2).toFixed(1)} MiB · Original source
                availability unchanged
              </small>
            ) : null}
          </section>
        )}
        <details className={view.recoveryNotes}>
          <summary>Access, scope & original source</summary>
          <p>
            {container?.registryEvidence?.reason ||
              "Authentication errors and unreachable sources do not prove deletion."}
          </p>
          <p>
            {container
              ? "Only the configured host is checked. Other nodes and runtimes need separately approved access."
              : "Original chart archive, signatures and dependency completeness remain unverified."}{" "}
            Artifacts are stored privately for this customer and assessment.
            Source workloads and target registries are not changed.
          </p>
        </details>
        {matchingJobs.length > 1 && (
          <details className={view.recoveryNotes}>
            <summary>
              Previous recovery attempts ({matchingJobs.length})
            </summary>
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
      </div>
    </EvidenceDrawer>
  );
}
