"use client";
import Link from "next/link";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { GitBranch, LoaderCircle, Plus, Trash2 } from "lucide-react";
import { useAuth } from "@/shared/auth/auth-provider";
import { hasPermission } from "@/shared/auth/permissions";
import { normalizeApiError } from "@/shared/api/client";
import {
  deploymentDiscovery,
  type DeploymentSourcesConfiguration,
} from "./deployment-evidence-service";
import { scopeKey } from "./source-migration-scope";
import type { Migration } from "./model";
import styles from "./deployment-evidence-panel.module.css";

export function DeploymentEvidencePanel({
  migration,
  selectedKeys,
  inventoryDigest,
  onRefresh,
  hideConnections = false,
}: {
  migration: Migration;
  selectedKeys?: Set<string>;
  inventoryDigest?: string;
  onRefresh?: () => void;
  hideConnections?: boolean;
}) {
  const { identity } = useAuth();
  const canEdit = hasPermission(identity, "migration.edit");
  const cache = useQueryClient();
  const sourceId = String(migration.sourceConfiguration.sourceClusterId ?? "");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<DeploymentSourcesConfiguration>({
    repositories: [],
    registries: [],
  });
  const [registryText, setRegistryText] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [tab, setTab] = useState("workloads");
  const [choices, setChoices] = useState<Record<string, number>>({});
  const query = useQuery({
    queryKey: ["deployment-evidence", migration.migrationId, inventoryDigest],
    queryFn: ({ signal }) =>
      deploymentDiscovery.evidence(migration.migrationId, signal),
    enabled: Boolean(sourceId),
    retry: false,
    refetchOnWindowFocus: false,
  });
  const settings = useQuery({
    queryKey: ["deployment-sources", sourceId],
    queryFn: ({ signal }) => deploymentDiscovery.settings(sourceId, signal),
    enabled: Boolean(sourceId) && !selectedKeys,
    retry: false,
  });
  const evidence = query.data;
  const matching =
    !inventoryDigest || evidence?.inventoryDigest === inventoryDigest;
  const workloads = matching
    ? (evidence?.workloads ?? []).filter(
        (r) => !selectedKeys || selectedKeys.has(scopeKey(r.workload)),
      )
    : [];
  const needsRuntime = workloads.some((w) =>
    ["NOT_COLLECTED", "UNAVAILABLE"].includes(w.runtimeStatus),
  );
  const reportError = (e: unknown) =>
    setError(normalizeApiError(e).message || "Deployment analysis failed.");
  async function perform(action: "save" | "analyze" | "refresh") {
    setError("");
    setNotice("");
    const hosts = [
      ...new Set(
        registryText
          .split(/[\n,]/)
          .map((v) => v.trim())
          .filter(Boolean),
      ),
    ];
    if (
      action === "save" &&
      (draft.repositories.some(
        (r) =>
          !/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(r.repository.trim()) ||
          !r.revision.trim() ||
          r.directory.startsWith("/") ||
          r.directory.split("/").some((p) => p === "." || p === ".."),
      ) ||
        hosts.some((h) => !/^[a-z0-9]+(?:[a-z0-9.-]*[a-z0-9])?$/.test(h)))
    ) {
      setError(
        "Enter owner/repository, revision, a relative directory without traversal, and registry hostnames without URLs or credentials.",
      );
      return;
    }
    setBusy(action);
    try {
      if (action === "save") {
        if (!settings.data)
          throw new Error("Reload source settings before saving.");
        const result = await deploymentDiscovery.saveSettings(
          sourceId,
          settings.data.version,
          {
            confirmations: draft.confirmations ?? [],
            repositories: draft.repositories.map((r) => ({
              repository: r.repository.trim(),
              revision: r.revision.trim(),
              directory: r.directory.trim(),
            })),
            registries: hosts,
          },
        );
        cache.setQueryData(["deployment-sources", sourceId], result);
        setEditing(false);
        setNotice(
          "Connections saved for this customer’s source cluster. Analyze deployment sources to inspect them.",
        );
        await cache.invalidateQueries({
          queryKey: ["deployment-evidence", migration.migrationId],
        });
      } else if (action === "analyze") {
        const result = await deploymentDiscovery.analyze(
          migration.migrationId,
          migration.version,
        );
        cache.setQueryData(
          ["deployment-evidence", migration.migrationId, inventoryDigest],
          result,
        );
        await settings.refetch();
        setNotice(
          "Analysis finished. Review candidate sources, running versions and evidence gaps.",
        );
      } else {
        await deploymentDiscovery.refresh(
          migration.migrationId,
          migration.version,
        );
        setNotice(
          "Cluster evidence refresh requested. Previous evidence remains stored while the connector collects a new inventory and assessment.",
        );
        await cache.invalidateQueries({
          queryKey: ["source-discovery", migration.migrationId],
        });
        onRefresh?.();
      }
    } catch (e) {
      reportError(e);
    } finally {
      setBusy("");
    }
  }
  async function confirmMappings(rows: typeof workloads) {
    if (!settings.data || !evidence || busy) return;
    setBusy("confirm");
    setError("");
    try {
      const next = rows.map((w) => ({
        ...w.workload,
        namespace: w.workload.namespace ?? "",
        repository: w.candidates[choices[scopeKey(w.workload)] ?? 0].repository,
        commit: w.candidates[choices[scopeKey(w.workload)] ?? 0].commit,
        filePath: w.candidates[choices[scopeKey(w.workload)] ?? 0].filePath,
      }));
      const confirmations = [
        ...(settings.data.configuration.confirmations ?? []).filter(
          (m) => !rows.some((w) => scopeKey(w.workload) === scopeKey(m)),
        ),
        ...next,
      ];
      const result = await deploymentDiscovery.saveSettings(
        sourceId,
        settings.data.version,
        { ...settings.data.configuration, confirmations },
      );
      cache.setQueryData(["deployment-sources", sourceId], result);
      await cache.invalidateQueries({
        queryKey: ["deployment-evidence", migration.migrationId],
      });
      setNotice(
        "Source mappings confirmed by you. This records your selection; it does not independently verify the deployed Git commit.",
      );
    } catch (e) {
      reportError(e);
    } finally {
      setBusy("");
    }
  }
  return (
    <section
      className={styles.panel}
      aria-label="Deployment sources and versions"
    >
      <div className={styles.heading}>
        <div>
          <h2>
            <GitBranch size={20} />
            {selectedKeys
              ? "4. Deployment sources and versions"
              : "Deployment sources and versions"}
          </h2>
          <p>
            {selectedKeys
              ? "Detected evidence for selected workloads. Resolve missing sources in discovery."
              : "Discover how applications are deployed and which container versions are running."}
          </p>
        </div>
        {!selectedKeys && (
          <div className={styles.actions}>
            {!hideConnections && (
              <button
                disabled={!canEdit || !!busy || !settings.data || editing}
                title="Register repositories and registries once for this customer’s source cluster."
                onClick={() => {
                  setDraft(structuredClone(settings.data!.configuration));
                  setRegistryText(
                    settings.data!.configuration.registries.join("\n"),
                  );
                  setEditing(true);
                  setError("");
                }}
              >
                Manage deployment sources
              </button>
            )}
            {!needsRuntime && migration.status === "ASSESSMENT_READY" && (
              <button
                disabled={
                  !canEdit ||
                  !!busy ||
                  editing ||
                  (hideConnections && !settings.data?.readyForDiscovery)
                }
                onClick={() => void perform("refresh")}
              >
                Refresh cluster evidence
              </button>
            )}
            <button
              className={styles.primary}
              disabled={
                !canEdit ||
                !!busy ||
                editing ||
                !evidence?.inventoryDigest ||
                !matching
              }
              onClick={() => void perform("analyze")}
              title="Read configured repositories and referenced images. Scripts are never executed."
            >
              {busy === "analyze" && (
                <LoaderCircle size={15} className={styles.spin} />
              )}
              {busy === "analyze"
                ? "Analyzing sources…"
                : "Analyze deployment sources"}
            </button>
          </div>
        )}
      </div>
      {query.isPending && <p role="status">Loading deployment evidence…</p>}
      {query.isError && (
        <p role="alert">
          Deployment evidence could not be loaded.{" "}
          <button onClick={() => void query.refetch()}>Retry evidence</button>
        </p>
      )}
      {!selectedKeys && settings.isError && (
        <p role="alert">
          Source connection settings could not be loaded.{" "}
          <button onClick={() => void settings.refetch()}>
            Retry settings
          </button>
        </p>
      )}
      {error && (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className={styles.note}>
          {notice}
        </p>
      )}
      {evidence && !matching && (
        <p role="alert">
          Evidence belongs to another inventory snapshot. Reload before
          reviewing deployment sources.
        </p>
      )}
      {editing && (
        <form
          className={styles.form}
          onSubmit={(e) => {
            e.preventDefault();
            void perform("save");
          }}
        >
          <h3>Customer source connections</h3>
          <p>
            Settings are reused by assessments using this registered source. No
            credentials are entered here.
          </p>
          <p>
            GitHub access:{" "}
            {settings.data?.githubOrganizations.length
              ? `customer App connections: ${settings.data.githubOrganizations.join(", ")}`
              : "public repositories; private repositories require the customer’s GitHub App connection."}
          </p>
          {draft.repositories.map((r, i) => (
            <fieldset key={i} disabled={!!busy} className={styles.repo}>
              <legend>Repository {i + 1}</legend>
              {(
                [
                  [
                    "repository",
                    "GitHub repository *",
                    "organization/application-repo",
                    "GitHub owner/repository. Existing customer App access is reused for private repositories.",
                  ],
                  [
                    "revision",
                    "Revision *",
                    "main",
                    "Branch, tag or commit. Navigan pins the inspected commit; it does not assume it is deployed.",
                  ],
                  [
                    "directory",
                    "Deployment directory",
                    "deploy/production",
                    "Optional relative directory containing deployment artifacts. Narrow the path for the deployed environment.",
                  ],
                ] as const
              ).map(([field, label, placeholder, tip]) => (
                <label key={field}>
                  {label}
                  <input
                    required={field !== "directory"}
                    value={r[field]}
                    maxLength={field === "directory" ? 500 : 200}
                    placeholder={placeholder}
                    title={tip}
                    onChange={(e) =>
                      setDraft((d) => ({
                        ...d,
                        repositories: d.repositories.map((v, j) =>
                          i === j ? { ...v, [field]: e.target.value } : v,
                        ),
                      }))
                    }
                  />
                </label>
              ))}
              <button
                type="button"
                aria-label={`Remove repository ${i + 1}`}
                onClick={() =>
                  setDraft((d) => ({
                    ...d,
                    repositories: d.repositories.filter((_, j) => i !== j),
                  }))
                }
              >
                <Trash2 size={15} />
              </button>
            </fieldset>
          ))}
          <button
            type="button"
            disabled={!!busy || draft.repositories.length >= 3}
            onClick={() =>
              setDraft((d) => ({
                ...d,
                repositories: [
                  ...d.repositories,
                  { repository: "", revision: "main", directory: "" },
                ],
              }))
            }
          >
            <Plus size={15} />
            Add repository
          </button>
          <label>
            Container registry hosts
            <textarea
              value={registryText}
              rows={3}
              maxLength={2500}
              placeholder={
                "docker.io\n905418045935.dkr.ecr.ap-south-1.amazonaws.com"
              }
              title="One hostname per line. Initial adapters: source-account AWS ECR and public Docker Hub. Other private registries need an additional adapter."
              onChange={(e) => setRegistryText(e.target.value)}
            />
          </label>
          <small>
            Only referenced images are inspected. Initial adapters:
            source-account AWS ECR and public Docker Hub. Registry metadata
            availability does not prove target pull access.
          </small>
          <div className={styles.actions}>
            <button
              disabled={!!busy}
              type="button"
              onClick={() => setEditing(false)}
            >
              Cancel
            </button>
            <button disabled={!!busy} className={styles.primary}>
              {busy === "save" ? "Saving…" : "Save source connections"}
            </button>
          </div>
        </form>
      )}
      {evidence && (
        <>
          {!selectedKeys &&
            workloads.some(
              (w) =>
                w.candidates.length === 1 && w.mappingStatus !== "CONFIRMED",
            ) && (
              <button
                disabled={!canEdit || !!busy || editing || !settings.data}
                onClick={() =>
                  void confirmMappings(
                    workloads.filter(
                      (w) =>
                        w.candidates.length === 1 &&
                        w.mappingStatus !== "CONFIRMED",
                    ),
                  )
                }
                title="Record your confirmation for unique candidate mappings. This does not independently prove which Git commit was deployed."
              >
                Confirm unique source mappings
              </button>
            )}
          <div className={styles.metrics}>
            <span>
              <strong>{workloads.length}</strong>{" "}
              {selectedKeys ? "selected" : "discovered"} workloads
            </span>
            <span>
              <strong>
                {workloads.filter((w) => w.candidates.length).length}
              </strong>{" "}
              candidate source mappings
            </span>
            <span>
              <strong>
                {
                  workloads.filter((w) =>
                    w.containers.some((c) => c.observedDigests.length),
                  ).length
                }
              </strong>{" "}
              workloads with running digests
            </span>
          </div>
          {!selectedKeys && (
            <nav className={styles.tabs} aria-label="Deployment evidence views">
              {[
                ["workloads", "Workloads & versions"],
                ["sources", "Deployment structure"],
                ["images", "Container registry"],
                ["gaps", "Evidence gaps"],
              ].map(([v, label]) => (
                <button
                  key={v}
                  aria-pressed={tab === v}
                  onClick={() => setTab(v)}
                >
                  {label}
                </button>
              ))}
            </nav>
          )}
          {(selectedKeys || tab === "workloads") && (
            <div className={styles.scroll}>
              <table>
                <thead>
                  <tr>
                    <th>Workload</th>
                    <th>Deployment source</th>
                    <th>Container versions</th>
                    <th>Evidence</th>
                  </tr>
                </thead>
                <tbody>
                  {workloads.map((w) => (
                    <tr
                      key={`${w.workload.namespace}/${w.workload.kind}/${w.workload.name}`}
                    >
                      <td>
                        <strong>{w.workload.name}</strong>
                        <small>
                          {w.workload.namespace} · {w.workload.kind}
                        </small>
                        {w.applicationVersion && (
                          <small>
                            Reported application version: {w.applicationVersion}
                          </small>
                        )}
                      </td>
                      <td>
                        {w.artifactFormat} · {w.deliveryTool}
                        {w.helmChart && <small>Chart: {w.helmChart}</small>}
                        {w.helmRelease && (
                          <small>Release: {w.helmRelease}</small>
                        )}
                        {w.candidates.map((c) => (
                          <small
                            key={`${c.repository}/${c.filePath}/${c.commit}`}
                            title="Candidate only; deployed commit has not been verified."
                          >
                            {c.repository} / {c.filePath}
                            <code>
                              Inspected commit: {c.commit.slice(0, 12)}
                            </code>
                          </small>
                        ))}
                      </td>
                      <td>
                        {w.containers.map((c) => (
                          <details key={`${c.containerType}/${c.name}`}>
                            <summary>
                              {c.name}
                              {c.containerType === "INIT" ? " (init)" : ""}
                              <small>{c.configuredImage}</small>
                            </summary>
                            <p>{c.runningPodCount} observed Pods</p>
                            {c.observedDigests.length ? (
                              c.observedDigests.map((d) => (
                                <code key={d}>{d}</code>
                              ))
                            ) : (
                              <small>Running digest not reported</small>
                            )}
                            {c.multipleRunningVersions && (
                              <small>
                                Multiple image identities — review rollout
                                state.
                              </small>
                            )}
                            {c.digestComparison === "DIFFERENT" && (
                              <small>
                                Digests differ. A multi-architecture image index
                                can also differ from a runtime platform digest.
                              </small>
                            )}
                            <small>
                              Registry:{" "}
                              {c.registryEvidence?.status ?? "Not analyzed"}
                            </small>
                          </details>
                        ))}
                        {!w.containers.length && (
                          <small>No container references reported.</small>
                        )}
                      </td>
                      <td>
                        <span className={styles.badge}>
                          {w.mappingStatus === "CONFIRMED"
                            ? "User-confirmed source"
                            : w.mappingStatus === "CANDIDATE"
                              ? "Candidate · needs confirmation"
                              : "Source unresolved"}
                        </span>
                        <small>
                          Runtime:{" "}
                          {w.runtimeStatus.toLowerCase().replaceAll("_", " ")}
                        </small>
                        {w.candidates.length > 1 && (
                          <small>Multiple matching artifacts</small>
                        )}
                        {!selectedKeys &&
                          w.candidates.length > 1 &&
                          w.mappingStatus !== "CONFIRMED" && (
                            <div>
                              <select
                                aria-label={`Source artifact for ${w.workload.name}`}
                                value={choices[scopeKey(w.workload)] ?? 0}
                                onChange={(e) =>
                                  setChoices((c) => ({
                                    ...c,
                                    [scopeKey(w.workload)]: Number(
                                      e.target.value,
                                    ),
                                  }))
                                }
                              >
                                {w.candidates.map((c, i) => (
                                  <option key={i} value={i}>
                                    {c.repository}/{c.filePath}
                                  </option>
                                ))}
                              </select>
                              <button
                                disabled={
                                  !canEdit ||
                                  !!busy ||
                                  editing ||
                                  !settings.data
                                }
                                onClick={() => void confirmMappings([w])}
                              >
                                Confirm source
                              </button>
                            </div>
                          )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!workloads.length && (
                <p>
                  {selectedKeys
                    ? "Select workloads to review deployment evidence."
                    : "Complete source inventory discovery to see workload evidence."}
                </p>
              )}
            </div>
          )}
          {!selectedKeys && tab === "sources" && (
            <div className={styles.cards}>
              {!evidence.repositories.length && (
                <p>
                  Connect a repository and analyze deployment sources to inspect
                  charts, manifests and scripts.
                </p>
              )}
              {evidence.repositories.map((r) => (
                <article key={r.repository}>
                  <h3>{r.repository}</h3>
                  <span>{r.status}</span>
                  {r.commit && <code>Inspected commit: {r.commit}</code>}
                  <p>
                    {r.artifacts.length} deployment artifacts found. Shared
                    chart and script relationships require review.
                  </p>
                  {r.artifacts.map((a, i) => (
                    <p key={`${a.filePath}/${i}`}>
                      <strong>{a.format}</strong> · {a.filePath}
                      {a.format === "SCRIPT" && (
                        <small>
                          Static references:{" "}
                          {[a.usesHelm && "Helm", a.usesKubectl && "kubectl"]
                            .filter(Boolean)
                            .join(", ") || "No recognized command"}
                        </small>
                      )}
                      {Boolean(a.referencedPaths?.length) && (
                        <small>
                          Referenced paths: {a.referencedPaths!.join(", ")}
                        </small>
                      )}
                      {a.dynamicReferences && (
                        <small>
                          Variable-based script paths require review.
                        </small>
                      )}
                    </p>
                  ))}
                  {r.gaps.map((g) => (
                    <p key={g}>{g}</p>
                  ))}
                </article>
              ))}
            </div>
          )}
          {!selectedKeys && tab === "images" && (
            <div className={styles.scroll}>
              <p>
                Referenced images only. Availability does not verify target pull
                access.
              </p>
              <table>
                <thead>
                  <tr>
                    <th>Image</th>
                    <th>Registry evidence</th>
                    <th>Digest / architectures</th>
                  </tr>
                </thead>
                <tbody>
                  {evidence.images.map((i) => (
                    <tr key={i.image}>
                      <td>
                        <code>{i.image}</code>
                      </td>
                      <td>
                        {i.status}
                        <small>{i.reason}</small>
                      </td>
                      <td>
                        <code>{i.registryDigest || "Digest not reported"}</code>
                        {i.architectures?.join(", ") ||
                          "Architecture not verified"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!evidence.images.length && (
                <p>
                  Configure registry hosts and analyze deployment sources to
                  inspect images.
                </p>
              )}
            </div>
          )}
          {!selectedKeys && tab === "gaps" && (
            <div className={styles.cards}>
              {workloads.map((w) => (
                <article
                  key={`${w.workload.namespace}/${w.workload.kind}/${w.workload.name}`}
                >
                  <strong>
                    {w.workload.namespace}/{w.workload.name}
                  </strong>
                  {w.gaps.map((g) => (
                    <p key={g}>{g}</p>
                  ))}
                </article>
              ))}
            </div>
          )}
          {needsRuntime && !selectedKeys && (
            <div className={styles.note}>
              <div>
                <strong>Additional running-image evidence is needed</strong>
                <p>
                  Upgrade the connector using the DEV deployment script, then
                  refresh cluster evidence. A new inventory and assessment are
                  generated; saved migration scope must be reviewed against
                  them.
                </p>
                <button
                  disabled={
                    !canEdit ||
                    !!busy ||
                    editing ||
                    migration.status !== "ASSESSMENT_READY" ||
                    (hideConnections && !settings.data?.readyForDiscovery)
                  }
                  onClick={() => void perform("refresh")}
                >
                  {busy === "refresh"
                    ? "Requesting refresh…"
                    : "Refresh cluster evidence"}
                </button>
              </div>
            </div>
          )}
          {selectedKeys ? (
            <Link
              className={styles.link}
              href={`/migrations/${migration.migrationId}/discovery#deployment-evidence`}
            >
              Review or resolve deployment sources in discovery
            </Link>
          ) : (
            <p className={styles.caption}>
              Cluster observed: {evidence.observedAt || "Not reported"} ·
              Sources analyzed: {evidence.analyzedAt || "Not analyzed"}.
              Repository matches do not verify the deployed Git revision.
              Selected artifact extraction follows scope selection.
            </p>
          )}
        </>
      )}
    </section>
  );
}
