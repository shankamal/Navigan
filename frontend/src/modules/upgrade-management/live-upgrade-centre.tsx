"use client";

import { useMemo, useState } from "react";
import { useQueries } from "@tanstack/react-query";
import {
  AlertTriangle,
  CalendarClock,
  Check,
  CheckCircle2,
  Circle,
  Clock3,
  RefreshCw,
  Sparkles,
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
import { containerIdentity, PlatformIdentity } from "./platform-identity";
import { planningBlockReason } from "./plan-availability";
import { planStage } from "./component-plan-metrics";
import { Doughnut } from "./upgrade-metrics";
import { useScheduleClock } from "./schedule-state";
import { clusterAccount } from "./cluster-context";

type CentreView = "plans" | "available";
type Lifecycle =
  | "active"
  | "approval"
  | "scheduled"
  | "running"
  | "attention"
  | "upgraded";

const lifecycleTabs: ReadonlyArray<{ id: Lifecycle; label: string }> = [
  { id: "active", label: "Active" },
  { id: "approval", label: "Awaiting Approval" },
  { id: "scheduled", label: "Scheduled" },
  { id: "running", label: "In Progress" },
  { id: "attention", label: "Needs Attention" },
  { id: "upgraded", label: "Upgraded" },
];

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

function reconciliationStatus(plan: EksUpgradePlan): string | undefined {
  const value = plan.execution.iacReconciliation;
  if (!value || typeof value !== "object" || Array.isArray(value)) return;
  const status = (value as Record<string, unknown>).status;
  return typeof status === "string" ? status : undefined;
}

function isUpgraded(plan: EksUpgradePlan): boolean {
  return (
    plan.status === "SUCCEEDED" &&
    plan.execution.phase === "IAC_SYNCHRONIZED" &&
    reconciliationStatus(plan) === "SYNCHRONIZED"
  );
}

function lifecycleFor(plan: EksUpgradePlan, now: number): Lifecycle {
  if (isUpgraded(plan)) return "upgraded";
  if (
    plan.status === "FAILED" ||
    plan.status === "REJECTED" ||
    planStage(plan, now) === "Overdue"
  )
    return "attention";
  if (plan.status === "SUBMITTED") return "approval";
  if (plan.status === "EXECUTING") return "running";
  if (["APPROVED", "SCHEDULED"].includes(plan.status)) return "scheduled";
  return "active";
}

type WorkflowStep = {
  id: string;
  label: string;
  done: boolean;
  active: boolean;
};

function workflow(plan: EksUpgradePlan): WorkflowStep[] {
  const results = Array.isArray(plan.execution.results)
    ? (plan.execution.results as Array<Record<string, unknown>>)
    : [];
  const resultDone = (kind: string) =>
    results.some((item) => item.kind === kind && item.status === "SUCCEEDED");

  const currentGate =
    plan.execution.gate &&
    typeof plan.execution.gate === "object" &&
    !Array.isArray(plan.execution.gate)
      ? (plan.execution.gate as Record<string, unknown>)
      : undefined;
  const gatePendingAfter = (stage: string) =>
    currentGate?.status === "PENDING" && currentGate.afterStage === stage;

  const postValidation =
    plan.execution.postValidation &&
    typeof plan.execution.postValidation === "object" &&
    !Array.isArray(plan.execution.postValidation)
      ? (plan.execution.postValidation as Record<string, unknown>).status ===
        "PASSED"
      : false;
  const iac = reconciliationStatus(plan) === "SYNCHRONIZED";
  const upgraded = isUpgraded(plan);
  const readiness = Boolean(plan.readinessEvidence || plan.planSpec);
  const approved = Boolean(plan.approvedBy);
  const window = Boolean(plan.scheduledFor);
  const phase = String(plan.execution.phase ?? "");
  const controlDone = resultDone("CONTROL_PLANE");
  const addonNeeded =
    plan.planSpec?.steps.some((step) =>
      step.operations.some((operation) => operation.kind === "ADDON"),
    ) ?? false;
  const addonDone = addonNeeded ? resultDone("ADDON") : controlDone;
  const nodeNeeded =
    plan.planSpec?.steps.some((step) =>
      step.operations.some((operation) => operation.kind === "NODEGROUP"),
    ) ?? false;
  const nodeDone = nodeNeeded ? resultDone("NODEGROUP") : addonDone;
  const controlHealthDone =
    controlDone &&
    !gatePendingAfter("CONTROL_PLANE") &&
    (addonDone ||
      nodeDone ||
      postValidation ||
      iac ||
      upgraded ||
      phase.includes("DATA_PLANE"));
  const nodeHealthDone =
    nodeDone &&
    !gatePendingAfter("DATA_PLANE") &&
    (postValidation || iac || upgraded || phase.includes("POST_VALIDATION"));

  const definitions = [
    ["readiness", "Readiness", readiness],
    ["plan", "Plan", true],
    ["approval", "Approval", approved],
    ["window", "Maintenance Window", window],
    ["control", "Control Plane", controlDone],
    ["control-gate", "Health Gate", controlHealthDone],
    ["addons", "Add-ons", addonDone],
    ["nodes", "Node Groups", nodeDone],
    ["node-gate", "Health Gate", nodeHealthDone],
    ["validation", "Post Validation", postValidation],
    ["iac", "IaC Sync", iac],
    ["upgraded", "Upgraded", upgraded],
  ] as const;

  const firstPending = definitions.findIndex(([, , done]) => !done);
  return definitions.map(([id, label, done], index) => ({
    id,
    label,
    done,
    active:
      !upgraded &&
      (index === firstPending ||
        (id === "control" && phase.includes("CONTROL_PLANE")) ||
        (id === "control-gate" &&
          phase.includes("AWAITING_CONTROL_PLANE_HEALTH")) ||
        (id === "nodes" && phase.includes("DATA_PLANE")) ||
        (id === "node-gate" && phase.includes("AWAITING_DATA_PLANE_HEALTH")) ||
        (id === "validation" && phase.includes("POST_VALIDATION")) ||
        (id === "iac" && phase.includes("IAC_"))),
  }));
}

function progressFor(plan: EksUpgradePlan): number {
  const steps = workflow(plan);
  return Math.round(
    (steps.filter((step) => step.done).length / steps.length) * 100,
  );
}

function planStatus(plan: EksUpgradePlan, now: number): string {
  if (isUpgraded(plan)) return "Upgraded";
  const lifecycle = lifecycleFor(plan, now);
  if (lifecycle === "running") return "In Progress";
  if (lifecycle === "approval") return "Awaiting Approval";
  if (lifecycle === "attention") return "Needs Attention";
  if (lifecycle === "scheduled") return "Scheduled";
  return plan.status === "DRAFT" ? "Draft" : "Active";
}

function recommendationText(plan: EksUpgradePlan) {
  if (isUpgraded(plan))
    return [
      "Upgrade completed and IaC is synchronized.",
      "No control-plane downgrade is required or supported.",
      "Retain the execution evidence for audit and future planning.",
    ];
  if (plan.status === "EXECUTING")
    return [
      "Continue only through the governed stage gates.",
      "Validate application health before advancing a pending health gate.",
      "IaC desired state is persisted only after successful synchronization.",
    ];
  if (plan.status === "SUBMITTED")
    return [
      "Plan is waiting for Platform Architect review.",
      "Review scope, maintenance window and component impact before approval.",
      "Any changed live evidence should trigger a fresh review.",
    ];
  return [
    "Review the supported target and component scope before submission.",
    "Use an approved maintenance window for every upgrade step.",
    "Run readiness checks again if cluster state changes.",
  ];
}

export function LiveUpgradeCentre({
  onPlan,
  onReview,
  initialView = "plans",
}: {
  onPlan: (cluster: UpgradeCluster) => void;
  onReview: (id: string | null, reschedule?: boolean) => void;
  initialView?: CentreView;
}) {
  const data = useUpgradePlans();
  const now = useScheduleClock();
  const [view, setView] = useState<CentreView>(initialView);
  const [lifecycle, setLifecycle] = useState<Lifecycle>("active");
  const [search, setSearch] = useState("");
  const [customer, setCustomer] = useState("all");
  const [environment, setEnvironment] = useState("all");
  const [selectedId, setSelectedId] = useState<string>();

  const activeClusters = data.fleet.filter((cluster) => cluster.status === "ACTIVE");
  const evidence = useQueries({
    queries: activeClusters.map((cluster) => ({
      queryKey: ["eks-upgrade-readiness", cluster.clusterId],
      queryFn: () => clusters.upgradeReadiness(cluster.clusterId),
      staleTime: 30_000,
      retry: false,
      refetchOnWindowFocus: false,
      enabled: view === "available",
    })),
  });

  const customers = [
    ...new Map(
      data.fleet.map((cluster) => [
        cluster.customerId,
        cluster.customerName ?? cluster.customerId,
      ]),
    ).entries(),
  ];
  const environments = [
    ...new Map(
      data.fleet.map((cluster) => [
        cluster.environmentId,
        cluster.environmentName ?? cluster.environmentId,
      ]),
    ).entries(),
  ];

  const lifecycleCounts = useMemo(() => {
    const result: Record<Lifecycle, number> = {
      active: 0,
      approval: 0,
      scheduled: 0,
      running: 0,
      attention: 0,
      upgraded: 0,
    };
    for (const row of data.rows) {
      if (row.plan.kind === "UTILITY") continue;
      const value = lifecycleFor(row.plan, now);
      result[value] += 1;
      if (value !== "upgraded") result.active += value === "active" ? 0 : 1;
    }
    return result;
  }, [data.rows, now]);

  const planRows = data.rows.filter((row) => {
    if (row.plan.kind === "UTILITY") return false;
    const planLifecycle = lifecycleFor(row.plan, now);
    const lifecycleMatch =
      lifecycle === "active"
        ? planLifecycle !== "upgraded"
        : planLifecycle === lifecycle;
    return (
      lifecycleMatch &&
      (customer === "all" || row.cluster.customerId === customer) &&
      (environment === "all" || row.cluster.environmentId === environment) &&
      [
        row.plan.planId,
        row.clusterName,
        row.cluster.customerName,
        row.environment,
        clusterAccount(row.cluster),
      ]
        .join(" ")
        .toLowerCase()
        .includes(search.toLowerCase())
    );
  });

  const selected =
    planRows.find((row) => row.plan.planId === selectedId) ?? planRows[0];
  const selectedProgress = selected ? progressFor(selected.plan) : 0;
  const selectedWorkflow = selected ? workflow(selected.plan) : [];

  const overdue = data.rows.filter(
    (row) => row.plan.kind !== "UTILITY" && planStage(row.plan, now) === "Overdue",
  );

  return (
    <div className="upgrade-centre upgrade-context-workbench">
      <section className="upgrade-overview-strip" aria-label="Upgrade overview">
        <div>
          <span>Total clusters</span>
          <strong>{data.fleet.length}</strong>
        </div>
        <div>
          <span>Awaiting approval</span>
          <strong>{lifecycleCounts.approval}</strong>
        </div>
        <div>
          <span>Scheduled</span>
          <strong>{lifecycleCounts.scheduled}</strong>
        </div>
        <div>
          <span>In progress</span>
          <strong>{lifecycleCounts.running}</strong>
        </div>
        <div>
          <span>Needs attention</span>
          <strong>{lifecycleCounts.attention}</strong>
        </div>
        <div>
          <span>Upgraded</span>
          <strong>{lifecycleCounts.upgraded}</strong>
        </div>
      </section>

      {data.errors.length > 0 && (
        <div role="alert" className="upgrade-blocker-notice">
          Some plan records are unavailable. Available results are shown while
          the remaining inventory can be retried.
          <Button variant="secondary" onClick={data.refresh}>
            Retry plans
          </Button>
        </div>
      )}

      {!!overdue.length && view === "plans" && (
        <div className="upgrade-attention-strip">
          <AlertTriangle size={18} aria-hidden="true" />
          <strong>
            {overdue.length} maintenance{" "}
            {overdue.length === 1 ? "request needs" : "requests need"} a new time
          </strong>
          <Button
            variant="secondary"
            onClick={() => onReview(overdue[0].plan.planId, true)}
          >
            Review & reschedule
          </Button>
        </div>
      )}

      <div className="upgrade-centre-modebar">
        <nav
          className="upgrade-lifecycle-tabs"
          aria-label="Upgrade lifecycle"
          role="tablist"
        >
          {lifecycleTabs.map((item) => (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={view === "plans" && lifecycle === item.id}
              className={view === "plans" && lifecycle === item.id ? "active" : ""}
              onClick={() => {
                setView("plans");
                setLifecycle(item.id);
                setSelectedId(undefined);
              }}
            >
              {item.label}
              <span>{lifecycleCounts[item.id]}</span>
            </button>
          ))}
        </nav>
      </div>

      {view === "plans" ? (
        <div className="upgrade-centre-dashboard">
          <section className="upgrade-plan-list" aria-label="Upgrade requests">
            <div className="upgrade-centre-filters">
              <input
                aria-label="Search upgrade plans"
                placeholder="Search cluster, plan or account…"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
              <select
                aria-label="Customer filter"
                value={customer}
                onChange={(event) => setCustomer(event.target.value)}
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
                onChange={(event) => setEnvironment(event.target.value)}
              >
                <option value="all">All environments</option>
                {environments.map(([id, name]) => (
                  <option value={id} key={id}>
                    {name}
                  </option>
                ))}
              </select>
              <Button variant="secondary" onClick={data.refresh}>
                <RefreshCw size={15} aria-hidden="true" />
                Refresh
              </Button>
            </div>

            <div className="table-scroll">
              <table className="upgrade-dashboard-table">
                <caption className="sr-only">
                  Upgrade plans across managed clusters
                </caption>
                <thead>
                  <tr>
                    <th>Cluster</th>
                    <th>Current → target</th>
                    <th>Status</th>
                    <th>Progress</th>
                    <th>Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {planRows.map((row) => {
                    const progress = progressFor(row.plan);
                    const status = planStatus(row.plan, now);
                    return (
                      <tr
                        key={row.plan.planId}
                        className={selected?.plan.planId === row.plan.planId ? "selected" : ""}
                        onClick={() => setSelectedId(row.plan.planId)}
                      >
                        <td>
                          <button
                            type="button"
                            className="upgrade-cluster-link"
                            aria-pressed={selected?.plan.planId === row.plan.planId}
                            onClick={(event) => {
                              event.stopPropagation();
                              setSelectedId(row.plan.planId);
                            }}
                          >
                            <strong>{row.clusterName}</strong>
                            <span>
                              {row.environment} · {row.plan.planId.slice(0, 12)}
                            </span>
                          </button>
                        </td>
                        <td>
                          {row.plan.currentVersion} → {row.plan.targetVersion}
                        </td>
                        <td>
                          <span
                            className="upgrade-plan-status"
                            data-status={status}
                          >
                            {status}
                          </span>
                        </td>
                        <td>
                          <div className="upgrade-row-progress">
                            <strong>{progress}%</strong>
                            <span>
                              <i style={{ width: progress + "%" }} />
                            </span>
                          </div>
                        </td>
                        <td>{new Date(row.plan.updatedAt).toLocaleString()}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {!planRows.length && (
              <div className="upgrade-empty-state" role="status">
                {data.pending ? (
                  <>
                    <div className="upgrade-skeleton-line" />
                    <div className="upgrade-skeleton-line short" />
                    Loading upgrade plans…
                  </>
                ) : lifecycle === "upgraded" ? (
                  "No fully reconciled upgrades are recorded yet."
                ) : (
                  "No upgrade plans match this lifecycle view."
                )}
              </div>
            )}
          </section>

          <aside className="upgrade-selected-panel">
            {selected ? (
              <>
                <header className="upgrade-selected-header">
                  <div>
                    <strong>{selected.clusterName}</strong>
                    <span>
                      {selected.environment} · {selected.plan.currentVersion} →{" "}
                      {selected.plan.targetVersion}
                    </span>
                  </div>
                  <Button
                    variant="secondary"
                    onClick={() =>
                      onReview(
                        selected.plan.planId,
                        planStage(selected.plan, now) === "Overdue",
                      )
                    }
                  >
                    View Plan
                  </Button>
                </header>

                <section className="upgrade-selected-progress">
                  <div>
                    <Doughnut
                      total={100}
                      label={isUpgraded(selected.plan) ? "Upgraded" : "In progress"}
                      centerValue={selectedProgress + "%"}
                      slices={[
                        {
                          label: "Complete",
                          count: selectedProgress,
                          color: "#26890d",
                        },
                        {
                          label: "Remaining",
                          count: 100 - selectedProgress,
                          color: "#d9dee3",
                        },
                      ]}
                    />
                  </div>
                  <div>
                    <span>Upgrade progress</span>
                    <strong>{selectedProgress}%</strong>
                    <p>
                      {
                        selectedWorkflow.filter((step) => step.done).length
                      }{" "}
                      of {selectedWorkflow.length} stages complete
                    </p>
                  </div>
                  <div className="upgrade-selected-time">
                    <span>
                      <CalendarClock size={15} />
                      {selected.plan.scheduledFor
                        ? new Date(selected.plan.scheduledFor).toLocaleString()
                        : "Maintenance window not requested"}
                    </span>
                    <span>
                      <Clock3 size={15} />
                      Updated {new Date(selected.plan.updatedAt).toLocaleString()}
                    </span>
                  </div>
                </section>

                <section className="upgrade-workflow-card">
                  <h3>Upgrade workflow</h3>
                  <ol className="upgrade-workflow-track">
                    {selectedWorkflow.map((step) => (
                      <li
                        key={step.id}
                        className={
                          step.done ? "done" : step.active ? "active" : ""
                        }
                      >
                        <span>
                          {step.done ? (
                            <Check size={14} aria-hidden="true" />
                          ) : (
                            <Circle size={12} aria-hidden="true" />
                          )}
                        </span>
                        <small>{step.label}</small>
                      </li>
                    ))}
                  </ol>
                </section>

                <section className="upgrade-advisor-card">
                  <header>
                    <Sparkles size={18} aria-hidden="true" />
                    <div>
                      <h3>Navigan AI Upgrade Advisor</h3>
                      <span>Preview · deterministic guidance for now</span>
                    </div>
                  </header>
                  <ul>
                    {recommendationText(selected.plan).map((item) => (
                      <li key={item}>
                        <CheckCircle2 size={16} aria-hidden="true" />
                        {item}
                      </li>
                    ))}
                  </ul>
                </section>
              </>
            ) : (
              <div className="upgrade-empty-state">
                Select an upgrade plan to view progress and workflow.
              </div>
            )}
          </aside>
        </div>
      ) : (
        <section
          className="upgrade-opportunities"
          tabIndex={-1}
          aria-label="Available cluster upgrades"
        >
          <header className="upgrade-centre-section-heading">
            <div>
              <h2>Create Upgrade Plan</h2>
              <p>
                Readiness is loaded only for this view so the Upgrade Centre can
                open quickly. Choose a managed cluster after its evidence is
                available.
              </p>
            </div>
            <Button
              variant="secondary"
              onClick={() => {
                setView("plans");
                setLifecycle("active");
              }}
            >
              Back to Upgrade Centre
            </Button>
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
                {activeClusters.map((cluster, index) => {
                  const query = evidence[index];
                  const readiness = query.data;
                  const existing = data.rows.find(
                    (row) =>
                      row.plan.kind !== "UTILITY" &&
                      row.plan.clusterId === cluster.clusterId &&
                      [
                        "DRAFT",
                        "SUBMITTED",
                        "APPROVED",
                        "SCHEDULED",
                        "EXECUTING",
                      ].includes(row.plan.status),
                  )?.plan;
                  const state = data.stateForCluster(cluster.clusterId);
                  const blocked = planningBlockReason(data.identity, readiness, {
                    readinessPending: query.isFetching,
                    readinessError: query.isError,
                    planPending: state.pending,
                    planError: state.error,
                    activePlan: existing,
                  });
                  const opportunity = hasClusterUpgradeOpportunity(readiness);

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
                        {query.isPending
                          ? "Loading…"
                          : opportunity
                            ? `${readiness?.controlPlane.version ?? "—"} → ${readiness?.recommendedTarget?.version ?? "Component update"}`
                            : "No upgrade available"}
                      </td>
                      <td>
                        {query.isError
                          ? "Evidence unavailable"
                          : query.isPending
                            ? "Checking…"
                            : (readiness?.readiness.status ?? "Not reported")}
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
                              disabled={!!blocked || !opportunity}
                              onClick={() =>
                                onPlan(liveCluster(cluster, readiness))
                              }
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

          {evidence.some((query) => query.isFetching) && (
            <p role="status" className="upgrade-empty-state">
              Checking readiness in parallel. Available clusters will become
              actionable as each response arrives.
            </p>
          )}
        </section>
      )}
    </div>
  );
}
