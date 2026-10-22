"use client";
import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  GitBranch,
  LoaderCircle,
  Plus,
  Trash2,
  Box,
  Database,
  Clock3,
  CheckCircle2,
  CircleMinus,
  ChevronRight,
  Search,
  Info,
  AlertTriangle,
  ExternalLink,
} from "lucide-react";
import {
  DeploymentStructure,
  ArtifactResolution,
} from "./deployment-structure";
import { ArtifactWorkspacePanel } from "./artifact-workspace-panel";
import { EvidenceDrawer } from "./evidence-drawer";
import { EvidenceCoverageRing } from "./evidence-coverage-ring";
import { useAuth } from "@/shared/auth/auth-provider";
import { hasPermission } from "@/shared/auth/permissions";
import { normalizeApiError } from "@/shared/api/client";
import {
  deploymentDiscovery,
  type DeploymentSourcesConfiguration,
} from "./deployment-evidence-service";
import { scopeKey } from "./source-migration-scope";
import { migrations } from "./service";
import type { Migration, Assessment } from "./model";
import styles from "./deployment-evidence-panel.module.css";

export function DeploymentEvidencePanel({
  migration,
  selectedKeys,
  inventoryDigest,
  onRefresh,
  hideConnections = false,
  footerAction,
  findings = [],
  onManageConnections,
  diagnosticsContent,
}: {
  migration: Migration;
  selectedKeys?: Set<string>;
  inventoryDigest?: string;
  onRefresh?: () => void;
  hideConnections?: boolean;
  footerAction?: ReactNode;
  findings?: Assessment["findings"];
  onManageConnections?: () => void;
  diagnosticsContent?: ReactNode;
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
  const [search, setSearch] = useState("");
  const [view, setView] = useState<"overview" | "explorer" | "files">(
    "overview",
  );
  const guided = hideConnections && !selectedKeys;
  const [inspectedKey, setInspectedKey] = useState<string | null>(null);
  const [diagnostics, setDiagnostics] = useState(false);
  const analyzedInventory = useRef("");
  const [resolution, setResolution] = useState<{
    workload: import("./deployment-evidence-service").DeploymentWorkloadEvidence;
    container?: import("./deployment-evidence-service").DeploymentWorkloadEvidence["containers"][number];
  } | null>(null);
  const [evidenceNamespace, setEvidenceNamespace] = useState("");
  const [snapshots, setSnapshots] = useState<
    Record<string, { resource?: Record<string, unknown>; error?: string }>
  >({});
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
  const allWorkloads = matching ? (evidence?.workloads ?? []) : [];
  const inspected = allWorkloads.find(
    (w) =>
      scopeKey(w.workload) === inspectedKey &&
      (!selectedKeys || selectedKeys.has(scopeKey(w.workload))),
  );
  const workloads = allWorkloads.filter(
    (r) =>
      (!search ||
        `${r.workload.name} ${r.workload.namespace ?? ""} ${r.containers.map((c) => c.configuredImage).join(" ")}`
          .toLowerCase()
          .includes(search.toLowerCase())) &&
      (selectedKeys
        ? selectedKeys.has(scopeKey(r.workload))
        : !evidenceNamespace || r.workload.namespace === evidenceNamespace),
  );
  const evidenceNamespaces = [
    ...new Set([
      ...(evidence?.namespaces ?? []).map((n) => n.name),
      ...allWorkloads
        .map((r) => r.workload.namespace)
        .filter((value): value is string => Boolean(value)),
    ]),
  ].sort();
  const repositoryMatched = allWorkloads.filter(
    (w) => w.candidates.length > 0,
  ).length;
  const imagesVerified = allWorkloads.filter(
    (w) =>
      w.containers.length > 0 &&
      w.containers.every((c) => c.registryEvidence?.status === "AVAILABLE"),
  ).length;
  const needsAttention = allWorkloads.filter(
    (w) =>
      !w.candidates.length ||
      w.gaps.length > 0 ||
      !w.containers.length ||
      w.containers.some((c) => c.registryEvidence?.status !== "AVAILABLE"),
  ).length;
  const formatObserved = (value: string | null) => {
    if (!value) return "Not reported";
    const date = new Date(value);
    return Number.isNaN(date.getTime())
      ? "Not reported"
      : new Intl.DateTimeFormat(undefined, {
          day: "numeric",
          month: "short",
          hour: "2-digit",
          minute: "2-digit",
          timeZoneName: "short",
        }).format(date);
  };
  const images =
    (evidenceNamespace || search) && !selectedKeys
      ? (evidence?.images ?? []).filter((image) =>
          workloads.some((w) =>
            w.containers.some((c) => c.configuredImage === image.image),
          ),
        )
      : (evidence?.images ?? []);
  async function loadSnapshot(w: (typeof workloads)[number]) {
    if (!w.clusterSnapshot || w.clusterSnapshot.resource) return;
    const key = scopeKey(w.workload);
    const snapshotKey = `${w.clusterSnapshot.inventoryDigest}/${key}`;
    try {
      const result = await cache.fetchQuery({
        queryKey: [
          "source-inventory-evidence",
          migration.migrationId,
          w.clusterSnapshot.inventoryDigest,
        ],
        queryFn: () => migrations.sourceInventory(migration.migrationId),
        staleTime: Infinity,
      });
      if (
        !result.inventory ||
        result.inventory.inventoryDigest !== w.clusterSnapshot.inventoryDigest
      )
        throw new Error(
          "Inventory changed. Refresh the discovery view before reviewing this snapshot.",
        );
      const resource = result.inventory.resources.find(
        (item) =>
          typeof item.name === "string" &&
          scopeKey({ ...item, name: item.name }) === key,
      );
      if (!resource)
        throw new Error(
          "This workload was not found in the matching inventory snapshot.",
        );
      setSnapshots((old) => ({ ...old, [snapshotKey]: { resource } }));
    } catch (failure) {
      setSnapshots((old) => ({
        ...old,
        [snapshotKey]: {
          error:
            failure instanceof Error
              ? failure.message
              : "Unable to load captured inventory.",
        },
      }));
    }
  }
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
        const hasPending = (value: typeof evidence) =>
          Boolean(
            value?.images.some((item) => item.status === "PENDING") ||
            value?.repositories.some((item) => item.status === "PENDING"),
          );
        let result = hasPending(evidence)
          ? await deploymentDiscovery.analyze(
              migration.migrationId,
              migration.version,
              true,
            )
          : await deploymentDiscovery.analyze(
              migration.migrationId,
              migration.version,
            );
        for (let batch = 1; batch < 4 && hasPending(result); batch++) {
          setNotice(
            `Continuing evidence analysis, batch ${batch + 1}. Completed checks are retained.`,
          );
          result = await deploymentDiscovery.analyze(
            migration.migrationId,
            migration.version,
            true,
          );
        }
        cache.setQueryData(
          ["deployment-evidence", migration.migrationId, inventoryDigest],
          result,
        );
        await settings.refetch();
        setNotice(
          result.coverage?.status === "WITH_GAPS"
            ? "Source analysis updated. Select a workload to review its deployment files, images and items needing attention."
            : "Analysis finished. Review candidate sources, running versions and evidence gaps.",
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
  useEffect(() => {
    if (
      !hideConnections ||
      selectedKeys ||
      !canEdit ||
      busy ||
      migration.status !== "ASSESSMENT_READY" ||
      !matching ||
      !evidence?.inventoryDigest ||
      !settings.data?.readyForDiscovery ||
      settings.data.configuration.inventoryOnly
    )
      return;
    const stale = evidence.analysisCurrent === false || !evidence.analyzedAt;
    const key = `${migration.migrationId}/${evidence.inventoryDigest}`;
    if (!stale || analyzedInventory.current === key) return;
    analyzedInventory.current = key;
    void perform("analyze");
  }, [
    hideConnections,
    selectedKeys,
    canEdit,
    busy,
    migration.status,
    migration.migrationId,
    matching,
    evidence?.inventoryDigest,
    evidence?.analyzedAt,
    evidence?.analysisCurrent,
    settings.data?.readyForDiscovery,
  ]);
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
  const sourceAnalysisAction = (
    <button
      className={hideConnections ? undefined : styles.primary}
      disabled={
        !canEdit || !!busy || editing || !evidence?.inventoryDigest || !matching
      }
      onClick={() => void perform("analyze")}
      title="Read configured repositories and referenced images. Scripts are never executed."
    >
      {busy === "analyze" && <LoaderCircle size={15} className={styles.spin} />}
      {busy === "analyze"
        ? "Analyzing sources…"
        : evidence?.analyzedAt
          ? "Recheck sources"
          : "Analyze deployment sources"}
    </button>
  );
  const actionBar = (
    <div className={hideConnections ? styles.evidenceActions : styles.heading}>
      {!hideConnections && (
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
      )}
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
          {!hideConnections &&
            !needsRuntime &&
            migration.status === "ASSESSMENT_READY" && (
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
          {!hideConnections && sourceAnalysisAction}
          {footerAction}
          {hideConnections && (
            <details
              className={styles.moreOptions}
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  event.currentTarget.open = false;
                  event.currentTarget.querySelector("summary")?.focus();
                }
              }}
            >
              <summary aria-label="More options">⋮</summary>
              <div
                className={styles.moreOptionsPanel}
                onClick={(event) => {
                  if (
                    (event.target as HTMLElement).closest(
                      "button:not(:disabled)",
                    )
                  ) {
                    const details = event.currentTarget.closest("details");
                    if (details) details.open = false;
                  }
                }}
              >
                {(!guided || view !== "overview") && sourceAnalysisAction}
                <button onClick={() => setDiagnostics(true)}>
                  Source diagnostics
                </button>
              </div>
            </details>
          )}
        </div>
      )}
    </div>
  );
  return (
    <section
      className={`${styles.panel} ${hideConnections ? styles.workbench : ""}`}
      aria-label="Deployment sources and versions"
    >
      {guided && (
        <nav
          className={styles.viewNavigation}
          aria-label="Source discovery views"
        >
          {(
            [
              ["overview", "1", "Discovery overview", "Results & next actions"],
              [
                "explorer",
                "2",
                "Workload explorer",
                "Definitions, images & checks",
              ],
              ["files", "3", "Files & images", "Collect, recover & export"],
            ] as const
          ).map(([key, number, title, description]) => (
            <button
              key={key}
              type="button"
              aria-pressed={view === key}
              onClick={() => setView(key)}
            >
              <span className={styles.viewNumber}>{number}</span>
              <span>
                <strong>{title}</strong>
                <small>{description}</small>
              </span>
            </button>
          ))}
        </nav>
      )}
      {!hideConnections && actionBar}
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
          {!selectedKeys && (
            <div className={styles.explorerHeading}>
              <div>
                <h2>
                  {guided
                    ? {
                        overview: "Discovery overview",
                        explorer: "Workload explorer",
                        files: "Files & images",
                      }[view]
                    : "Source workload explorer"}
                </h2>
                <p>
                  {guided
                    ? {
                        overview:
                          "Review the discovered inventory and source evidence before choosing your next action.",
                        explorer:
                          "Inspect workloads here. These filters do not change migration scope.",
                        files:
                          "Save deployment files and container images to your private S3 workspace.",
                      }[view]
                    : "Select a namespace and workload to review its deployment evidence."}
                </p>
              </div>
              <div className={styles.explorerActions}>
                {hideConnections && actionBar}
                {!hideConnections && (
                  <button onClick={() => setDiagnostics(true)}>
                    Source diagnostics
                  </button>
                )}
              </div>
            </div>
          )}
          {!selectedKeys && matching && (!guided || view === "overview") && (
            <section
              className={styles.discoverySummary}
              aria-label="Discovery evidence summary"
            >
              <h3 className={styles.scorecardTitle}>
                Discovered inventory & source evidence
              </h3>
              {guided &&
                (!evidence.analyzedAt ||
                  evidence.analysisCurrent === false) && (
                  <p className={styles.analysisNotice} role="status">
                    <Info size={16} aria-hidden="true" />
                    {!evidence.analyzedAt
                      ? "Deployment source checks have not completed. Zero matches do not mean files or images are missing."
                      : "Source checks need refreshing for the current inventory. The counts below show the last reported result."}
                  </p>
                )}
              <div className={styles.scorecards}>
                <div>
                  <Database size={42} aria-hidden="true" />
                  <div>
                    <strong>{evidenceNamespaces.length}</strong>
                    <b>Namespaces</b>
                    <span>Namespaces discovered</span>
                  </div>
                </div>
                <div>
                  <Box size={42} aria-hidden="true" />
                  <div>
                    <strong>{allWorkloads.length}</strong>
                    <b>Workloads</b>
                    <span>Workloads discovered</span>
                  </div>
                </div>
                <div title="Workloads with at least one matching repository definition. This does not verify the deployed Git revision.">
                  {(!guided || evidence.analyzedAt) && (
                    <EvidenceCoverageRing
                      value={repositoryMatched}
                      total={allWorkloads.length}
                      label="Repository definitions matched"
                    />
                  )}
                  <div>
                    <strong>
                      {guided && !evidence.analyzedAt
                        ? "Not checked"
                        : `${repositoryMatched} / ${allWorkloads.length}`}
                    </strong>
                    <b>Repository matched</b>
                    <span>Repository definitions matched</span>
                  </div>
                </div>
                <div title="Workloads for which every application and init container image is available in its source registry.">
                  {(!guided || evidence.analyzedAt) && (
                    <EvidenceCoverageRing
                      value={imagesVerified}
                      total={allWorkloads.length}
                      label="All container images available"
                    />
                  )}
                  <div>
                    <strong>
                      {guided && !evidence.analyzedAt
                        ? "Not checked"
                        : `${imagesVerified} / ${allWorkloads.length}`}
                    </strong>
                    <b>Images available</b>
                    <span>All container images available</span>
                  </div>
                </div>
              </div>
              <div className={styles.scorecardNote}>
                {needsAttention > 0 ? (
                  <AlertTriangle size={17} aria-hidden="true" />
                ) : (
                  <Info size={17} aria-hidden="true" />
                )}
                <strong>
                  {needsAttention > 0
                    ? `${needsAttention} workload${needsAttention === 1 ? "" : "s"} need evidence review`
                    : allWorkloads.length === 0
                      ? "Awaiting workload evidence"
                      : "No reported evidence gaps"}
                </strong>
                <span>
                  Repository matches are candidates; they do not verify the
                  deployed Git revision.
                </span>
              </div>
              {guided && (
                <div
                  className={styles.nextActions}
                  aria-label="Discovery next actions"
                >
                  <div>
                    <GitBranch size={20} />
                    <h3>Check deployment sources</h3>
                    <p>
                      Read configured repositories and check referenced images.
                      This does not collect files into S3.
                    </p>
                    {sourceAnalysisAction}
                  </div>
                  <div>
                    <Box size={20} />
                    <h3>Review workload evidence</h3>
                    <p>
                      {needsAttention} of {allWorkloads.length} workloads have
                      reported gaps or unchecked evidence.
                    </p>
                    <button onClick={() => setView("explorer")}>
                      Open workload explorer <ChevronRight size={14} />
                    </button>
                  </div>
                  <div>
                    <Database size={20} />
                    <h3>Prepare files & images</h3>
                    <p>
                      Open a saved workspace or choose namespaces to collect.
                      Target compatibility is checked later.
                    </p>
                    <button onClick={() => setView("files")}>
                      Open files & images <ChevronRight size={14} />
                    </button>
                  </div>
                </div>
              )}
            </section>
          )}
          {!selectedKeys && (!guided || view === "explorer") && (
            <div className={styles.toolbar}>
              <select
                aria-label="Evidence namespace"
                title="Filter this view only; migration scope is selected in the workspace."
                value={evidenceNamespace}
                onChange={(event) => setEvidenceNamespace(event.target.value)}
              >
                <option value="">All namespaces</option>
                {evidenceNamespaces.map((namespace) => (
                  <option key={namespace} value={namespace}>
                    {namespace}
                  </option>
                ))}
              </select>
              <label className={styles.search}>
                <Search size={16} />
                <input
                  type="search"
                  aria-label="Search workloads"
                  placeholder="Search workloads, namespace or image…"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
              </label>
              <span>
                {workloads.length} workload{workloads.length === 1 ? "" : "s"}
              </span>
            </div>
          )}
          {selectedKeys && (
            <div className={styles.scroll}>
              <table>
                <thead>
                  <tr>
                    <th>Workload</th>
                    <th>Namespace</th>
                    <th>Deployment evidence</th>
                    <th>Registry</th>
                    <th>Runtime</th>
                    <th>
                      <span className={styles.srOnly}>Inspect workload</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {workloads.map((w) => {
                    const Icon =
                      w.workload.kind === "StatefulSet"
                        ? Database
                        : ["Job", "CronJob"].includes(w.workload.kind)
                          ? Clock3
                          : Box;
                    const available =
                      w.containers.length > 0 &&
                      w.containers.every(
                        (c) => c.registryEvidence?.status === "AVAILABLE",
                      );
                    const observed = w.runtimeStatus === "OBSERVED";
                    return (
                      <tr
                        key={scopeKey(w.workload)}
                        className={
                          inspectedKey === scopeKey(w.workload)
                            ? styles.selectedRow
                            : undefined
                        }
                      >
                        <td>
                          <button
                            className={styles.workloadButton}
                            aria-haspopup="dialog"
                            aria-label={`Inspect ${w.workload.name} in ${w.workload.namespace || "cluster"}`}
                            onClick={() =>
                              setInspectedKey(scopeKey(w.workload))
                            }
                          >
                            <Icon size={21} />
                            <span>
                              <strong>{w.workload.name}</strong>
                              <small>{w.workload.kind}</small>
                            </span>
                          </button>
                        </td>
                        <td>{w.workload.namespace || "Cluster-scoped"}</td>
                        <td>
                          <span>
                            {w.artifactFormat === "Unresolved"
                              ? w.clusterSnapshot
                                ? "Cluster snapshot"
                                : "Not detected"
                              : w.artifactFormat}
                          </span>
                          <small>
                            {w.mappingStatus === "CONFIRMED"
                              ? "User-confirmed source"
                              : w.candidates.length
                                ? "Candidate · needs confirmation"
                                : "Repository not mapped"}
                          </small>
                        </td>
                        <td>
                          <span
                            className={
                              available ? styles.successText : styles.mutedText
                            }
                          >
                            {available ? (
                              <CheckCircle2 size={14} />
                            ) : (
                              <CircleMinus size={14} />
                            )}{" "}
                            {available ? "Available" : "Needs review"}
                          </span>
                          <small>
                            {w.containers.length} container
                            {w.containers.length === 1 ? "" : "s"}
                          </small>
                        </td>
                        <td>
                          <span
                            className={
                              observed ? styles.successText : styles.mutedText
                            }
                          >
                            {observed ? (
                              <CheckCircle2 size={14} />
                            ) : (
                              <CircleMinus size={14} />
                            )}{" "}
                            {observed
                              ? "Observed"
                              : w.runtimeStatus === "NO_RUNNING_EVIDENCE"
                                ? "No active Pod"
                                : w.runtimeStatus
                                    .toLowerCase()
                                    .replaceAll("_", " ")}
                          </span>
                        </td>
                        <td>
                          <button
                            className={styles.inspectButton}
                            aria-label={`View evidence for ${w.workload.name} in ${w.workload.namespace || "cluster"}`}
                            onClick={() =>
                              setInspectedKey(scopeKey(w.workload))
                            }
                          >
                            <ChevronRight size={17} />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {!workloads.length && (
                <p>
                  {selectedKeys
                    ? "Select workloads to review deployment evidence."
                    : allWorkloads.length
                      ? "No workloads match these filters."
                      : "Complete source inventory discovery to see workload evidence."}
                </p>
              )}
            </div>
          )}
          {inspected &&
            (() => {
              const w = inspected;
              return (
                <EvidenceDrawer
                  key={`${inventoryDigest}/${scopeKey(w.workload)}`}
                  title={w.workload.name}
                  subtitle={`${w.workload.kind} · ${w.workload.namespace || "Cluster-scoped"}`}
                  onClose={() => setInspectedKey(null)}
                >
                  <section className={styles.drawerSection}>
                    <h3>Repository evidence</h3>
                    <dl className={styles.evidenceFacts}>
                      {!w.candidates.length && (
                        <div>
                          <dt>Artifact type</dt>
                          <dd>
                            {w.artifactFormat === "Unresolved"
                              ? "Original artifact not mapped"
                              : w.artifactFormat}
                          </dd>
                        </div>
                      )}
                      {w.applicationVersion && (
                        <div>
                          <dt>Application version</dt>
                          <dd>{w.applicationVersion}</dd>
                        </div>
                      )}
                      {w.helmChart && (
                        <div>
                          <dt>Helm chart</dt>
                          <dd>{w.helmChart}</dd>
                        </div>
                      )}
                      {w.helmRelease && (
                        <div>
                          <dt>Helm release</dt>
                          <dd>{w.helmRelease}</dd>
                        </div>
                      )}
                    </dl>
                    {w.candidates.map((c) => (
                      <div
                        className={styles.repoEvidence}
                        key={`${c.repository}/${c.filePath}/${c.commit}`}
                      >
                        <div className={styles.artifactRow}>
                          <span title={w.artifactFormat}>
                            {w.artifactFormat ===
                            "Kubernetes manifests (candidate)"
                              ? "Manifest candidate"
                              : w.artifactFormat}
                          </span>{" "}
                          <a
                            href={`https://github.com/${c.repository}/blob/${c.commit}/${c.filePath}`}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            <GitBranch size={16} />
                            {c.repository}
                            <ExternalLink size={13} />
                          </a>
                        </div>
                        <dl className={styles.evidenceFacts}>
                          <div>
                            <dt>Path</dt>
                            <dd>{c.filePath}</dd>
                          </div>
                          <div>
                            <dt>Inspected commit</dt>
                            <dd title={c.commit}>{c.commit.slice(0, 12)}</dd>
                          </div>
                        </dl>
                        {c.match === "NAMESPACE_UNSPECIFIED" &&
                          w.mappingStatus !== "CONFIRMED" && (
                            <small>
                              Manifest namespace unspecified — confirm
                              deployment namespace and ownership.
                            </small>
                          )}
                      </div>
                    ))}
                    {!w.candidates.length && (
                      <p className={styles.mutedText}>
                        Repository not mapped. Review captured cluster evidence
                        below.
                      </p>
                    )}
                    {w.candidates.length > 0 && (
                      <div className={styles.provenanceNote}>
                        <AlertTriangle size={18} />
                        <div>
                          <strong>Deployed Git revision not verified.</strong>
                          <small>
                            Repository matches do not prove the deployed Git
                            revision.
                          </small>
                        </div>
                      </div>
                    )}
                  </section>
                  <section className={styles.drawerSection}>
                    <h3>Delivery evidence</h3>
                    <p>
                      {w.deliveryTool === "Unresolved"
                        ? "Update tool not detected"
                        : w.deliveryTool.toLowerCase().includes("kubectl")
                          ? "Updated using kubectl"
                          : w.deliveryTool.replace(
                              /\s*\(field-manager evidence\)/i,
                              "",
                            )}
                    </p>
                    {(w.deliveryEvidenceBasis === "FIELD_MANAGER" ||
                      w.deliveryTool.toLowerCase().includes("kubectl")) && (
                      <small>
                        kubectl is the command-line tool for managing
                        Kubernetes. The cluster records which tool updated this
                        resource; this does not confirm the original Git file or
                        deployment pipeline.
                      </small>
                    )}
                  </section>
                  <section className={styles.drawerSection}>
                    <h3>Container versions</h3>
                    <div className={styles.containerTableHeading}>
                      <span>Container</span>
                      <span>Image (truncated)</span>
                      <span>Registry</span>
                    </div>
                    {w.containers.map((c) => (
                      <details
                        className={styles.containerEvidence}
                        key={`${c.containerType}/${c.name}`}
                      >
                        <summary>
                          <span>
                            {c.name}
                            {c.containerType === "INIT" ? " (init)" : ""}
                          </span>
                          <small title={c.configuredImage}>
                            <span>
                              {c.configuredImage.includes("/") &&
                              /[.:]/.test(c.configuredImage.split("/")[0])
                                ? c.configuredImage.split("/")[0]
                                : "docker.io"}
                            </span>
                            <span>
                              {c.configuredImage
                                .split("/")
                                .at(-1)
                                ?.replace(
                                  /(@sha256:[a-f0-9]{12})[a-f0-9]+/i,
                                  "$1…",
                                )}
                            </span>
                          </small>
                          <span
                            className={
                              c.registryEvidence?.status === "AVAILABLE"
                                ? styles.successText
                                : styles.mutedText
                            }
                          >
                            {c.registryEvidence?.status === "AVAILABLE" ? (
                              <CheckCircle2 size={13} />
                            ) : (
                              <CircleMinus size={13} />
                            )}{" "}
                            {c.registryEvidence?.status === "AVAILABLE"
                              ? "Available"
                              : "Review"}
                          </span>
                        </summary>
                        <code>{c.configuredImage}</code>
                        <p>{c.runningPodCount} observed Pods</p>
                        {c.observedDigests.length ? (
                          c.observedDigests.map((d) => <code key={d}>{d}</code>)
                        ) : (
                          <small>Running digest not reported</small>
                        )}
                        {c.multipleRunningVersions && (
                          <small>
                            Multiple image identities — review rollout state.
                          </small>
                        )}
                        {c.digestComparison === "DIFFERENT" && (
                          <small>
                            Digests differ. A multi-architecture image index can
                            also differ from a runtime platform digest.
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
                  </section>
                  <section className={styles.drawerSection}>
                    <h3>Runtime status</h3>
                    <span
                      className={
                        w.mappingStatus === "CONFIRMED"
                          ? styles.confirmedLabel
                          : styles.badge
                      }
                    >
                      {w.mappingStatus === "CONFIRMED"
                        ? "User-confirmed source"
                        : w.mappingStatus === "CANDIDATE"
                          ? "Candidate · needs confirmation"
                          : "Repository not mapped"}
                    </span>
                    <small>
                      Runtime:{" "}
                      {w.runtimeStatus === "NO_RUNNING_EVIDENCE"
                        ? "No running Pod observed"
                        : w.runtimeStatus.toLowerCase().replaceAll("_", " ")}
                      {w.runtimeStatus === "NO_RUNNING_EVIDENCE" &&
                        ["Job", "CronJob"].includes(w.workload.kind) && (
                          <small>
                            Scheduled or completed Jobs may have no running
                            Pods. This alone does not indicate failure.
                          </small>
                        )}
                    </small>
                    {w.candidates.length > 1 && (
                      <small>Multiple matching artifacts</small>
                    )}
                    {!selectedKeys &&
                      w.candidates.length > 0 &&
                      w.mappingStatus !== "CONFIRMED" && (
                        <div>
                          <select
                            aria-label={`Source artifact for ${w.workload.name}`}
                            value={choices[scopeKey(w.workload)] ?? 0}
                            onChange={(e) =>
                              setChoices((c) => ({
                                ...c,
                                [scopeKey(w.workload)]: Number(e.target.value),
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
                              !canEdit || !!busy || editing || !settings.data
                            }
                            onClick={() => void confirmMappings([w])}
                          >
                            Confirm source
                          </button>
                        </div>
                      )}
                  </section>
                  {w.clusterSnapshot && (
                    <section className={styles.drawerSection}>
                      <h3>Captured inventory</h3>{" "}
                      {w.clusterSnapshot && (
                        <details
                          onToggle={(event) => {
                            if (event.currentTarget.open) void loadSnapshot(w);
                          }}
                        >
                          <summary>Review captured cluster inventory</summary>
                          <p>
                            Read-only sanitized evidence from{" "}
                            {w.clusterSnapshot.observedAt ||
                              "the saved discovery"}
                            . This is not a deployable manifest; deployment
                            commands and secret/configuration values are not
                            captured.
                          </p>
                          <code>
                            Inventory digest:{" "}
                            {w.clusterSnapshot.inventoryDigest || "Unavailable"}
                          </code>
                          <pre className={styles.snapshot}>
                            {snapshots[
                              `${w.clusterSnapshot.inventoryDigest}/${scopeKey(w.workload)}`
                            ]?.error ||
                              JSON.stringify(
                                w.clusterSnapshot.resource ??
                                  snapshots[
                                    `${w.clusterSnapshot.inventoryDigest}/${scopeKey(w.workload)}`
                                  ]?.resource,
                                null,
                                2,
                              ) ||
                              "Loading captured inventory…"}
                          </pre>
                        </details>
                      )}
                    </section>
                  )}
                  {w.gaps.length > 0 && (
                    <details className={styles.drawerSection}>
                      <summary>Evidence gaps ({w.gaps.length})</summary>
                      {w.gaps.map((gap) => (
                        <p key={gap}>{gap}</p>
                      ))}
                    </details>
                  )}
                </EvidenceDrawer>
              );
            })()}
          {!selectedKeys && (
            <>
              <div
                hidden={guided && view !== "files"}
                className={styles.viewContent}
              >
                <ArtifactWorkspacePanel
                  guided={guided}
                  active={guided && view === "files"}
                  key={`${migration.migrationId}/${inventoryDigest ?? ""}`}
                  migrationId={migration.migrationId}
                  version={migration.version}
                  inventoryDigest={inventoryDigest}
                  namespaces={evidenceNamespaces}
                  canEdit={canEdit}
                />
              </div>
              <div
                hidden={guided && view !== "explorer"}
                className={styles.viewContent}
              >
                <DeploymentStructure
                  workloads={workloads}
                  namespaces={evidenceNamespaces.filter(
                    (n) => !evidenceNamespace || n === evidenceNamespace,
                  )}
                  findings={findings}
                  recoveries={(evidence.recoveries ?? []).filter(
                    (job) => job.inventoryDigest === evidence.inventoryDigest,
                  )}
                  onConnect={onManageConnections}
                  onInspect={(w) => setInspectedKey(scopeKey(w.workload))}
                  onResolve={(workload, container) =>
                    setResolution({ workload, container })
                  }
                />
              </div>
            </>
          )}
          {resolution && (
            <ArtifactResolution
              migrationId={migration.migrationId}
              version={migration.version}
              inventoryDigest={
                inventoryDigest || evidence.inventoryDigest || undefined
              }
              workload={resolution.workload}
              container={resolution.container}
              jobs={evidence.recoveries || []}
              canEdit={canEdit}
              onClose={() => setResolution(null)}
            />
          )}
          {diagnostics && !selectedKeys && (
            <EvidenceDrawer
              title="Source diagnostics"
              subtitle="Collection coverage, repository index and registry checks"
              onClose={() => setDiagnostics(false)}
            >
              {diagnosticsContent}
              <section className={styles.drawerSection}>
                <h3>Collection coverage</h3>
                <p>
                  {evidence.coverage?.scope ||
                    "All discovered namespaces. Filters change this view only."}
                </p>
                {evidence.coverage?.limitations.map((gap) => (
                  <p key={gap}>{gap}</p>
                ))}
                <p>
                  Cluster observed: {evidence.observedAt || "Not reported"} ·
                  Sources analyzed: {evidence.analyzedAt || "Not analyzed"}
                </p>
              </section>
              <details className={styles.artifactIndex}>
                <summary>Repository artifact index</summary>
                <p>
                  All inspected files. A script or workflow’s presence does not
                  prove it deployed a workload.
                </p>
                {evidence.repositories.map((repo) => (
                  <section key={repo.repository}>
                    <h3>{repo.repository}</h3>
                    <small>
                      {repo.status} · inspected commit{" "}
                      {repo.commit?.slice(0, 12) || "Unavailable"}
                    </small>
                    {[...new Set(repo.artifacts.map((a) => a.filePath))].map(
                      (path) => (
                        <details key={path}>
                          <summary>{path}</summary>
                          {repo.artifacts
                            .filter((a) => a.filePath === path)
                            .map((a, i) => (
                              <p key={i}>
                                {a.format === "GITHUB_ACTIONS"
                                  ? "GitHub Actions workflow"
                                  : a.format}
                                {a.resource && (
                                  <small>
                                    {a.resource.kind} ·{" "}
                                    {a.resource.namespace ||
                                      "Namespace not specified in manifest"}{" "}
                                    · {a.resource.name}
                                  </small>
                                )}
                                {a.format === "SCRIPT" && (
                                  <small>
                                    Script found — never executed during
                                    analysis.{" "}
                                    {a.usesHelm ? "References Helm. " : ""}
                                    {a.usesKubectl
                                      ? "References kubectl. "
                                      : ""}
                                    {a.dynamicReferences
                                      ? "Dynamic references need review."
                                      : ""}
                                  </small>
                                )}
                              </p>
                            ))}
                        </details>
                      ),
                    )}
                    {repo.gaps.map((g) => (
                      <p key={g}>{g}</p>
                    ))}
                  </section>
                ))}
              </details>
              <section className={styles.drawerSection}>
                <h3>Registry checks</h3>
                <p>
                  Referenced images only. Connecting a registry does not change
                  source workload images. Availability does not verify target
                  pull access.
                </p>
                {images.map((image) => (
                  <details
                    className={styles.registryDiagnostic}
                    key={image.image}
                  >
                    <summary
                      aria-label={`Inspect registry image ${image.image}`}
                    >
                      <strong>
                        {image.image
                          .split("/")
                          .at(-1)
                          ?.replace(/(@sha256:[a-f0-9]{12})[a-f0-9]+/i, "$1…")}
                      </strong>
                      <span>
                        {image.status === "NOT_CONNECTED"
                          ? "Registry not configured"
                          : image.status.toLowerCase().replaceAll("_", " ")}
                      </span>
                    </summary>
                    <code>{image.image}</code>
                    <p>
                      {image.status === "NOT_CONNECTED"
                        ? "This image's registry has not been connected for inspection. Image availability is unknown."
                        : image.reason}
                    </p>
                    {workloads
                      .filter((w) =>
                        w.containers.some(
                          (c) => c.configuredImage === image.image,
                        ),
                      )
                      .map((w) => (
                        <small key={scopeKey(w.workload)}>
                          {w.workload.namespace} · {w.workload.kind} /{" "}
                          {w.workload.name}
                        </small>
                      ))}
                    <small>Registry digest</small>
                    <code>{image.registryDigest || "Not reported"}</code>
                    <small>
                      {image.architectures?.join(", ") ||
                        "Architecture not verified"}
                    </small>
                  </details>
                ))}
                {!images.length && <p>No image checks match this view.</p>}
              </section>
            </EvidenceDrawer>
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
              <Clock3 size={15} aria-hidden="true" />
              <span title={evidence.observedAt || undefined}>
                Last discovered: {formatObserved(evidence.observedAt)}
              </span>
              <span title={evidence.analyzedAt || undefined}>
                {" "}
                · Sources checked: {formatObserved(evidence.analyzedAt)}
              </span>
            </p>
          )}
        </>
      )}
    </section>
  );
}
