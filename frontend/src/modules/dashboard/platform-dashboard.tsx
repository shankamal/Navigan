"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  ArrowUpRight,
  Boxes,
  Building2,
  CheckCircle2,
  ChevronRight,
  Clock3,
  Cloud,
  Container,
  Gauge,
  Layers3,
  Plus,
  RefreshCw,
  ServerCog,
  ShieldCheck,
  Workflow,
  Wrench,
} from "lucide-react";
import { useAuth } from "@/shared/auth/auth-provider";
import { hasPermission } from "@/shared/auth/permissions";
import { ErrorNotice, Loading, formatDateTime } from "@/shared/components/ui";
import {
  useCustomerCount,
  useCustomers,
} from "@/modules/customer-management/hooks/queries";
import {
  useEnvironmentCount,
  useEnvironments,
} from "@/modules/environment-management/hooks/queries";
import {
  useClusterCount,
  useClusters,
} from "@/modules/cluster-management/hooks/queries";
import "./platform-dashboard.css";

type Provider = "AWS" | "AZURE" | "GCP" | "OCI";

const display = (value?: number) => value ?? "—";
const sum = (...values: Array<number | undefined>) =>
  values.reduce<number>((total, value) => total + (value ?? 0), 0);
const percent = (value?: number, total?: number) =>
  total ? Math.round(((value ?? 0) / total) * 100) : 0;

function ProviderLogo({
  provider,
  label = true,
}: {
  provider: Provider;
  label?: boolean;
}) {
  const names: Record<Provider, string> = {
    AWS: "AWS",
    AZURE: "Azure",
    GCP: "Google Cloud",
    OCI: "OCI",
  };

  const assets: Record<Provider, string> = {
    AWS: "amazonwebservices",
    AZURE: "microsoftazure",
    GCP: "googlecloud",
    OCI: "oracle",
  };
  return (
    <span className={`pd-provider pd-provider-${provider.toLowerCase()}`}>
      <img
        className="pd-brand-logo"
        src={`/logos/${assets[provider]}.svg`}
        alt={label ? "" : names[provider]}
      />
      {label && <span>{names[provider]}</span>}
    </span>
  );
}

function DonutChart({
  title,
  value,
  subtitle,
  segments,
}: {
  title: string;
  value: string | number;
  subtitle: string;
  segments: Array<{ value: number; color: string }>;
}) {
  let offset = 0;
  return (
    <div className="pd-donut">
      <svg viewBox="0 0 42 42" role="img" aria-label={title}>
        <circle className="pd-donut-track" cx="21" cy="21" r="15.9155" />
        {segments.map((segment, index) => {
          const dashOffset = 25 - offset;
          offset += segment.value;
          return (
            <circle
              key={`${segment.color}-${index}`}
              className="pd-donut-segment"
              cx="21"
              cy="21"
              r="15.9155"
              stroke={segment.color}
              strokeDasharray={`${segment.value} ${100 - segment.value}`}
              strokeDashoffset={dashOffset}
            />
          );
        })}
      </svg>
      <div className="pd-donut-center">
        <strong>{value}</strong>
        <span>{subtitle}</span>
      </div>
    </div>
  );
}

export function PlatformDashboard() {
  const { identity } = useAuth();
  const [currentDate, setCurrentDate] = useState("");
  const [refreshError, setRefreshError] = useState(false);
  const [lastUpdated, setLastUpdated] = useState("");

  useEffect(() => {
    const updateDate = () =>
      setCurrentDate(
        new Intl.DateTimeFormat("en-GB", {
          weekday: "long",
          day: "numeric",
          month: "long",
          year: "numeric",
        }).format(new Date()),
      );
    updateDate();
    const interval = window.setInterval(updateDate, 60_000);
    return () => window.clearInterval(interval);
  }, []);
  const totalCustomers = useCustomerCount();
  const activeCustomers = useCustomerCount("ACTIVE");
  const submittedCustomers = useCustomerCount("SUBMITTED");
  const reviewCustomers = useCustomerCount("UNDER_REVIEW");
  const totalEnvironments = useEnvironmentCount();
  const activeEnvironments = useEnvironmentCount("ACTIVE");
  const submittedEnvironments = useEnvironmentCount("SUBMITTED");
  const reviewEnvironments = useEnvironmentCount("UNDER_REVIEW");
  const totalClusters = useClusterCount();
  const activeClusters = useClusterCount("ACTIVE");
  const submittedClusters = useClusterCount("SUBMITTED");
  const reviewClusters = useClusterCount("UNDER_REVIEW");
  const planReadyClusters = useClusterCount("PLAN_READY");
  const applyingClusters = useClusterCount("APPLYING");
  const failedClusters = useClusterCount("FAILED");
  const environments = useEnvironments({
    page: 0,
    pageSize: 100,
    sort: "updatedAt,desc",
  });
  const pendingCustomers = useCustomers({
    page: 0,
    pageSize: 3,
    status: "SUBMITTED",
    sort: "updatedAt,desc",
  });
  const pendingEnvironments = useEnvironments({
    page: 0,
    pageSize: 3,
    status: "SUBMITTED",
    sort: "updatedAt,desc",
  });
  const pendingClusters = useClusters({
    page: 0,
    pageSize: 3,
    status: "SUBMITTED",
  });
  const recentClusters = useClusters({ page: 0, pageSize: 3 });

  const countQueries = [
    totalCustomers,
    activeCustomers,
    submittedCustomers,
    reviewCustomers,
    totalEnvironments,
    activeEnvironments,
    submittedEnvironments,
    reviewEnvironments,
    totalClusters,
    activeClusters,
    submittedClusters,
    reviewClusters,
    planReadyClusters,
    applyingClusters,
    failedClusters,
  ];
  const dashboardQueries = [
    ...countQueries,
    environments,
    pendingCustomers,
    pendingEnvironments,
    pendingClusters,
    recentClusters,
  ];
  const refreshing = dashboardQueries.some((query) => query.isFetching);
  const hasPartialError = dashboardQueries.some((query) => query.error);
  const oldestUpdate = Math.min(
    ...dashboardQueries.map((query) => query.dataUpdatedAt || 0),
  );
  useEffect(() => {
    setLastUpdated(
      oldestUpdate
        ? new Date(oldestUpdate).toLocaleTimeString("en-GB", {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
          })
        : "",
    );
  }, [oldestUpdate]);
  async function refreshDashboard() {
    setRefreshError(false);
    const results = await Promise.allSettled(
      dashboardQueries.map((query) => query.refetch({ throwOnError: true })),
    );
    setRefreshError(results.some((result) => result.status === "rejected"));
  }
  const failedQuery = countQueries.find((query) => query.error);
  const awaitingAction = sum(
    submittedCustomers.data,
    reviewCustomers.data,
    submittedEnvironments.data,
    reviewEnvironments.data,
    submittedClusters.data,
    reviewClusters.data,
  );
  const provisioningNow = sum(planReadyClusters.data, applyingClusters.data);
  const providerCounts = (environments.data?.items ?? []).reduce<
    Record<string, number>
  >((counts, environment) => {
    counts[environment.cloudProvider] =
      (counts[environment.cloudProvider] ?? 0) + 1;
    return counts;
  }, {});
  const providerTotal = Object.values(providerCounts).reduce(
    (total, value) => total + value,
    0,
  );
  const providerOrder: Provider[] = ["AWS", "AZURE", "GCP", "OCI"];
  const providerColors: Record<Provider, string> = {
    AWS: "#f59e0b",
    AZURE: "#1689d4",
    GCP: "#4f7fe9",
    OCI: "#d43b2f",
  };
  const customerHealth = percent(activeCustomers.data, totalCustomers.data);
  const environmentHealth = percent(
    activeEnvironments.data,
    totalEnvironments.data,
  );
  const clusterHealth = percent(activeClusters.data, totalClusters.data);
  const postureValues = [
    totalCustomers.data ? customerHealth : undefined,
    totalEnvironments.data ? environmentHealth : undefined,
    totalClusters.data ? clusterHealth : undefined,
  ].filter((value): value is number => value !== undefined);
  const overallPosture = postureValues.length
    ? Math.round(
        postureValues.reduce((total, value) => total + value, 0) /
          postureValues.length,
      )
    : 0;
  const workflowInProgress = sum(
    submittedClusters.data,
    reviewClusters.data,
    planReadyClusters.data,
    applyingClusters.data,
  );
  const workflowKnown = sum(
    activeClusters.data,
    workflowInProgress,
    failedClusters.data,
  );
  const workflowOther = Math.max(0, (totalClusters.data ?? 0) - workflowKnown);
  const workflowTotal = totalClusters.data ?? 0;
  const canCreateEnvironment = hasPermission(identity, "environment.create");
  const canCreateCluster = hasPermission(identity, "cluster.create");
  const canReview =
    hasPermission(identity, "customer.review") ||
    hasPermission(identity, "environment.review") ||
    hasPermission(identity, "cluster.review");

  const attentionItems = [
    ...(pendingCustomers.data?.items ?? []).map((customer) => ({
      id: customer.customerId,
      title: customer.name,
      meta: `Customer onboarding · ${customer.status.replaceAll("_", " ")}`,
      href: `/customers/${customer.customerId}`,
      icon: Building2,
      tone: "info",
    })),
    ...(pendingEnvironments.data?.items ?? []).map((environment) => ({
      id: environment.environmentId,
      title: environment.environmentName,
      meta: `${environment.cloudProvider} environment · ${environment.status.replaceAll("_", " ")}`,
      href: `/environments/${environment.environmentId}`,
      icon: Layers3,
      tone: "warning",
    })),
    ...(pendingClusters.data?.items ?? []).map((cluster) => ({
      id: cluster.clusterId,
      title: cluster.clusterName,
      meta: `${cluster.customerName ?? "Customer"} · cluster request · ${cluster.status.replaceAll("_", " ")}`,
      href: `/clusters/${cluster.clusterId}`,
      icon: ServerCog,
      tone: "success",
    })),
  ].slice(0, 2);

  if (countQueries.some((query) => query.isPending)) {
    return <Loading label="Loading platform dashboard…" />;
  }
  if (failedQuery?.error) {
    return (
      <ErrorNotice
        error={failedQuery.error}
        onRetry={() => countQueries.forEach((query) => void query.refetch())}
      />
    );
  }

  const kpis = [
    {
      label: "Onboarded customers",
      total: totalCustomers.data,
      value: activeCustomers.data,
      detail: `${display(totalCustomers.data)} total in your scope`,
      note: `${sum(submittedCustomers.data, reviewCustomers.data)} in onboarding`,
      icon: Building2,
      href: "/customers?status=ACTIVE",
      tone: "green",
    },
    {
      label: "Governed environments",
      total: totalEnvironments.data,
      value: activeEnvironments.data,
      detail: `${display(totalEnvironments.data)} environment profiles`,
      note: `${providerTotal} mapped to cloud providers`,
      icon: Layers3,
      href: "/environments?status=ACTIVE",
      tone: "blue",
    },
    {
      label: "Active clusters",
      total: totalClusters.data,
      value: activeClusters.data,
      detail: `${display(totalClusters.data)} cluster requests`,
      note: `${clusterHealth}% active estate`,
      icon: ServerCog,
      href: "/clusters?status=ACTIVE",
      tone: "green",
    },
    {
      label: "Provisioning now",
      total: undefined,
      value: provisioningNow,
      detail: `${display(planReadyClusters.data)} plan ready`,
      note: `${display(applyingClusters.data)} Terraform applies`,
      icon: Workflow,
      href: "#dashboard-provisioning",
      tone: "violet",
    },
    {
      label: "Awaiting action",
      total: undefined,
      value: awaitingAction,
      detail: "Submitted or under review",
      note: "Across governed workflows",
      icon: ShieldCheck,
      href: "#dashboard-attention",
      tone: "teal",
    },
    {
      label: "Failed operations",
      total: undefined,
      value: failedClusters.data,
      detail: "Cluster workflows requiring action",
      note: failedClusters.data ? "Remediation required" : "No active failures",
      icon: AlertTriangle,
      href: "/clusters?status=FAILED",
      tone: "orange",
    },
  ] as const;

  return (
    <div className="platform-dashboard command-dashboard">
      <section className="pd-heading">
        <div>
          <p className="pd-date">{currentDate}</p>
          <h1>Platform command center</h1>
          <p className="muted">
            Live governance, provisioning, and lifecycle status across the
            Navigan-managed Kubernetes estate.
          </p>
        </div>
        <div className="pd-actions">
          <span className="pd-freshness" role="status" aria-live="polite">
            {refreshing
              ? "Refreshing…"
              : refreshError || hasPartialError
                ? "Some data could not be refreshed"
                : lastUpdated
                  ? `Updated ${lastUpdated}`
                  : "Loading data…"}
          </span>
          <button
            type="button"
            className="button button-secondary"
            onClick={() => void refreshDashboard()}
            disabled={refreshing}
          >
            <RefreshCw size={15} /> Refresh
          </button>
          {canCreateEnvironment && (
            <Link className="button button-secondary" href="/environments/new">
              <Plus size={17} /> New environment
            </Link>
          )}
          {canCreateCluster && (
            <Link className="button button-primary" href="/clusters/new">
              <Plus size={17} /> New cluster request
            </Link>
          )}
          {canReview && (
            <Link className="button button-primary" href="/clusters/reviews">
              Open review queue
            </Link>
          )}
        </div>
      </section>

      <section className="pd-kpis" aria-label="Navigan platform KPIs">
        {kpis.map((kpi) => (
          <Link
            className={`pd-kpi pd-kpi-${kpi.tone} ${kpi.total !== undefined ? "pd-kpi-with-ring" : ""}`}
            href={kpi.href}
            key={kpi.label}
          >
            {kpi.total !== undefined ? (
              <span className="pd-kpi-ring">
                <DonutChart
                  title={`${kpi.label}: ${display(kpi.value)} of ${kpi.total} (${percent(kpi.value, kpi.total)}%)`}
                  value={display(kpi.value)}
                  subtitle={
                    kpi.total
                      ? `${percent(kpi.value, kpi.total)}%`
                      : "No records"
                  }
                  segments={[
                    { value: percent(kpi.value, kpi.total), color: "#23845B" },
                  ]}
                />
              </span>
            ) : (
              <span className="pd-kpi-icon">
                <kpi.icon size={20} />
              </span>
            )}
            <span className="pd-kpi-copy">
              <span>{kpi.label}</span>
              <strong>{display(kpi.value)}</strong>
              <small>{kpi.detail}</small>
            </span>
            <span className="pd-kpi-note">{kpi.note}</span>
          </Link>
        ))}
      </section>

      <section className="pd-card" id="dashboard-attention">
        <header className="pd-card-heading">
          <div>
            <span className="pd-card-icon pd-attention-icon">
              <AlertTriangle size={19} />
            </span>
            <div>
              <h2>
                Needs your attention{" "}
                <span className="pd-count">{awaitingAction}</span>
              </h2>
              <p>
                Navigan approvals, provisioning exceptions, and requests
                requiring action.
              </p>
            </div>
          </div>
          {canReview && (
            <Link className="pd-card-link" href="/customers">
              Customer directory <ChevronRight size={15} />
            </Link>
          )}
        </header>
        <div
          className="pd-governance-inline"
          aria-label="Pending governance by module"
        >
          {[
            {
              label: "Customers",
              path: "/customers",
              submitted: submittedCustomers.data,
              reviewing: reviewCustomers.data,
            },
            {
              label: "Environments",
              path: "/environments",
              submitted: submittedEnvironments.data,
              reviewing: reviewEnvironments.data,
            },
            {
              label: "Clusters",
              path: "/clusters",
              submitted: submittedClusters.data,
              reviewing: reviewClusters.data,
            },
          ].map((item) => (
            <span key={item.path}>
              <strong>{item.label}</strong>{" "}
              <Link href={`${item.path}?status=SUBMITTED`}>
                Submitted {display(item.submitted)}
              </Link>
              {" · "}
              <Link href={`${item.path}?status=UNDER_REVIEW`}>
                Under review {display(item.reviewing)}
              </Link>
            </span>
          ))}
        </div>
        <p className="pd-preview-count">
          Showing {attentionItems.length} submitted requests. {awaitingAction}{" "}
          records are submitted or under review.
        </p>
        <div className="pd-attention-list">
          {pendingCustomers.isPending ||
          pendingEnvironments.isPending ||
          pendingClusters.isPending ? (
            <Loading label="Loading attention queue…" />
          ) : attentionItems.length ? (
            attentionItems.map((item) => (
              <Link
                className="pd-attention-row"
                href={item.href}
                key={`${item.id}-${item.href}`}
              >
                <span
                  className={`pd-attention-row-icon pd-attention-${item.tone}`}
                >
                  <item.icon size={17} />
                </span>
                <span>
                  <strong>{item.title}</strong>
                  <small>{item.meta}</small>
                </span>
                <span className="pd-review-action">
                  View request <ArrowRight size={16} />
                </span>
              </Link>
            ))
          ) : (
            <div className="pd-empty pd-empty-success">
              <CheckCircle2 size={20} />
              No newly submitted requests require attention.
            </div>
          )}
        </div>
      </section>

      <section className="pd-primary-grid">
        <article className="pd-card">
          <header className="pd-card-heading">
            <div>
              <span className="pd-card-icon">
                <Cloud size={19} />
              </span>
              <div>
                <h2>Cloud footprint</h2>
                <p>Environment profiles by cloud provider.</p>
              </div>
            </div>
          </header>
          {environments.isPending ? (
            <Loading label="Loading cloud footprint…" />
          ) : environments.error ? (
            <ErrorNotice
              error={environments.error}
              onRetry={() => environments.refetch()}
            />
          ) : providerTotal === 0 ? (
            <p className="pd-empty">No environment profiles are available.</p>
          ) : (
            <div className="pd-footprint">
              <DonutChart
                title="Environment profiles by cloud provider"
                value={providerTotal}
                subtitle="environments"
                segments={providerOrder.map((provider) => ({
                  value:
                    ((providerCounts[provider] ?? 0) / providerTotal) * 100,
                  color: providerColors[provider],
                }))}
              />
              <div className="pd-legend pd-provider-legend">
                {providerOrder.map((provider) => (
                  <div key={provider}>
                    <ProviderLogo provider={provider} />
                    <strong>{providerCounts[provider] ?? 0}</strong>
                    <span>
                      {percent(providerCounts[provider], providerTotal)}%
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
          <Link
            className="pd-card-link pd-card-footer-link"
            href="/environments"
          >
            View environment directory <ArrowRight size={15} />
          </Link>
        </article>

        <article className="pd-card">
          <header className="pd-card-heading">
            <div>
              <span className="pd-card-icon">
                <Gauge size={19} />
              </span>
              <div>
                <h2>Active record coverage</h2>
                <p>
                  Average active-record percentage across customers,
                  environments, and clusters. This is not runtime health.
                </p>
              </div>
            </div>
            <span className="pd-data-label">Current records</span>
          </header>
          <div className="pd-posture">
            <div className="pd-gauge">
              <svg
                viewBox="0 0 180 180"
                role="img"
                aria-label={`Average active record coverage ${overallPosture}%`}
              >
                <circle className="pd-gauge-track" cx="90" cy="90" r="70" />
                <circle
                  className="pd-gauge-value"
                  cx="90"
                  cy="90"
                  r="70"
                  pathLength="100"
                  strokeDasharray={`${overallPosture} 100`}
                />
              </svg>
              <div>
                <strong>{overallPosture}%</strong>
                <span>Active</span>
              </div>
            </div>
            <div className="pd-posture-metrics">
              <div>
                <span>
                  <i className="pd-dot-green" />
                  Customers
                </span>
                <strong>{customerHealth}%</strong>
                <small>Active onboarding records</small>
              </div>
              <div>
                <span>
                  <i className="pd-dot-blue" />
                  Environments
                </span>
                <strong>{environmentHealth}%</strong>
                <small>Active governed profiles</small>
              </div>
              <div>
                <span>
                  <i className="pd-dot-teal" />
                  Clusters
                </span>
                <strong>{clusterHealth}%</strong>
                <small>Active cluster records</small>
              </div>
            </div>
          </div>
          <div
            className={`pd-signal ${(failedClusters.data ?? 0) > 0 ? "pd-signal-warning" : ""}`}
          >
            {(failedClusters.data ?? 0) > 0 ? (
              <AlertTriangle size={17} />
            ) : (
              <CheckCircle2 size={17} />
            )}
            <span>
              {(failedClusters.data ?? 0) > 0
                ? `${failedClusters.data} failed cluster operation${failedClusters.data === 1 ? "" : "s"} require remediation.`
                : "No failed cluster operations are active in your access scope."}
            </span>
          </div>
        </article>

        <article className="pd-card">
          <header className="pd-card-heading">
            <div>
              <span className="pd-card-icon">
                <Workflow size={19} />
              </span>
              <div>
                <h2 id="dashboard-provisioning">Cluster workflow state</h2>
                <p>Current lifecycle position of Navigan cluster requests.</p>
              </div>
            </div>
          </header>
          <div className="pd-provisioning-links">
            <Link href="/clusters?status=PLAN_READY">
              Plan ready {display(planReadyClusters.data)}
            </Link>
            <Link href="/clusters?status=APPLYING">
              Applying {display(applyingClusters.data)}
            </Link>
          </div>
          {workflowTotal === 0 ? (
            <p className="pd-empty">No cluster requests are available.</p>
          ) : (
            <div className="pd-workflow">
              <div
                className="pd-workflow-bar"
                aria-label="Cluster lifecycle distribution"
              >
                {[
                  {
                    label: "Active",
                    value: activeClusters.data ?? 0,
                    color: "#65A449",
                  },
                  {
                    label: "In delivery",
                    value: workflowInProgress,
                    color: "#237448",
                  },
                  {
                    label: "Failed",
                    value: failedClusters.data ?? 0,
                    color: "#C84835",
                  },
                  { label: "Other", value: workflowOther, color: "#94A3B8" },
                ]
                  .filter((item) => item.value > 0)
                  .map((item) => (
                    <span
                      key={item.label}
                      title={`${item.label}: ${item.value}`}
                      style={{ flex: item.value, background: item.color }}
                    >
                      {item.value}
                    </span>
                  ))}
              </div>
              <div className="pd-legend pd-workflow-legend">
                <div>
                  <span>
                    <i className="pd-legend-active" />
                    Active
                  </span>
                  <strong>{display(activeClusters.data)}</strong>
                  <small>{percent(activeClusters.data, workflowTotal)}%</small>
                </div>
                <div>
                  <span>
                    <i className="pd-legend-progress" />
                    In delivery
                  </span>
                  <strong>{workflowInProgress}</strong>
                  <small>{percent(workflowInProgress, workflowTotal)}%</small>
                </div>
                <div>
                  <span>
                    <i className="pd-legend-failed" />
                    Failed
                  </span>
                  <strong>{display(failedClusters.data)}</strong>
                  <small>{percent(failedClusters.data, workflowTotal)}%</small>
                </div>
                <div>
                  <span>
                    <i className="pd-legend-other" />
                    Other states
                  </span>
                  <strong>{workflowOther}</strong>
                  <small>{percent(workflowOther, workflowTotal)}%</small>
                </div>
              </div>
            </div>
          )}
        </article>
      </section>

      <section className="pd-card">
        <header className="pd-card-heading">
          <div>
            <span className="pd-card-icon">
              <Clock3 size={19} />
            </span>
            <div>
              <h2>Recent cluster activity</h2>
              <p>Latest Kubernetes cluster requests in your access scope.</p>
            </div>
          </div>
          <Link className="pd-card-link" href="/clusters">
            View cluster directory <ChevronRight size={15} />
          </Link>
        </header>
        {recentClusters.isPending ? (
          <Loading label="Loading cluster activity…" />
        ) : recentClusters.error ? (
          <ErrorNotice
            error={recentClusters.error}
            onRetry={() => recentClusters.refetch()}
          />
        ) : (
          <div className="table-scroll">
            <table className="pd-activity-table">
              <thead>
                <tr>
                  <th>Cluster</th>
                  <th>Customer</th>
                  <th>Platform</th>
                  <th>State</th>
                  <th>Updated</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {(recentClusters.data?.items ?? []).map((cluster) => (
                  <tr key={cluster.clusterId}>
                    <td>
                      <span className="pd-resource">
                        <Container size={15} />
                        {cluster.clusterName}
                      </span>
                    </td>
                    <td>
                      <strong>
                        {cluster.customerName ?? cluster.customerId}
                      </strong>
                    </td>
                    <td>
                      <span className="pd-platform">
                        <ProviderLogo provider="AWS" label={false} />
                        EKS
                      </span>
                    </td>
                    <td>
                      <span
                        className={`pd-status pd-status-${cluster.status.toLowerCase()}`}
                      >
                        {cluster.status.replaceAll("_", " ")}
                      </span>
                    </td>
                    <td>{formatDateTime(cluster.updatedAt)}</td>
                    <td>
                      <Link
                        className="pd-row-action"
                        href={`/clusters/${cluster.clusterId}`}
                      >
                        View cluster <ArrowUpRight size={14} />
                      </Link>
                    </td>
                  </tr>
                ))}
                {!(recentClusters.data?.items.length ?? 0) && (
                  <tr>
                    <td colSpan={6} className="pd-empty">
                      No cluster requests are available.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section
        className="pd-tool-strip"
        aria-label="Navigan platform toolchain"
      >
        <div>
          <span className="pd-card-icon">
            <Wrench size={18} />
          </span>
          <div>
            <strong>Platform toolchain</strong>
            <p>Capabilities managed through Navigan cluster operations.</p>
          </div>
        </div>
        <div className="pd-tools">
          {[
            ["terraform", "Terraform"],
            ["kubernetes", "Kubernetes"],
            ["docker", "Containers"],
            ["prometheus", "Prometheus"],
            ["grafana", "Grafana"],
            ["argo", "Argo CD"],
          ].map(([asset, name]) => (
            <span key={asset}>
              <img
                className="pd-brand-logo"
                src={`/logos/${asset}.svg`}
                alt=""
              />
              {name}
            </span>
          ))}
        </div>
        <Link href="/clusters" aria-label="Open cluster operations">
          <ArrowUpRight size={18} />
        </Link>
      </section>
    </div>
  );
}
