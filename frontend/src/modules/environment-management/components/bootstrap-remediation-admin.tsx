"use client";

import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Search, ShieldAlert, XCircle } from "lucide-react";
import { useAuth } from "@/shared/auth/auth-provider";
import {
  Button,
  EmptyState,
  ErrorNotice,
  Loading,
  PageHeading,
  Pagination,
  formatDateTime,
} from "@/shared/components/ui";
import { environments } from "../services/environments";
import {
  useBootstrapRemediation,
  useBootstrapRemediations,
} from "../hooks/queries";
import type {
  BootstrapRemediation,
  BootstrapRemediationFilters,
} from "../model/types";

const statusLabels: Record<BootstrapRemediation["status"], string> = {
  REQUESTED: "Awaiting review",
  APPROVED: "Approved for plan",
  REJECTED: "Rejected",
  PLAN_RUNNING: "Plan running",
  PLAN_READY: "Plan ready",
  APPLY_RUNNING: "Apply running",
  COMPLETED: "Completed",
  FAILED: "Failed",
};

function StatusBadge({ status }: { status: BootstrapRemediation["status"] }) {
  return (
    <span className={`status-badge status-${status.toLowerCase()}`}>
      {statusLabels[status]}
    </span>
  );
}

export function BootstrapRemediationQueue() {
  const { identity } = useAuth();
  const [filters, setFilters] = useState<BootstrapRemediationFilters>({
    page: 0,
    pageSize: 20,
    status: "REQUESTED",
  });
  const [search, setSearch] = useState("");
  const query = useBootstrapRemediations(filters);

  useEffect(() => {
    const timer = setTimeout(
      () =>
        setFilters((old) => ({
          ...old,
          page: 0,
          search: search.trim() || undefined,
        })),
      300,
    );
    return () => clearTimeout(timer);
  }, [search]);

  if (!identity?.roles.includes("PLATFORM_ARCHITECT")) {
    return (
      <EmptyState title="Platform Architect access required">
        Bootstrap remediation approvals require an independent Platform
        Architect review.
      </EmptyState>
    );
  }

  return (
    <>
      <PageHeading
        eyebrow="GOVERNED REMEDIATION"
        title="Bootstrap Approvals"
        description="Review customer-account resource creation requests before Terraform planning begins."
      />
      <section className="panel">
        <div className="list-heading">
          <div>
            <h2>Remediation request queue</h2>
            <p className="muted">
              Approval authorizes plan generation only. It never applies AWS
              changes.
            </p>
          </div>
        </div>
        <div className="filter-bar">
          <label className="search-field">
            <Search size={18} aria-hidden="true" />
            <span className="sr-only">Search remediation requests</span>
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search request, customer, or AWS account"
            />
          </label>
          <label className="filter-field">
            <span className="sr-only">Filter by status</span>
            <select
              value={filters.status ?? ""}
              onChange={(event) =>
                setFilters((old) => ({
                  ...old,
                  page: 0,
                  status:
                    (event.target.value as BootstrapRemediation["status"]) ||
                    undefined,
                }))
              }
            >
              <option value="">All statuses</option>
              {Object.entries(statusLabels).map(([value, label]) => (
                <option value={value} key={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </div>
        {query.isPending ? (
          <Loading label="Loading remediation requests…" />
        ) : query.isError ? (
          <div className="panel-padding">
            <ErrorNotice error={query.error} onRetry={() => query.refetch()} />
          </div>
        ) : query.data.items.length === 0 ? (
          <EmptyState icon={<ShieldAlert size={28} />} title="No matching requests">
            There are no bootstrap remediation requests in this view.
          </EmptyState>
        ) : (
          <>
            <div className="table-scroll">
              <table className="customer-table">
                <thead>
                  <tr>
                    <th>Request</th>
                    <th>Customer account</th>
                    <th>Resources</th>
                    <th>Status</th>
                    <th>Requested</th>
                  </tr>
                </thead>
                <tbody>
                  {query.data.items.map((item) => (
                    <tr key={item.requestId}>
                      <td>
                        <Link href={`/environments/remediations/${item.requestId}`}>
                          <strong>{item.requestId}</strong>
                        </Link>
                        <div className="metadata">{item.region}</div>
                      </td>
                      <td>
                        {item.customerName || item.customerId}
                        <div className="metadata">{item.accountId}</div>
                      </td>
                      <td>{item.missingResources.length} requested</td>
                      <td><StatusBadge status={item.status} /></td>
                      <td>{formatDateTime(item.requestedAt)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="list-footer">
              <Pagination
                {...query.data.pagination}
                onChange={(page) => setFilters((old) => ({ ...old, page }))}
                disabled={query.isFetching}
              />
            </div>
          </>
        )}
      </section>
    </>
  );
}

export function BootstrapRemediationDetails({
  requestId,
}: {
  requestId: string;
}) {
  const { identity } = useAuth();
  const cache = useQueryClient();
  const query = useBootstrapRemediation(requestId);
  const [reason, setReason] = useState("");
  const mutation = useMutation({
    mutationFn: (decision: "approve" | "reject") =>
      environments.decideBootstrapRemediation(
        requestId,
        decision,
        { version: query.data!.version, reason: reason.trim() || undefined },
        { key: crypto.randomUUID() },
      ),
    onSuccess: (value) => {
      cache.setQueryData(["bootstrap-remediation", requestId], value);
      void cache.invalidateQueries({ queryKey: ["bootstrap-remediations"] });
    },
  });

  if (!identity?.roles.includes("PLATFORM_ARCHITECT")) {
    return (
      <EmptyState title="Platform Architect access required">
        This request requires an independent Platform Architect reviewer.
      </EmptyState>
    );
  }
  if (query.isPending) return <Loading label="Loading remediation request…" />;
  if (query.isError)
    return <ErrorNotice error={query.error} onRetry={() => query.refetch()} />;

  const item = query.data;
  const ownRequest = item.requestedBy === identity.subject;
  const pending = item.status === "REQUESTED";
  const submit = (decision: "approve" | "reject") => (event: FormEvent) => {
    event.preventDefault();
    mutation.mutate(decision);
  };

  return (
    <>
      <PageHeading
        eyebrow="BOOTSTRAP REMEDIATION"
        title={item.requestId}
        description="Independent review of proposed customer-account prerequisites."
        action={<StatusBadge status={item.status} />}
      />
      <div className="remediation-detail-grid">
        <section className="panel panel-padding">
          <h2>Requested account changes</h2>
          <p className="muted">
            Customer: {item.customerName || item.customerId} · AWS account{" "}
            {item.accountId} · {item.region}
          </p>
          <div className="remediation-resource-list">
            {item.missingResources.map((resource, index) => (
              <article key={`${resource}-${index}`}>
                <CheckCircle2 size={20} aria-hidden="true" />
                <div>
                  <strong>{resource}</strong>
                  <p>{item.requestedActions[index] || "Create and validate this prerequisite."}</p>
                </div>
              </article>
            ))}
          </div>
          <dl className="remediation-audit-grid">
            <div><dt>Requested by</dt><dd>{item.requestedBy}</dd></div>
            <div><dt>Confirmed at</dt><dd>{formatDateTime(item.confirmedAt)}</dd></div>
            <div><dt>Discovery role</dt><dd className="break-all">{item.discoveryRoleArn}</dd></div>
            <div><dt>Correlation ID</dt><dd className="break-all">{item.correlationId}</dd></div>
          </dl>
        </section>
        <aside className="panel panel-padding remediation-decision">
          <p className="eyebrow">DECISION GATE</p>
          <h2>Authorize Terraform planning</h2>
          <p>
            Approval permits Navigan to generate and validate an immutable
            Terraform plan. A separate certified-plan gate is required before
            any apply.
          </p>
          {ownRequest && (
            <div className="notice notice-error">
              <XCircle size={20} />
              <div>
                <strong>Independent reviewer required</strong>
                <p>You cannot approve a request you submitted.</p>
              </div>
            </div>
          )}
          {pending && !ownRequest ? (
            <form>
              <label className="field">
                <span>Decision reason</span>
                <textarea
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  placeholder="Record review evidence or rejection guidance"
                  maxLength={2000}
                />
              </label>
              {mutation.isError && <ErrorNotice error={mutation.error} />}
              <div className="form-actions">
                <Button
                  variant="danger"
                  disabled={mutation.isPending || !reason.trim()}
                  onClick={submit("reject")}
                >
                  Reject
                </Button>
                <Button
                  disabled={mutation.isPending}
                  onClick={submit("approve")}
                >
                  Approve for plan
                </Button>
              </div>
            </form>
          ) : (
            <div className="remediation-decision-record">
              <strong>{statusLabels[item.status]}</strong>
              <p>{item.decisionReason || "No decision reason recorded."}</p>
              {item.decidedBy && (
                <span>
                  {item.decidedBy} · {formatDateTime(item.decidedAt)}
                </span>
              )}
            </div>
          )}
        </aside>
      </div>
    </>
  );
}
