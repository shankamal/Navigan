"use client";
import "./environment-workspace.css";
import Link from "next/link";
import { useEffect, useState } from "react";
import {
  CheckCircle2,
  ClipboardList,
  FilePenLine,
  Layers3,
  Plus,
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
      <PageHeading
        eyebrow="ENVIRONMENT MANAGEMENT"
        title={
          mode === "reviews" ? "Environment Reviews" : "Environment Management"
        }
        description={
          mode === "reviews"
            ? "Review submitted environment profiles and move approved requests through the governed lifecycle."
            : "Track reusable infrastructure profiles and create container environments across your clouds."
        }
        action={
          mode === "directory" &&
          hasPermission(identity, "environment.create") && (
            <Link className="button button-primary" href="/environments/new">
              <Plus size={18} />
              New Environment
            </Link>
          )
        }
      />
      <div className="metrics-grid">
        {metrics.map((metric) => (
          <div className="metric" key={metric.label}>
            <div className="metric-label">
              {metric.label}
              <metric.icon size={20} aria-hidden="true" />
            </div>
            <strong>{metric.value ?? "—"}</strong>
            {metric.value !== undefined &&
              total.data !== undefined &&
              mode === "directory" && (
                <meter
                  min={0}
                  max={Math.max(total.data, metric.value, 1)}
                  value={metric.value}
                  aria-label={`${metric.label}: ${metric.value} of ${total.data}`}
                />
              )}
            <p>{metric.note}</p>
          </div>
        ))}
      </div>
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
      </section>
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
          <section className="panel">
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
                    <section className="environment-board-column" key={status}>
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
                        <td>{formatDate(row.updatedAt || row.createdAt)}</td>
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
          </section>
        )
      )}
    </div>
  );
}
