"use client";

import { useMemo, useState, type CSSProperties } from "react";
import { useQueries } from "@tanstack/react-query";
import {
  AlertTriangle,
  CalendarClock,
  CheckCircle2,
  Clock3,
  Layers3,
  RefreshCw,
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

function requiredUpgradeLabel(evidence: EksUpgradeReadiness): string {
  const controlPlane = Boolean(evidence.recommendedTarget?.version);
  const nodeGroups = evidence.nodeGroups.some(
    (node) =>
      Boolean(node.version) &&
      node.version !== evidence.controlPlane.version,
  );
  const addons = evidence.addons.some(
    (addon) =>
      Boolean(addon.targetVersion) && addon.targetVersion !== addon.version,
  );
  const changes = [
    controlPlane ? "Control Plane" : "",
    nodeGroups ? "Node Groups" : "",
    addons ? "Managed Add-ons" : "",
  ].filter(Boolean);
  return changes.join(" + ") || "Version Review";
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
  const [platform, setPlatform] = useState("all");
  const [version, setVersion] = useState("all");
  const [readinessFilter, setReadinessFilter] = useState("all");

  const activeClusters = data.fleet.filter((cluster) => cluster.status === "ACTIVE");
  const evidence = useQueries({
    queries: activeClusters.map((cluster) => ({
      queryKey: ["eks-upgrade-readiness", cluster.clusterId],
      queryFn: () => clusters.upgradeReadiness(cluster.clusterId),
      staleTime: 30_000,
      retry: false,
      refetchOnWindowFocus: false,
      enabled:
        view === "available" ||
        (view === "plans" && lifecycle === "active"),
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
  const platforms = [...new Set(data.fleet.map((cluster) => cluster.platform))];

  const currentRows = useMemo(() => {
    const byCluster = new Map<string, (typeof data.rows)[number]>();
    for (const row of data.rows) {
      if (row.plan.kind === "UTILITY") continue;
      const current = byCluster.get(row.cluster.clusterId);
      if (
        !current ||
        Date.parse(row.plan.updatedAt) > Date.parse(current.plan.updatedAt) ||
        (row.plan.updatedAt === current.plan.updatedAt &&
          row.plan.version > current.plan.version)
      ) {
        byCluster.set(row.cluster.clusterId, row);
      }
    }
    return [...byCluster.values()].sort(
      (left, right) =>
        Date.parse(right.plan.updatedAt) - Date.parse(left.plan.updatedAt),
    );
  }, [data.rows]);

  const candidateRows = activeClusters.flatMap((cluster, index) => {
    const readiness = evidence[index]?.data;
    if (!readiness || !hasClusterUpgradeOpportunity(readiness)) return [];
    const currentPlan = currentRows.find(
      (row) => row.cluster.clusterId === cluster.clusterId,
    );
    const openPlan =
      currentPlan &&
      [
        "DRAFT",
        "SUBMITTED",
        "APPROVED",
        "SCHEDULED",
        "EXECUTING",
        "FAILED",
        "REJECTED",
      ].includes(currentPlan.plan.status)
        ? currentPlan.plan
        : undefined;
    return [
      {
        cluster,
        clusterName: cluster.clusterName,
        environment: cluster.environmentName ?? "Environment",
        readiness,
        plan: openPlan,
      },
    ];
  });

  const versions = [
    ...new Set(
      candidateRows.flatMap((row) => [
        row.readiness.controlPlane.version,
        row.readiness.recommendedTarget?.version,
      ]),
    ),
  ].filter((value): value is string => Boolean(value));

  const candidateStatus = (row: (typeof candidateRows)[number]) =>
    row.plan
      ? planStatus(row.plan, now)
      : row.readiness.readiness.status === "READY"
        ? "Ready to Plan"
        : row.readiness.readiness.status === "BLOCKED"
          ? "Needs Attention"
          : "Review Required";

  const filteredCandidates = candidateRows.filter((row) => {
    const status = candidateStatus(row);
    const versionMatch =
      version === "all" ||
      row.readiness.controlPlane.version === version ||
      row.readiness.recommendedTarget?.version === version;
    const readinessMatch =
      readinessFilter === "all" ||
      (readinessFilter === "ready" && status === "Ready to Plan") ||
      (readinessFilter === "review" && status === "Review Required") ||
      (readinessFilter === "attention" && status === "Needs Attention") ||
      (readinessFilter === "planned" && Boolean(row.plan));
    return (
      (customer === "all" || row.cluster.customerId === customer) &&
      (environment === "all" || row.cluster.environmentId === environment) &&
      (platform === "all" || row.cluster.platform === platform) &&
      versionMatch &&
      readinessMatch &&
      [
        row.cluster.clusterId,
        row.clusterName,
        row.cluster.customerName,
        row.environment,
        row.cluster.platform,
        row.plan?.planId,
        clusterAccount(row.cluster),
        requiredUpgradeLabel(row.readiness),
      ]
        .join(" ")
        .toLowerCase()
        .includes(search.toLowerCase())
    );
  });

  const lifecycleCounts = useMemo(() => {
    const result: Record<Lifecycle, number> = {
      active: 0,
      approval: 0,
      scheduled: 0,
      running: 0,
      attention: 0,
      upgraded: 0,
    };
    for (const row of currentRows) {
      const value = lifecycleFor(row.plan, now);
      result[value] += 1;
    }
    result.active = candidateRows.length;
    return result;
  }, [candidateRows.length, currentRows, now]);

  const planRows = currentRows.filter((row) => {
    if (lifecycle === "active") return false;
    const planLifecycle = lifecycleFor(row.plan, now);
    return (
      planLifecycle === lifecycle &&
      (customer === "all" || row.cluster.customerId === customer) &&
      (environment === "all" || row.cluster.environmentId === environment) &&
      (platform === "all" || row.cluster.platform === platform) &&
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

  const overdue = currentRows.filter(
    (row) => planStage(row.plan, now) === "Overdue",
  );
  const upToDateCount = Math.max(data.fleet.length - candidateRows.length, 0);
  const latestEvidenceAt = candidateRows
    .map((row) => Date.parse(row.readiness.observedAt))
    .filter(Number.isFinite)
    .sort((left, right) => right - left)[0];
  const recentActivity = currentRows.slice(0, 3);


  return (
    <div className="upgrade-centre upgrade-context-workbench">
      <section className="upgrade-overview-strip" aria-label="Upgrade overview">
        <div>
          <span>Total clusters</span>
          <strong>{data.fleet.length}</strong>
        </div>
        <div>
          <span>Candidate upgrades</span>
          <strong>{candidateRows.length}</strong>
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
              aria-label={item.label}
              aria-selected={view === "plans" && lifecycle === item.id}
              className={view === "plans" && lifecycle === item.id ? "active" : ""}
              onClick={() => {
                setView("plans");
                setLifecycle(item.id);
              }}
            >
              {item.label}
              <span aria-hidden="true">{lifecycleCounts[item.id]}</span>
            </button>
          ))}
        </nav>
      </div>

      {view === "plans" ? (
        <div className="upgrade-centre-dashboard upgrade-centre-approved">
          <section className="upgrade-centre-main" aria-label="Upgrade requests">
            <div className="upgrade-centre-filters upgrade-centre-filters-approved">
              <input
                aria-label="Search upgrade plans"
                placeholder="Search cluster, customer or environment…"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
              <select
                aria-label="Customer filter"
                value={customer}
                onChange={(event) => setCustomer(event.target.value)}
              >
                <option value="all">All Customers</option>
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
                <option value="all">All Environments</option>
                {environments.map(([id, name]) => (
                  <option value={id} key={id}>
                    {name}
                  </option>
                ))}
              </select>
              <select
                aria-label="Platform filter"
                value={platform}
                onChange={(event) => setPlatform(event.target.value)}
              >
                <option value="all">All Platforms</option>
                {platforms.map((value) => (
                  <option value={value} key={value}>
                    {value}
                  </option>
                ))}
              </select>
              {lifecycle === "active" && (
                <>
                  <select
                    aria-label="Version filter"
                    value={version}
                    onChange={(event) => setVersion(event.target.value)}
                  >
                    <option value="all">All Versions</option>
                    {versions.map((value) => (
                      <option value={value} key={value}>
                        {value}
                      </option>
                    ))}
                  </select>
                  <select
                    aria-label="Readiness filter"
                    value={readinessFilter}
                    onChange={(event) => setReadinessFilter(event.target.value)}
                  >
                    <option value="all">All Readiness</option>
                    <option value="ready">Ready to Plan</option>
                    <option value="review">Review Required</option>
                    <option value="attention">Needs Attention</option>
                    <option value="planned">Plan Exists</option>
                  </select>
                </>
              )}
            </div>

            {lifecycle === "active" ? (
              <>
                <header className="upgrade-opportunity-heading">
                  <div className="upgrade-opportunity-heading-icon" aria-hidden="true">
                    <Layers3 size={20} />
                  </div>
                  <div>
                    <h2>Verified Upgrade Opportunities</h2>
                    <p>
                      Only clusters with validated upgrade opportunities appear
                      here, based on current readiness evidence.
                    </p>
                  </div>
                  {latestEvidenceAt && (
                    <span className="upgrade-last-checked">
                      <RefreshCw size={14} aria-hidden="true" />
                      Last checked: {new Date(latestEvidenceAt).toLocaleString()}
                    </span>
                  )}
                </header>

                <div className="table-scroll upgrade-opportunity-table-wrap">
                  <table className="upgrade-dashboard-table upgrade-opportunity-table">
                    <caption className="sr-only">
                      Candidate clusters requiring upgrade
                    </caption>
                    <thead>
                      <tr>
                        <th>Cluster</th>
                        <th>Customer</th>
                        <th>Environment</th>
                        <th>Platform</th>
                        <th>Current → Target</th>
                        <th>Required Upgrade</th>
                        <th>Readiness / Status</th>
                        <th>Last Assessed</th>
                        <th>Next Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredCandidates.map((row) => {
                        const status = candidateStatus(row);
                        const current = row.readiness.controlPlane.version;
                        const target =
                          row.readiness.recommendedTarget?.version ??
                          "Component update";
                        return (
                          <tr key={row.cluster.clusterId}>
                            <td>
                              <div className="upgrade-cluster-identity">
                                <Layers3 size={17} aria-hidden="true" />
                                <span>
                                  <strong>{row.clusterName}</strong>
                                  <small>{row.cluster.clusterId}</small>
                                </span>
                              </div>
                            </td>
                            <td>{row.cluster.customerName ?? row.cluster.customerId}</td>
                            <td>
                              <span className="upgrade-environment-chip">
                                {row.environment}
                              </span>
                            </td>
                            <td>
                              <PlatformIdentity
                                identity={containerIdentity(row.cluster.platform)}
                                kind="platform"
                              />
                            </td>
                            <td className="upgrade-version-cell">
                              <strong>{current}</strong>
                              <span>→</span>
                              <strong>{target}</strong>
                            </td>
                            <td>{requiredUpgradeLabel(row.readiness)}</td>
                            <td>
                              <span
                                className="upgrade-plan-status"
                                data-status={status}
                              >
                                {status}
                              </span>
                            </td>
                            <td>
                              {new Date(row.readiness.observedAt).toLocaleString()}
                            </td>
                            <td>
                              {row.plan ? (
                                <Button
                                  variant="secondary"
                                  onClick={() =>
                                    onReview(
                                      row.plan!.planId,
                                      planStage(row.plan!, now) === "Overdue",
                                    )
                                  }
                                >
                                  View Plan
                                </Button>
                              ) : (
                                <Button
                                  onClick={() =>
                                    onPlan(liveCluster(row.cluster, row.readiness))
                                  }
                                >
                                  Create Plan
                                </Button>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                {!filteredCandidates.length && (
                  <div className="upgrade-centre-empty" role="status">
                    {evidence.some((query) => query.isFetching) ? (
                      <>
                        <RefreshCw className="spin" size={22} aria-hidden="true" />
                        <div>
                          <strong>Checking managed cluster readiness</strong>
                          <span>
                            Validating current versions and upgrade evidence…
                          </span>
                        </div>
                      </>
                    ) : candidateRows.length && filteredCandidates.length === 0 ? (
                      <>
                        <CheckCircle2 size={28} aria-hidden="true" />
                        <div>
                          <strong>No opportunities match these filters</strong>
                          <span>
                            Clear or adjust the filters to view the available upgrade
                            opportunities.
                          </span>
                        </div>
                      </>
                    ) : (
                      <>
                        <CheckCircle2 size={32} aria-hidden="true" />
                        <div>
                          <strong>All managed clusters are currently up to date</strong>
                          <span>
                            No verified upgrade opportunities were found based on
                            the latest readiness evidence.
                          </span>
                          <div className="upgrade-empty-actions">
                            <Button variant="secondary" onClick={data.refresh}>
                              <RefreshCw size={15} aria-hidden="true" />
                              Refresh Readiness
                            </Button>
                            <a href="/clusters" className="upgrade-empty-link">
                              <Layers3 size={15} aria-hidden="true" />
                              View All Clusters
                            </a>
                          </div>
                        </div>
                      </>
                    )}
                  </div>
                )}
              </>
            ) : (
              <>
                <header className="upgrade-opportunity-heading compact">
                  <div>
                    <h2>{lifecycleTabs.find((item) => item.id === lifecycle)?.label}</h2>
                    <p>
                      Current governed upgrade plans in this lifecycle stage.
                    </p>
                  </div>
                </header>
                <div className="table-scroll upgrade-opportunity-table-wrap">
                  <table className="upgrade-dashboard-table upgrade-plan-stage-table">
                    <caption className="sr-only">
                      Upgrade plans across managed clusters
                    </caption>
                    <thead>
                      <tr>
                        <th>Cluster</th>
                        <th>Customer</th>
                        <th>Environment</th>
                        <th>Platform</th>
                        <th>Current → Target</th>
                        <th>Status</th>
                        <th>Progress</th>
                        <th>Last Updated</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {planRows.map((row) => {
                        const progress = progressFor(row.plan);
                        const status = planStatus(row.plan, now);
                        return (
                          <tr key={row.plan.planId}>
                            <td>
                              <div className="upgrade-cluster-identity">
                                <Layers3 size={17} aria-hidden="true" />
                                <span>
                                  <strong>{row.clusterName}</strong>
                                  <small>{row.cluster.clusterId}</small>
                                </span>
                              </div>
                            </td>
                            <td>{row.cluster.customerName ?? row.cluster.customerId}</td>
                            <td>
                              <span className="upgrade-environment-chip">
                                {row.environment}
                              </span>
                            </td>
                            <td>
                              <PlatformIdentity
                                identity={containerIdentity(row.cluster.platform)}
                                kind="platform"
                              />
                            </td>
                            <td className="upgrade-version-cell">
                              <strong>{row.plan.currentVersion}</strong>
                              <span>→</span>
                              <strong>{row.plan.targetVersion}</strong>
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
                            <td>
                              {new Date(row.plan.updatedAt).toLocaleString()}
                            </td>
                            <td>
                              <Button
                                variant="secondary"
                                onClick={() =>
                                  onReview(
                                    row.plan.planId,
                                    planStage(row.plan, now) === "Overdue",
                                  )
                                }
                              >
                                View Plan
                              </Button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                {!planRows.length && (
                  <div className="upgrade-centre-empty compact" role="status">
                    <CheckCircle2 size={26} aria-hidden="true" />
                    <div>
                      <strong>
                        {lifecycle === "upgraded"
                          ? "No completed upgrades are recorded yet"
                          : "No upgrade plans in this stage"}
                      </strong>
                      <span>
                        Plans will appear here when they enter this lifecycle stage.
                      </span>
                    </div>
                  </div>
                )}
              </>
            )}
          </section>

          <section className="upgrade-centre-insights" aria-label="Upgrade insights">
            <article className="upgrade-insight-card">
              <header>
                <Layers3 size={17} aria-hidden="true" />
                <h3>Fleet Readiness</h3>
              </header>
              <div className="upgrade-readiness-summary">
                <div
                  className="upgrade-readiness-ring"
                  style={{
                    "--upgrade-ready-angle":
                      data.fleet.length
                        ? `${Math.round((upToDateCount / data.fleet.length) * 360)}deg`
                        : "0deg",
                  } as CSSProperties}
                >
                  <span>
                    <strong>
                      {data.fleet.length
                        ? Math.round((upToDateCount / data.fleet.length) * 100)
                        : 0}
                      %
                    </strong>
                    <small>Up to date</small>
                  </span>
                </div>
                <dl>
                  <div>
                    <dt>{upToDateCount} of {data.fleet.length} clusters</dt>
                    <dd>on current versions</dd>
                  </div>
                  <div>
                    <dt>{candidateRows.length} upgrade {candidateRows.length === 1 ? "opportunity" : "opportunities"}</dt>
                    <dd>{candidateRows.length ? "requires action" : "currently identified"}</dd>
                  </div>
                </dl>
              </div>
            </article>

            <article className="upgrade-insight-card attention">
              <header>
                <AlertTriangle size={18} aria-hidden="true" />
                <h3>Attention Required</h3>
              </header>
              <div className="upgrade-attention-summary">
                <strong>{overdue.length}</strong>
                <span>
                  maintenance {overdue.length === 1 ? "request needs" : "requests need"} a new time.
                </span>
                {overdue.length > 0 && (
                  <Button
                    variant="secondary"
                    onClick={() => onReview(overdue[0].plan.planId, true)}
                  >
                    <CalendarClock size={15} aria-hidden="true" />
                    Review & Reschedule
                  </Button>
                )}
              </div>
            </article>

            <article className="upgrade-insight-card">
              <header>
                <Clock3 size={17} aria-hidden="true" />
                <h3>Recent Upgrade Activity</h3>
              </header>
              {recentActivity.length ? (
                <ul className="upgrade-activity-list">
                  {recentActivity.map((row) => (
                    <li key={row.plan.planId}>
                      <CheckCircle2 size={15} aria-hidden="true" />
                      <span>
                        <strong>{row.clusterName}</strong>
                        <small>
                          {planStatus(row.plan, now)} ·{" "}
                          {row.plan.currentVersion} → {row.plan.targetVersion}
                        </small>
                      </span>
                      <time dateTime={row.plan.updatedAt}>
                        {new Date(row.plan.updatedAt).toLocaleDateString()}
                      </time>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="upgrade-no-activity">No upgrade activity recorded yet.</p>
              )}
            </article>
          </section>
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
                  const existing = currentRows.find(
                    (row) =>
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
