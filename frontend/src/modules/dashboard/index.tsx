"use client";
import Link from "next/link";
import { Building2, Layers3, Network } from "lucide-react";
import { PageHeading } from "@/shared/components/ui";
import { useCustomerCount } from "@/modules/customer-management/hooks/queries";
import { useEnvironmentCount } from "@/modules/environment-management/hooks/queries";
import { useClusterCount } from "@/modules/cluster-management/hooks/queries";

export function DashboardPage() {
  const customers = useCustomerCount();
  const activeCustomers = useCustomerCount("ACTIVE");
  const environments = useEnvironmentCount();
  const activeEnvironments = useEnvironmentCount("ACTIVE");
  const clusterRequests = useClusterCount();
  const activeClusterRequests = useClusterCount("ACTIVE");
  const metrics = [
    {
      label: "Customers",
      value: customers.data,
      note: `${activeCustomers.data ?? "—"} active`,
      icon: Building2,
    },
    {
      label: "Environments",
      value: environments.data,
      note: `${activeEnvironments.data ?? "—"} active`,
      icon: Layers3,
    },
    {
      label: "Cluster setup requests",
      value: clusterRequests.data,
      note: `${activeClusterRequests.data ?? "—"} active`,
      icon: Network,
    },
  ];
  return (
    <>
      <PageHeading
        eyebrow="NAVIGAN"
        title="Platform overview"
        description="Live counts across customers, environments and cluster setup requests within your access scope."
      />
      <div className="metrics-grid">
        {metrics.map((metric) => (
          <div className="metric" key={metric.label}>
            <div className="metric-label">
              {metric.label}
              <metric.icon size={20} aria-hidden="true" />
            </div>
            <strong>{metric.value ?? "—"}</strong>
            <p>{metric.note}</p>
          </div>
        ))}
      </div>
      <section className="panel panel-padding">
        <h2>Get started</h2>
        <div className="form-actions">
          <Link className="button button-primary" href="/customers/new">
            Create customer
          </Link>
          <Link className="button button-secondary" href="/environments/new">
            Create environment
          </Link>
          <Link className="button button-secondary" href="/clusters/new">
            New cluster setup
          </Link>
        </div>
      </section>
    </>
  );
}
