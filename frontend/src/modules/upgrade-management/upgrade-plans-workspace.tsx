"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { X, RefreshCw } from "lucide-react";
import { clusters } from "@/modules/cluster-management/service";
import { hasPermission } from "@/shared/auth/permissions";
import { Button } from "@/shared/components/ui";
import { useUpgradePlans } from "./upgrade-plan-data";
import { PlanComponents, EvidenceChecks, PlanCheck } from "./plan-components";
import { scheduleOverdue, useScheduleClock } from "./schedule-state";
import { ClusterContext } from "./cluster-context";
import { MaintenanceCalendar } from "./maintenance-calendar";
import { rescheduleBlockReason } from "./plan-availability";
import { PlatformIdentity, containerIdentity } from "./platform-identity";
import { PlanScopeLabel } from "./plan-scope";

type Filter = "all" | "drafts" | "review" | "scheduled" | "overdue";
const statusLabel = (status: string) =>
  status === "SUBMITTED" ? "Awaiting approval" : status.replaceAll("_", " ");
const timeLabel = (value?: string | null) =>
  value ? new Date(value).toLocaleString() : "No time requested";

export function UpgradePlansWorkspace({
  mode,
  initialPlanId,
  rescheduleRequested = false,
  onCreate,
  drawerOnly = false,
  onClose,
}: {
  drawerOnly?: boolean;
  onClose?: () => void;
  mode: "schedule" | "history";
  initialPlanId?: string;
  rescheduleRequested?: boolean;
  onCreate?: (kind: "containers" | "utilities", date: string) => void;
}) {
  const data = useUpgradePlans();
  const now = useScheduleClock();
  const [newSchedule, setNewSchedule] = useState("");
  const [filter, setFilter] = useState<Filter>(
    rescheduleRequested && !initialPlanId ? "overdue" : "all",
  );
  const [selectedId, setSelectedId] = useState<string | null>(
    initialPlanId ?? null,
  );
  const [reason, setReason] = useState("");
  const [confirmStart, setConfirmStart] = useState(false);
  const drawerRef = useRef<HTMLElement>(null);
  const rescheduleRef = useRef<HTMLInputElement>(null);
  const closeCallback = useRef(onClose);
  closeCallback.current = onClose;
  const closeDrawer = () => {
    if (window.history.state?.naviganUpgradePlan === selectedId)
      window.history.back();
    setSelectedId(null);
    closeCallback.current?.();
  };
  useEffect(() => {
    if (!selectedId) return;
    const previous = window.location.href;
    const previousState = window.history.state;
    window.history.pushState(
      { ...window.history.state, naviganUpgradePlan: selectedId },
      "",
      "#upgrade-plan=" + encodeURIComponent(selectedId),
    );
    const back = () => {
      setSelectedId(null);
      closeCallback.current?.();
    };
    window.addEventListener("popstate", back);
    return () => {
      window.removeEventListener("popstate", back);
      if (window.history.state?.naviganUpgradePlan === selectedId)
        window.history.replaceState(previousState, "", previous);
    };
  }, [selectedId]);
  const selected = data.rows.find((row) => row.plan.planId === selectedId);
  const hasSelectedPlan = Boolean(selected);
  useEffect(() => {
    if (!selectedId || !hasSelectedPlan) return;
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    (rescheduleRequested && !rescheduleRef.current?.disabled
      ? (rescheduleRef.current ?? drawerRef.current)
      : drawerRef.current
    )?.focus();
    return () => {
      document.body.style.overflow = overflow;
      previous?.focus();
    };
  }, [selectedId, hasSelectedPlan, rescheduleRequested]);
  const canApprove =
    hasPermission(data.identity, "cluster.approve") ||
    hasPermission(data.identity, "cluster.upgrade.approve");
  const canPlan = hasPermission(data.identity, "cluster.upgrade.plan");
  const canExecute = hasPermission(data.identity, "cluster.apply");
  const subject = data.identity?.subject;
  const waiting = data.rows.filter(
    (row) =>
      row.plan.status === "SUBMITTED" &&
      row.plan.createdBy !== subject &&
      row.plan.submittedBy !== subject &&
      !scheduleOverdue(row.plan, now) &&
      canApprove,
  );
  const rows = data.rows
    .filter((row) => {
      if (
        mode === "schedule" &&
        !["DRAFT", "SUBMITTED", "APPROVED", "SCHEDULED", "EXECUTING"].includes(
          row.plan.status,
        )
      )
        return false;
      if (mode === "schedule" && !row.plan.scheduledFor) return false;
      if (filter === "drafts")
        return (
          row.plan.status === "DRAFT" &&
          (row.plan.createdBy === subject || row.plan.updatedBy === subject)
        );
      if (filter === "overdue") return scheduleOverdue(row.plan, now);
      if (filter === "review")
        return waiting.some((item) => item.plan.planId === row.plan.planId);
      if (filter === "scheduled")
        return ["APPROVED", "SCHEDULED", "EXECUTING"].includes(row.plan.status);
      return true;
    })
    .sort((a, b) =>
      mode === "schedule"
        ? (a.plan.scheduledFor ?? "").localeCompare(b.plan.scheduledFor ?? "")
        : b.plan.updatedAt.localeCompare(a.plan.updatedAt),
    );
  const action = useMutation({
    mutationFn: ({
      planId,
      name,
    }: {
      planId: string;
      name:
        | "submit"
        | "approve"
        | "reject"
        | "cancel"
        | "execute"
        | "refresh"
        | "reschedule";
    }) => {
      const row = data.rows.find((item) => item.plan.planId === planId)!;
      return clusters.changeUpgradePlan(
        row.plan.clusterId,
        planId,
        name,
        row.plan.version,
        name === "approve" || name === "reject"
          ? reason.trim() || undefined
          : undefined,
        ...(name === "reschedule" ? [new Date(newSchedule).toISOString()] : []),
      );
    },
    onSuccess: () => {
      data.refresh();
      setReason("");
      setNewSchedule("");
      setConfirmStart(false);
    },
  });
  const plan = selected?.plan;
  const overdue = plan ? scheduleOverdue(plan, now) : false;
  const canReviewSelected = Boolean(
    plan &&
    plan.status === "SUBMITTED" &&
    canApprove &&
    !overdue &&
    plan.createdBy !== subject &&
    plan.submittedBy !== subject,
  );
  const rescheduleBlocked = plan
    ? rescheduleBlockReason(data.identity, plan)
    : undefined;
  const run = (
    name:
      | "submit"
      | "approve"
      | "reject"
      | "cancel"
      | "execute"
      | "refresh"
      | "reschedule",
  ) => {
    if (plan) action.mutate({ planId: plan.planId, name });
  };
  return (
    <section
      className={
        drawerOnly ? "upgrade-plan-overlay-host" : "upgrade-live-capability"
      }
    >
      <div hidden={drawerOnly}>
        <header className="upgrade-live-header">
          <div>
            <p className="eyebrow">Governed upgrade records</p>
            <h2>
              {mode === "schedule"
                ? "Maintenance schedule"
                : "Plans and execution history"}
            </h2>
            <p>
              Requested windows remain visible during review. Approval and
              starting execution are separate actions.
            </p>
          </div>
          <Button
            variant="secondary"
            disabled={data.pending}
            onClick={data.refresh}
          >
            <RefreshCw size={16} /> Refresh plans
          </Button>
        </header>
        <div className="upgrade-plan-filters" aria-label="Filter upgrade plans">
          {(
            [
              ["all", "All"],
              ["drafts", "My drafts"],
              ["review", "Awaiting my review (" + waiting.length + ")"],
              ["scheduled", "Approved / scheduled"],
              ["overdue", "Overdue / inactive"],
            ] as const
          ).map(([value, label]) => (
            <button
              type="button"
              aria-pressed={filter === value}
              key={value}
              onClick={() => setFilter(value)}
            >
              {label}
            </button>
          ))}
        </div>
        {data.errors.length > 0 && (
          <div className="upgrade-blocker-notice" role="alert">
            <strong>Some plan records could not be loaded</strong>
            {data.errors.map((message) => (
              <p key={message}>{message}</p>
            ))}
            <p>
              Only clusters within your account's authorized scope can be shown.
            </p>
          </div>
        )}
        {data.pending ? (
          <p role="status">Loading governed upgrade plans…</p>
        ) : mode === "schedule" ? (
          <MaintenanceCalendar
            rows={rows}
            onReview={setSelectedId}
            now={now}
            canCreate={canPlan}
            onCreate={onCreate}
          />
        ) : !rows.length ? (
          <p role="status" className="upgrade-live-message">
            No upgrade plans match this filter in your authorized cluster scope.
          </p>
        ) : (
          <div className="table-scroll">
            <table className="upgrade-fleet-table">
              <thead>
                <tr>
                  <th>Plan</th>
                  <th>Cluster</th>
                  <th>Version change</th>
                  <th>Status</th>
                  <th>Requested window</th>
                  <th>Submitted by</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.plan.planId}>
                    <td>
                      {row.plan.planId}
                      <PlanScopeLabel plan={row.plan} />
                    </td>
                    <td>
                      <strong>{row.clusterName}</strong>
                      <br />
                      <ClusterContext cluster={row.cluster} compact />
                    </td>
                    <td>
                      {row.plan.currentVersion} → {row.plan.targetVersion}
                    </td>
                    <td>
                      <span
                        className={
                          "utility-state state-" + row.plan.status.toLowerCase()
                        }
                      >
                        {scheduleOverdue(row.plan, now)
                          ? "Overdue · inactive"
                          : statusLabel(row.plan.status)}
                      </span>
                    </td>
                    <td>
                      {timeLabel(row.plan.scheduledFor)}
                      {["DRAFT", "SUBMITTED"].includes(row.plan.status) &&
                        row.plan.scheduledFor && (
                          <small className="upgrade-window-pending">
                            {scheduleOverdue(row.plan, now)
                              ? "Past due — new schedule required"
                              : row.plan.status === "DRAFT"
                                ? "Draft · not submitted"
                                : "Requested · awaiting approval"}
                          </small>
                        )}
                    </td>
                    <td>
                      {row.plan.submittedBy
                        ? row.plan.submittedByName || row.plan.submittedBy
                        : "Not submitted"}
                      {row.plan.submittedAt && (
                        <small className="upgrade-window-pending">
                          {timeLabel(row.plan.submittedAt)}
                        </small>
                      )}
                    </td>
                    <td>
                      <Button
                        variant="secondary"
                        onClick={() => {
                          setNewSchedule("");
                          setSelectedId(row.plan.planId);
                          setReason("");
                          setConfirmStart(false);
                          action.reset();
                        }}
                      >
                        Review plan
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {drawerOnly && !plan && (
        <div className="upgrade-drawer-backdrop">
          <section
            className="upgrade-review-drawer"
            role="dialog"
            aria-label="Plan details"
          >
            <p role="status">
              {data.pending
                ? "Loading plan…"
                : "Plan details unavailable. Refresh plans to retry."}
            </p>
            <Button variant="secondary" onClick={data.refresh}>
              Refresh plans
            </Button>
            <Button onClick={closeDrawer}>Close</Button>
          </section>
        </div>
      )}
      {plan && selected && (
        <div className="upgrade-drawer-backdrop" onClick={closeDrawer}>
          <section
            ref={drawerRef}
            className="upgrade-review-drawer"
            role="dialog"
            aria-modal="true"
            aria-labelledby="upgrade-review-title"
            onClick={(event) => event.stopPropagation()}
            onKeyDown={(event) => {
              if (event.key === "Escape") closeDrawer();
              if (event.key === "Tab") {
                const controls = Array.from(
                  drawerRef.current?.querySelectorAll<HTMLElement>(
                    "button:not(:disabled), textarea:not(:disabled), input:not(:disabled), a[href]",
                  ) ?? [],
                );
                const first = controls[0],
                  last = controls.at(-1);
                if (
                  event.shiftKey &&
                  (document.activeElement === first ||
                    document.activeElement === drawerRef.current)
                ) {
                  event.preventDefault();
                  last?.focus();
                } else if (!event.shiftKey && document.activeElement === last) {
                  event.preventDefault();
                  first?.focus();
                }
              }
            }}
            tabIndex={-1}
          >
            <header>
              <h2 id="upgrade-review-title">
                {canReviewSelected
                  ? "Review upgrade plan"
                  : "Upgrade plan details"}
              </h2>
              <button
                type="button"
                aria-label="Close plan review"
                onClick={closeDrawer}
                autoFocus
              >
                <X />
              </button>
            </header>
            <span className="utility-state">
              {overdue ? "Overdue · inactive" : statusLabel(plan.status)}
            </span>
            <h3>
              {selected.clusterName} · {plan.currentVersion} →{" "}
              {plan.targetVersion}
            </h3>
            <PlatformIdentity
              identity={containerIdentity(selected.cluster.platform)}
              kind="platform"
            />
            <ClusterContext cluster={selected.cluster} />
            <dl className="upgrade-scope-list">
              <div>
                <dt>Plan</dt>
                <dd>{plan.planId}</dd>
              </div>
              <div>
                <dt>Requested window</dt>
                <dd>{timeLabel(plan.scheduledFor)}</dd>
              </div>
              <div>
                <dt>Created by</dt>
                <dd>{plan.createdByName || plan.createdBy}</dd>
              </div>
              <div>
                <dt>Submitted by</dt>
                <dd>
                  {plan.submittedBy
                    ? plan.submittedByName || plan.submittedBy
                    : "Not submitted"}
                </dd>
              </div>
              <div>
                <dt>Submitted at</dt>
                <dd>
                  {plan.submittedAt
                    ? timeLabel(plan.submittedAt)
                    : "Not submitted"}
                </dd>
              </div>
              <div>
                <dt>Approved by</dt>
                <dd>
                  {plan.approvedByName ||
                    plan.approvedBy ||
                    "Awaiting independent approval"}
                </dd>
              </div>
            </dl>
            <p>
              Times shown in {Intl.DateTimeFormat().resolvedOptions().timeZone}.
            </p>
            {overdue && (
              <div className="upgrade-overdue-notice" role="alert">
                <strong>Past due · schedule inactive</strong>
                <p>
                  The requested start time has passed. Approval is blocked. An
                  authorized Cloud Engineer must choose a future schedule and
                  resubmit.
                </p>
                {rescheduleBlocked && (
                  <p className="upgrade-access-explanation">
                    {rescheduleBlocked}
                  </p>
                )}
                <>
                  <label className="upgrade-live-field">
                    <span>New maintenance start</span>
                    <input
                      type="datetime-local"
                      aria-label="New maintenance start"
                      ref={rescheduleRef}
                      disabled={Boolean(rescheduleBlocked)}
                      value={newSchedule}
                      onChange={(event) => setNewSchedule(event.target.value)}
                    />
                  </label>
                  <Button
                    disabled={
                      Boolean(rescheduleBlocked) ||
                      action.isPending ||
                      !newSchedule ||
                      !Number.isFinite(new Date(newSchedule).getTime()) ||
                      new Date(newSchedule).getTime() <= now
                    }
                    onClick={() => run("reschedule")}
                  >
                    Save new schedule
                  </Button>
                  <p>
                    Saving returns the plan to Draft and clears the previous
                    submission. Submit it again for independent approval.
                  </p>
                </>
              </div>
            )}
            {plan.kind === "UTILITY" ? (
              <section className="upgrade-utility-evidence">
                <h3>{plan.utilityEvidence?.label}</h3>
                <p>
                  Helm chart {plan.managedGroup}: {plan.currentVersion} →{" "}
                  {plan.targetVersion}
                </p>
                <p>
                  Approval records the reviewed request. Chart compatibility and
                  GitOps execution are not enabled in this release.
                </p>
              </section>
            ) : (
              <>
                <h3>Upgrade components</h3>
                <PlanComponents
                  compact
                  evidence={plan.readinessEvidence}
                  target={plan.targetVersion}
                />
                <h3>Readiness evidence at plan creation</h3>
                <ul className="upgrade-review-checks">
                  <EvidenceChecks evidence={plan.readinessEvidence} />
                  <PlanCheck
                    label="Independent approval recorded"
                    passed={Boolean(plan.approvedAt)}
                    pending
                  />
                </ul>
                <p>
                  Evidence observed:{" "}
                  {new Date(
                    plan.readinessEvidence?.observedAt ?? plan.createdAt,
                  ).toLocaleString()}
                  . Execution revalidates live evidence.
                </p>
              </>
            )}
            <h3>Change reason</h3>
            <p>{plan.changeReason}</p>
            {plan.status === "SUBMITTED" && !canReviewSelected && !overdue && (
              <p role="status">
                Submitted for Platform Architect approval. No review comments
                are required from you. An independent authorized Platform
                Architect can review and approve or reject this request.
              </p>
            )}
            {canReviewSelected && (
              <label className="upgrade-live-field">
                <span>
                  Review comment (optional for approval; required for rejection)
                </span>
                <textarea
                  aria-label="Review comment"
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  maxLength={2000}
                />
              </label>
            )}
            {action.isError && (
              <div role="alert" className="upgrade-blocker-notice">
                {action.error.message}
              </div>
            )}
            {action.isSuccess && (
              <p role="status">
                {action.variables?.name === "submit"
                  ? "Plan submitted successfully. Awaiting Platform Architect approval."
                  : action.variables?.name === "reschedule"
                    ? "New schedule saved as a draft. Submit it for Platform Architect approval."
                    : "Plan action saved."}
              </p>
            )}
            {plan.execution.phase != null && (
              <p>
                Execution stage: {String(plan.execution.phase)} ·{" "}
                {String(plan.execution.providerStatus ?? "")}
              </p>
            )}
            <footer>
              <Button variant="secondary" onClick={closeDrawer}>
                Close
              </Button>
              {plan.status === "DRAFT" && canPlan && !overdue && (
                <Button
                  disabled={action.isPending}
                  onClick={() => run("submit")}
                >
                  Submit for approval
                </Button>
              )}
              {canReviewSelected && (
                <>
                  <Button
                    variant="secondary"
                    disabled={action.isPending || !reason.trim()}
                    onClick={() => run("reject")}
                  >
                    Reject with reason
                  </Button>
                  <Button
                    disabled={action.isPending}
                    onClick={() => run("approve")}
                  >
                    Approve plan
                  </Button>
                </>
              )}
              {["DRAFT", "SUBMITTED", "APPROVED", "SCHEDULED"].includes(
                plan.status,
              ) &&
                canPlan && (
                  <Button
                    variant="secondary"
                    disabled={action.isPending}
                    onClick={() => run("cancel")}
                  >
                    Cancel plan
                  </Button>
                )}
              {["APPROVED", "SCHEDULED"].includes(plan.status) &&
                canExecute &&
                plan.kind !== "UTILITY" && (
                  <>
                    {plan.scheduledFor &&
                    new Date(plan.scheduledFor).getTime() > Date.now() ? (
                      <p>
                        Execution becomes available when the approved window
                        starts.
                      </p>
                    ) : confirmStart ? (
                      <>
                        <p>
                          This starts an EKS version upgrade. Control-plane
                          downgrades are unavailable.
                        </p>
                        <Button
                          disabled={action.isPending}
                          onClick={() => run("execute")}
                        >
                          Confirm start upgrade
                        </Button>
                        <Button
                          variant="secondary"
                          onClick={() => setConfirmStart(false)}
                        >
                          Go back
                        </Button>
                      </>
                    ) : (
                      <Button
                        disabled={action.isPending}
                        onClick={() => setConfirmStart(true)}
                      >
                        Start approved upgrade
                      </Button>
                    )}
                  </>
                )}
              {plan.status === "EXECUTING" &&
                canExecute &&
                plan.kind !== "UTILITY" && (
                  <Button
                    disabled={action.isPending}
                    onClick={() => run("refresh")}
                  >
                    Refresh execution / advance stage
                  </Button>
                )}
            </footer>
            <p>Approval does not start the upgrade.</p>
          </section>
        </div>
      )}
    </section>
  );
}
