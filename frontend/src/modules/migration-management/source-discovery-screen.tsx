"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Search,
  LoaderCircle,
  Network,
  ShieldCheck,
  Info,
} from "lucide-react";
import { customersService } from "@/modules/customer-management/services/customers";
import { normalizeApiError } from "@/shared/api/client";
import { migrations, sourceClusters } from "./service";
import {
  sourceDiscoveryRunning,
  sourceWorkspaceReady,
} from "./source-discovery-state";
import { SourceConnectionsPanel } from "./source-connections-panel";
import { deploymentDiscovery } from "./deployment-evidence-service";
import { DeploymentEvidencePanel } from "./deployment-evidence-panel";
import { MigrationWorkflow } from "./migration-workflow";
import shared from "./source-connection-screen.module.css";
import styles from "./source-discovery-screen.module.css";

const workloadKinds = new Set([
  "Deployment",
  "StatefulSet",
  "DaemonSet",
  "Job",
  "CronJob",
]);

export function useSourceDiscoverySnapshot(
  migrationId: string,
  pollingEnabled = true,
) {
  return useQuery({
    queryKey: ["source-discovery", migrationId],
    queryFn: async ({ signal }) => {
      const migration = await migrations.get(migrationId, signal);
      const [catalogue, inventory, assessment] = await Promise.all([
        migrations.sourceCatalogue(migrationId, signal),
        migrations.sourceInventory(migrationId, signal),
        migrations.assessment(migrationId, signal),
      ]);
      return {
        migration,
        catalogue: catalogue.catalogue,
        inventory: inventory.inventory,
        assessment: assessment.assessment,
      };
    },
    retry: false,
    refetchInterval: (query) =>
      pollingEnabled &&
      sourceDiscoveryRunning(query.state.data?.migration.status ?? "")
        ? 5000
        : false,
    refetchOnWindowFocus: false,
  });
}

export function SourceDiscoveryScreen({
  migrationId,
}: {
  migrationId: string;
}) {
  const [timedOut, setTimedOut] = useState(false);
  const query = useSourceDiscoverySnapshot(migrationId, !timedOut);
  const cache = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [repairUntil, setRepairUntil] = useState(0);
  const [recoveryMessage, setRecoveryMessage] = useState("");
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("");
  const [namespace, setNamespace] = useState("");
  const [resourcePage, setResourcePage] = useState(0);
  const [findingGroup, setFindingGroup] = useState("application");
  const resourceInventoryRef = useRef<HTMLElement>(null);
  const migration = query.data?.migration;
  const catalogue = query.data?.catalogue;
  const inventory = query.data?.inventory;
  const assessment = query.data?.assessment;
  const sourceId = String(migration?.sourceConfiguration.sourceClusterId ?? "");
  const customerQuery = useQuery({
    queryKey: ["customer", migration?.customerId],
    queryFn: ({ signal }) =>
      customersService.detail(migration!.customerId, signal),
    enabled: Boolean(migration),
    retry: false,
  });
  const sourceQuery = useQuery({
    queryKey: ["discovery-source", sourceId],
    queryFn: () => sourceClusters.get(sourceId, true),
    enabled: Boolean(sourceId),
    retry: false,
    refetchInterval:
      repairUntil ||
      (!timedOut && sourceDiscoveryRunning(migration?.status ?? ""))
        ? 5000
        : false,
    refetchOnWindowFocus: false,
  });
  const connectionSettings = useQuery({
    queryKey: ["deployment-sources", sourceId],
    queryFn: ({ signal }) => deploymentDiscovery.settings(sourceId, signal),
    enabled: Boolean(sourceId),
    retry: false,
  });
  const seen = sourceQuery.data?.connectorLastSeenAt;
  const heartbeatAge =
    Date.now() - Date.parse(typeof seen === "string" ? seen : "");
  const sourceFresh =
    sourceQuery.data?.status === "CONNECTED" &&
    heartbeatAge >= -30000 &&
    heartbeatAge < 120000;
  const waitingForConnector = Boolean(
    sourceQuery.data &&
    !sourceFresh &&
    ["SOURCE_ENROLLMENT_PENDING", "DISCOVERY_PENDING"].includes(
      migration?.status ?? "",
    ),
  );
  const recovering = Boolean(repairUntil);
  const installationCheck = sourceQuery.data?.installationCheck;
  useEffect(() => {
    if (!repairUntil) return;
    if (sourceFresh) {
      setRepairUntil(0);
      setRecoveryMessage(
        "Source connection restored. The connector can now claim the pending discovery assignment.",
      );
      void query.refetch();
      return;
    }
    const timer = setTimeout(
      () => {
        setRepairUntil(0);
        setRecoveryMessage(
          "Recovery was requested but no recent heartbeat arrived within two minutes. Refresh status to check again; another installation has not been started.",
        );
      },
      Math.max(0, repairUntil - Date.now()),
    );
    return () => clearTimeout(timer);
  }, [repairUntil, sourceFresh, query.refetch]);
  const running = sourceDiscoveryRunning(migration?.status ?? "");
  useEffect(() => {
    if (!running) {
      setTimedOut(false);
      return;
    }
    const timer = setTimeout(() => setTimedOut(true), 120000);
    return () => clearTimeout(timer);
  }, [running, repairUntil]);
  const ready = Boolean(
    migration &&
    sourceWorkspaceReady(migration, assessment ?? null, inventory ?? null),
  );
  const findings =
    assessment?.findings.filter((item) => !item.code.startsWith("TARGET_")) ??
    [];
  const platformNamespaces = new Set([
    "kube-system",
    "kube-public",
    "kube-node-lease",
    "calico-system",
    "tigera-operator",
    "ingress-nginx",
    "headlamp",
    "navigan-migration",
  ]);
  const isPlatform = (item: (typeof findings)[number]) =>
    Boolean(item.namespace && platformNamespaces.has(item.namespace));
  const visibleFindings = findings.filter(
    (item) =>
      findingGroup === "all" ||
      (findingGroup === "platform" ? isPlatform(item) : !isPlatform(item)),
  );
  const resources = inventory?.resources ?? [];
  const kinds = resources.reduce<Record<string, number>>((counts, item) => {
    counts[item.kind] = (counts[item.kind] ?? 0) + 1;
    return counts;
  }, {});
  const namespaces = catalogue?.namespaces ?? [];
  const matchedNamespaces = namespaces.filter((item) =>
    item.name.toLowerCase().includes(filter.toLowerCase()),
  );
  const namespaceResources = resources.filter(
    (item) => !namespace || item.namespace === namespace,
  );
  const pageCount = Math.max(1, Math.ceil(namespaceResources.length / 100));
  const currentPage = Math.min(resourcePage, pageCount - 1);
  const sourceOwned = sourceQuery.data?.customerId === migration?.customerId;
  const canStart =
    migration?.status === "DRAFT" || migration?.status === "REJECTED";
  const canAssess = migration?.status === "INVENTORY_READY";

  async function restoreConnection() {
    if (!migration || busy || recovering || !installationCheck?.canRestore)
      return;
    setBusy(true);
    setError("");
    try {
      const current = await migrations.get(migrationId);
      if (
        current.customerId !== migration.customerId ||
        current.sourceConfiguration.sourceClusterId !== sourceId
      )
        throw new Error(
          "The assessment association changed. Refresh before restoring its connection.",
        );
      const latest = await sourceClusters.get(sourceId, true);
      if (
        latest.customerId !== current.customerId ||
        !latest.installationCheck?.canRestore
      )
        throw new Error(
          latest.installationCheck?.message ??
            "Recovery checks did not pass. Deploy the latest DEV backend and refresh status.",
        );
      const installation = await sourceClusters.install(
        sourceId,
        latest.version,
        migrationId,
      );
      setRecoveryMessage(
        `Restoring the existing source registration through AWS Systems Manager. Command: ${installation.commandId}. Waiting for a recent heartbeat…`,
      );
      setTimedOut(false);
      setRepairUntil(Date.now() + 120000);
      await sourceQuery.refetch();
    } catch (failure) {
      setError(
        failure instanceof Error && !("status" in failure)
          ? failure.message
          : normalizeApiError(failure).message,
      );
    } finally {
      setBusy(false);
    }
  }

  async function refreshStatus() {
    await Promise.all([
      query.refetch({ cancelRefetch: false }),
      sourceId
        ? sourceQuery.refetch({ cancelRefetch: false })
        : Promise.resolve(),
    ]);
  }

  async function run() {
    if (!migration || busy || !sourceOwned) return;
    setBusy(true);
    setError("");
    try {
      // Re-read the version immediately before the explicit user action.
      const current = await migrations.get(migrationId);
      if (current.status === "INVENTORY_READY")
        await migrations.assess(migrationId, current.version);
      else if (current.status === "ASSESSMENT_READY")
        await deploymentDiscovery.refresh(migrationId, current.version);
      else if (["DRAFT", "REJECTED"].includes(current.status))
        await migrations.discover(migrationId, current.version);
      else
        throw new Error(
          "The discovery state changed. Refresh the latest status before continuing.",
        );
      await query.refetch();
      await cache.invalidateQueries({ queryKey: ["migrations", migrationId] });
    } catch (failure) {
      setError(normalizeApiError(failure).message);
    } finally {
      setBusy(false);
    }
  }

  if (query.isPending) return <p role="status">Loading source discovery…</p>;
  if (!migration)
    return (
      <div role="alert">
        Unable to load source discovery.{" "}
        <button onClick={() => query.refetch()}>Retry</button>
      </div>
    );
  const phase = ready
    ? "Source assessment complete"
    : recovering
      ? "Restoring source connection"
      : waitingForConnector
        ? "Waiting for source connector"
        : migration.status === "INVENTORY_READY"
          ? "Namespace catalogue ready"
          : running
            ? "Source discovery in progress"
            : "Ready to discover your source";

  return (
    <div className={shared.screen}>
      <header className={shared.heading}>
        <div className={shared.titleGroup}>
          <Network size={25} />
          <div>
            <h1>Source Discovery & Assessment</h1>
            <p>Understand the source before choosing what to migrate.</p>
          </div>
        </div>
        <Link className={shared.back} href="/migrations">
          <ArrowLeft size={15} /> Back to assessments
        </Link>
      </header>
      <MigrationWorkflow
        active={2}
        completed={sourceFresh || ready ? [1] : []}
      />
      <section
        className={`${shared.panel} ${styles.context}`}
        aria-label="Migration context"
      >
        <div>
          <small>ASSESSMENT</small>
          <strong>{migration.name}</strong>
          <span>{migrationId}</span>
        </div>
        <div>
          <small>CUSTOMER</small>
          <strong>{customerQuery.data?.name ?? migration.customerId}</strong>
          <span>Target environment selected in workspace</span>
        </div>
        <div>
          <small>SOURCE CLUSTER</small>
          <strong>
            {(sourceQuery.data?.name ?? sourceId) || "No source selected"}
          </strong>
          <span>
            {sourceQuery.data?.distribution ?? "Distribution not reported"} ·{" "}
            {sourceQuery.data?.region ?? "Location not reported"}
          </span>
        </div>
        <div>
          <small>DISCOVERY ACCESS</small>
          <strong>Read-only connector</strong>
          <span>All namespaces · supported resources · read-only</span>
        </div>
      </section>
      {(sourceQuery.isError ||
        customerQuery.isError ||
        (sourceQuery.data && !sourceOwned)) && (
        <p role="alert" className={shared.error}>
          Unable to confirm the customer and source registration. Discovery is
          unavailable until ownership can be verified.{" "}
          <button
            onClick={() => {
              void sourceQuery.refetch();
              void customerQuery.refetch();
            }}
          >
            Retry context
          </button>
        </p>
      )}
      {sourceOwned && (
        <SourceConnectionsPanel
          key={sourceId}
          sourceId={sourceId}
          assessmentComplete={ready}
        />
      )}
      <section
        className={`${shared.panel} ${styles.run}`}
        aria-label="Discovery progress"
      >
        <div className={styles.phase}>
          {recovering || (running && !waitingForConnector) ? (
            <LoaderCircle className={shared.spinner} size={24} />
          ) : ready ? (
            <CheckCircle2 size={24} />
          ) : (
            <Search size={24} />
          )}
          <div>
            <h2>{phase}</h2>
            <p>
              {recovering
                ? "Restoring this customer's existing registration. Discovery will resume when its connector reports a heartbeat."
                : waitingForConnector
                  ? "The connector for this assessment's source registration has no recent heartbeat. Inventory collection is waiting; it is not making progress."
                  : running
                    ? "Collecting source evidence. This panel stays visible while status updates in the background."
                    : ready
                      ? "Inventory and findings are saved. Choose migration scope in the workspace next."
                      : canAssess
                        ? "The connector has discovered the namespace catalogue. Run the source assessment to collect detailed resource evidence."
                        : "Discover namespaces first, then assess application workloads and their associated resources."}
            </p>
          </div>
        </div>
        {(canStart || canAssess) &&
          !connectionSettings.data?.readyForDiscovery && (
            <p role="status">
              Complete Source connections above and verify access, or save the
              inventory-only choice, before starting discovery.
            </p>
          )}
        <div className={styles.runActions}>
          {(canStart ||
            canAssess ||
            (ready && migration.status === "ASSESSMENT_READY")) && (
            <button
              className={shared.primary}
              disabled={
                busy ||
                recovering ||
                !sourceOwned ||
                query.isError ||
                !sourceFresh ||
                !connectionSettings.data?.readyForDiscovery
              }
              onClick={run}
            >
              {busy
                ? "Starting…"
                : canAssess
                  ? "Run source assessment"
                  : ready
                    ? "Run discovery again"
                    : "Discover source inventory"}
            </button>
          )}
          {waitingForConnector && installationCheck?.canRestore && (
            <button
              className={shared.primary}
              disabled={busy || recovering || !sourceOwned}
              onClick={restoreConnection}
            >
              {recovering
                ? "Restoring connection…"
                : busy
                  ? "Checking recovery…"
                  : "Restore source connection"}
            </button>
          )}
          <button
            disabled={busy}
            aria-busy={query.isFetching || sourceQuery.isFetching}
            onClick={refreshStatus}
          >
            Refresh status
          </button>
        </div>
        {waitingForConnector && (
          <div className={styles.caution} role="status">
            <strong>Source registration: {sourceId}</strong>
            <p>
              Last heartbeat: {typeof seen === "string" ? seen : "Not reported"}
              .
            </p>
            <p>
              {installationCheck?.message ??
                "Recovery diagnostics are unavailable. Deploy the latest DEV backend and refresh status."}
            </p>
            {Boolean(installationCheck?.conflicts.length) && (
              <p>
                Other live registrations on this host:{" "}
                {installationCheck!.conflicts
                  .map(
                    (item) => `${item.customerName} (${item.sourceClusterId})`,
                  )
                  .join(", ")}
                . Restoring replaces the connector credentials on this
                installation; those registrations will stop receiving
                heartbeats.
              </p>
            )}
            <p>
              The existing registration is reused. No customer ownership,
              assessment scope, target environment or application workload is
              changed.
            </p>
          </div>
        )}
        {recoveryMessage && <p role="status">{recoveryMessage}</p>}
        <ol className={styles.phases}>
          {[
            "Namespace catalogue",
            "Detailed source inventory",
            "Source assessment",
          ].map((label, index) => (
            <li key={label}>
              <CheckCircle2
                size={16}
                className={
                  (index === 0 ? catalogue : index === 1 ? inventory : ready)
                    ? shared.complete
                    : styles.pending
                }
              />
              {label}
              <span>
                {(index === 0 ? catalogue : index === 1 ? inventory : ready)
                  ? "Complete"
                  : "Pending"}
              </span>
            </li>
          ))}
        </ol>
        {timedOut && !waitingForConnector && !recovering && (
          <p role="status" className={styles.caution}>
            Discovery is taking longer than expected. Check the source connector
            and API access; use Refresh status to check progress. No completed
            assessment has been inferred.
          </p>
        )}
        {query.isError && (
          <p role="alert" className={shared.error}>
            Status refresh failed. Displaying the last received evidence.
            Refresh successfully before opening the workspace.
          </p>
        )}
        {error && (
          <p role="alert" className={shared.error}>
            {error}
          </p>
        )}
      </section>
      <div className={styles.metrics}>
        {[
          ["Namespaces", catalogue ? namespaces.length : null],
          [
            "Application workloads",
            inventory
              ? Object.entries(kinds)
                  .filter(([kind]) => workloadKinds.has(kind))
                  .reduce((sum, [, count]) => sum + count, 0)
              : null,
          ],
          ["Resources assessed", inventory?.resourceCount ?? null],
          ["Source findings", assessment ? findings.length : null],
        ].map(([label, count]) => (
          <div className={shared.panel} key={String(label)}>
            <span>{label}</span>
            <strong>{count ?? "—"}</strong>
            <small>
              {count === null
                ? "Awaiting discovery"
                : "Reported source evidence"}
            </small>
          </div>
        ))}
      </div>
      <div className={styles.columns}>
        <section className={shared.panel} aria-labelledby="source-namespaces">
          <div className={styles.sectionHeading}>
            <div>
              <h2 id="source-namespaces">Discovered namespaces</h2>
              <p>
                Inspect inventory here. Select migration scope in the workspace.
              </p>
            </div>
            <label>
              Find namespace
              <input
                type="search"
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
                placeholder="Namespace name"
              />
            </label>
          </div>
          {!catalogue ? (
            <p className={shared.empty}>
              Namespace evidence will appear after discovery completes.
            </p>
          ) : (
            <div className={styles.tableScroll}>
              <table>
                <thead>
                  <tr>
                    <th>Namespace</th>
                    <th>Workloads</th>
                    <th>Services</th>
                    <th>PVCs</th>
                    <th>Inspect</th>
                  </tr>
                </thead>
                <tbody>
                  {matchedNamespaces.map((item) => (
                    <tr key={item.name}>
                      <td>
                        <strong>{item.name}</strong>
                      </td>
                      <td>
                        {Object.entries(item.resourceCounts)
                          .filter(([kind]) => workloadKinds.has(kind))
                          .reduce((sum, [, count]) => sum + count, 0)}
                      </td>
                      <td>{item.resourceCounts.Service ?? 0}</td>
                      <td>{item.resourceCounts.PersistentVolumeClaim ?? 0}</td>
                      <td>
                        <button
                          onClick={() => {
                            setNamespace(item.name);
                            setResourcePage(0);
                            resourceInventoryRef.current?.focus({
                              preventScroll: true,
                            });
                            resourceInventoryRef.current?.scrollIntoView({
                              block: "start",
                            });
                          }}
                          aria-controls="application-resource-inventory"
                        >
                          View resources
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!matchedNamespaces.length && <p>No matching namespaces.</p>}
            </div>
          )}
        </section>
        <section className={shared.panel} aria-labelledby="source-evidence">
          <h2 id="source-evidence">Source evidence</h2>
          <dl className={shared.facts}>
            <div>
              <dt>Kubernetes version</dt>
              <dd>
                {inventory?.sourceKubernetesVersion ??
                  catalogue?.sourceKubernetesVersion ??
                  "Not reported"}
              </dd>
            </div>
            <div>
              <dt>Nodes</dt>
              <dd>{catalogue?.nodeCount ?? "Not reported"}</dd>
            </div>
            <div>
              <dt>Architectures</dt>
              <dd>{catalogue?.architectures.join(", ") || "Not reported"}</dd>
            </div>
            <div>
              <dt>Observed at</dt>
              <dd>
                {inventory?.observedAt ??
                  catalogue?.observedAt ??
                  "Not reported"}
              </dd>
            </div>
          </dl>
          <p className={styles.note}>
            <ShieldCheck size={17} /> Sanitized inventory only. Secret values
            and kubeconfig contents are not displayed.
          </p>
          <p className={styles.note}>
            <Info size={17} /> Target compatibility, selective artifact
            extraction and deployment adaptation are evaluated in later workflow
            steps.
          </p>
        </section>
      </div>
      <section
        id="application-resource-inventory"
        ref={resourceInventoryRef}
        tabIndex={-1}
        className={`${shared.panel} ${styles.resourceInventory}`}
        aria-labelledby="resource-evidence"
      >
        <div className={styles.sectionHeading}>
          <div>
            <h2 id="resource-evidence">Application resource inventory</h2>
            <p aria-live="polite">
              {namespace
                ? `Showing resources in ${namespace}.`
                : "Source namespace, workload and associated resource evidence."}
            </p>
          </div>
          <label>
            Namespace
            <select
              value={namespace}
              onChange={(event) => {
                setNamespace(event.target.value);
                setResourcePage(0);
              }}
            >
              <option value="">All discovered namespaces</option>
              {namespaces.map((item) => (
                <option key={item.name}>{item.name}</option>
              ))}
            </select>
          </label>
        </div>
        {!inventory ? (
          <p className={shared.empty}>
            Run the source assessment to collect detailed resources.
          </p>
        ) : (
          <div className={styles.tableScroll}>
            <table>
              <thead>
                <tr>
                  <th>Namespace</th>
                  <th>Resource</th>
                  <th>Kind</th>
                  <th>API version</th>
                </tr>
              </thead>
              <tbody>
                {namespaceResources
                  .slice(currentPage * 100, (currentPage + 1) * 100)
                  .map((item, index) => (
                    <tr
                      key={`${item.kind}/${item.namespace}/${item.name}/${index}`}
                    >
                      <td>{item.namespace ?? "Cluster-scoped"}</td>
                      <td>{item.name ?? "Not reported"}</td>
                      <td>{item.kind}</td>
                      <td>{item.apiVersion}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
            <p>
              Showing {namespaceResources.length ? currentPage * 100 + 1 : 0}–
              {Math.min((currentPage + 1) * 100, namespaceResources.length)} of{" "}
              {namespaceResources.length} matching resources.
            </p>
            <div className={styles.pagination}>
              <button
                disabled={currentPage === 0}
                onClick={() => setResourcePage(currentPage - 1)}
              >
                Previous resources
              </button>
              <span>
                Page {currentPage + 1} of {pageCount}
              </span>
              <button
                disabled={currentPage + 1 >= pageCount}
                onClick={() => setResourcePage(currentPage + 1)}
              >
                Next resources
              </button>
            </div>
          </div>
        )}
      </section>
      {sourceOwned && (
        <div id="deployment-evidence">
          <DeploymentEvidencePanel
            hideConnections
            migration={migration}
            inventoryDigest={inventory?.inventoryDigest}
            onRefresh={() => {
              setTimedOut(false);
              void query.refetch();
            }}
          />
        </div>
      )}
      <section className={shared.panel} aria-labelledby="source-findings">
        <div className={styles.sectionHeading}>
          <div>
            <h2 id="source-findings">Source assessment findings</h2>
            <p>
              Source concerns to review during planning. These are not target
              compatibility results.
            </p>
          </div>
          <span className={shared.badge}>
            {ready ? "Assessment complete" : "Awaiting assessment"}
          </span>
        </div>
        {assessment && (
          <div className={styles.findingControls}>
            <label>
              Findings view
              <select
                aria-label="Findings view"
                value={findingGroup}
                onChange={(event) => setFindingGroup(event.target.value)}
              >
                <option value="application">
                  Application and shared dependencies (
                  {findings.filter((item) => !isPlatform(item)).length})
                </option>
                <option value="platform">
                  Platform namespaces ({findings.filter(isPlatform).length})
                </option>
                <option value="all">All findings ({findings.length})</option>
              </select>
            </label>
            <p>
              Grouped by known platform namespaces. All findings remain
              available; confirm application dependencies when selecting
              migration scope.
            </p>
          </div>
        )}
        {!assessment ? (
          <p className={shared.empty}>No assessment has completed yet.</p>
        ) : !findings.length ? (
          <p>
            No source findings were reported by the current assessment rules.
          </p>
        ) : (
          <div className={styles.findings}>
            {!visibleFindings.length && <p>No findings in this view.</p>}
            {visibleFindings.map((item, index) => (
              <article key={`${item.code}/${index}`}>
                <span className={styles.severity}>{item.severity}</span>
                <div>
                  <strong>{item.message}</strong>
                  <p>
                    {item.namespace ?? "Source cluster"}
                    {item.resourceName ? ` · ${item.resourceName}` : ""} ·{" "}
                    {item.category}
                  </p>
                  {item.remediation && <p>{item.remediation}</p>}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
      <footer className={`${shared.panel} ${styles.footer}`}>
        <div>
          <strong>
            {ready
              ? "Ready to choose migration scope"
              : "Complete source discovery and assessment to continue"}
          </strong>
          <p>
            The workspace continues with source scope, target selection and
            compatibility, review and approval, then execution.
          </p>
        </div>
        {ready && !query.isError ? (
          <Link
            className={shared.back}
            href={`/migrations/${migrationId}/plan`}
          >
            Open Migration Workspace <ArrowRight size={16} />
          </Link>
        ) : (
          <button
            disabled
            title="Requires completed discovery, matching inventory and assessment evidence, and a successful status refresh."
          >
            Open Migration Workspace <ArrowRight size={16} />
          </button>
        )}
      </footer>
    </div>
  );
}
