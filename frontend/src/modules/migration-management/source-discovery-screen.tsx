"use client";

import { useEffect, useState } from "react";
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
import shared from "./source-connection-screen.module.css";
import styles from "./source-discovery-screen.module.css";

const workloadKinds = new Set([
  "Deployment",
  "StatefulSet",
  "DaemonSet",
  "Job",
  "CronJob",
]);
const steps = [
  "Source connection",
  "Discovery & assessment",
  "Migration scope",
  "Target & compatibility",
  "Review & approval",
  "Execute",
];

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
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("");
  const [namespace, setNamespace] = useState("");
  const [resourcePage, setResourcePage] = useState(0);
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
    queryFn: () => sourceClusters.get(sourceId),
    enabled: Boolean(sourceId),
    retry: false,
  });
  const running = sourceDiscoveryRunning(migration?.status ?? "");
  useEffect(() => {
    if (!running) {
      setTimedOut(false);
      return;
    }
    const timer = setTimeout(() => setTimedOut(true), 120000);
    return () => clearTimeout(timer);
  }, [running]);
  const ready = Boolean(
    migration &&
    sourceWorkspaceReady(migration, assessment ?? null, inventory ?? null),
  );
  const findings =
    assessment?.findings.filter((item) => !item.code.startsWith("TARGET_")) ??
    [];
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

  async function run() {
    if (!migration || busy || !sourceOwned) return;
    setBusy(true);
    setError("");
    try {
      // Re-read the version immediately before the explicit user action.
      const current = await migrations.get(migrationId);
      if (current.status === "INVENTORY_READY")
        await migrations.assess(migrationId, current.version);
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
      <ol
        className={`${shared.journey} ${styles.journey}`}
        aria-label="Migration workflow"
      >
        {steps.map((step, index) => (
          <li key={step} aria-current={index === 1 ? "step" : undefined}>
            <span>{index === 0 ? <CheckCircle2 size={16} /> : index + 1}</span>
            {step}
          </li>
        ))}
      </ol>
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
          <span>Application inventory · system namespaces excluded</span>
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
      <section
        className={`${shared.panel} ${styles.run}`}
        aria-label="Discovery progress"
      >
        <div className={styles.phase}>
          {running ? (
            <LoaderCircle className={shared.spinner} size={24} />
          ) : ready ? (
            <CheckCircle2 size={24} />
          ) : (
            <Search size={24} />
          )}
          <div>
            <h2>{phase}</h2>
            <p>
              {running
                ? "Collecting source evidence. This panel stays visible while status updates in the background."
                : ready
                  ? "Inventory and findings are saved. Choose migration scope in the workspace next."
                  : canAssess
                    ? "The connector has discovered the namespace catalogue. Run the source assessment to collect detailed resource evidence."
                    : "Discover namespaces first, then assess application workloads and their associated resources."}
            </p>
          </div>
        </div>
        <div className={styles.runActions}>
          {(canStart || canAssess) && (
            <button
              className={shared.primary}
              disabled={busy || !sourceOwned || query.isError}
              onClick={run}
            >
              {busy
                ? "Starting…"
                : canAssess
                  ? "Run source assessment"
                  : "Discover source inventory"}
            </button>
          )}
          <button
            disabled={busy || query.isFetching}
            onClick={() => query.refetch()}
          >
            Refresh status
          </button>
        </div>
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
        {timedOut && (
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
                          }}
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
            <Info size={17} /> Target compatibility, deployment artifacts and
            AI-guided transformation are evaluated in later workflow steps.
          </p>
        </section>
      </div>
      <section className={shared.panel} aria-labelledby="resource-evidence">
        <div className={styles.sectionHeading}>
          <div>
            <h2 id="resource-evidence">Application resource inventory</h2>
            <p>Source namespace, workload and associated resource evidence.</p>
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
        {!assessment ? (
          <p className={shared.empty}>No assessment has completed yet.</p>
        ) : !findings.length ? (
          <p>
            No source findings were reported by the current assessment rules.
          </p>
        ) : (
          <div className={styles.findings}>
            {findings.map((item, index) => (
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
