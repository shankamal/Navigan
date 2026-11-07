"use client";

import { ClusterContext } from "./cluster-context";
import { UpgradeMetrics } from "./upgrade-metrics";
import { Fragment, useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  Cpu,
  ChevronDown,
  Puzzle,
  CheckCircle2,
  ChevronRight,
  CloudCog,
  Layers3,
  RefreshCw,
  ShieldAlert,
} from "lucide-react";
import { clusters } from "@/modules/cluster-management/service";
import type {
  Cluster,
  EksUpgradePlan,
  EksUpgradeReadiness,
} from "@/modules/cluster-management/model";
import { Button } from "@/shared/components/ui";
import type { UpgradeCluster } from "./upgrade-workspace";
import { useUpgradePlans } from "./upgrade-plan-data";
import { supportLabel } from "./support-label";
import { scheduleOverdue, useScheduleClock } from "./schedule-state";
import { containerIdentity, PlatformIdentity } from "./platform-identity";
import {
  planningBlockReason,
  rescheduleBlockReason,
} from "./plan-availability";

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

function ClusterChanges({
  evidence,
  overdue,
  plan,
}: {
  evidence: EksUpgradeReadiness;
  overdue: boolean;
  plan?: EksUpgradePlan;
}) {
  const target = evidence.recommendedTarget?.version;
  const findings = [
    ...evidence.readiness.blockers,
    ...evidence.readiness.warnings,
  ];
  return (
    <>
      <ul
        className="upgrade-change-cards"
        aria-label="Proposed component changes"
      >
        <li>
          <Cpu size={30} aria-hidden="true" />
          <div>
            <strong>Control plane</strong>
            <span>
              {evidence.controlPlane.version} →{" "}
              {target ?? "Target not reported"}
            </span>
          </div>
        </li>
        {evidence.nodeGroups.map((node) => (
          <li key={"node-" + node.name}>
            <Layers3 size={30} aria-hidden="true" />
            <div>
              <strong>Managed node group {node.name}</strong>
              <span>
                {node.version ?? "Not reported"} →{" "}
                {target ?? "Target not reported"}
              </span>
              <small>
                {node.version === target
                  ? "Keep version; verify node health"
                  : "Rolling update after compatible add-ons"}
              </small>
            </div>
          </li>
        ))}
        {evidence.addons.map((addon) => (
          <li key={"addon-" + addon.name}>
            <Puzzle size={30} aria-hidden="true" />
            <div>
              <strong>Managed add-on</strong>
              <span>{addon.name}</span>
              <small>
                {!addon.targetVersion
                  ? "Verify target compatibility"
                  : addon.targetVersion === addon.version
                    ? "Keep " + addon.version + "; target-compatible"
                    : (addon.version ?? "Not reported") +
                      " → " +
                      addon.targetVersion}
              </small>
            </div>
          </li>
        ))}
      </ul>
      <p className="upgrade-expanded-guidance">
        {evidence.readiness.status === "READY"
          ? overdue
            ? "Cluster readiness passed. Choose a future maintenance time before submitting again."
            : "Provider readiness checks passed. A plan requires independent approval before execution."
          : "Review the provider findings before creating or submitting a plan."}
      </p>
      {findings.length > 0 && (
        <ul className="upgrade-expanded-findings">
          {findings.map((finding) => (
            <li key={finding.code + finding.message}>{finding.message}</li>
          ))}
        </ul>
      )}
      {overdue && plan?.scheduledFor && (
        <p className="upgrade-expired-time">
          <strong>Expired:</strong>{" "}
          {new Date(plan.scheduledFor).toLocaleString()} ·{" "}
          {Intl.DateTimeFormat().resolvedOptions().timeZone}
        </p>
      )}
      <p className="upgrade-expanded-observed">
        {evidence.region} · Support:{" "}
        {supportLabel(evidence.controlPlane.support?.supportStatus)} · Evidence
        observed {new Date(evidence.observedAt).toLocaleString()}
      </p>
    </>
  );
}

export function LiveUpgradeCentre({
  onPlan,
  onReview,
}: {
  onPlan: (cluster: UpgradeCluster) => void;
  onReview: (planId: string | null, reschedule?: boolean) => void;
}) {
  const [expandedId, setExpandedId] = useState<string | null>();
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
          row.plan.kind !== "UTILITY" &&
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
      record,
      identity: containerIdentity(record.platform),
      evidence,
      plan,
      query,
    };
  });
  const openId = expandedId === undefined ? rows[0]?.id : expandedId;
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
  const overdueRequests = plans.rows.filter(
    (row) =>
      items.some((item) => item.clusterId === row.plan.clusterId) &&
      scheduleOverdue(row.plan, now),
  );
  const overdueCount = overdueRequests.length;
  const refreshing =
    fleet.isFetching || readinessQueries.some((query) => query.isFetching);
  const blockReason = (row: (typeof rows)[number]) => {
    const state = plans.stateForCluster(row.id);
    return planningBlockReason(plans.identity, row.evidence, {
      readinessPending: row.query.isFetching,
      readinessError: row.query.isError,
      planPending: state.pending,
      planError: state.error,
      activePlan: row.plan,
    });
  };
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

  const planUnknown = plans.pending || plans.errors.length > 0;
  return (
    <div className="upgrade-centre upgrade-accordion-centre">
      <UpgradeMetrics
        ready={
          rows.filter((row) => row.evidence?.readiness.status === "READY")
            .length
        }
        blocked={
          rows.filter((row) => row.evidence?.readiness.status === "BLOCKED")
            .length
        }
        review={
          rows.filter((row) => row.evidence?.readiness.status === "WARNING")
            .length
        }
        unknown={rows.filter((row) => !row.evidence).length}
        plans={plans.rows.map((row) => row.plan)}
        loading={refreshing || plans.pending}
      />
      <section
        className="upgrade-attention-strip"
        aria-label="Upgrade fleet summary"
      >
        <div className="upgrade-attention-message">
          {overdueCount > 0 && !planUnknown ? (
            <>
              <AlertTriangle size={25} aria-hidden="true" />
              <strong>
                {overdueCount} maintenance{" "}
                {overdueCount === 1 ? "request needs" : "requests need"} a new
                time
              </strong>
              <button
                className="upgrade-row-action"
                onClick={() =>
                  onReview(
                    overdueCount === 1 ? overdueRequests[0].plan.planId : null,
                    overdueCount === 1
                      ? !rescheduleBlockReason(
                          plans.identity,
                          overdueRequests[0].plan,
                        )
                      : true,
                  )
                }
              >
                {overdueCount === 1 &&
                !rescheduleBlockReason(plans.identity, overdueRequests[0].plan)
                  ? "Review & reschedule"
                  : "Review overdue requests"}
              </button>
            </>
          ) : (
            <>
              <CalendarStatus pending={planUnknown} />
              <span>
                {planUnknown
                  ? plans.pending
                    ? "Loading maintenance requests…"
                    : "Maintenance requests unavailable"
                  : "No overdue maintenance requests"}
              </span>
            </>
          )}
        </div>
        <p>
          {evidenceComplete ? available : "—"}{" "}
          {available === 1 ? "upgrade" : "upgrades"} available{" "}
          <span aria-hidden="true">·</span> {evidenceComplete ? blockers : "—"}{" "}
          readiness blockers
        </p>
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
            <RefreshCw size={18} className={refreshing ? "spin" : ""} />
            {refreshing ? "Refreshing" : "Refresh inventory"}
          </Button>
        </header>
        {unavailable > 0 && (
          <p className="upgrade-centre-evidence-note" role="status">
            {unavailable} cluster evidence{" "}
            {unavailable === 1 ? "request failed" : "requests failed"}. Expand a
            cluster to review its status.
          </p>
        )}
        <div className="table-scroll upgrade-accordion-table-wrap">
          <table className="upgrade-accordion-table">
            <caption className="sr-only">
              Registered active clusters and upgrade readiness
            </caption>
            <thead>
              <tr>
                <th>Cluster</th>
                <th>Version change</th>
                <th>Provider readiness</th>
                <th>Maintenance</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const expanded = row.id === openId;
                const overdue = Boolean(
                  row.plan && scheduleOverdue(row.plan, now),
                );
                const panelId = "upgrade-changes-" + row.id;
                const planState = plans.stateForCluster(row.id);
                const rowPlanUnknown =
                  planState.pending || Boolean(planState.error);
                const blocked = blockReason(row);
                const canReschedule = Boolean(
                  row.plan && !rescheduleBlockReason(plans.identity, row.plan),
                );
                return (
                  <Fragment key={row.id}>
                    <tr
                      className={
                        expanded
                          ? "upgrade-cluster-row is-expanded"
                          : "upgrade-cluster-row"
                      }
                    >
                      <td>
                        <div className="upgrade-accordion-cluster">
                          <button
                            className="upgrade-expand-cluster"
                            aria-expanded={expanded}
                            aria-controls={expanded ? panelId : undefined}
                            aria-label={
                              (expanded ? "Collapse " : "Expand ") + row.name
                            }
                            onClick={() =>
                              setExpandedId(expanded ? null : row.id)
                            }
                          >
                            {expanded ? (
                              <ChevronDown size={20} aria-hidden="true" />
                            ) : (
                              <ChevronRight size={20} aria-hidden="true" />
                            )}
                            <strong>{row.name}</strong>
                          </button>
                          <ClusterContext cluster={row.record} compact />
                          <div className="upgrade-cluster-identities">
                            <PlatformIdentity
                              identity={row.identity}
                              kind="cloud"
                            />
                            <PlatformIdentity
                              identity={row.identity}
                              kind="platform"
                            />
                          </div>
                        </div>
                      </td>
                      <td>
                        <span className="upgrade-version-change">
                          {row.query.isError
                            ? "Unavailable"
                            : row.currentVersion + " → " + row.targetVersion}
                        </span>
                      </td>
                      <td>
                        <ReadinessBadge
                          evidence={row.evidence}
                          loading={row.query.isPending}
                        />
                      </td>
                      <td>
                        <span
                          className={
                            overdue
                              ? "upgrade-overdue-text"
                              : "upgrade-maintenance-label"
                          }
                        >
                          {rowPlanUnknown
                            ? planState.pending
                              ? "Loading plans…"
                              : "Unavailable"
                            : row.plan
                              ? overdue
                                ? "Overdue"
                                : planLabel(row.plan)
                              : "No active plan"}
                        </span>
                        {row.plan?.scheduledFor && (
                          <small className="upgrade-window-pending">
                            {new Date(row.plan.scheduledFor).toLocaleString()}
                          </small>
                        )}
                      </td>
                      <td>
                        {row.plan && !rowPlanUnknown ? (
                          <button
                            className="upgrade-row-action"
                            onClick={() =>
                              onReview(
                                row.plan!.planId,
                                overdue && canReschedule,
                              )
                            }
                          >
                            {overdue && canReschedule
                              ? "Review & reschedule"
                              : "Review plan"}
                          </button>
                        ) : (
                          <button
                            className="upgrade-row-action"
                            disabled={Boolean(blocked)}
                            aria-describedby={"upgrade-plan-help-" + row.id}
                            aria-label={"Create plan for " + row.name}
                            onClick={() => onPlan(row)}
                          >
                            Create plan
                          </button>
                        )}
                        {!row.plan && blocked && (
                          <small
                            className="upgrade-action-help"
                            id={"upgrade-plan-help-" + row.id}
                          >
                            {blocked}
                          </small>
                        )}
                      </td>
                    </tr>
                    {expanded && (
                      <tr className="upgrade-expanded-row">
                        <td colSpan={5}>
                          <section
                            className="upgrade-expanded-changes"
                            id={panelId}
                            aria-label={"Proposed changes for " + row.name}
                          >
                            <h3>Proposed changes for {row.name}</h3>
                            {row.query.isError ? (
                              <div
                                className="upgrade-blocker-notice"
                                role="alert"
                              >
                                <strong>Live evidence unavailable</strong>
                                <p>
                                  Refresh inventory to retry the provider
                                  checks.
                                </p>
                              </div>
                            ) : row.evidence ? (
                              <ClusterChanges
                                evidence={row.evidence}
                                overdue={overdue}
                                plan={row.plan}
                              />
                            ) : (
                              <p role="status">
                                Collecting provider readiness evidence…
                              </p>
                            )}
                          </section>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function CalendarStatus({ pending }: { pending: boolean }) {
  return pending ? (
    <RefreshCw size={23} aria-hidden="true" />
  ) : (
    <CheckCircle2 size={23} aria-hidden="true" />
  );
}
