"use client";

import { calendarSchedule } from "./schedule-state";
import { useUpgradePlans } from "./upgrade-plan-data";
import { containerIdentity, PlatformIdentity } from "./platform-identity";
import { ClusterContext } from "./cluster-context";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  CalendarDays,
  CircleArrowUp,
  CheckCircle2,
  Circle,
  CloudCog,
  History,
  ShieldAlert,
  Wrench,
} from "lucide-react";
import { Button } from "@/shared/components/ui";
import type {
  EksUpgradeReadiness,
  EksUpgradePlan,
} from "@/modules/cluster-management/model";
import { useAuth } from "@/shared/auth/auth-provider";
import { hasPermission } from "@/shared/auth/permissions";
import { PlanComponents, EvidenceChecks, PlanCheck } from "./plan-components";
import { clusters } from "@/modules/cluster-management/service";
import { LiveUpgradeInventory } from "./live-upgrade-inventory";
import { LiveUpgradeCentre } from "./live-upgrade-centre";
import { UpgradePlansWorkspace } from "./upgrade-plans-workspace";
import "./upgrade-workspace.css";

type WorkspaceTab = "readiness" | "utilities" | "schedule" | "history";

type Readiness = "READY" | "WARNING" | "BLOCKED";

export interface UpgradeCluster {
  id: string;
  name: string;
  environment: string;
  provider: "EKS" | "AKS" | "GKE" | "OPENSHIFT";
  providerLabel: string;
  currentVersion: string;
  targetVersion: string;
  path: string[];
  support: "SUPPORTED" | "EXTENDED_SUPPORT";
  readiness: Readiness;
  findings: string;
  window: string;
  evidence?: EksUpgradeReadiness;
}

const tabs: ReadonlyArray<{
  id: WorkspaceTab;
  label: string;
  icon: typeof CircleArrowUp;
}> = [
  { id: "readiness", label: "Upgrade Centre", icon: ShieldAlert },
  { id: "utilities", label: "System Utilities", icon: Wrench },
  { id: "history", label: "Plans & Approvals", icon: History },
  { id: "schedule", label: "Maintenance Calendar", icon: CalendarDays },
];

function UpgradeTabs({
  active,
  onChange,
}: {
  active: WorkspaceTab;
  onChange: (tab: WorkspaceTab) => void;
}) {
  return (
    <nav className="upgrade-tabs" aria-label="Upgrade workspace" role="tablist">
      {tabs.map(({ id, label, icon: Icon }) => (
        <button
          key={id}
          type="button"
          role="tab"
          className={active === id ? "active" : ""}
          id={"upgrade-tab-" + id}
          aria-controls="upgrade-tabpanel"
          tabIndex={active === id ? 0 : -1}
          aria-selected={active === id}
          onKeyDown={(event) => {
            if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key))
              return;
            event.preventDefault();
            const index = tabs.findIndex((item) => item.id === id);
            const next =
              event.key === "Home"
                ? tabs[0]
                : event.key === "End"
                  ? tabs[tabs.length - 1]
                  : tabs[
                      (index +
                        (event.key === "ArrowRight" ? 1 : -1) +
                        tabs.length) %
                        tabs.length
                    ];
            onChange(next.id);
            document.getElementById("upgrade-tab-" + next.id)?.focus();
          }}
          onClick={() => onChange(id)}
        >
          <Icon size={16} aria-hidden="true" />
          {label}
        </button>
      ))}
    </nav>
  );
}

function SupportingTab({
  tab,
  onPlan,
  reviewPlanId,
  rescheduleRequested,
  onReview,
  onCreate,
  requestedDate,
}: {
  onCreate: (kind: "containers" | "utilities", date: string) => void;
  requestedDate?: string;
  tab: Exclude<WorkspaceTab, "readiness">;
  reviewPlanId?: string;
  rescheduleRequested?: boolean;
  onReview: (planId: string | null, reschedule?: boolean) => void;
  onPlan: (cluster: UpgradeCluster) => void;
}) {
  if (tab === "utilities") {
    return (
      <LiveUpgradeInventory
        mode={tab}
        onPlan={onPlan}
        onReview={onReview}
        requestedDate={requestedDate}
      />
    );
  }
  return (
    <UpgradePlansWorkspace
      key={(reviewPlanId ?? tab) + (rescheduleRequested ? "-reschedule" : "")}
      mode={tab}
      onCreate={onCreate}
      initialPlanId={reviewPlanId}
      rescheduleRequested={rescheduleRequested}
    />
  );
}

function PlanWizard({
  cluster,
  initialDate,
  onClose,
}: {
  cluster: UpgradeCluster;
  initialDate?: string;
  onClose: () => void;
}) {
  const cache = useQueryClient();
  const { identity } = useAuth();
  const evidenceQuery = useQuery({
    queryKey: ["eks-upgrade-readiness", cluster.id],
    queryFn: () => clusters.upgradeReadiness(cluster.id),
    initialData: cluster.evidence,
    staleTime: 30_000,
  });
  const evidence = evidenceQuery.data;
  const target = evidence?.recommendedTarget?.version ?? cluster.targetVersion;
  const [scheduledFor, setScheduledFor] = useState(() =>
    calendarSchedule(initialDate),
  );
  const [changeReason, setChangeReason] = useState("");
  const [created, setCreated] = useState<EksUpgradePlan | null>(null);
  const validTime =
    !scheduledFor ||
    (Number.isFinite(new Date(scheduledFor).getTime()) &&
      new Date(scheduledFor).getTime() > Date.now());
  const ready =
    evidence?.readiness.status === "READY" &&
    Boolean(evidence.recommendedTarget) &&
    !evidenceQuery.isFetching &&
    !evidenceQuery.isError;
  const reasonReady = changeReason.trim().length >= 8;
  const canCreate = hasPermission(identity, "cluster.upgrade.plan");
  const missing = !canCreate
    ? "Your account needs permission to plan cluster upgrades."
    : !ready
      ? "Refresh evidence and resolve readiness findings."
      : !reasonReady
        ? "Enter a change reason of at least 8 characters."
        : !validTime
          ? "Choose a future maintenance time or leave it empty."
          : "";
  const mutation = useMutation({
    mutationFn: async (submit: boolean) => {
      let plan = created;
      if (!plan) {
        plan = await clusters.createUpgradePlan(cluster.id, {
          targetVersion: target,
          strategy: "PROVIDER_MANAGED_ROLLING",
          ...(scheduledFor
            ? { scheduledFor: new Date(scheduledFor).toISOString() }
            : {}),
          changeReason: changeReason.trim(),
        });
        setCreated(plan);
      }
      if (submit && plan.status === "DRAFT") {
        plan = await clusters.changeUpgradePlan(
          cluster.id,
          plan.planId,
          "submit",
          plan.version,
        );
        setCreated(plan);
      }
      return plan;
    },
    onSettled: () => {
      void cache.invalidateQueries({ queryKey: ["eks-upgrade-plans"] });
    },
  });
  const locked = Boolean(created) || mutation.isPending;
  return (
    <div className="upgrade-plan-workspace upgrade-reference-planner">
      <button className="upgrade-back-link" type="button" onClick={onClose}>
        <ArrowLeft size={16} /> Upgrades & Patching
      </button>
      <header className="upgrade-planner-heading">
        <h2>Create upgrade plan</h2>
        <p>
          Review the cluster, confirm the upgrade scope and request a
          maintenance time.
        </p>
      </header>
      <ClusterContext
        cluster={{
          clusterId: cluster.id,
          clusterName: cluster.name,
          environmentName: cluster.environment,
        }}
      />
      <div className="upgrade-cluster-strip">
        <div>
          <small>Distribution</small>
          <strong>
            <PlatformIdentity
              identity={containerIdentity(cluster.provider)}
              kind="platform"
            />
          </strong>
        </div>
        <div>
          <small>EKS version</small>
          <strong>
            <span>
              Current:{" "}
              {evidence?.controlPlane.version ?? cluster.currentVersion}
            </span>
            <span>→</span>
            <span className="upgrade-target-chip">Target: {target}</span>
          </strong>
        </div>
      </div>
      <div className="upgrade-compact-layout">
        <div className="upgrade-compact-sections">
          <section className="upgrade-compact-card">
            <h2>1. Cluster & target</h2>
            <div className="upgrade-compact-fields">
              <label className="upgrade-live-field">
                <span>Cluster</span>
                <input
                  aria-label="Plan cluster"
                  value={cluster.name}
                  readOnly
                />
              </label>
              <label className="upgrade-live-field">
                <span>Target EKS version</span>
                <input
                  aria-label="Plan target version"
                  value={target}
                  readOnly
                />
                <small>Provider-supported next version</small>
              </label>
            </div>
          </section>
          <section className="upgrade-compact-card">
            <div className="upgrade-compact-card-heading">
              <h2>2. Components & readiness</h2>
              <Button
                variant="secondary"
                disabled={evidenceQuery.isFetching || locked}
                onClick={() => void evidenceQuery.refetch()}
              >
                Refresh evidence
              </Button>
            </div>
            <div
              className="upgrade-strategy-line"
              role="group"
              aria-label="Upgrade strategy"
            >
              <span>Upgrade strategy</span>
              <strong>Provider-managed rolling</strong>
            </div>
            <p className="upgrade-section-help">
              The current EKS workflow uses a rolling upgrade: control plane
              first, then compatible add-ons and managed node groups.
            </p>
            <PlanComponents evidence={evidence} target={target} />
            <p>
              Only discovered EKS managed node groups and add-ons are included.
              Self-managed nodes and system utilities require separate plans.
            </p>
            {[
              ...(evidence?.readiness.blockers ?? []),
              ...(evidence?.readiness.warnings ?? []),
            ].map((item, index) => (
              <p role="alert" key={index}>
                {item.message}
              </p>
            ))}
          </section>
          <section className="upgrade-compact-card">
            <h2>3. Maintenance & reason</h2>
            <div className="upgrade-compact-fields">
              <label className="upgrade-live-field">
                <span>Requested maintenance start (optional)</span>
                <input
                  aria-label="Maintenance start"
                  type="datetime-local"
                  value={scheduledFor}
                  disabled={locked}
                  onChange={(event) => setScheduledFor(event.target.value)}
                />
                <small>
                  {Intl.DateTimeFormat().resolvedOptions().timeZone} · Subject
                  to Platform Architect approval
                </small>
              </label>
              <label className="upgrade-live-field">
                <span>Change reason (required, at least 8 characters)</span>
                <textarea
                  aria-label="Change reason"
                  value={changeReason}
                  disabled={locked}
                  rows={3}
                  maxLength={2000}
                  onChange={(event) => setChangeReason(event.target.value)}
                />
              </label>
            </div>
          </section>
        </div>
        <aside
          className="upgrade-compact-card upgrade-checklist"
          aria-label="Plan checklist"
        >
          <h2>Plan checklist</h2>
          <ul>
            <PlanCheck label="Scope defined" passed={Boolean(cluster.id)} />
            <PlanCheck
              label="Target version set"
              passed={Boolean(evidence?.recommendedTarget)}
            />
            <PlanCheck label="Live checks" passed={ready} />
            <PlanCheck label="Reason provided" passed={reasonReady} />
            <PlanCheck
              label="Requested time"
              passed={Boolean(scheduledFor) && validTime}
              pending={!scheduledFor}
            />
            <PlanCheck
              label="Platform Architect approval"
              passed={false}
              pending
            />
          </ul>
          <details className="upgrade-evidence-details">
            <summary>View evidence checklist</summary>
            <ul>
              <EvidenceChecks evidence={evidence} />
            </ul>
          </details>
          <h3>Plan status & flow</h3>
          <ol className="upgrade-status-flow">
            <li className={created?.status === "SUBMITTED" ? "done" : ""}>
              <CheckCircle2 />
              <strong>Submitted</strong>
              <small>
                {created?.submittedAt
                  ? new Date(created.submittedAt).toLocaleString()
                  : "Not submitted"}
              </small>
            </li>
            <li>
              <Circle />
              <strong>Approval</strong>
              <small>Awaiting approval</small>
            </li>
            <li>
              <Circle />
              <strong>Execution</strong>
              <small>Pending approval</small>
            </li>
          </ol>
          <p>
            Evidence observed:{" "}
            {evidence
              ? new Date(evidence.observedAt).toLocaleString()
              : "Unavailable"}
          </p>
          <p>
            Saving and submitting do not start an upgrade. Approval is followed
            by an explicit start action.
          </p>
        </aside>
      </div>
      {mutation.isError && (
        <div className="upgrade-blocker-notice" role="alert">
          <strong>Plan request failed</strong>
          <p>{mutation.error.message}</p>
        </div>
      )}
      {created && (
        <div role="status" className="upgrade-submit-boundary">
          Plan {created.planId} ·{" "}
          {created.status === "SUBMITTED"
            ? "Awaiting Platform Architect approval. Find it in Plans & Approvals."
            : "Draft saved. Submit when ready."}
        </div>
      )}
      <div className="upgrade-compact-actions">
        <span id="plan-save-help">
          {missing ||
            (created?.status === "SUBMITTED"
              ? "Submitted for Platform Architect approval"
              : "Ready to save")}
        </span>
        <Button variant="secondary" onClick={onClose}>
          Close
        </Button>
        <Button
          variant="secondary"
          aria-describedby="plan-save-help"
          disabled={Boolean(missing) || locked}
          onClick={() => mutation.mutate(false)}
        >
          Save draft
        </Button>
        <Button
          aria-describedby="plan-save-help"
          disabled={
            Boolean(missing) ||
            mutation.isPending ||
            created?.status === "SUBMITTED"
          }
          onClick={() => mutation.mutate(true)}
        >
          {mutation.isPending
            ? "Saving…"
            : created
              ? "Submit for approval"
              : "Save & submit"}
        </Button>
      </div>
    </div>
  );
}

export function UpgradeWorkspace() {
  const fleetData = useUpgradePlans();
  const providers = [
    ...new Set(fleetData.fleet.map((cluster) => cluster.platform)),
  ];
  const [requestedDate, setRequestedDate] = useState<string>();
  const [tab, setTab] = useState<WorkspaceTab>("readiness");
  const [reviewPlanId, setReviewPlanId] = useState<string>();
  const [rescheduleRequested, setRescheduleRequested] = useState(false);
  const [plannerOrigin, setPlannerOrigin] = useState<WorkspaceTab>("readiness");
  const [planning, setPlanning] = useState<UpgradeCluster | null>(null);
  const openPlan = (planId: string | null, reschedule = false) => {
    setReviewPlanId(planId ?? undefined);
    setRescheduleRequested(reschedule);
    setPlanning(null);
  };

  return (
    <div
      className={
        planning ? "upgrade-workspace is-planning" : "upgrade-workspace"
      }
    >
      <header className="upgrade-page-heading">
        <div className="upgrade-page-heading-copy">
          <h1>Upgrades &amp; Patching</h1>
          <p>
            Review available upgrades, assess readiness and manage maintenance
            plans.
          </p>
        </div>
        <div
          className="upgrade-provider-scope"
          aria-label="Managed cloud providers"
        >
          {providers.map((provider) => (
            <PlatformIdentity
              key={provider}
              identity={containerIdentity(provider)}
              kind="cloud"
            />
          ))}
        </div>
      </header>
      <UpgradeTabs
        active={planning ? "readiness" : tab}
        onChange={(value) => {
          setRequestedDate(undefined);
          setPlanning(null);
          setReviewPlanId(undefined);
          setRescheduleRequested(false);
          setTab(value);
        }}
      />
      <div
        role="tabpanel"
        id="upgrade-tabpanel"
        aria-labelledby={"upgrade-tab-" + (planning ? "readiness" : tab)}
      >
        {planning ? (
          <PlanWizard
            key={planning.id}
            cluster={planning}
            initialDate={requestedDate}
            onClose={() => {
              setPlanning(null);
              setReviewPlanId(undefined);
              setRescheduleRequested(false);
              setTab(plannerOrigin);
            }}
          />
        ) : tab === "readiness" ? (
          <LiveUpgradeCentre onPlan={setPlanning} onReview={openPlan} />
        ) : (
          <SupportingTab
            tab={tab}
            requestedDate={requestedDate}
            onCreate={(kind, date) => {
              setPlanning(null);
              setPlannerOrigin("schedule");
              setRequestedDate(date);
              setReviewPlanId(undefined);
              setRescheduleRequested(false);
              setTab(kind === "containers" ? "readiness" : "utilities");
            }}
            onPlan={setPlanning}
            reviewPlanId={undefined}
            rescheduleRequested={false}
            onReview={openPlan}
          />
        )}
      </div>
      {reviewPlanId && (
        <UpgradePlansWorkspace
          key={reviewPlanId}
          mode="history"
          drawerOnly
          initialPlanId={reviewPlanId}
          rescheduleRequested={rescheduleRequested}
          onClose={() => {
            setReviewPlanId(undefined);
            setRescheduleRequested(false);
          }}
        />
      )}
    </div>
  );
}
