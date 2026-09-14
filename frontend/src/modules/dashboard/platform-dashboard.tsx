"use client";

import Link from "next/link";
import {
  AlertTriangle,
  ArrowRight,
  Building2,
  CheckCircle2,
  Cloud,
  Layers3,
  ServerCog,
  ShieldCheck,
} from "lucide-react";
import { useAuth } from "@/shared/auth/auth-provider";
import { hasPermission } from "@/shared/auth/permissions";
import { ErrorNotice, Loading, PageHeading } from "@/shared/components/ui";
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

const display = (number?: number) => number ?? "—";

export function PlatformDashboard() {
  const { identity } = useAuth();
  const totalCustomers = useCustomerCount();
  const activeCustomers = useCustomerCount("ACTIVE");
  const totalEnvironments = useEnvironmentCount();
  const activeEnvironments = useEnvironmentCount("ACTIVE");
  const totalClusters = useClusterCount();
  const activeClusters = useClusterCount("ACTIVE");
  const submittedCustomers = useCustomerCount("SUBMITTED");
  const reviewCustomers = useCustomerCount("UNDER_REVIEW");
  const submittedEnvironments = useEnvironmentCount("SUBMITTED");
  const reviewEnvironments = useEnvironmentCount("UNDER_REVIEW");
  const submittedClusters = useClusterCount("SUBMITTED");
  const reviewClusters = useClusterCount("UNDER_REVIEW");
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
  const pendingClusters = useClusters({
    page: 0,
    pageSize: 3,
    status: "SUBMITTED",
  });

  const countQueries = [
    totalCustomers,
    activeCustomers,
    totalEnvironments,
    activeEnvironments,
    totalClusters,
    activeClusters,
    submittedCustomers,
    reviewCustomers,
    submittedEnvironments,
    reviewEnvironments,
    submittedClusters,
    reviewClusters,
    failedClusters,
  ];
  const failedQuery = countQueries.find((query) => query.error);
  const actionCounts = [
    submittedCustomers.data,
    reviewCustomers.data,
    submittedEnvironments.data,
    reviewEnvironments.data,
    submittedClusters.data,
    reviewClusters.data,
  ];
  const awaitingAction = actionCounts.every((item) => item !== undefined)
    ? actionCounts.reduce((sum, item) => sum + (item ?? 0), 0)
    : undefined;
  const providerCounts = (environments.data?.items ?? []).reduce<
    Record<string, number>
  >((counts, environment) => {
    counts[environment.cloudProvider] =
      (counts[environment.cloudProvider] ?? 0) + 1;
    return counts;
  }, {});
  const providerTotal = Object.values(providerCounts).reduce(
    (sum, count) => sum + count,
    0,
  );
  const canCreateEnvironment = hasPermission(
    identity,
    "environment.create",
  );
  const canCreateCluster = hasPermission(identity, "cluster.create");
  const canReview =
    hasPermission(identity, "customer.review") ||
    hasPermission(identity, "environment.review") ||
    hasPermission(identity, "cluster.review");

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

  const metrics = [
    {
      label: "Active customers",
      value: activeCustomers.data,
      total: totalCustomers.data,
      icon: Building2,
      href: "/customers",
    },
    {
      label: "Active environments",
      value: activeEnvironments.data,
      total: totalEnvironments.data,
      icon: Layers3,
      href: "/environments",
    },
    {
      label: "Active clusters",
      value: activeClusters.data,
      total: totalClusters.data,
      icon: ServerCog,
      href: "/clusters",
    },
    {
      label: "Awaiting action",
      value: awaitingAction,
      total: undefined,
      icon: ShieldCheck,
      href: canReview ? "/clusters" : "/environments",
    },
  ];

  return (
    <div className="platform-dashboard">
      <PageHeading
        eyebrow="PLATFORM OVERVIEW"
        title="Dashboard"
        description="A live view of your customers, cloud environments, Kubernetes estate and work requiring attention."
        action={
          <div className="dashboard-actions">
            {canCreateEnvironment && (
              <Link className="button button-secondary" href="/environments/new">
                New environment
              </Link>
            )}
            {canCreateCluster && (
              <Link className="button button-primary" href="/clusters/new">
                New cluster request
              </Link>
            )}
            {canReview && (
              <Link className="button button-primary" href="/clusters">
                Open review queue
              </Link>
            )}
          </div>
        }
      />

      <div className="dashboard-metrics">
        {metrics.map((metric) => (
          <Link className="dashboard-metric" href={metric.href} key={metric.label}>
            <span className="dashboard-metric-icon">
              <metric.icon size={21} />
            </span>
            <span>{metric.label}</span>
            <strong>{display(metric.value)}</strong>
            <small>
              {metric.total === undefined
                ? "Across your access scope"
                : `of ${metric.total ?? "—"} total`}
            </small>
          </Link>
        ))}
      </div>

      <div className="dashboard-layout">
        <section className="panel dashboard-panel">
          <div className="dashboard-panel-heading">
            <div>
              <p className="eyebrow">PLATFORM ESTATE</p>
              <h2>Cloud distribution</h2>
              <p className="muted">Environment profiles grouped by provider.</p>
            </div>
            <Cloud size={24} />
          </div>
          {environments.isPending ? (
            <Loading label="Loading cloud distribution…" />
          ) : environments.error ? (
            <ErrorNotice
              error={environments.error}
              onRetry={() => environments.refetch()}
            />
          ) : providerTotal === 0 ? (
            <p className="dashboard-empty">No environment profiles are available.</p>
          ) : (
            <div className="provider-bars">
              {["AWS", "AZURE", "GCP", "OCI"].map((provider) => {
                const count = providerCounts[provider] ?? 0;
                const percent = Math.round((count / providerTotal) * 100);
                return (
                  <div className="provider-row" key={provider}>
                    <div>
                      <strong>{provider}</strong>
                      <span>{count} environments</span>
                    </div>
                    <div className="provider-track">
                      <span style={{ width: `${percent}%` }} />
                    </div>
                    <b>{percent}%</b>
                  </div>
                );
              })}
            </div>
          )}
          <Link className="dashboard-text-link" href="/environments">
            View all environments <ArrowRight size={16} />
          </Link>
        </section>

        <section className="panel dashboard-panel">
          <div className="dashboard-panel-heading">
            <div>
              <p className="eyebrow">OPERATIONS</p>
              <h2>Attention queue</h2>
              <p className="muted">Items that may require a decision or action.</p>
            </div>
            {(failedClusters.data ?? 0) > 0 ? (
              <AlertTriangle className="dashboard-warning" size={24} />
            ) : (
              <CheckCircle2 className="dashboard-ok" size={24} />
            )}
          </div>
          <div className="attention-summary">
            <div>
              <strong>{display(awaitingAction)}</strong>
              <span>Submitted or under review</span>
            </div>
            <div>
              <strong>{display(failedClusters.data)}</strong>
              <span>Failed cluster operations</span>
            </div>
          </div>
          <div className="attention-list">
            {(pendingCustomers.data?.items ?? []).map((customer) => (
              <Link href={`/customers/${customer.customerId}`} key={customer.customerId}>
                <span>
                  <Building2 size={17} />
                  <span>
                    <strong>{customer.name}</strong>
                    <small>Customer request · {customer.status.replaceAll("_", " ")}</small>
                  </span>
                </span>
                <ArrowRight size={16} />
              </Link>
            ))}
            {(pendingClusters.data?.items ?? []).map((cluster) => (
              <Link href={`/clusters/${cluster.clusterId}`} key={cluster.clusterId}>
                <span>
                  <ServerCog size={17} />
                  <span>
                    <strong>{cluster.clusterName}</strong>
                    <small>Cluster request · {cluster.status.replaceAll("_", " ")}</small>
                  </span>
                </span>
                <ArrowRight size={16} />
              </Link>
            ))}
            {!pendingCustomers.isPending &&
              !pendingClusters.isPending &&
              !(pendingCustomers.data?.items.length ?? 0) &&
              !(pendingClusters.data?.items.length ?? 0) && (
                <p className="dashboard-empty">
                  No newly submitted requests in your access scope.
                </p>
              )}
          </div>
        </section>
      </div>
    </div>
  );
}
