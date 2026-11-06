"use client";

import { useMemo, useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronRight,
  CloudCog,
  RefreshCw,
  ShieldAlert,
} from "lucide-react";
import { clusters } from "@/modules/cluster-management/service";
import type {
  Cluster,
  EksUpgradeReadiness,
} from "@/modules/cluster-management/model";
import { Button } from "@/shared/components/ui";
import type { UpgradeCluster } from "./upgrade-workspace";

function configuredVersion(cluster: Cluster): string {
  const configuration = cluster.configuration ?? {};
  const outputs = cluster.outputs ?? {};
  const value =
    configuration.kubernetesVersion ??
    outputs.kubernetesVersion ??
    outputs.clusterVersion;
  return typeof value === "string" && value ? value : "Not reported";
}

function liveCluster(
  cluster: Cluster,
  evidence?: EksUpgradeReadiness,
): UpgradeCluster {
  const current = evidence?.controlPlane.version ?? configuredVersion(cluster);
  const target = evidence?.recommendedTarget?.version;
  const readiness = evidence?.readiness.status ?? "WARNING";
  const findings = evidence
    ? [...evidence.readiness.blockers, ...evidence.readiness.warnings].map(
        (item) => item.message,
      )
    : ["Live Amazon EKS readiness evidence is unavailable."];
  return {
    id: cluster.clusterId,
    name: cluster.clusterName,
    environment: cluster.environmentName ?? "Environment",
    provider: "EKS",
    providerLabel: "Amazon EKS",
    currentVersion: current,
    targetVersion: target ?? "Not reported",
    path: target ? [current, target] : [current],
    support:
      evidence?.controlPlane.support?.supportStatus === "EXTENDED_SUPPORT"
        ? "EXTENDED_SUPPORT"
        : "SUPPORTED",
    readiness,
    findings: findings.length
      ? `${findings.length} ${findings.length === 1 ? "finding" : "findings"}`
      : "Ready",
    window: "Not scheduled",
    evidence,
  };
}

function ReadinessBadge({ value }: { value: UpgradeCluster["readiness"] }) {
  const Icon =
    value === "READY"
      ? CheckCircle2
      : value === "BLOCKED"
        ? ShieldAlert
        : AlertTriangle;
  return (
    <span
      className={`upgrade-readiness-badge readiness-${value.toLowerCase()}`}
    >
      <Icon size={15} aria-hidden="true" />
      {value === "READY"
        ? "Ready"
        : value === "BLOCKED"
          ? "Blocked"
          : "Evidence unavailable"}
    </span>
  );
}

function LoadingState({ children }: { children: string }) {
  return (
    <section className="upgrade-live-message loading" role="status">
      <RefreshCw className="spin" />
      <p>{children}</p>
    </section>
  );
}

export function LiveUpgradeCentre({
  onPlan,
}: {
  onPlan: (cluster: UpgradeCluster) => void;
}) {
  const [selectedId, setSelectedId] = useState("");
  const fleet = useQuery({
    queryKey: ["upgrade-centre-fleet"],
    queryFn: () => clusters.list({ page: 0, pageSize: 100, status: "ACTIVE" }),
    staleTime: 30_000,
  });
  const items = fleet.data?.items ?? [];
  const readinessQueries = useQueries({
    queries: items.map((cluster) => ({
      queryKey: ["eks-upgrade-readiness", cluster.clusterId],
      queryFn: () => clusters.upgradeReadiness(cluster.clusterId),
      staleTime: 30_000,
      retry: false,
    })),
  });
  const rows = useMemo(
    () =>
      items.map((cluster, index) =>
        liveCluster(cluster, readinessQueries[index]?.data),
      ),
    [items, readinessQueries],
  );
  const effectiveId = rows.some((row) => row.id === selectedId)
    ? selectedId
    : (rows[0]?.id ?? "");
  const selected = rows.find((row) => row.id === effectiveId);
  const selectedQuery =
    readinessQueries[items.findIndex((item) => item.clusterId === effectiveId)];
  const evidence = selected?.evidence;
  const unavailable = readinessQueries.filter((query) => query.isError).length;
  const blocked = rows.filter(
    (row) => row.evidence?.readiness.status === "BLOCKED",
  ).length;
  const requiresAction = rows.filter(
    (row) =>
      row.evidence?.recommendedTarget ||
      row.evidence?.readiness.status === "BLOCKED",
  ).length;
  const approachingSupportEnd = rows.filter(
    (row) =>
      row.evidence?.controlPlane.support?.supportStatus === "EXTENDED_SUPPORT",
  ).length;
  const refreshing =
    fleet.isFetching || readinessQueries.some((query) => query.isFetching);

  if (fleet.isPending)
    return <LoadingState>Loading managed cluster inventory…</LoadingState>;
  if (fleet.isError)
    return (
      <section className="upgrade-live-message error" role="alert">
        <AlertTriangle />
        <p>Managed clusters could not be loaded.</p>
      </section>
    );
  if (!items.length)
    return (
      <section className="upgrade-live-message empty" role="status">
        <CloudCog />
        <p>No active managed clusters are available for upgrade planning.</p>
      </section>
    );

  const findings = evidence
    ? [...evidence.readiness.blockers, ...evidence.readiness.warnings]
    : [];
  const canPlan = Boolean(
    selected &&
    evidence?.readiness.status === "READY" &&
    evidence.recommendedTarget,
  );

  return (
    <div className="upgrade-readiness-layout">
      <section className="upgrade-fleet" aria-labelledby="upgrade-fleet-title">
        <div className="upgrade-summary-strip">
          <div>
            <strong>{requiresAction}</strong>
            <span>Clusters require action</span>
          </div>
          <div>
            <strong>{approachingSupportEnd}</strong>
            <span>Approaching end of support</span>
          </div>
          <div>
            <strong>{blocked}</strong>
            <span>Blocked by readiness findings</span>
          </div>
        </div>
        <div className="upgrade-fleet-heading">
          <div>
            <h2 id="upgrade-fleet-title">Fleet upgrade exposure</h2>
            <p>
              Live Amazon EKS support, target and readiness evidence across
              active managed clusters.
              {unavailable
                ? ` ${unavailable} cluster evidence request failed.`
                : ""}
            </p>
          </div>
          <Button
            variant="secondary"
            disabled={refreshing}
            onClick={() => {
              void fleet.refetch();
              for (const query of readinessQueries) void query.refetch();
            }}
          >
            <RefreshCw size={16} className={refreshing ? "spin" : ""} />
            {refreshing ? "Refreshing" : "Refresh inventory"}
          </Button>
        </div>
        <div className="table-scroll">
          <table className="upgrade-fleet-table">
            <thead>
              <tr>
                <th>Cluster</th>
                <th>Platform</th>
                <th>Current</th>
                <th>Recommended target</th>
                <th>Support</th>
                <th>Readiness</th>
                <th>Maintenance window</th>
                <th>
                  <span className="sr-only">Action</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((cluster, index) => (
                <tr
                  key={cluster.id}
                  className={cluster.id === effectiveId ? "selected" : ""}
                >
                  <td>
                    <button
                      type="button"
                      className="upgrade-cluster-link"
                      onClick={() => setSelectedId(cluster.id)}
                    >
                      <strong>{cluster.name}</strong>
                      <span>{cluster.environment}</span>
                    </button>
                  </td>
                  <td>
                    <span className="upgrade-provider-cell">
                      <span className="upgrade-provider-mark provider-eks">
                        EKS
                      </span>
                      Amazon EKS
                    </span>
                  </td>
                  <td>
                    {readinessQueries[index]?.isError
                      ? "Unavailable"
                      : cluster.currentVersion}
                  </td>
                  <td>
                    {readinessQueries[index]?.isError
                      ? "Unavailable"
                      : cluster.targetVersion}
                  </td>
                  <td>
                    {cluster.evidence?.controlPlane.support?.supportStatus ??
                      "Unavailable"}
                  </td>
                  <td>
                    <ReadinessBadge value={cluster.readiness} />
                  </td>
                  <td>{cluster.window}</td>
                  <td>
                    <button
                      type="button"
                      className="upgrade-row-action"
                      onClick={() => {
                        setSelectedId(cluster.id);
                        if (cluster.evidence) onPlan(cluster);
                      }}
                    >
                      {cluster.evidence?.readiness.status === "READY"
                        ? "Plan"
                        : "Review"}
                      <ChevronRight size={15} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {selected && (
        <aside
          className="upgrade-cluster-drawer"
          aria-label={`${selected.name} upgrade details`}
        >
          <div className="upgrade-drawer-title">
            <div>
              <p>Amazon EKS · {evidence?.region ?? "Region unavailable"}</p>
              <h2>{selected.name}</h2>
            </div>
            <ReadinessBadge value={selected.readiness} />
          </div>
          <dl className="upgrade-version-summary">
            <div>
              <dt>Current</dt>
              <dd>
                {selectedQuery?.isError
                  ? "Unavailable"
                  : selected.currentVersion}
              </dd>
            </div>
            <div>
              <dt>Target</dt>
              <dd>
                {selectedQuery?.isError
                  ? "Unavailable"
                  : selected.targetVersion}
              </dd>
            </div>
          </dl>
          <div className="upgrade-path">
            <h3>Provider-supported upgrade path</h3>
            <ol>
              <li className="complete">
                <span>
                  <Check size={14} />
                </span>
                <div>
                  <strong>Live pre-flight evidence</strong>
                  <p>
                    {evidence
                      ? `${evidence.nodeGroups.length} node groups, ${evidence.addons.length} add-ons and ${evidence.insights.length} insights evaluated.`
                      : "Evidence unavailable."}
                  </p>
                </div>
              </li>
              {evidence?.recommendedTarget && (
                <>
                  <li>
                    <span />
                    <div>
                      <strong>
                        Control plane {evidence.recommendedTarget.version}
                      </strong>
                      <p>Apply the next sequential EKS control-plane update.</p>
                    </div>
                  </li>
                  <li>
                    <span />
                    <div>
                      <strong>Managed add-ons</strong>
                      <p>
                        Apply only target-compatible versions reported by EKS.
                      </p>
                    </div>
                  </li>
                  <li>
                    <span />
                    <div>
                      <strong>Managed node groups</strong>
                      <p>
                        Roll each managed node group after the control plane and
                        add-ons.
                      </p>
                    </div>
                  </li>
                </>
              )}
              <li>
                <span />
                <div>
                  <strong>Post-upgrade validation</strong>
                  <p>Re-run EKS readiness and confirm workload health.</p>
                </div>
              </li>
            </ol>
          </div>
          {findings.length > 0 && (
            <div
              className={
                evidence?.readiness.status === "BLOCKED"
                  ? "upgrade-blocker-notice"
                  : "upgrade-warning-notice"
              }
            >
              <strong>
                <AlertTriangle size={17} /> {findings.length} readiness{" "}
                {findings.length === 1 ? "finding" : "findings"}
              </strong>
              <ul>
                {findings.slice(0, 6).map((finding) => (
                  <li key={`${finding.code}-${finding.message}`}>
                    {finding.message}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {selectedQuery?.isError && (
            <div className="upgrade-blocker-notice">
              <strong>
                <AlertTriangle size={17} /> Live evidence unavailable
              </strong>
              <p>
                Refresh the inventory after correcting the reported API error.
              </p>
            </div>
          )}
          <Button
            className="upgrade-drawer-action"
            disabled={!canPlan}
            title={
              canPlan
                ? undefined
                : "A supported target and READY evidence are required"
            }
            onClick={() => onPlan(selected)}
          >
            {canPlan
              ? "Create upgrade plan"
              : "Resolve readiness before planning"}
          </Button>
        </aside>
      )}
    </div>
  );
}
