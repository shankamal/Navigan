"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowUpRight,
  Building2,
  CheckCircle2,
  Columns3,
  List,
  Plus,
  RefreshCw,
  Search,
} from "lucide-react";
import { useAuth } from "@/shared/auth/auth-provider";
import {
  Button,
  EmptyState,
  ErrorNotice,
  Loading,
  PageHeading,
  Pagination,
  formatDate,
} from "@/shared/components/ui";
import { useCustomerCount, useCustomers } from "../hooks/queries";
import { canCreate, cloudProviders, statusLabels } from "../model/policy";
import {
  statuses,
  type CustomerFilters,
  type CustomerStatus,
} from "../model/types";
import "./customer-workspace.css";
import { CustomerMetrics } from "./customer-metrics";
import { ProviderBadges, StatusBadge } from "./customer-badges";
export function CustomerListView() {
  const { identity } = useAuth();
  const [filters, setFilters] = useState<CustomerFilters>({
    page: 0,
    pageSize: 5,
    sort: "createdAt,desc",
  });
  useEffect(() => {
    const syncStatus = () => {
      const value = new URLSearchParams(window.location.search).get("status");
      const status = statuses.find((item) => item === value);
      setFilters((old) => ({ ...old, page: 0, status }));
    };
    syncStatus();
    window.addEventListener("popstate", syncStatus);
    return () => window.removeEventListener("popstate", syncStatus);
  }, []);
  const [search, setSearch] = useState("");
  useEffect(() => {
    const timeout = setTimeout(
      () =>
        setFilters((previous) => ({
          ...previous,
          page: 0,
          search: search.trim() || undefined,
        })),
      300,
    );
    return () => clearTimeout(timeout);
  }, [search]);
  const customers = useCustomers(filters);
  const total = useCustomerCount();
  const active = useCustomerCount("ACTIVE");
  const submitted = useCustomerCount("SUBMITTED");
  const review = useCustomerCount("UNDER_REVIEW");
  const draft = useCustomerCount("DRAFT");
  const [view, setView] = useState<"list" | "board">("list");
  const metricQueries = [total, active, submitted, review, draft];
  const boardStatuses = statuses.filter(
    (status) =>
      ["DRAFT", "SUBMITTED", "UNDER_REVIEW", "ACTIVE"].includes(status) ||
      customers.data?.items.some((customer) => customer.status === status),
  );
  const reset = () => {
    setSearch("");
    setFilters({ page: 0, pageSize: 5, sort: "createdAt,desc" });
  };
  const filter = (values: Partial<CustomerFilters>) =>
    setFilters((old) => ({ ...old, ...values, page: 0 }));
  return (
    <div className="customer-workspace">
      <PageHeading
        eyebrow="CUSTOMER MANAGEMENT"
        title="Customers"
        description="Onboard customers and manage their journey across your cloud platform."
        action={
          canCreate(identity) && (
            <Link href="/customers/new" className="button button-primary">
              <Plus size={18} />
              Create customer
            </Link>
          )
        }
      />
      <CustomerMetrics
        total={total.data}
        active={active.data}
        draft={draft.data}
        submitted={submitted.data}
        review={review.data}
        failed={metricQueries.some((query) => query.isError)}
      />
      <section className="panel">
        <div className="list-heading">
          <div>
            <h2>Customer directory</h2>
            <p className="muted">
              Customer records, provider associations, and onboarding status.
            </p>
          </div>
          <Button
            variant="ghost"
            aria-label="Refresh customer directory"
            disabled={customers.isFetching}
            onClick={() => {
              void customers.refetch();
              void total.refetch();
              void active.refetch();
              void submitted.refetch();
              void review.refetch();
              void draft.refetch();
            }}
          >
            <RefreshCw
              size={18}
              className={customers.isFetching ? "animate-spin" : ""}
            />
            <span>Refresh</span>
          </Button>
        </div>
        <div
          className="customer-view-toggle"
          role="group"
          aria-label="Customer view"
        >
          <Button
            variant="secondary"
            aria-pressed={view === "list"}
            onClick={() => setView("list")}
          >
            <List size={17} />
            List
          </Button>
          <Button
            variant="secondary"
            aria-pressed={view === "board"}
            onClick={() => setView("board")}
          >
            <Columns3 size={17} />
            Board
          </Button>
        </div>
        <div className="filter-bar">
          <label className="search-field">
            <Search size={18} aria-hidden="true" />
            <span className="sr-only">Search customers by name or ID</span>
            <input
              value={search}
              maxLength={255}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search by customer name or ID"
              type="search"
            />
          </label>
          <label className="filter-field">
            <span className="sr-only">Filter by status</span>
            <select
              aria-label="Filter by status"
              value={filters.status ?? ""}
              onChange={(event) =>
                filter({
                  status: (event.target.value || undefined) as
                    CustomerStatus | undefined,
                })
              }
            >
              <option value="">All statuses</option>
              {statuses.map((status) => (
                <option key={status} value={status}>
                  {statusLabels[status]}
                </option>
              ))}
            </select>
          </label>
          <label className="filter-field">
            <span className="sr-only">Filter by cloud provider</span>
            <select
              value={filters.cloudProvider ?? ""}
              onChange={(event) =>
                filter({ cloudProvider: event.target.value || undefined })
              }
            >
              <option value="">All cloud providers</option>
              {cloudProviders.map((p) => (
                <option key={p.code} value={p.code}>
                  {p.shortName}
                </option>
              ))}
            </select>
          </label>
          <label className="filter-field">
            <span className="sr-only">Sort customers</span>
            <select
              value={filters.sort}
              onChange={(event) =>
                filter({ sort: event.target.value as CustomerFilters["sort"] })
              }
            >
              <option value="createdAt,desc">Newest first</option>
              <option value="createdAt,asc">Oldest first</option>
              <option value="name,asc">Name A–Z</option>
              <option value="name,desc">Name Z–A</option>
              <option value="updatedAt,desc">Recently updated</option>
              <option value="status,asc">Status A–Z</option>
            </select>
          </label>
        </div>
        {(filters.status || filters.cloudProvider || search) && (
          <div className="filter-summary">
            <span>Filters applied</span>
            <Button variant="ghost" onClick={reset}>
              Clear filters
            </Button>
          </div>
        )}
        {customers.isPending ? (
          <Loading />
        ) : customers.isError ? (
          <div className="panel-padding">
            <ErrorNotice
              error={customers.error}
              onRetry={() => void customers.refetch()}
            />
          </div>
        ) : customers.data.items.length === 0 ? (
          <EmptyState
            icon={<Building2 size={28} />}
            title={
              filters.status || filters.cloudProvider || search
                ? "No matching customers"
                : "Your customer directory starts here"
            }
            action={
              filters.status || filters.cloudProvider || search ? (
                <Button variant="secondary" onClick={reset}>
                  Clear filters
                </Button>
              ) : canCreate(identity) ? (
                <Link href="/customers/new" className="button button-primary">
                  <Plus size={18} />
                  Create customer
                </Link>
              ) : undefined
            }
          >
            {filters.status || filters.cloudProvider || search
              ? "Try another name, status, or cloud provider."
              : "Create a customer draft, add contacts and cloud providers, then submit it for review."}
          </EmptyState>
        ) : (
          <>
            {view === "board" ? (
              <>
                <p className="customer-board-note">
                  Board shows customers on this page. Status changes follow the
                  approval workflow.
                </p>
                <div className="customer-board">
                  {boardStatuses.map((status) => {
                    const items = customers.data.items.filter(
                      (customer) => customer.status === status,
                    );
                    return (
                      <section
                        className={`customer-board-column board-${status.toLowerCase()}`}
                        key={status}
                        aria-label={`${statusLabels[status]} customers`}
                      >
                        <header>
                          <h3>{statusLabels[status]}</h3>
                          <span>{items.length} on this page</span>
                        </header>
                        {items.length === 0 ? (
                          <p className="customer-board-empty">
                            No customers on this page
                          </p>
                        ) : (
                          items.map((customer) => (
                            <article
                              className="customer-board-card"
                              key={customer.customerId}
                            >
                              <div className="customer-cell">
                                <span
                                  className="customer-avatar"
                                  aria-hidden="true"
                                >
                                  {customer.name.substring(0, 2).toUpperCase()}
                                </span>
                                <div>
                                  <Link
                                    className="customer-name"
                                    href={`/customers/${customer.customerId}`}
                                  >
                                    {customer.name}
                                  </Link>
                                  <p
                                    className="customer-id"
                                    title={customer.customerId}
                                  >
                                    {customer.customerId}
                                  </p>
                                </div>
                              </div>
                              <ProviderBadges codes={customer.cloudProviders} />
                              <footer>
                                <span>
                                  Updated {formatDate(customer.updatedAt)}
                                </span>
                                <Link
                                  href={`/customers/${customer.customerId}`}
                                  aria-label={`View ${customer.name}`}
                                >
                                  Open <ArrowUpRight size={16} />
                                </Link>
                              </footer>
                            </article>
                          ))
                        )}
                      </section>
                    );
                  })}
                </div>
              </>
            ) : (
              <div className="table-scroll">
                <table className="customer-table">
                  <caption className="sr-only">
                    Customers matching the current filters
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col">Customer</th>
                      <th scope="col">Cloud providers</th>
                      <th scope="col">Status</th>
                      <th scope="col">Created</th>
                      <th scope="col">Last updated</th>
                      <th scope="col">
                        <span className="sr-only">Open customer</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {customers.data.items.map((customer) => (
                      <tr key={customer.customerId}>
                        <td>
                          <div className="customer-cell">
                            <span
                              className="customer-avatar"
                              aria-hidden="true"
                            >
                              {customer.name.substring(0, 2).toUpperCase()}
                            </span>
                            <div>
                              <Link
                                href={`/customers/${customer.customerId}`}
                                className="customer-name"
                              >
                                {customer.name}
                              </Link>
                              <p
                                className="customer-id"
                                title={customer.customerId}
                              >
                                {customer.customerId}
                              </p>
                            </div>
                          </div>
                        </td>
                        <td>
                          <ProviderBadges codes={customer.cloudProviders} />
                        </td>
                        <td>
                          <StatusBadge status={customer.status} />
                        </td>
                        <td>{formatDate(customer.createdAt)}</td>
                        <td>{formatDate(customer.updatedAt)}</td>
                        <td>
                          <Link
                            href={`/customers/${customer.customerId}`}
                            className="icon-link"
                            aria-label={`View ${customer.name}`}
                          >
                            <ArrowUpRight size={19} />
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <div className="list-footer">
              <label>
                Rows per page
                <select
                  aria-label="Rows per page"
                  value={filters.pageSize}
                  onChange={(event) =>
                    filter({ pageSize: Number(event.target.value) })
                  }
                >
                  {[5, 10, 20, 50, 100].map((size) => (
                    <option key={size}>{size}</option>
                  ))}
                </select>
              </label>
              <Pagination
                {...customers.data.pagination}
                onChange={(page) => setFilters((old) => ({ ...old, page }))}
                disabled={customers.isFetching}
              />
            </div>
          </>
        )}
      </section>
    </div>
  );
}
