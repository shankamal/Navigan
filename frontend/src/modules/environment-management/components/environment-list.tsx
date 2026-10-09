"use client";
import "./environment-workspace.css";
import { EnvironmentRing } from "./environment-metrics";
import Link from "next/link";
import { useEffect, useState } from "react";
import {
  CheckCircle2,
  ClipboardList,
  FilePenLine,
  Layers3,
  Plus,
  RefreshCw,
  Clock3,
  FileText,
} from "lucide-react";
import {
  PageHeading,
  Loading,
  ErrorNotice,
  EmptyState,
  Pagination,
  formatDate,
} from "@/shared/components/ui";
import { useAuth } from "@/shared/auth/auth-provider";
import { hasPermission } from "@/shared/auth/permissions";
import { statuses } from "@/modules/customer-management/model/types";
import {
  useEnvironmentCount,
  useEnvironments,
  useMetadata,
} from "../hooks/queries";
import { ProviderBadges } from "@/modules/customer-management/components/customer-badges";
import type { Filters } from "../model/types";

interface EnvironmentListProps {
  mode?: "directory" | "reviews";
}

export function EnvironmentList({
  mode = "directory",
}: EnvironmentListProps = {}) {
  const { identity } = useAuth();
  const [filters, setFilters] = useState<Filters>({
    page: 0,
    pageSize: 20,
    sort: "createdAt,desc",
    status: mode === "reviews" ? "SUBMITTED" : undefined,
  });
  useEffect(() => {
    const syncStatus = () => {
      const value = new URLSearchParams(window.location.search).get("status");
      const status = statuses.find((item) => item === value);
      setFilters((old) => ({
        ...old,
        page: 0,
        status: status ?? (mode === "reviews" ? "SUBMITTED" : undefined),
      }));
    };
    syncStatus();
    window.addEventListener("popstate", syncStatus);
    return () => window.removeEventListener("popstate", syncStatus);
  }, [mode]);
  const [view, setView] = useState<"list" | "board">("list");
  const query = useEnvironments(filters);
  const metadata = useMetadata();
  const awsCount = useEnvironments({
    page: 0,
    pageSize: 1,
    sort: "createdAt,desc",
    cloudProvider: "AWS",
  });
  const azureCount = useEnvironments({
    page: 0,
    pageSize: 1,
    sort: "createdAt,desc",
    cloudProvider: "AZURE",
  });
  const gcpCount = useEnvironments({
    page: 0,
    pageSize: 1,
    sort: "createdAt,desc",
    cloudProvider: "GCP",
  });
  const ociCount = useEnvironments({
    page: 0,
    pageSize: 1,
    sort: "createdAt,desc",
    cloudProvider: "OCI",
  });
  const cloudCounts = [awsCount, azureCount, gcpCount, ociCount];
  const refresh = () => {
    void query.refetch();
    [total, active, submitted, review, draft, ...cloudCounts].forEach(
      (item) => void item.refetch(),
    );
  };
  const total = useEnvironmentCount(undefined, mode === "directory");
  const active = useEnvironmentCount("ACTIVE", mode === "directory");
  const submitted = useEnvironmentCount("SUBMITTED");
  const review = useEnvironmentCount("UNDER_REVIEW");
  const draft = useEnvironmentCount("DRAFT", mode === "directory");
  const approved = useEnvironmentCount("APPROVED", mode === "reviews");
  const rejected = useEnvironmentCount("REJECTED", mode === "reviews");
  const metrics =
    mode === "reviews"
      ? [
          {
            label: "Submitted",
            value: submitted.data,
            icon: ClipboardList,
            note: "Waiting for a reviewer",
          },
          {
            label: "Under review",
            value: review.data,
            icon: FilePenLine,
            note: "Review currently in progress",
          },
          {
            label: "Approved",
            value: approved.data,
            icon: CheckCircle2,
            note: "Approved environment revisions",
          },
          {
            label: "Rejected",
            value: rejected.data,
            icon: Layers3,
            note: "Returned for revision",
          },
        ]
      : [
          {
            label: "Total environments",
            value: total.data,
            icon: Layers3,
            note: "Reusable infrastructure profiles",
          },
          {
            label: "Active",
            value: active.data,
            icon: CheckCircle2,
            note: "Approved for cluster requests",
          },
          {
            label: "Awaiting approval",
            value:
              submitted.data !== undefined && review.data !== undefined
                ? submitted.data + review.data
                : undefined,
            icon: ClipboardList,
            note: "Submitted and under review",
          },
          {
            label: "Drafts",
            value: draft.data,
            icon: FilePenLine,
            note: "Environment profiles in progress",
          },
        ];
  const availableStatuses =
    mode === "reviews"
      ? statuses.filter((status) =>
          ["SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED"].includes(
            status,
          ),
        )
      : statuses;
  const set = (key: string, value: string) =>
    setFilters((f) => ({ ...f, page: 0, [key]: value || undefined }));
  return (
    <div className="environment-workspace environment-list-workspace">
      <div className="environment-portfolio-heading">
        <Layers3 size={32} aria-hidden="true" />
        <PageHeading
          title={
            mode === "reviews"
              ? "Environment Reviews"
              : "Environment Management"
          }
          description={
            mode === "reviews"
              ? "Review submitted environment profiles and move approved requests through the governed lifecycle."
              : "Track reusable infrastructure profiles and create container environments across your clouds."
          }
          action={
            mode === "directory" &&
            hasPermission(identity, "environment.create") && (
              <div className="environment-heading-actions">
                <button
                  className="button button-secondary"
                  type="button"
                  onClick={refresh}
                  aria-label="Refresh environment portfolio"
                >
                  <RefreshCw size={18} />
                </button>
                <Link
                  className="button button-primary"
                  href="/environments/new"
                >
                  <Plus size={18} />
                  New Environment
                </Link>
              </div>
            )
          }
        />
      </div>
      {mode === "directory" ? (
        <div className="environment-portfolio-overview">
          <section
            className="panel environment-portfolio-charts"
            aria-label="Environment portfolio metrics"
          >
            <div className="environment-portfolio-lifecycle">
              <h2>Environments by lifecycle</h2>
              {[total, active, draft, submitted, review].some(
                (q) => q.isError,
              ) ? (
                <p role="status">Metrics unavailable. Refresh to retry.</p>
              ) : [
                  total.data,
                  active.data,
                  draft.data,
                  submitted.data,
                  review.data,
                ].some((v) => v === undefined) ? (
                <p role="status">Loading lifecycle metrics…</p>
              ) : (
                <div className="environment-chart-content">
                  <EnvironmentRing
                    values={[
                      active.data!,
                      draft.data!,
                      submitted.data!,
                      review.data!,
                      Math.max(
                        0,
                        total.data! -
                          active.data! -
                          draft.data! -
                          submitted.data! -
                          review.data!,
                      ),
                    ]}
                    total={total.data!}
                    center={String(total.data)}
                    label={`Environment lifecycle: ${total.data} total environments`}
                  />
                  <ul className="environment-chart-legend">
                    {[
                      { label: "Active", value: active.data, color: "#65a449" },
                      { label: "Draft", value: draft.data, color: "#94a3b8" },
                      {
                        label: "Submitted",
                        value: submitted.data,
                        color: "#b68c45",
                      },
                      {
                        label: "Under review",
                        value: review.data,
                        color: "#64748b",
                      },
                      {
                        label: "Other statuses",
                        value: Math.max(
                          0,
                          total.data! -
                            active.data! -
                            draft.data! -
                            submitted.data! -
                            review.data!,
                        ),
                        color: "#cbd5e1",
                      },
                    ]
                      .filter(
                        (item) => item.label !== "Other statuses" || item.value,
                      )
                      .map((item) => (
                        <li key={item.label}>
                          <span
                            className="environment-chart-dot"
                            style={{ backgroundColor: item.color }}
                          />
                          <span>{item.label}</span>
                          <strong>{item.value}</strong>
                        </li>
                      ))}
                  </ul>
                </div>
              )}
            </div>
            <div className="environment-provider-distribution">
              <h2>Environments by cloud provider</h2>
              {["AWS", "AZURE", "GCP", "OCI"].map((provider, index) => (
                <div className="environment-provider-row" key={provider}>
                  <ProviderBadges codes={[provider]} compact />
                  <span>
                    {provider} / {["EKS", "AKS", "GKE", "OKE"][index]}
                  </span>
                  <strong>
                    {cloudCounts[index].data?.pagination.totalElements ?? "—"}
                  </strong>
                  <meter
                    min={0}
                    max={Math.max(
                      1,
                      total.data ?? 0,
                      cloudCounts[index].data?.pagination.totalElements ?? 0,
                    )}
                    value={
                      cloudCounts[index].data?.pagination.totalElements ?? 0
                    }
                    aria-label={`${provider} environment count`}
                  />
                </div>
              ))}
            </div>
          </section>
          <aside
            className="panel environment-attention"
            aria-label="Environment attention queue"
          >
            <header>
              <h2>
                Attention (
                {submitted.data !== undefined &&
                review.data !== undefined &&
                draft.data !== undefined
                  ? submitted.data + review.data + draft.data
                  : "—"}
                )
              </h2>
              <Link href="/environments/reviews">Open queue →</Link>
            </header>
            {[
              {
                status: "UNDER_REVIEW",
                label: "Under review",
                count: review.data,
                icon: Clock3,
              },
              {
                status: "SUBMITTED",
                label: "Submitted",
                count: submitted.data,
                icon: ClipboardList,
              },
              {
                status: "DRAFT",
                label: "Draft",
                count: draft.data,
                icon: FileText,
              },
            ].map((item) => (
              <button
                type="button"
                key={item.status}
                onClick={() => set("status", item.status)}
              >
                <item.icon size={22} />
                <span>
                  <strong>{item.label}</strong>
                  <small>{item.count ?? "—"} environments</small>
                </span>
                <span aria-hidden="true">›</span>
              </button>
            ))}
          </aside>
        </div>
      ) : (
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
      )}
      <section className="panel panel-padding environment-list-filters">
        <div className="environment-section-heading">
          <div>
            <h2>
              {mode === "reviews"
                ? "Environment review queue"
                : "Environment profiles"}
            </h2>
            <p className="muted">
              {mode === "reviews"
                ? "Submitted requests are shown first. Change the status filter to inspect requests already under review."
                : "Search and manage environment baselines across every lifecycle status."}
            </p>
          </div>
        </div>
        <div
          className="environment-view-switch"
          role="group"
          aria-label="Environment display"
        >
          <button
            type="button"
            className={view === "list" ? "selected" : ""}
            aria-pressed={view === "list"}
            onClick={() => setView("list")}
          >
            List view
          </button>
          <button
            type="button"
            className={view === "board" ? "selected" : ""}
            aria-pressed={view === "board"}
            onClick={() => setView("board")}
          >
            Board view
          </button>
        </div>
        <div className="environment-filter-grid">
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
              {mode === "directory" && <option value="">All statuses</option>}
              {availableStatuses.map((v) => (
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
        {query.isPending ? (
          <Loading label="Loading environments…" />
        ) : query.error ? (
          <ErrorNotice error={query.error} onRetry={() => query.refetch()} />
        ) : query.data && !query.data.items.length ? (
          <EmptyState
            icon={<Layers3 />}
            title={
              mode === "reviews"
                ? "No environment requests in this review state"
                : "No environments found"
            }
          >
            {mode === "reviews"
              ? "Choose another review status or return when new requests are submitted."
              : "Create your first environment or adjust the filters."}
          </EmptyState>
        ) : (
          query.data && (
            <div className="environment-directory-results">
              {view === "board" ? (
                <div
                  className="environment-board"
                  aria-label="Environments grouped by lifecycle status"
                >
                  {availableStatuses
                    .filter((status) =>
                      query.data!.items.some((row) => row.status === status),
                    )
                    .map((status) => (
                      <section
                        className="environment-board-column"
                        key={status}
                      >
                        <h3>
                          {status.replaceAll("_", " ")}{" "}
                          <span>
                            {
                              query.data!.items.filter(
                                (row) => row.status === status,
                              ).length
                            }{" "}
                            on this page
                          </span>
                        </h3>
                        {query
                          .data!.items.filter((row) => row.status === status)
                          .map((row) => (
                            <article
                              className="environment-board-card"
                              key={row.environmentId}
                            >
                              <Link href={`/environments/${row.environmentId}`}>
                                <strong>{row.environmentName}</strong>
                              </Link>
                              <Link href={`/customers/${row.customerId}`}>
                                {row.customerName}
                              </Link>
                              <ProviderBadges codes={[row.cloudProvider]} />
                              <p>
                                {row.kubernetesDistribution} ·{" "}
                                {row.environmentType} · Version {row.version}
                              </p>
                              <small>
                                Updated{" "}
                                {formatDate(row.updatedAt || row.createdAt)}
                              </small>
                              <Link
                                className="environment-open-link"
                                href={`/environments/${row.environmentId}`}
                              >
                                Open environment →
                              </Link>
                            </article>
                          ))}
                      </section>
                    ))}
                </div>
              ) : (
                <div className="table-scroll">
                  <table className="customer-table">
                    <thead>
                      <tr>
                        <th>Environment</th>
                        <th>Customer</th>
                        <th>Distribution</th>
                        <th>Type</th>
                        <th>Status</th>
                        <th>Version</th>
                        <th>Updated</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {query.data.items.map((row) => (
                        <tr key={row.environmentId}>
                          <td>
                            <Link href={`/environments/${row.environmentId}`}>
                              <strong>{row.environmentName}</strong>
                            </Link>
                            <div className="metadata">
                              Version {row.version}
                            </div>
                          </td>
                          <td>
                            <Link href={`/customers/${row.customerId}`}>
                              {row.customerName}
                            </Link>
                          </td>
                          <td>
                            <ProviderBadges codes={[row.cloudProvider]} />
                            <span className="metadata">
                              {row.kubernetesDistribution}
                            </span>
                          </td>
                          <td>{row.environmentType}</td>
                          <td>
                            <span
                              className={`status-badge status-${row.status.toLowerCase()}`}
                            >
                              {row.status.replaceAll("_", " ")}
                            </span>
                          </td>
                          <td>
                            <strong>v{row.version}</strong>
                          </td>
                          <td>{formatDate(row.updatedAt || row.createdAt)}</td>
                          <td>
                            <Link
                              className="environment-row-open"
                              href={`/environments/${row.environmentId}`}
                              aria-label={`Open ${row.environmentName}`}
                            >
                              Open
                            </Link>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <Pagination
                {...query.data.pagination}
                onChange={(page) => setFilters((f) => ({ ...f, page }))}
              />
            </div>
          )
        )}
      </section>
    </div>
  );
}
