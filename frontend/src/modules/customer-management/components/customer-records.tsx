"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { History, MessageSquare, ShieldCheck } from "lucide-react";
import {
  EmptyState,
  ErrorNotice,
  Loading,
  Pagination,
  formatDateTime,
} from "@/shared/components/ui";
import { customersService } from "../services/customers";
import { StatusBadge } from "./customer-badges";
export function StatusHistory({ customerId }: { customerId: string }) {
  const [page, setPage] = useState(0);
  const query = useQuery({
    queryKey: ["customers", customerId, "status-history", page],
    queryFn: ({ signal }) => customersService.history(customerId, page, signal),
  });
  if (query.isPending) return <Loading label="Loading lifecycle history…" />;
  if (query.isError)
    return (
      <ErrorNotice error={query.error} onRetry={() => void query.refetch()} />
    );
  return (
    <section className="panel form-section">
      <h2>Lifecycle history</h2>
      {query.data.history.length === 0 ? (
        <EmptyState icon={<History />} title="No lifecycle records">
          Status changes will appear here.
        </EmptyState>
      ) : (
        <ol className="timeline">
          {query.data.history.map((record) => (
            <li key={record.historyId}>
              <div className="timeline-marker" aria-hidden="true" />
              <div>
                <div className="timeline-heading">
                  {record.fromStatus && (
                    <>
                      <StatusBadge status={record.fromStatus} />
                      <span className="muted">to</span>
                    </>
                  )}
                  <StatusBadge status={record.toStatus} />
                  <time>{formatDateTime(record.changedAt)}</time>
                </div>
                <p className="metadata break-all">
                  Changed by {record.changedBy}
                </p>
                {record.reason && (
                  <p>
                    <strong>Reason:</strong> {record.reason}
                  </p>
                )}
                {record.comments && <p>{record.comments}</p>}
                <details>
                  <summary>Request reference</summary>
                  <code className="break-all">{record.correlationId}</code>
                </details>
              </div>
            </li>
          ))}
        </ol>
      )}
      <Pagination
        {...query.data.pagination}
        onChange={setPage}
        disabled={query.isFetching}
      />
    </section>
  );
}
export function Reviews({ customerId }: { customerId: string }) {
  const [page, setPage] = useState(0);
  const query = useQuery({
    queryKey: ["customers", customerId, "reviews", page],
    queryFn: ({ signal }) => customersService.reviews(customerId, page, signal),
  });
  if (query.isPending) return <Loading label="Loading reviews…" />;
  if (query.isError)
    return (
      <ErrorNotice error={query.error} onRetry={() => void query.refetch()} />
    );
  return (
    <section className="panel form-section">
      <h2>Review history</h2>
      {query.data.items.length === 0 ? (
        <EmptyState icon={<MessageSquare />} title="No reviews yet">
          Reviews appear after a Platform Architect starts reviewing this
          customer.
        </EmptyState>
      ) : (
        <div className="review-list">
          {query.data.items.map((record) => (
            <article key={record.reviewId} className="review-card">
              <div className="panel-title">
                <strong>Review cycle {record.reviewCycle}</strong>
                <span className="status-badge">
                  {record.reviewStatus.replaceAll("_", " ")}
                </span>
              </div>
              <p className="metadata">{formatDateTime(record.reviewedAt)}</p>
              <p className="metadata break-all">
                Reviewer: {record.reviewerId}
              </p>
              {record.comments && <p>{record.comments}</p>}
              {record.rejectionReason && (
                <div className="notice notice-warning">
                  <strong>Rejection reason</strong>
                  <p>{record.rejectionReason}</p>
                </div>
              )}
            </article>
          ))}
        </div>
      )}
      <Pagination
        {...query.data.pagination}
        onChange={setPage}
        disabled={query.isFetching}
      />
    </section>
  );
}
export function AuditLog({ customerId }: { customerId: string }) {
  const [page, setPage] = useState(0);
  const query = useQuery({
    queryKey: ["customers", customerId, "audit-log", page],
    queryFn: ({ signal }) => customersService.audit(customerId, page, signal),
  });
  if (query.isPending) return <Loading label="Loading audit log…" />;
  if (query.isError)
    return (
      <ErrorNotice error={query.error} onRetry={() => void query.refetch()} />
    );
  return (
    <section className="panel form-section">
      <h2>Audit log</h2>
      <p className="muted">
        Immutable records of customer changes and governance actions.
      </p>
      {query.data.items.length === 0 ? (
        <EmptyState icon={<ShieldCheck />} title="No audit records">
          Audited customer actions will appear here.
        </EmptyState>
      ) : (
        <div className="table-scroll">
          <table>
            <caption className="sr-only">Customer audit records</caption>
            <thead>
              <tr>
                <th>Action</th>
                <th>Performed by</th>
                <th>Time</th>
                <th>Change details</th>
              </tr>
            </thead>
            <tbody>
              {query.data.items.map((record) => (
                <tr key={record.auditId}>
                  <td>{record.action.replaceAll("_", " ")}</td>
                  <td className="break-all">{record.performedBy}</td>
                  <td>{formatDateTime(record.performedAt)}</td>
                  <td>
                    <details>
                      <summary>View changes</summary>
                      <div className="audit-values">
                        <strong>Before</strong>
                        <pre>
                          {JSON.stringify(record.oldValue, null, 2) ?? "—"}
                        </pre>
                        <strong>After</strong>
                        <pre>
                          {JSON.stringify(record.newValue, null, 2) ?? "—"}
                        </pre>
                        <p className="metadata break-all">
                          {record.correlationId}
                        </p>
                      </div>
                    </details>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Pagination
        {...query.data.pagination}
        onChange={setPage}
        disabled={query.isFetching}
      />
    </section>
  );
}
