"use client";
import { useState, type KeyboardEvent } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Pencil,
  RefreshCw,
  UserRound,
  ClipboardCheck,
} from "lucide-react";
import { useAuth } from "@/shared/auth/auth-provider";
import {
  Button,
  ErrorNotice,
  Loading,
  PageHeading,
  formatDateTime,
} from "@/shared/components/ui";
import { useCustomer } from "../hooks/queries";
import { allowedActions, canEdit, submissionMissing } from "../model/policy";
import type { Customer, WorkflowAction } from "../model/types";
import { StatusBadge } from "./customer-badges";
import { CustomerProviders } from "./customer-providers";
import { CustomerActionDialog } from "./customer-actions";
import { AuditLog, Reviews, StatusHistory } from "./customer-records";
export function CustomerDetailsView({ customerId }: { customerId: string }) {
  const query = useCustomer(customerId);
  const { identity } = useAuth();
  const [tab, setTab] = useState("overview");
  const [action, setAction] = useState<WorkflowAction | null>(null);
  if (query.isPending) return <Loading label="Loading customer…" />;
  if (query.isError)
    return (
      <>
        <Link className="back-link" href="/customers">
          <ArrowLeft size={16} />
          Back to customers
        </Link>
        <ErrorNotice error={query.error} onRetry={() => void query.refetch()} />
      </>
    );
  const customer = query.data;
  const editable = canEdit(identity, customer);
  const actions = allowedActions(identity, customer);
  const architect = identity?.roles.includes("PLATFORM_ARCHITECT");
  const tabs = [
    { key: "overview", label: "Overview" },
    { key: "history", label: "Lifecycle history" },
    { key: "reviews", label: "Reviews" },
    ...(architect ? [{ key: "audit", label: "Audit log" }] : []),
  ];
  const handleTabKey = (
    event: KeyboardEvent<HTMLButtonElement>,
    index: number,
  ) => {
    let next: number | undefined;
    if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
    if (event.key === "ArrowLeft")
      next = (index - 1 + tabs.length) % tabs.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = tabs.length - 1;
    if (next !== undefined) {
      event.preventDefault();
      setTab(tabs[next].key);
      document.getElementById(`tab-${tabs[next].key}`)?.focus();
    }
  };
  return (
    <>
      <Link className="back-link" href="/customers">
        <ArrowLeft size={16} />
        Back to customers
      </Link>
      <PageHeading
        eyebrow="CUSTOMER PROFILE"
        title={customer.name}
        description={customer.customerId}
        action={
          <>
            <Button
              variant="secondary"
              disabled={query.isFetching}
              onClick={() => void query.refetch()}
              aria-label="Refresh customer"
            >
              <RefreshCw size={17} />
            </Button>
            {editable && (
              <Link
                href={`/customers/${customer.customerId}/edit`}
                className="button button-secondary"
              >
                <Pencil size={16} />
                Edit customer
              </Link>
            )}
            {actions.map((item) => (
              <Button
                key={item.action}
                variant={item.destructive ? "danger" : "primary"}
                onClick={() => setAction(item)}
              >
                {item.label}
              </Button>
            ))}
          </>
        }
      />
      <div className="customer-meta">
        <StatusBadge status={customer.status} />
        <span>Version {customer.version}</span>
        <span>Review cycle {customer.reviewCycle ?? 0}</span>
        <span>Created {formatDateTime(customer.createdAt)}</span>
      </div>
      {customer.status === "REJECTED" && customer.rejectionReason && (
        <div className="notice notice-warning">
          <ClipboardCheck size={20} />
          <div>
            <strong>Changes requested</strong>
            <p>{customer.rejectionReason}</p>
          </div>
        </div>
      )}
      {customer.status === "SUSPENDED" && customer.suspensionReason && (
        <div className="notice notice-warning">
          <strong>Suspension reason</strong>
          <p>{customer.suspensionReason}</p>
        </div>
      )}
      {customer.status === "DEACTIVATED" && (
        <div className="notice">
          <strong>This customer has been deactivated.</strong>
          <p>{customer.deactivationReason}</p>
        </div>
      )}
      {architect &&
        ["SUBMITTED", "UNDER_REVIEW"].includes(customer.status) &&
        [customer.createdBy, customer.submittedBy].includes(
          identity?.subject,
        ) && (
          <div className="notice">
            An independent Platform Architect must review this request. You
            created or submitted it.
          </div>
        )}
      <div className="tabs" role="tablist" aria-label="Customer information">
        {tabs.map((item, index) => (
          <button
            role="tab"
            key={item.key}
            id={`tab-${item.key}`}
            aria-controls={`panel-${item.key}`}
            aria-selected={tab === item.key}
            tabIndex={tab === item.key ? 0 : -1}
            onKeyDown={(event) => handleTabKey(event, index)}
            onClick={() => setTab(item.key)}
          >
            {item.label}
          </button>
        ))}
      </div>
      <div
        role="tabpanel"
        id={`panel-${tab}`}
        aria-labelledby={`tab-${tab}`}
        tabIndex={0}
      >
        {tab === "overview" && (
          <div className="detail-layout">
            <div className="detail-main">
              <section className="panel form-section">
                <h2>Customer information</h2>
                <dl className="details-grid">
                  <div>
                    <dt>Customer name</dt>
                    <dd>{customer.name}</dd>
                  </div>
                  <div>
                    <dt>Onboarding request</dt>
                    <dd className="break-all">
                      {customer.onboardingRequestId}
                    </dd>
                  </div>
                  <div className="full-width">
                    <dt>Description</dt>
                    <dd className="preserve-lines">
                      {customer.description || "No description added."}
                    </dd>
                  </div>
                </dl>
              </section>
              <CustomerProviders
                customerId={customer.customerId}
                editable={editable}
              />
              <section className="panel form-section">
                <h2>Contacts</h2>
                {customer.contacts.length ? (
                  <div className="contacts-grid">
                    {customer.contacts.map((contact, index) => (
                      <article key={index} className="contact-card">
                        <div className="contact-icon">
                          <UserRound size={20} />
                        </div>
                        <div>
                          <p className="contact-type">
                            {contact.type.toLowerCase()}
                          </p>
                          <h3>{contact.name}</h3>
                          {contact.email && (
                            <a
                              href={`mailto:${contact.email}`}
                              className="break-all"
                            >
                              {contact.email}
                            </a>
                          )}
                          {contact.phone && <p>{contact.phone}</p>}
                        </div>
                      </article>
                    ))}
                  </div>
                ) : (
                  <p className="muted">
                    No contacts added. Add a primary contact before submission.
                  </p>
                )}
              </section>
            </div>
            <aside>
              <section className="panel form-section lifecycle-card">
                <span className="eyebrow">GOVERNANCE</span>
                <h2>Onboarding progress</h2>
                <ol className="progress-list">
                  {[
                    "Draft",
                    "Submitted",
                    "Under review",
                    "Approved",
                    "Active",
                  ].map((label, index) => (
                    <li
                      key={label}
                      className={
                        index <= progressIndex(customer) ? "complete" : ""
                      }
                    >
                      <span>{index + 1}</span>
                      {label}
                    </li>
                  ))}
                </ol>
                {editable && submissionMissing(customer).length > 0 && (
                  <div className="notice">
                    <strong>Before you submit</strong>
                    <ul>
                      {submissionMissing(customer).map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </div>
                )}
                <dl className="metadata-list">
                  <div>
                    <dt>Created by</dt>
                    <dd>{customer.createdBy ?? "—"}</dd>
                  </div>
                  <div>
                    <dt>Last updated</dt>
                    <dd>{formatDateTime(customer.updatedAt)}</dd>
                  </div>
                  {customer.submittedAt && (
                    <div>
                      <dt>Submitted</dt>
                      <dd>{formatDateTime(customer.submittedAt)}</dd>
                    </div>
                  )}
                  {customer.approvedAt && (
                    <div>
                      <dt>Approved</dt>
                      <dd>{formatDateTime(customer.approvedAt)}</dd>
                    </div>
                  )}
                </dl>
              </section>
            </aside>
          </div>
        )}
        {tab === "history" && (
          <StatusHistory customerId={customer.customerId} />
        )}{" "}
        {tab === "reviews" && <Reviews customerId={customer.customerId} />}{" "}
        {tab === "audit" && architect && (
          <AuditLog customerId={customer.customerId} />
        )}
      </div>
      {action && (
        <CustomerActionDialog
          customer={customer}
          action={action}
          onClose={() => setAction(null)}
        />
      )}
    </>
  );
}
function progressIndex(customer: Customer): number {
  return {
    DRAFT: 0,
    SUBMITTED: 1,
    UNDER_REVIEW: 2,
    APPROVED: 3,
    ACTIVE: 4,
    REJECTED: 0,
    SUSPENDED: 4,
    DEACTIVATED: 4,
  }[customer.status];
}
