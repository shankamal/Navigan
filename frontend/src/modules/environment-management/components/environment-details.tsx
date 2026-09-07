"use client";
import Link from "next/link";
import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/shared/auth/auth-provider";
import { ApiError } from "@/shared/api/client";
import {
  Button,
  ErrorNotice,
  Loading,
  Modal,
  PageHeading,
  Pagination,
  formatDateTime,
} from "@/shared/components/ui";
import { useEnvironment } from "../hooks/queries";
import { allowedActions, labels } from "../model/policy";
import { environments } from "../services/environments";
import type { Action, HistoryKind } from "../model/types";
export function EnvironmentDetails({ id }: { id: string }) {
  const query = useEnvironment(id);
  const { identity } = useAuth();
  const cache = useQueryClient();
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
    },
  });
  if (query.isPending) return <Loading label="Loading environment…" />;
  if (query.error)
    return <ErrorNotice error={query.error} onRetry={() => query.refetch()} />;
  const env = query.data!;
  const editable =
    ["DRAFT", "REJECTED"].includes(env.status) &&
    identity?.roles.some(
      (r) => r === "CLOUD_ENGINEER" || r === "PLATFORM_ARCHITECT",
    );
  return (
    <>
      <Link href="/environments">← All environments</Link>
      <PageHeading
        eyebrow={`${env.cloudProvider} / ${env.kubernetesDistribution}`}
        title={env.environmentName}
        description={
          env.description || "Reusable cloud infrastructure baseline"
        }
        action={
          editable && (
            <Link
              className="button button-secondary"
              href={`/environments/${id}/edit`}
            >
              Edit environment
            </Link>
          )
        }
      />
      <section className="panel panel-padding">
        <div className="environment-summary">
          <div>
            <span className="muted">Customer</span>
            <p>
              <Link href={`/customers/${env.customerId}`}>
                {env.customerName}
              </Link>
            </p>
          </div>
          <div>
            <span className="muted">Status</span>
            <p>
              <strong>{env.status.replaceAll("_", " ")}</strong>
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
        </div>
        <div className="environment-actions">
          {allowedActions(env, identity).map((a) => (
            <Button
              key={a}
              variant={
                ["reject", "suspend", "deactivate"].includes(a)
                  ? "danger"
                  : "primary"
              }
              onClick={() => {
                setAction(a);
                setReason("");
                setComments("");
                mutation.reset();
              }}
            >
              {labels[a]}
            </Button>
          ))}
        </div>
        {env.status !== "ACTIVE" && (
          <p className="muted">
            New cluster provisioning requires an ACTIVE environment and an
            active parent customer.
          </p>
        )}
      </section>
      {Object.entries(env.workflow).map(
        ([key, value]) =>
          (value.reason || value.comments) && (
            <div className="panel panel-padding" key={key}>
              <strong>
                {key} · {formatDateTime(value.at)}
              </strong>
              {value.reason && <p>{value.reason}</p>}
              {value.comments && <p>{value.comments}</p>}
            </div>
          ),
      )}
      <nav className="environment-tabs" aria-label="Environment records">
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
            variant={tab === t ? "primary" : "secondary"}
            aria-pressed={tab === t}
            onClick={() => {
              setTab(t as typeof tab);
              setPage(0);
            }}
          >
            {t.replaceAll("-", " ")}
          </Button>
        ))}
      </nav>
      {tab === "configuration" ? (
        <section className="panel panel-padding">
          {Object.entries(env.configuration).map(([key, value]) => (
            <details key={key} open className="environment-config-section">
              <summary>{key}</summary>
              <pre className="environment-json">
                {JSON.stringify(value, null, 2)}
              </pre>
            </details>
          ))}
          {!Object.keys(env.configuration).length && (
            <p>Configuration has not been entered yet.</p>
          )}
        </section>
      ) : records.isPending ? (
        <Loading label="Loading history…" />
      ) : records.error ? (
        <ErrorNotice error={records.error} />
      ) : (
        records.data && (
          <section className="panel panel-padding">
            {records.data.items.map((r, i) => (
              <article className="environment-history" key={i}>
                <strong>
                  {r.newStatus ||
                    r.reviewStatus ||
                    r.action ||
                    `Version ${r.version}`}
                </strong>
                <p className="metadata">
                  {formatDateTime(
                    r.changedAt || r.reviewedAt || r.performedAt || r.createdAt,
                  )}{" "}
                  ·{" "}
                  {r.changedBy || r.reviewerId || r.performedBy || r.createdBy}
                </p>
                {r.reason && <p>{r.reason}</p>}
                {r.comments && <p>{r.comments}</p>}
                {r.changeReason && <p>{r.changeReason}</p>}
                {r.version && (
                  <Button
                    variant="secondary"
                    onClick={() => setVersion(r.version!)}
                  >
                    View version {r.version}
                  </Button>
                )}
                {tab === "audit-log" && (
                  <details>
                    <summary>Change snapshots</summary>
                    <pre className="environment-json">
                      {JSON.stringify(
                        { before: r.oldValue, after: r.newValue },
                        null,
                        2,
                      )}
                    </pre>
                  </details>
                )}
              </article>
            ))}
            {!records.data.items.length && <p>No records yet.</p>}
            <Pagination {...records.data.pagination} onChange={setPage} />
          </section>
        )
      )}
      {action && (
        <Modal
          title={labels[action]}
          busy={mutation.isPending}
          onClose={() => setAction(null)}
        >
          <form
            onSubmit={(e) => {
              e.preventDefault();
              mutation.mutate();
            }}
          >
            <p>
              Apply this action to {env.environmentName}, version {env.version}?
            </p>
            {["reject", "suspend", "deactivate"].includes(action) && (
              <label className="field">
                Reason *
                <textarea
                  required
                  maxLength={2000}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
              </label>
            )}
            <label className="field">
              Comments
              <textarea
                maxLength={4000}
                value={comments}
                onChange={(e) => setComments(e.target.value)}
              />
            </label>
            {mutation.error && <ErrorNotice error={mutation.error} />}{" "}
            {mutation.error instanceof ApiError &&
              Array.isArray(mutation.error.details?.fields) && (
                <ul>
                  {(
                    mutation.error.details.fields as {
                      field?: string;
                      message?: string;
                    }[]
                  ).map((f, i) => (
                    <li key={i}>
                      {f.field}: {f.message}
                    </li>
                  ))}
                </ul>
              )}
            <Button disabled={mutation.isPending}>
              {mutation.isPending ? "Applying…" : labels[action]}
            </Button>
          </form>
        </Modal>
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
            <pre className="environment-json">
              {JSON.stringify(historical.data, null, 2)}
            </pre>
          )}
        </Modal>
      )}
    </>
  );
}
