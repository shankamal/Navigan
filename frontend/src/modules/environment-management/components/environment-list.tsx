"use client";
import Link from "next/link";
import { useState } from "react";
import { Layers3, Plus } from "lucide-react";
import {
  PageHeading,
  Loading,
  ErrorNotice,
  EmptyState,
  Pagination,
  formatDate,
} from "@/shared/components/ui";
import { useAuth } from "@/shared/auth/auth-provider";
import { statuses } from "@/modules/customer-management/model/types";
import { useEnvironments, useMetadata } from "../hooks/queries";
import type { Filters } from "../model/types";
export function EnvironmentList() {
  const { identity } = useAuth();
  const [filters, setFilters] = useState<Filters>({
    page: 0,
    pageSize: 20,
    sort: "createdAt,desc",
  });
  const query = useEnvironments(filters);
  const metadata = useMetadata();
  const set = (key: string, value: string) =>
    setFilters((f) => ({ ...f, page: 0, [key]: value || undefined }));
  return (
    <>
      <PageHeading
        eyebrow="Infrastructure governance"
        title="Environments"
        description="Create and approve reusable infrastructure baselines across your clouds."
        action={
          identity?.roles.includes("CLOUD_ENGINEER") && (
            <Link className="button button-primary" href="/environments/new">
              <Plus size={18} />
              Create environment
            </Link>
          )
        }
      />
      <section className="panel panel-padding">
        <div className="form-grid">
          <label className="field">
            Search
            <input
              placeholder="Environment or customer name"
              value={filters.search || ""}
              onChange={(e) => set("search", e.target.value)}
            />
          </label>
          <label className="field">
            Cloud provider
            <select
              value={filters.cloudProvider || ""}
              onChange={(e) => set("cloudProvider", e.target.value)}
            >
              <option value="">All clouds</option>
              {["AWS", "AZURE", "GCP", "OCI"].map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </label>
          <label className="field">
            Status
            <select
              value={filters.status || ""}
              onChange={(e) => set("status", e.target.value)}
            >
              <option value="">All statuses</option>
              {statuses.map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </label>
          <label className="field">
            Environment type
            <select
              value={filters.environmentType || ""}
              onChange={(e) => set("environmentType", e.target.value)}
            >
              <option value="">All types</option>
              {metadata.data?.environmentTypes.map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </label>
          <label className="field">
            Region
            <input
              value={filters.region || ""}
              onChange={(e) => set("region", e.target.value)}
              placeholder="Filter by exact region"
            />
          </label>
          <label className="field">
            Sort
            <select
              value={filters.sort}
              onChange={(e) => set("sort", e.target.value)}
            >
              <option value="createdAt,desc">Newest first</option>
              <option value="createdAt,asc">Oldest first</option>
              <option value="environmentName,asc">Name A–Z</option>
              <option value="updatedAt,desc">Recently updated</option>
            </select>
          </label>
        </div>
      </section>
      {query.isPending ? (
        <Loading label="Loading environments…" />
      ) : query.error ? (
        <ErrorNotice error={query.error} onRetry={() => query.refetch()} />
      ) : query.data && !query.data.items.length ? (
        <EmptyState icon={<Layers3 />} title="No environments found">
          Create your first environment or adjust the filters.
        </EmptyState>
      ) : (
        query.data && (
          <section className="panel">
            <div className="table-scroll">
              <table className="customer-table">
                <thead>
                  <tr>
                    <th>Environment</th>
                    <th>Customer</th>
                    <th>Distribution</th>
                    <th>Type</th>
                    <th>Status</th>
                    <th>Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {query.data.items.map((row) => (
                    <tr key={row.environmentId}>
                      <td>
                        <Link href={`/environments/${row.environmentId}`}>
                          <strong>{row.environmentName}</strong>
                        </Link>
                        <div className="metadata">Version {row.version}</div>
                      </td>
                      <td>
                        <Link href={`/customers/${row.customerId}`}>
                          {row.customerName}
                        </Link>
                      </td>
                      <td>
                        {row.cloudProvider} / {row.kubernetesDistribution}
                      </td>
                      <td>{row.environmentType}</td>
                      <td>
                        <span
                          className={`status-badge status-${row.status.toLowerCase()}`}
                        >
                          {row.status.replaceAll("_", " ")}
                        </span>
                      </td>
                      <td>{formatDate(row.updatedAt || row.createdAt)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination
              {...query.data.pagination}
              onChange={(page) => setFilters((f) => ({ ...f, page }))}
            />
          </section>
        )
      )}
    </>
  );
}
