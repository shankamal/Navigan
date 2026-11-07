"use client";

import { useRef, useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CalendarClock,
  CheckCircle2,
  ChevronRight,
  CloudCog,
  Layers3,
  LifeBuoy,
  RefreshCw,
  ShieldAlert,
} from "lucide-react";
import { clusters } from "@/modules/cluster-management/service";
import type {
  Cluster,
  EksUpgradePlan,
  EksUpgradeReadiness,
} from "@/modules/cluster-management/model";
import { hasPermission } from "@/shared/auth/permissions";
import { Button } from "@/shared/components/ui";
import type { UpgradeCluster } from "./upgrade-workspace";
import { useUpgradePlans } from "./upgrade-plan-data";
import { supportLabel } from "./support-label";
import { scheduleOverdue, useScheduleClock } from "./schedule-state";
import { containerIdentity, PlatformIdentity } from "./platform-identity";

function liveCluster(
  cluster: Cluster,
  evidence?: EksUpgradeReadiness,
): UpgradeCluster {
  const configured =
    cluster.configuration?.kubernetesVersion ??
    cluster.outputs?.kubernetesVersion;
  const current =
    evidence?.controlPlane.version ??
    (typeof configured === "string" ? configured : "Not reported");
  const target = evidence?.recommendedTarget?.version;
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
    readiness: evidence?.readiness.status ?? "WARNING",
    findings:
      evidence?.readiness.status === "READY" ? "Ready" : "Review findings",
    window: "",
    evidence,
  };
}

function ReadinessBadge({
  evidence,
  loading,
}: {
  evidence?: EksUpgradeReadiness;
  loading: boolean;
}) {
  const status = evidence?.readiness.status;
  const Icon =
    loading && !evidence
      ? RefreshCw
      : status === "READY"
        ? CheckCircle2
        : status === "BLOCKED"
          ? ShieldAlert
          : AlertTriangle;
  return (
    <span
      className={
        "upgrade-readiness-badge readiness-" +
        (status?.toLowerCase() ?? "warning")
      }
    >
      <Icon size={15} aria-hidden="true" />
      {loading && !evidence
        ? "Discovering"
        : status === "READY"
          ? "Ready"
          : status === "BLOCKED"
            ? "Blocked"
            : evidence
              ? "Review required"
              : "Unavailable"}
    </span>
  );
}

function planLabel(plan: EksUpgradePlan) {
  const labels: Partial<Record<EksUpgradePlan["status"], string>> = {
    DRAFT: "Draft · not submitted",
    SUBMITTED: "Awaiting approval",
    APPROVED: "Approved",
    SCHEDULED: "Scheduled",
    EXECUTING: "Upgrade in progress",
  };
  return labels[plan.status] ?? plan.status;
}

function UpgradeImpact({ evidence }: { evidence: EksUpgradeReadiness }) {
  const target = evidence.recommendedTarget?.version;
  return (
    <div className="table-scroll upgrade-impact-table-wrap">
      <table className="upgrade-impact-table">
        <caption className="sr-only">Proposed component changes</caption>
        <thead>
          <tr>
            <th>Component</th>
            <th>Current</th>
            <th>Target</th>
            <th>Update method / notes</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>
              <strong>Control plane</strong>
            </td>
            <td>{evidence.controlPlane.version}</td>
            <td>{target ?? "Not reported"}</td>
            <td>
              {target
                ? "Update control plane to Kubernetes " + target + "."
                : "No provider-supported sequential target reported."}
            </td>
          </tr>
          {evidence.nodeGroups.map((node) => (
            <tr key={"node-" + node.name}>
              <td>
                <strong>Managed node group</strong>
                <small>{node.name}</small>
              </td>
              <td>{node.version ?? "Not reported"}</td>
              <td>{target ?? "Not reported"}</td>
              <td>
                {!target
                  ? "Target evidence required."
                  : node.version === target
                    ? "Keep version; verify node health after the control-plane update."
                    : "Rolling update to Kubernetes " +
                      target +
                      " after compatible add-ons."}
              </td>
            </tr>
          ))}
          {evidence.addons.map((addon) => (
            <tr key={"addon-" + addon.name}>
              <td>
                <strong>Managed add-on</strong>
                <small>{addon.name}</small>
              </td>
              <td>{addon.version ?? "Not reported"}</td>
              <td>{addon.targetVersion ?? "Review required"}</td>
              <td>
                {!addon.targetVersion
                  ? "Verify a target-compatible version before planning."
                  : addon.targetVersion === addon.version
                    ? "Keep version; compatible with the proposed Kubernetes target."
                    : "Update to the provider-reported compatible version."}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function LiveUpgradeCentre({
  onPlan,
  onReview,
}: {
  onPlan: (cluster: UpgradeCluster) => void;
  onReview: (planId: string) => void;
}) {
  const [selectedId, setSelectedId] = useState("");
  const detailsRef = useRef<HTMLElement>(null);
  const plans = useUpgradePlans();
  const now = useScheduleClock();
  const fleet = useQuery({
    queryKey: ["upgrade-centre-fleet"],
    queryFn: async () => {
      const first = await clusters.list({
        page: 0,
        pageSize: 100,
        status: "ACTIVE",
      });
      const items = [...first.items];
      for (let page = 1; page < first.pagination.totalPages; page++) {
        const next = await clusters.list({
          page,
          pageSize: 100,
          status: "ACTIVE",
        });
        items.push(...next.items);
      }
      return items;
    },
    staleTime: 30_000,
  });
  const items = fleet.data ?? [];
  const readinessQueries = useQueries({
    queries: items.map((cluster) => ({
      queryKey: ["eks-upgrade-readiness", cluster.clusterId],
      queryFn: () => clusters.upgradeReadiness(cluster.clusterId),
      staleTime: 30_000,
      retry: false,
    })),
  });
  const rows = items.map((record, index) => {
    const query = readinessQueries[index];
    const evidence = query.isError ? undefined : query.data;
    const plan = plans.rows
      .filter(
        (row) =>
          row.plan.clusterId === record.clusterId &&
          ["DRAFT", "SUBMITTED", "APPROVED", "SCHEDULED", "EXECUTING"].includes(
            row.plan.status,
          ),
      )
      .sort((a, b) =>
        b.plan.updatedAt.localeCompare(a.plan.updatedAt),
      )[0]?.plan;
    return {
      ...liveCluster(record, evidence),
      identity: containerIdentity(record.platform),
      evidence,
      plan,
      query,
    };
  });
  const selected = rows.find((row) => row.id === selectedId) ?? rows[0];
  const evidence = selected?.evidence;
  const unavailable = readinessQueries.filter((query) => query.isError).length;
  const evidenceComplete = readinessQueries.every(
    (query) => !query.isPending && !query.isError,
  );
  const available = rows.filter(
    (row) => row.evidence?.recommendedTarget,
  ).length;
  const blockers = rows.reduce(
    (count, row) =>
      count +
      (row.evidence?.readiness.blockers.length ||
        (row.evidence?.readiness.status === "BLOCKED" ? 1 : 0)),
    0,
  );
  const endingSoon = rows.filter((row) => {
    const support = row.evidence?.controlPlane.support;
    const date =
      support?.supportStatus === "EXTENDED_SUPPORT"
        ? support.endOfExtendedSupportDate
        : support?.endOfStandardSupportDate;
    const end = date ? new Date(date).getTime() : NaN;
    return end > now && end <= now + 90 * 86400000;
  }).length;
  const overdueCount = plans.rows.filter(
    (row) =>
      items.some((item) => item.clusterId === row.plan.clusterId) &&
      scheduleOverdue(row.plan, now),
  ).length;
  const refreshing =
    fleet.isFetching || readinessQueries.some((query) => query.isFetching);
  const canPlan = Boolean(
    hasPermission(plans.identity, "cluster.plan") &&
    evidence?.readiness.status === "READY" &&
    evidence.recommendedTarget &&
    !selected?.query.isFetching &&
    !selected?.query.isError &&
    !plans.pending &&
    !plans.errors.length,
  );
  const review = (plan: EksUpgradePlan) => onReview(plan.planId);

  if (fleet.isPending)
    return (
      <section className="upgrade-live-message" role="status">
        <RefreshCw className="spin" />
        <p>Loading managed cluster inventory…</p>
      </section>
    );
  if (fleet.isError)
    return (
      <section className="upgrade-live-message error" role="alert">
        <AlertTriangle />
        <p>Managed clusters could not be loaded.</p>
        <Button variant="secondary" onClick={() => void fleet.refetch()}>
          Retry inventory
        </Button>
      </section>
    );
  if (!items.length)
    return (
      <section className="upgrade-live-message" role="status">
        <CloudCog />
        <p>No active managed clusters are available for upgrade planning.</p>
      </section>
    );

  const findings = evidence
    ? [...evidence.readiness.blockers, ...evidence.readiness.warnings]
    : [];
  const overdue = Boolean(
    selected?.plan && scheduleOverdue(selected.plan, now),
  );
  const planUnknown = plans.pending || plans.errors.length > 0;
  const metrics = [
    {
      label: "Upgrade available",
      value: evidenceComplete ? available : "—",
      Icon: Layers3,
      hint: "Clusters with a provider-reported sequential target",
    },
    {
      label: "Readiness blockers",
      value: evidenceComplete ? blockers : "—",
      Icon: AlertTriangle,
      hint: "Blocking provider-readiness findings",
    },
    {
      label: "Support ending soon",
      value: evidenceComplete ? endingSoon : "—",
      Icon: LifeBuoy,
      hint: "Current support phase ends within 90 days",
    },
    {
      label: "Overdue requests",
      value: planUnknown ? "—" : overdueCount,
      Icon: CalendarClock,
      hint: "Draft or submitted requests whose requested start has passed",
    },
  ];

  return (
    <div className="upgrade-centre">
      <section
        className="upgrade-centre-metrics"
        aria-label="Upgrade fleet summary"
      >
        {metrics.map(({ label, value, Icon, hint }) => (
          <div key={label} title={hint}>
            <Icon size={26} aria-hidden="true" />
            <div>
              <strong>{value}</strong>
              <span>{label}</span>
            </div>
          </div>
        ))}
      </section>

      <section
        className="upgrade-centre-inventory"
        aria-labelledby="upgrade-fleet-title"
      >
        <header className="upgrade-centre-section-heading">
          <h2 id="upgrade-fleet-title">Cluster upgrade readiness</h2>
          <Button
            variant="secondary"
            disabled={refreshing}
            onClick={() => {
              void fleet.refetch();
              for (const query of readinessQueries) void query.refetch();
              plans.refresh();
            }}
          >
            <RefreshCw size={16} className={refreshing ? "spin" : ""} />
            {refreshing ? "Refreshing" : "Refresh inventory"}
          </Button>
        </header>
        {unavailable > 0 && (
          <p className="upgrade-centre-evidence-note" role="status">
            {unavailable} cluster evidence{" "}
            {unavailable === 1 ? "request failed" : "requests failed"}. Select
            the cluster to review its status.
          </p>
        )}
        <div className="table-scroll upgrade-centre-table-wrap">
          <table className="upgrade-centre-table">
            <caption className="sr-only">
              Registered active clusters and upgrade readiness
            </caption>
            <thead>
              <tr>
                <th>Cluster</th>
                <th>Cloud</th>
                <th>Container platform</th>
                <th>Current</th>
                <th>Target</th>
                <th>Readiness</th>
                <th>Maintenance</th>
                <th>
                  <span className="sr-only">Action</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.id}
                  className={row.id === selected?.id ? "selected" : ""}
                >
                  <td>
                    <button
                      className="upgrade-cluster-link"
                      type="button"
                      aria-pressed={row.id === selected?.id}
                      onClick={() => setSelectedId(row.id)}
                    >
                      <strong>{row.name}</strong>
                      <span>{row.environment}</span>
                    </button>
                  </td>
                  <td>
                    <PlatformIdentity identity={row.identity} kind="cloud" />
                  </td>
                  <td>
                    <PlatformIdentity identity={row.identity} kind="platform" />
                  </td>
                  <td>
                    {row.query.isError ? "Unavailable" : row.currentVersion}
                  </td>
                  <td>
                    {row.query.isError ? "Unavailable" : row.targetVersion}
                  </td>
                  <td>
                    <ReadinessBadge
                      evidence={row.evidence}
                      loading={row.query.isPending}
                    />
                  </td>
                  <td>
                    <div className="upgrade-maintenance-cell">
                      {planUnknown ? (
                        <span>
                          {plans.pending
                            ? "Loading plans…"
                            : "Plan records unavailable"}
                        </span>
                      ) : row.plan ? (
                        <>
                          <span
                            className={
                              scheduleOverdue(row.plan, now)
                                ? "upgrade-overdue-text"
                                : ""
                            }
                          >
                            {scheduleOverdue(row.plan, now)
                              ? "Overdue"
                              : planLabel(row.plan)}
                          </span>
                          <button
                            className="upgrade-row-action"
                            aria-label={"Review plan for " + row.name}
                            onClick={() => review(row.plan!)}
                          >
                            Review plan
                          </button>
                        </>
                      ) : (
                        <span>No active plan</span>
                      )}
                    </div>
                  </td>
                  <td>
                    <button
                      className="upgrade-row-action"
                      aria-label={"View upgrade details for " + row.name}
                      onClick={() => {
                        setSelectedId(row.id);
                        detailsRef.current?.scrollIntoView?.({
                          block: "nearest",
                          behavior: "auto",
                        });
                      }}
                    >
                      <ChevronRight size={18} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {selected && (
        <section
          ref={detailsRef}
          className="upgrade-centre-impact"
          aria-labelledby="upgrade-impact-title"
        >
          <div className="upgrade-impact-heading">
            <div>
              <h2 id="upgrade-impact-title">What this upgrade includes</h2>
              <div className="upgrade-impact-context">
                <strong>{selected.name}</strong>
                <PlatformIdentity identity={selected.identity} kind="cloud" />
                <PlatformIdentity
                  identity={selected.identity}
                  kind="platform"
                />
                <span>{evidence?.region ?? "Region unavailable"}</span>
              </div>
              <p className="upgrade-proposed-change">
                <strong>Proposed change</strong>
                <span>
                  Kubernetes {selected.currentVersion} →{" "}
                  {evidence?.recommendedTarget?.version ??
                    "No supported target reported"}
                </span>
              </p>
              <p className="upgrade-impact-observed">
                Support:{" "}
                {supportLabel(evidence?.controlPlane.support?.supportStatus)}
                {evidence
                  ? " · Observed " +
                    new Date(evidence.observedAt).toLocaleString()
                  : ""}
              </p>
            </div>
            <div
              className={
                "upgrade-impact-status" + (overdue ? " is-overdue" : "")
              }
            >
              {overdue ? (
                <AlertTriangle size={23} aria-hidden="true" />
              ) : evidence?.readiness.status === "READY" ? (
                <CheckCircle2 size={23} aria-hidden="true" />
              ) : (
                <AlertTriangle size={23} aria-hidden="true" />
              )}
              <div>
                <strong>
                  {overdue
                    ? "Existing maintenance request overdue—choose a new time."
                    : selected.plan
                      ? planLabel(selected.plan)
                      : evidence?.readiness.status === "READY"
                        ? "Provider readiness checks passed."
                        : selected.query.isPending
                          ? "Collecting provider readiness evidence."
                          : "Review readiness before planning."}
                </strong>
                {selected.plan?.scheduledFor && (
                  <p>
                    {overdue ? "Expired request: " : "Requested time: "}
                    {new Date(selected.plan.scheduledFor).toLocaleString()}
                  </p>
                )}
                {selected.plan ? (
                  <button
                    className="upgrade-row-action"
                    onClick={() => review(selected.plan!)}
                  >
                    Review existing plan
                  </button>
                ) : (
                  <p>Creating a plan does not start an upgrade.</p>
                )}
              </div>
            </div>
          </div>
          {selected.query.isError && (
            <div className="upgrade-blocker-notice" role="alert">
              <strong>Live evidence unavailable</strong>
              <p>Refresh inventory to retry the provider checks.</p>
            </div>
          )}
          {findings.length > 0 && (
            <div
              className={
                evidence?.readiness.status === "BLOCKED"
                  ? "upgrade-blocker-notice"
                  : "upgrade-warning-notice"
              }
            >
              <div>
                <strong>
                  {findings.length} readiness{" "}
                  {findings.length === 1 ? "finding" : "findings"}
                </strong>
                <ul>
                  {findings.map((finding) => (
                    <li key={finding.code + finding.message}>
                      {finding.message}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}
          {evidence && <UpgradeImpact evidence={evidence} />}
          {!selected.plan && (
            <div className="upgrade-impact-actions">
              <Button disabled={!canPlan} onClick={() => onPlan(selected)}>
                Create upgrade plan
              </Button>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
