"use client";
import "./environment-workspace.css";
import styles from "./environment-details-studio.module.css";
import {
  EnvironmentContext,
  EnvironmentExplorer,
  EnvironmentRecordPanel,
  EnvironmentVersionView,
} from "./environment-detail-views";
import Link from "next/link";
import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  CheckCircle2,
  Circle,
  Clock3,
  MessageSquareText,
  Pencil,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import { useAuth } from "@/shared/auth/auth-provider";
import { ApiError } from "@/shared/api/client";
import {
  Button,
  ErrorNotice,
  Loading,
  Modal,
  PageHeading,
  formatDateTime,
} from "@/shared/components/ui";
import { useEnvironment } from "../hooks/queries";
import { allowedActions, labels } from "../model/policy";
import { environments } from "../services/environments";
import type { Action, HistoryKind } from "../model/types";

const lifecycle = [
  { status: "DRAFT", label: "Draft" },
  { status: "SUBMITTED", label: "Submitted" },
  { status: "APPROVED", label: "Approved" },
  { status: "ACTIVE", label: "Active" },
] as const;

const actionGuidance: Partial<Record<Action, string>> = {
  revise:
    "Start a new editable draft while the current approved baseline remains available for cluster setup.",
  submit: "Send this environment profile to a platform architect.",
  resubmit: "Send the revised profile back to a platform architect.",
  approve: "Confirm that the profile satisfies the platform requirements.",
  reject: "Return the profile with a clear reason for the author.",
  activate: "Make this approved profile available for cluster setup.",
  suspend: "Temporarily prevent new cluster setup from using this profile.",
  reactivate: "Make this profile available for cluster setup again.",
  deactivate: "Retire this profile from future cluster setup.",
};

export function EnvironmentDetails({ id }: { id: string }) {
  const query = useEnvironment(id);
  const { identity } = useAuth();
  const cache = useQueryClient();
  const governance = useRef<HTMLDetailsElement>(null);
  const [action, setAction] = useState<Action | null>(null);
  const [reason, setReason] = useState("");
  const [comments, setComments] = useState("");
  const [tab, setTab] = useState<HistoryKind | "configuration">(
    "configuration",
  );
  const [page, setPage] = useState(0);
  const [version, setVersion] = useState<number | null>(null);
  const attempt = useRef<{ body: string; key: string } | null>(null);
  const records = useQuery({
    queryKey: ["environment-records", id, tab, page, query.data?.version],
    queryFn: () => environments.records(id, tab as HistoryKind, page),
    enabled: tab !== "configuration",
  });
  const historical = useQuery({
    queryKey: ["environment-version", id, version],
    queryFn: () => environments.version(id, version!),
    enabled: version !== null,
  });
  const mutation = useMutation({
    mutationFn: async () => {
      const input = {
        version: query.data!.version,
        reason: reason || undefined,
        comments: comments || undefined,
      };
      const body = JSON.stringify({ action, ...input });
      if (attempt.current?.body !== body)
        attempt.current = { body, key: crypto.randomUUID() };
      return environments.action(id, action!, input, {
        key: attempt.current!.key,
        version: query.data!.version,
      });
    },
    onSuccess: async () => {
      setAction(null);
      setReason("");
      setComments("");
      await cache.invalidateQueries({ queryKey: ["environment", id] });
      await cache.invalidateQueries({ queryKey: ["environments"] });
      await cache.invalidateQueries({ queryKey: ["environment-count"] });
    },
  });
  if (query.isPending) return <Loading label="Loading environment…" />;
  if (query.error)
    return <ErrorNotice error={query.error} onRetry={() => query.refetch()} />;
  const env = query.data!;
  const editable =
    ["DRAFT", "REJECTED"].includes(env.status) &&
    identity?.roles.includes("CLOUD_ENGINEER");
  const actions = allowedActions(env, identity);
  const submissionAction = actions.find((item) =>
    ["submit", "resubmit"].includes(item),
  );
  const decisionActions = actions.filter(
    (item) => !["submit", "resubmit"].includes(item),
  );
  const lifecycleStatus =
    env.status === "UNDER_REVIEW" ? "SUBMITTED" : env.status;
  const lifecycleIndex = lifecycle.findIndex(
    (step) => step.status === lifecycleStatus,
  );
  return (
    <div
      className={`environment-workspace environment-details-workspace ${styles.workspace}`}
    >
      <Link className={`back-link ${styles.backLink}`} href="/environments">
        ← All environments
      </Link>
      <PageHeading
        eyebrow={`${env.cloudProvider} / ${env.kubernetesDistribution}`}
        title={env.environmentName}
        description={
          env.description || "Reusable cloud infrastructure baseline"
        }
        action={
          <>
            <span className={`status-badge status-${env.status.toLowerCase()}`}>
              {env.status.replaceAll("_", " ")}
            </span>
            <Button
              variant="secondary"
              onClick={() => {
                const element = governance.current;
                if (element) {
                  element.open = !element.open;
                  if (element.open)
                    element.scrollIntoView({ block: "nearest" });
                }
              }}
            >
              Lifecycle actions
            </Button>
            {(editable || submissionAction) && (
              <>
                {editable && (
                  <Link
                    className="button button-secondary"
                    href={`/environments/${id}/edit`}
                  >
                    <Pencil size={16} aria-hidden="true" />
                    Edit draft revision
                  </Link>
                )}
                {submissionAction && (
                  <Button
                    variant="primary"
                    aria-pressed={action === submissionAction}
                    onClick={() => {
                      setAction(
                        action === submissionAction ? null : submissionAction,
                      );
                      setReason("");
                      setComments("");
                      mutation.reset();
                    }}
                  >
                    {labels[submissionAction]}
                  </Button>
                )}
              </>
            )}
          </>
        }
      />
      <EnvironmentContext env={env} />
      <nav
        className={`environment-tabs ${styles.tabs}`}
        aria-label="Environment records"
      >
        {(
          [
            "configuration",
            "status-history",
            "versions",
            "reviews",
            ...(identity?.roles.includes("PLATFORM_ARCHITECT")
              ? ["audit-log"]
              : []),
          ] as const
        ).map((t) => (
          <Button
            key={t}
            variant="ghost"
            className={tab === t ? "selected" : ""}
            aria-pressed={tab === t}
            onClick={() => {
              setTab(t as typeof tab);
              setPage(0);
            }}
          >
            {
              {
                configuration: "Configuration",
                "status-history": "Status History",
                versions: "Versions",
                reviews: "Reviews",
                "audit-log": "Audit Log",
              }[t]
            }
          </Button>
        ))}
      </nav>
      <details
        ref={governance}
        className="environment-governance-controls"
        open={!!action}
      >
        <summary>Lifecycle and governance actions</summary>{" "}
        <section className="panel environment-command-center">
          <header className="environment-command-header">
            <div>
              <span
                className={`status-badge status-${env.status.toLowerCase()}`}
              >
                {env.status.replaceAll("_", " ")}
              </span>
              <h2>Environment lifecycle</h2>
              <p className="muted">
                Review the approved infrastructure baseline and complete the
                next governance action.
              </p>
            </div>
            <ShieldCheck size={26} aria-hidden="true" />
          </header>
          <ol className="lifecycle-track" aria-label="Environment lifecycle">
            {lifecycle.map((step, index) => {
              const complete = lifecycleIndex > index;
              const current = lifecycleIndex === index;
              return (
                <li
                  className={`${complete ? "complete" : ""} ${current ? "current" : ""}`}
                  aria-current={current ? "step" : undefined}
                  key={step.status}
                >
                  <span className="lifecycle-marker" aria-hidden="true">
                    {complete ? (
                      <Check size={15} />
                    ) : current ? (
                      <Clock3 size={15} />
                    ) : (
                      <Circle size={12} />
                    )}
                  </span>
                  <strong>{step.label}</strong>
                </li>
              );
            })}
          </ol>
          <div className="environment-overview-grid">
            <div>
              <span className="muted">Customer</span>
              <p>
                <Link href={`/customers/${env.customerId}`}>
                  {env.customerName}
                </Link>
              </p>
            </div>
            <div>
              <span className="muted">Type / version</span>
              <p>
                {env.environmentType} · v{env.version}
              </p>
            </div>
            <div>
              <span className="muted">Approved baseline</span>
              <p>
                {env.approvedVersion ? (
                  <Button
                    variant="ghost"
                    onClick={() => setVersion(env.approvedVersion!)}
                  >
                    Version {env.approvedVersion}
                  </Button>
                ) : (
                  "Awaiting approval"
                )}
              </p>
            </div>
            <div>
              <span className="muted">Baseline availability</span>
              <p>{env.approvedStatus || "Not active yet"}</p>
            </div>
            <div>
              <span className="muted">Last updated</span>
              <p>{formatDateTime(env.updatedAt || env.createdAt)}</p>
            </div>
          </div>
          {!!decisionActions.length && (
            <div className="environment-decision-bar">
              <div>
                <strong>Next action</strong>
                <p className="muted">
                  Actions remain fully audited and follow the existing
                  permission rules.
                </p>
              </div>
              <div className="environment-actions">
                {decisionActions.map((a) => (
                  <Button
                    key={a}
                    variant={
                      ["reject", "suspend", "deactivate"].includes(a)
                        ? "danger"
                        : action === a
                          ? "primary"
                          : "secondary"
                    }
                    aria-pressed={action === a}
                    onClick={() => {
                      setAction(action === a ? null : a);
                      setReason("");
                      setComments("");
                      mutation.reset();
                    }}
                  >
                    {a === "approve" && <CheckCircle2 size={17} />}
                    {a === "reject" && <XCircle size={17} />}
                    {labels[a]}
                  </Button>
                ))}
              </div>
            </div>
          )}
          {env.approvedVersion &&
            env.approvedStatus === "ACTIVE" &&
            env.status !== "ACTIVE" && (
              <div className="environment-availability-note">
                <ShieldCheck size={18} aria-hidden="true" />
                <p>
                  Approved baseline version {env.approvedVersion} remains active
                  while revision version {env.version} completes review.
                </p>
              </div>
            )}
          {action && (
            <form
              className="environment-decision-panel"
              onSubmit={(event) => {
                event.preventDefault();
                mutation.mutate();
              }}
            >
              <div className="environment-decision-copy">
                <span className="decision-icon" aria-hidden="true">
                  <MessageSquareText size={19} />
                </span>
                <div>
                  <h3>{labels[action]}</h3>
                  <p>{actionGuidance[action]}</p>
                </div>
              </div>
              {["reject", "suspend", "deactivate"].includes(action) && (
                <label className="field">
                  Reason *
                  <textarea
                    required
                    maxLength={2000}
                    value={reason}
                    onChange={(event) => setReason(event.target.value)}
                    placeholder="Explain what must change or why this action is required."
                  />
                </label>
              )}
              <label className="field">
                Review comments <span className="optional-label">Optional</span>
                <textarea
                  maxLength={4000}
                  value={comments}
                  onChange={(event) => setComments(event.target.value)}
                  placeholder="Add context for the audit history and other reviewers."
                />
              </label>
              {mutation.error && <ErrorNotice error={mutation.error} />}
              {mutation.error instanceof ApiError &&
                Array.isArray(mutation.error.details?.fields) && (
                  <ul className="field-error-list">
                    {(
                      mutation.error.details.fields as {
                        field?: string;
                        message?: string;
                      }[]
                    ).map((field, index) => (
                      <li key={index}>
                        {field.field}: {field.message}
                      </li>
                    ))}
                  </ul>
                )}
              <div className="decision-actions">
                <Button
                  type="button"
                  variant="ghost"
                  disabled={mutation.isPending}
                  onClick={() => setAction(null)}
                >
                  Cancel
                </Button>
                <Button
                  variant={
                    ["reject", "suspend", "deactivate"].includes(action)
                      ? "danger"
                      : "primary"
                  }
                  disabled={mutation.isPending}
                >
                  {mutation.isPending
                    ? "Applying…"
                    : `Confirm ${labels[action].toLowerCase()}`}
                </Button>
              </div>
            </form>
          )}
          {env.approvedStatus !== "ACTIVE" && (
            <div className="environment-availability-note">
              <Clock3 size={18} aria-hidden="true" />
              <p>
                New cluster provisioning requires an active environment and an
                active parent customer.
              </p>
            </div>
          )}
        </section>
      </details>
      {tab === "configuration" ? (
        <EnvironmentExplorer
          env={env}
          onVersion={setVersion}
          onReviews={() => {
            setTab("reviews");
            setPage(0);
          }}
        />
      ) : records.isPending ? (
        <Loading label="Loading history…" />
      ) : records.error ? (
        <ErrorNotice error={records.error} />
      ) : (
        records.data && (
          <EnvironmentRecordPanel
            key={`${tab}-${page}`}
            kind={tab}
            records={records.data}
            env={env}
            onVersion={setVersion}
            onPage={setPage}
          />
        )
      )}
      {version !== null && (
        <Modal
          title={`Environment version ${version}`}
          onClose={() => setVersion(null)}
        >
          {historical.isPending ? (
            <Loading label="Loading version…" />
          ) : historical.error ? (
            <ErrorNotice error={historical.error} />
          ) : (
            historical.data && <EnvironmentVersionView env={historical.data} />
          )}
        </Modal>
      )}
    </div>
  );
}
