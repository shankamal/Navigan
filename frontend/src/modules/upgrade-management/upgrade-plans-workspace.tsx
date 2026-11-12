"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { UpgradePathDetails } from "./scoped-upgrade-planner";
import { X, RefreshCw } from "lucide-react";
import { clusters } from "@/modules/cluster-management/service";
import { hasPermission } from "@/shared/auth/permissions";
import { Button } from "@/shared/components/ui";
import { useUpgradePlans } from "./upgrade-plan-data";
import { PlanComponents, EvidenceChecks, PlanCheck } from "./plan-components";
import {
  executionWindowState,
  scheduleOverdue,
  useScheduleClock,
} from "./schedule-state";
import { ClusterContext } from "./cluster-context";
import { MaintenanceCalendar } from "./maintenance-calendar";
import { rescheduleBlockReason } from "./plan-availability";
import { PlatformIdentity, containerIdentity } from "./platform-identity";
import { planVersionLabel, PlanScopeLabel } from "./plan-scope";

type Filter = "all" | "drafts" | "review" | "scheduled" | "overdue";
const statusLabel = (status: string) =>
  status === "SUBMITTED" ? "Awaiting approval" : status.replaceAll("_", " ");
const timeLabel = (value?: string | null) =>
  value ? new Date(value).toLocaleString() : "No time requested";

function actorName(name?: string | null, id?: string | null) {
  return name &&
    name !== id &&
    !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(name)
    ? name
    : "Name unavailable";
}

function executionStageLabel(operation?: {
  kind: "CONTROL_PLANE" | "NODEGROUP" | "ADDON";
  stage?:
    | "PREREQUISITE_COMPONENTS"
    | "CONTROL_PLANE"
    | "COMPATIBILITY_COMPONENTS"
    | "DATA_PLANE";
}) {
  if (operation?.stage)
    return operation.stage.replaceAll("_", " ").toLowerCase();
  if (operation?.kind === "CONTROL_PLANE") return "control plane";
  if (operation?.kind === "NODEGROUP") return "data plane";
  if (operation?.kind === "ADDON") return "compatibility components";
  return "approved component";
}

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
  const [stepSchedules, setStepSchedules] = useState<
    Record<number, { start: string; duration: number }>
  >({});
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
  const canExecute = hasPermission(data.identity, "cluster.upgrade.execute");
  const subject = data.identity?.subject;
  const canSelfApprove =
    canApprove && Boolean(data.identity?.roles.includes("PLATFORM_ARCHITECT"));
  const waiting = data.rows.filter(
    (row) =>
      row.plan.status === "SUBMITTED" &&
      (canSelfApprove ||
        (row.plan.createdBy !== subject && row.plan.submittedBy !== subject)) &&
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
        | "continue"
        | "reschedule"
        | "reconcile"
        | "refresh-reconciliation"
        | "apply-reconciliation";
    }) => {
      const row = data.rows.find((item) => item.plan.planId === planId)!;
      if (name === "reschedule")
        return clusters.changeUpgradePlan(
          row.plan.clusterId,
          planId,
          name,
          row.plan.version,
          undefined,
          row.plan.planSpec ? undefined : new Date(newSchedule).toISOString(),
          ...(row.plan.planSpec
            ? [
                row.plan.planSpec.steps.map((step, i) => ({
                  scheduledFor: stepSchedules[i]?.start
                    ? new Date(stepSchedules[i].start).toISOString()
                    : step.window?.scheduledFor || "",
                  durationMinutes:
                    stepSchedules[i]?.duration ||
                    step.window?.durationMinutes ||
                    120,
                })),
              ]
            : []),
        );
      return clusters.changeUpgradePlan(
        row.plan.clusterId,
        planId,
        name,
        row.plan.version,
        name === "approve" || name === "reject"
          ? reason.trim() || undefined
          : undefined,
      );
    },
    onSuccess: () => {
      data.refresh();
      setReason("");
      setNewSchedule("");
      setStepSchedules({});
      setConfirmStart(false);
    },
  });
  const plan = selected?.plan;
  const iacReconciliation =
    plan &&
    typeof plan.execution.iacReconciliation === "object" &&
    plan.execution.iacReconciliation !== null
      ? (plan.execution.iacReconciliation as Record<string, unknown>)
      : undefined;
  const terraformActions =
    iacReconciliation &&
    typeof iacReconciliation.planSummary === "object" &&
    iacReconciliation.planSummary !== null &&
    typeof (
      iacReconciliation.planSummary as Record<string, unknown>
    ).actions === "object"
      ? (
          iacReconciliation.planSummary as {
            actions: Record<string, unknown>;
          }
        ).actions
      : undefined;
  const gate = plan?.execution.gate;
  const gatePending =
    typeof gate === "object" &&
    gate !== null &&
    "status" in gate &&
    gate.status === "PENDING";
  const overdue = plan ? scheduleOverdue(plan, now) : false;
  const executionWindow = plan
    ? executionWindowState(plan, now)
    : { state: "UNSCHEDULED" as const, hopIndex: 0 };
  const currentStep =
    plan?.planSpec?.steps[executionWindow.hopIndex] ?? plan?.planSpec?.steps[0];
  const firstOperation = currentStep?.operations[0];
  const firstStage = executionStageLabel(firstOperation);
  const canReviewSelected = Boolean(
    plan &&
    plan.status === "SUBMITTED" &&
    canApprove &&
    !overdue &&
    (canSelfApprove ||
      (plan.createdBy !== subject && plan.submittedBy !== subject)),
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
      | "continue"
      | "reschedule"
      | "reconcile"
      | "refresh-reconciliation"
      | "apply-reconciliation",
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
                    <td>{planVersionLabel(row.plan)}</td>
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
                        ? actorName(
                            row.plan.submittedByName,
                            row.plan.submittedBy,
                          )
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
                          setStepSchedules({});
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
              {selected.clusterName} · {planVersionLabel(plan)}
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
                <dd>{actorName(plan.createdByName, plan.createdBy)}</dd>
              </div>
              <div>
                <dt>Submitted by</dt>
                <dd>
                  {plan.status !== "DRAFT" && plan.submittedBy
                    ? actorName(plan.submittedByName, plan.submittedBy)
                    : "—"}
                </dd>
              </div>
              <div>
                <dt>Submitted at</dt>
                <dd>
                  {plan.status !== "DRAFT" && plan.submittedAt
                    ? timeLabel(plan.submittedAt)
                    : "—"}
                </dd>
              </div>
              <div>
                <dt>Approved by</dt>
                <dd>
                  {plan.status !== "DRAFT"
                    ? plan.approvedBy
                      ? actorName(plan.approvedByName, plan.approvedBy)
                      : "—"
                    : "—"}
                </dd>
              </div>
              <div>
                <dt>Approval status</dt>
                <dd>
                  {plan.status === "DRAFT"
                    ? "Not requested"
                    : plan.status === "SUBMITTED"
                      ? overdue
                        ? "New schedule required"
                        : "Awaiting Platform Architect review"
                      : plan.status === "REJECTED"
                        ? "Rejected"
                        : plan.status === "CANCELLED"
                          ? "Cancelled"
                          : plan.approvedBy
                            ? "Approved"
                            : "Not recorded"}
                </dd>
              </div>
            </dl>
            <p>
              Times shown in {Intl.DateTimeFormat().resolvedOptions().timeZone}.
            </p>
            {overdue && !plan.planSpec && (
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
                    submission. Submit it again for Platform Architect approval.
                  </p>
                </>
              </div>
            )}
            {plan.planSpec && ["DRAFT", "SUBMITTED"].includes(plan.status) && (
              <section className="upgrade-path-step">
                <h3>
                  {overdue
                    ? "Past due · choose new maintenance windows"
                    : "Revise maintenance windows"}
                </h3>
                {plan.planSpec.steps.map((step, i) => (
                  <div className="upgrade-window-fields" key={i}>
                    <label className="upgrade-live-field">
                      <span>Step {i + 1} new maintenance start</span>
                      <input
                        type="datetime-local"
                        disabled={!canPlan}
                        value={stepSchedules[i]?.start ?? ""}
                        onChange={(e) =>
                          setStepSchedules((prev) => ({
                            ...prev,
                            [i]: {
                              start: e.target.value,
                              duration:
                                prev[i]?.duration ||
                                step.window?.durationMinutes ||
                                120,
                            },
                          }))
                        }
                      />
                    </label>
                    <label className="upgrade-live-field">
                      <span>Duration (minutes)</span>
                      <input
                        type="number"
                        min={30}
                        max={1440}
                        step={30}
                        disabled={!canPlan}
                        value={
                          stepSchedules[i]?.duration ??
                          step.window?.durationMinutes ??
                          120
                        }
                        onChange={(e) =>
                          setStepSchedules((prev) => ({
                            ...prev,
                            [i]: {
                              start: prev[i]?.start || "",
                              duration: Number(e.target.value),
                            },
                          }))
                        }
                      />
                    </label>
                  </div>
                ))}
                <Button
                  variant="secondary"
                  disabled={
                    !canPlan ||
                    action.isPending ||
                    plan.planSpec.steps.some(
                      (step, i) =>
                        !stepSchedules[i]?.start &&
                        (!step.window ||
                          new Date(step.window.scheduledFor).getTime() <= now),
                    )
                  }
                  onClick={() => run("reschedule")}
                >
                  Save maintenance windows
                </Button>
                <p>
                  Saving returns the plan to Draft. Submit it again for Platform
                  Architect approval.
                </p>
              </section>
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
            ) : plan.planSpec ? (
              <UpgradePathDetails
                spec={plan.planSpec}
                execution={plan.execution}
              />
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
                    label="Platform Architect approval"
                    completeLabel="Approved"
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
                {plan.createdBy === subject
                  ? "You created this plan. A different authorized Platform Architect must review it. Rescheduling or resubmitting does not change its original creator."
                  : plan.submittedBy === subject
                    ? "You submitted this plan. A different authorized Platform Architect must review it."
                    : "Your current account does not have the approval privilege for this request. A Platform Architect role label alone does not establish effective approval permission."}
              </p>
            )}
            {canReviewSelected &&
              (plan.createdBy === subject || plan.submittedBy === subject) && (
                <p role="status">
                  You can approve your own plan as Platform Architect. This
                  decision will be recorded as self-approval.
                </p>
              )}
            {plan.execution.approval &&
            typeof plan.execution.approval === "object" &&
            "selfApproved" in plan.execution.approval &&
            plan.execution.approval.selfApproved === true ? (
              <p>Approval mode: Platform Architect self-approval</p>
            ) : null}
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
            {plan.status === "SUCCEEDED" &&
              plan.kind !== "UTILITY" &&
              plan.planSpec &&
              iacReconciliation && (
                <div className="upgrade-blocker-notice" role="status">
                  <strong>IaC reconciliation</strong>
                  <p>
                    Status: {String(iacReconciliation.status ?? "Not started")}
                  </p>
                  {iacReconciliation.targetVersion != null && (
                    <p>
                      Desired Kubernetes version:{" "}
                      {String(
                        iacReconciliation.desiredVersionBefore ?? "Unknown",
                      )}{" "}
                      → {String(iacReconciliation.targetVersion)}
                    </p>
                  )}
                  {iacReconciliation.failureCode != null && (
                    <p>
                      Reconciliation finding:{" "}
                      {String(iacReconciliation.failureCode)}
                    </p>
                  )}
                  {terraformActions && (
                    <p>
                      Terraform actions:{" "}
                      {Object.entries(terraformActions)
                        .map(([action, count]) => `${action}: ${String(count)}`)
                        .join(", ")}
                    </p>
                  )}
                </div>
              )}
            {gatePending && (
              <div className="upgrade-blocker-notice" role="status">
                <strong>Stage health gate required</strong>
                <p>
                  The previous stage completed successfully. Navigan will
                  re-read live EKS health before starting the next approved
                  stage. Confirm application health and maintenance coverage
                  before continuing.
                </p>
              </div>
            )}
            {!plan.planSpec &&
              plan.kind !== "UTILITY" &&
              ["APPROVED", "SCHEDULED"].includes(plan.status) && (
                <p>
                  Legacy plan: create a new plan with explicit component scope
                  and maintenance windows before execution.
                </p>
              )}
            {plan.planSpec &&
              plan.kind !== "UTILITY" &&
              ["APPROVED", "SCHEDULED"].includes(plan.status) &&
              !canExecute && (
                <p role="status">
                  Execution must be started by an authorized Cloud Engineer
                  during the approved maintenance window.
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
                    {plan.createdBy === subject || plan.submittedBy === subject
                      ? "Approve own plan"
                      : "Approve plan"}
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
                plan.kind !== "UTILITY" &&
                Boolean(plan.planSpec) &&
                executionWindow.state === "UPCOMING" && (
                  <p role="status">
                    Approved execution window opens{" "}
                    {timeLabel(executionWindow.startsAt)} and closes{" "}
                    {timeLabel(executionWindow.endsAt)}. No upgrade can start
                    before this window.
                  </p>
                )}
              {["APPROVED", "SCHEDULED"].includes(plan.status) &&
                canExecute &&
                plan.kind !== "UTILITY" &&
                Boolean(plan.planSpec) &&
                executionWindow.state === "EXPIRED" && (
                  <div className="upgrade-blocker-notice" role="alert">
                    <strong>Approved execution window expired</strong>
                    <p>
                      No new provider operation can start. Create a new
                      maintenance schedule and obtain approval again.
                    </p>
                  </div>
                )}
              {["APPROVED", "SCHEDULED"].includes(plan.status) &&
                canExecute &&
                plan.kind !== "UTILITY" &&
                Boolean(plan.planSpec) &&
                executionWindow.state === "READY" &&
                !confirmStart && (
                  <>
                    <p role="status">
                      Approved execution window is open. Starting remains a
                      manual Cloud Engineer action.
                    </p>
                    <Button
                      disabled={action.isPending}
                      onClick={() => setConfirmStart(true)}
                    >
                      Start approved upgrade
                    </Button>
                  </>
                )}
              {["APPROVED", "SCHEDULED"].includes(plan.status) &&
                canExecute &&
                plan.kind !== "UTILITY" &&
                Boolean(plan.planSpec) &&
                executionWindow.state === "READY" &&
                confirmStart && (
                  <>
                    <p role="status">
                      Execution window is open until{" "}
                      {timeLabel(executionWindow.endsAt)}. Confirming starts the
                      first approved stage: {firstStage}. Navigan will re-read
                      live EKS health, versions, compatibility and upgrade
                      insights before calling the provider.
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
                )}
              {plan.status === "EXECUTING" &&
              canExecute &&
              plan.kind !== "UTILITY" &&
              gatePending ? (
                <Button
                  disabled={action.isPending}
                  onClick={() => run("continue")}
                >
                  Validate health & continue
                </Button>
              ) : (
                plan.status === "EXECUTING" &&
                canExecute &&
                plan.kind !== "UTILITY" && (
                  <Button
                    disabled={action.isPending}
                    onClick={() => run("refresh")}
                  >
                    Refresh execution
                  </Button>
                )
              )}
              {plan.status === "SUCCEEDED" &&
                canExecute &&
                plan.kind !== "UTILITY" &&
                plan.planSpec?.scope !== "ADDONS" &&
                Boolean(plan.planSpec) &&
                (!iacReconciliation ||
                  iacReconciliation.status === "FAILED" ||
                  iacReconciliation.status === "BLOCKED") && (
                  <Button
                    disabled={action.isPending}
                    onClick={() => run("reconcile")}
                  >
                    Reconcile IaC
                  </Button>
                )}
              {plan.status === "SUCCEEDED" &&
                canExecute &&
                plan.kind !== "UTILITY" &&
                ["PLAN_RUNNING", "APPLYING"].includes(
                  String(iacReconciliation?.status ?? ""),
                ) && (
                  <Button
                    disabled={action.isPending}
                    onClick={() => run("refresh-reconciliation")}
                  >
                    Refresh IaC reconciliation
                  </Button>
                )}
              {plan.status === "SUCCEEDED" &&
                canExecute &&
                plan.kind !== "UTILITY" &&
                String(iacReconciliation?.status ?? "") === "PLAN_READY" && (
                  <Button
                    disabled={action.isPending}
                    onClick={() => run("apply-reconciliation")}
                  >
                    Apply certified reconciliation
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
