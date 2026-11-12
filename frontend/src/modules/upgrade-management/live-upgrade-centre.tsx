"use client";
import { useState } from "react";
import { useQueries } from "@tanstack/react-query";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { clusters } from "@/modules/cluster-management/service";
import type {
  Cluster,
  EksUpgradeReadiness,
} from "@/modules/cluster-management/model";
import { Button } from "@/shared/components/ui";
import type { UpgradeCluster } from "./upgrade-workspace";
import { useUpgradePlans } from "./upgrade-plan-data";
import { containerIdentity, PlatformIdentity } from "./platform-identity";
import { planningBlockReason } from "./plan-availability";
import { ComponentPlanMetrics, planStage } from "./component-plan-metrics";
import {
  PlanScopeLabel,
  planScopes,
  scopeTypes,
  type PlanScope,
} from "./plan-scope";
import { planVersionLabel } from "./plan-scope";
import { useScheduleClock } from "./schedule-state";
import { clusterAccount } from "./cluster-context";
export function hasClusterUpgradeOpportunity(
  evidence?: EksUpgradeReadiness,
): boolean {
  if (!evidence) return false;
  const controlPlane = evidence.controlPlane.version;
  return (
    Boolean(evidence.recommendedTarget?.version) ||
    evidence.nodeGroups.some(
      (node) => Boolean(node.version) && node.version !== controlPlane,
    ) ||
    evidence.addons.some(
      (addon) =>
        Boolean(addon.targetVersion) && addon.targetVersion !== addon.version,
    )
  );
}

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

export function LiveUpgradeCentre({
  onPlan,
  onReview,
  initialView = "plans",
}: {
  onPlan: (cluster: UpgradeCluster) => void;
  onReview: (id: string | null, reschedule?: boolean) => void;
  initialView?: "plans" | "available";
}) {
  const data = useUpgradePlans(),
    now = useScheduleClock();
  const [view, setView] = useState<"plans" | "available">(initialView);
  const [type, setType] = useState<PlanScope | "all">("all");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [customer, setCustomer] = useState("all");
  const [environment, setEnvironment] = useState("all");
  const active = data.fleet.filter((c) => c.status === "ACTIVE");
  const evidence = useQueries({
    queries: active.map((c) => ({
      queryKey: ["eks-upgrade-readiness", c.clusterId],
      queryFn: () => clusters.upgradeReadiness(c.clusterId),
      staleTime: 30000,
      retry: false,
      enabled: view === "available",
    })),
  });
  const rows = data.rows.filter(
    (row) =>
      (type === "all" || planScopes(row.plan).includes(type)) &&
      (status === "all" || planStage(row.plan, now) === status) &&
      (customer === "all" || row.cluster.customerId === customer) &&
      (environment === "all" || row.cluster.environmentId === environment) &&
      [
        row.plan.planId,
        row.clusterName,
        row.cluster.customerName,
        row.environment,
        row.plan.utilityEvidence?.label,
        clusterAccount(row.cluster),
      ]
        .join(" ")
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  const overdue = data.rows.filter((r) => planStage(r.plan, now) === "Overdue");
  const customers = [
    ...new Map(
      data.fleet.map((c) => [c.customerId, c.customerName ?? c.customerId]),
    ).entries(),
  ];
  const environments = [
    ...new Map(
      data.fleet.map((c) => [
        c.environmentId,
        c.environmentName ?? c.environmentId,
      ]),
    ).entries(),
  ];
  return (
    <div className="upgrade-centre upgrade-context-workbench">
      {view === "plans" && (
        <ComponentPlanMetrics
          plans={data.rows.map((r) => r.plan)}
          loading={data.pending}
          unavailable={data.errors.length > 0}
          selected={type}
          onSelect={setType}
        />
      )}
      {data.errors.length > 0 && (
        <div role="alert" className="upgrade-blocker-notice">
          Some plan records are unavailable. Totals may be incomplete.
          <Button variant="secondary" onClick={data.refresh}>
            Retry plans
          </Button>
        </div>
      )}
      {!!overdue.length && (
        <div className="upgrade-attention-strip">
          <AlertTriangle size={18} />
          <strong>
            {overdue.length} maintenance{" "}
            {overdue.length === 1 ? "request needs" : "requests need"} a new
            time
          </strong>
          <Button
            variant="secondary"
            onClick={() => onReview(overdue[0].plan.planId, true)}
          >
            Review & reschedule
          </Button>
        </div>
      )}
      <nav
        className="upgrade-centre-tabs"
        aria-label="Upgrade Centre views"
        role="tablist"
      >
        <button
          type="button"
          role="tab"
          aria-selected={view === "plans"}
          className={view === "plans" ? "active" : ""}
          onClick={() => setView("plans")}
        >
          Saved upgrade plans
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={view === "available"}
          className={view === "available" ? "active" : ""}
          onClick={() => setView("available")}
        >
          Available cluster upgrades
        </button>
      </nav>
      {view === "plans" && (
        <section aria-label="Upgrade requests">
          <header className="upgrade-centre-section-heading">
            <div>
              <h2>Saved upgrade plans</h2>
              <p className="upgrade-section-help">
                Only created upgrade plans appear in this view.
              </p>
            </div>
            <div className="upgrade-action-group">
              <Button
                variant="secondary"
                onClick={() => {
                  data.refresh();
                  evidence.forEach((q) => void q.refetch());
                }}
              >
                <RefreshCw size={15} />
                Refresh inventory
              </Button>
            </div>
          </header>
          <div className="upgrade-centre-filters">
            <input
              aria-label="Search upgrade plans"
              placeholder="Search plans, clusters, components…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <select
              aria-label="Upgrade type"
              value={type}
              onChange={(e) => setType(e.target.value as PlanScope | "all")}
            >
              <option value="all">All types</option>
              {scopeTypes.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.label}
                </option>
              ))}
            </select>
            <select
              aria-label="Customer filter"
              value={customer}
              onChange={(e) => setCustomer(e.target.value)}
            >
              <option value="all">All customers</option>
              {customers.map(([id, name]) => (
                <option value={id} key={id}>
                  {name}
                </option>
              ))}
            </select>
            <select
              aria-label="Environment filter"
              value={environment}
              onChange={(e) => setEnvironment(e.target.value)}
            >
              <option value="all">All environments</option>
              {environments.map(([id, name]) => (
                <option value={id} key={id}>
                  {name}
                </option>
              ))}
            </select>
            <select
              aria-label="Plan status"
              value={status}
              onChange={(e) => setStatus(e.target.value)}
            >
              <option value="all">All statuses</option>
              {[
                "Draft",
                "Awaiting approval",
                "Approved",
                "Scheduled",
                "Running",
                "Overdue",
                "History",
              ].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </div>
          <div className="table-scroll">
            <table className="upgrade-request-table">
              <caption className="sr-only">
                Upgrade plans across component types
              </caption>
              <thead>
                <tr>
                  <th>Plan / scope</th>
                  <th>Customer / environment</th>
                  <th>Version change</th>
                  <th>Status / requested time</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(({ plan, cluster, clusterName, environment }) => (
                  <tr key={plan.planId}>
                    <td>
                      <strong title={plan.planId}>
                        {plan.planId.slice(0, 12)}
                      </strong>
                      <span className="upgrade-plan-cluster">
                        <PlatformIdentity
                          identity={containerIdentity(cluster.platform)}
                          kind="platform"
                        />
                        {clusterName}
                      </span>
                      <PlanScopeLabel plan={plan} />
                    </td>
                    <td>
                      {cluster.customerName ?? cluster.customerId}
                      <small>{environment}</small>
                    </td>
                    <td>{planVersionLabel(plan)}</td>
                    <td>
                      <span
                        className="upgrade-plan-status"
                        data-status={planStage(plan, now)}
                      >
                        {planStage(plan, now) === "History"
                          ? plan.status
                          : planStage(plan, now)}
                      </span>
                      <small>
                        {plan.scheduledFor
                          ? new Date(plan.scheduledFor).toLocaleString()
                          : "No time requested"}
                      </small>
                    </td>
                    <td>
                      <Button
                        variant="secondary"
                        onClick={() =>
                          onReview(
                            plan.planId,
                            planStage(plan, now) === "Overdue",
                          )
                        }
                      >
                        {planStage(plan, now) === "Overdue"
                          ? "Review & reschedule"
                          : "View plan"}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!rows.length && (
            <p role="status" className="upgrade-empty-state">
              {data.pending
                ? "Loading upgrade requests…"
                : "No upgrade requests match these filters."}
            </p>
          )}
        </section>
      )}
      {view === "available" && (
        <section
          className="upgrade-opportunities"
          tabIndex={-1}
          aria-label="Available cluster upgrades"
        >
          <header className="upgrade-centre-section-heading">
            <div>
              <h2>Available cluster upgrades</h2>
              <p>
                Only managed clusters with a control-plane, node-group, or
                EKS-managed add-on upgrade opportunity are shown.
              </p>
            </div>
          </header>
          <div className="table-scroll">
            <table className="upgrade-request-table">
              <caption className="sr-only">
                Registered active clusters and upgrade readiness
              </caption>
              <thead>
                <tr>
                  <th>Cluster / context</th>
                  <th>Distribution</th>
                  <th>Version change</th>
                  <th>Readiness</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {active.map((cluster, i) => {
                  const q = evidence[i],
                    e = q.data;
                  if (!hasClusterUpgradeOpportunity(e)) return null;
                  const existing = data.rows.find(
                    (r) =>
                      r.plan.kind !== "UTILITY" &&
                      r.plan.clusterId === cluster.clusterId &&
                      [
                        "DRAFT",
                        "SUBMITTED",
                        "APPROVED",
                        "SCHEDULED",
                        "EXECUTING",
                      ].includes(r.plan.status),
                  )?.plan;
                  const state = data.stateForCluster(cluster.clusterId);
                  const blocked = planningBlockReason(data.identity, e, {
                    readinessPending: q.isFetching,
                    readinessError: q.isError,
                    planPending: state.pending,
                    planError: state.error,
                    activePlan: existing,
                  });
                  return (
                    <tr key={cluster.clusterId}>
                      <td>
                        <strong>{cluster.clusterName}</strong>
                        <small>
                          {cluster.customerName ?? cluster.customerId} ·{" "}
                          {cluster.environmentName}
                        </small>
                      </td>
                      <td>
                        <PlatformIdentity
                          identity={containerIdentity(cluster.platform)}
                          kind="platform"
                        />
                      </td>
                      <td>
                        {e?.controlPlane.version ?? "Not reported"} →{" "}
                        {e?.recommendedTarget?.version ?? "No target reported"}
                      </td>
                      <td>
                        {q.isError
                          ? "Evidence unavailable"
                          : q.isPending
                            ? "Checking…"
                            : (e?.readiness.status ?? "Not reported")}
                      </td>
                      <td>
                        {existing ? (
                          <Button
                            variant="secondary"
                            onClick={() => onReview(existing.planId)}
                          >
                            Review existing plan
                          </Button>
                        ) : (
                          <>
                            <Button
                              disabled={!!blocked}
                              onClick={() => onPlan(liveCluster(cluster, e))}
                            >
                              Create upgrade plan
                            </Button>
                            {blocked && <small>{blocked}</small>}
                          </>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {!evidence.some((q) => q.isFetching) &&
            !active.some((_, i) =>
              hasClusterUpgradeOpportunity(evidence[i]?.data),
            ) && (
              <p role="status" className="upgrade-empty-state">
                No managed cluster upgrades are currently available.
              </p>
            )}
        </section>
      )}
    </div>
  );
}
