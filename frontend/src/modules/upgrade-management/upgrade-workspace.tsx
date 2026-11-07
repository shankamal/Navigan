"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  CalendarDays,
  CircleArrowUp,
  CloudCog,
  History,
  Info,
  ShieldAlert,
  Wrench,
} from "lucide-react";
import { Button, PageHeading } from "@/shared/components/ui";
import type {
  EksUpgradeReadiness,
  EksUpgradePlan,
} from "@/modules/cluster-management/model";
import { useAuth } from "@/shared/auth/auth-provider";
import { hasPermission } from "@/shared/auth/permissions";
import { PlanComponents, EvidenceChecks, PlanCheck } from "./plan-components";
import { useUpgradePlans } from "./upgrade-plan-data";
import { clusters } from "@/modules/cluster-management/service";
import { LiveUpgradeInventory } from "./live-upgrade-inventory";
import { LiveUpgradeCentre } from "./live-upgrade-centre";
import { UpgradePlansWorkspace } from "./upgrade-plans-workspace";
import "./upgrade-workspace.css";

type WorkspaceTab =
  "readiness" | "containers" | "utilities" | "schedule" | "history";

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
  { id: "containers", label: "Container Upgrades", icon: CloudCog },
  { id: "utilities", label: "System Utilities", icon: Wrench },
  { id: "schedule", label: "Maintenance Schedule", icon: CalendarDays },
  { id: "history", label: "Plans & History", icon: History },
];

function LiveCapabilityNotice() {
  return (
    <div className="upgrade-preview-notice" role="note">
      <Info size={17} aria-hidden="true" />
      <p>
        <strong>Live governed inventory.</strong> Cluster records, Amazon EKS
        readiness and EKS upgrade plans are connected. Execution requires
        independent approval, a valid maintenance window and fresh readiness
        evidence. Utility execution is not enabled yet.
      </p>
    </div>
  );
}

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
          aria-selected={active === id}
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
}: {
  tab: Exclude<WorkspaceTab, "readiness">;
  onPlan: (cluster: UpgradeCluster) => void;
}) {
  if (tab === "containers" || tab === "utilities") {
    return <LiveUpgradeInventory mode={tab} onPlan={onPlan} />;
  }
  return <UpgradePlansWorkspace mode={tab} />;
}

function PlanWizard({
  cluster,
  onClose,
}: {
  cluster: UpgradeCluster;
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
  const [scheduledFor, setScheduledFor] = useState("");
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
  const canCreate = hasPermission(identity, "cluster.plan");
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
    <div className="upgrade-plan-workspace">
      <button className="upgrade-back-link" type="button" onClick={onClose}>
        <ArrowLeft size={16} /> Upgrades & Patching
      </button>
      <PageHeading
        title="Create upgrade plan"
        description={cluster.name + " · " + cluster.environment}
        icon={<CircleArrowUp />}
      />
      <div className="upgrade-compact-layout">
        <div className="upgrade-compact-sections">
          <section className="upgrade-compact-card">
            <h2>1. Cluster & target</h2>
            <dl className="upgrade-scope-list">
              <div>
                <dt>Managed cluster</dt>
                <dd>{cluster.name}</dd>
              </div>
              <div>
                <dt>Distribution</dt>
                <dd>{cluster.providerLabel}</dd>
              </div>
              <div>
                <dt>Current Kubernetes</dt>
                <dd>
                  {evidence?.controlPlane.version ?? cluster.currentVersion}
                </dd>
              </div>
              <div>
                <dt>Supported target</dt>
                <dd>{target}</dd>
              </div>
            </dl>
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
            <p>
              Provider-managed rolling: control plane → managed add-ons → node
              groups → final validation.
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
                  to independent approval
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
            <PlanCheck label="Scope selected" passed={Boolean(cluster.id)} />
            <EvidenceChecks evidence={evidence} />
            <PlanCheck label="Change reason provided" passed={reasonReady} />
            <PlanCheck
              label={
                scheduledFor
                  ? "Future maintenance start"
                  : "No maintenance time requested (optional)"
              }
              passed={validTime}
            />
            <PlanCheck label="Plan saved" passed={Boolean(created)} pending />
            <PlanCheck
              label="Submitted for review"
              passed={created?.status === "SUBMITTED"}
              pending
            />
            <PlanCheck label="Independent approval" passed={false} pending />
          </ul>
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
            ? "Awaiting independent approval. Find it in Plans & History."
            : "Draft saved. Submit when ready."}
        </div>
      )}
      <div className="upgrade-compact-actions">
        <span id="plan-save-help">
          {missing ||
            (created?.status === "SUBMITTED"
              ? "Submitted for independent approval"
              : "Ready to save")}
        </span>
        <Button variant="secondary" onClick={onClose}>
          Back to plans
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
  const [tab, setTab] = useState<WorkspaceTab>("readiness");
  const [planning, setPlanning] = useState<UpgradeCluster | null>(null);
  const plans = useUpgradePlans();
  const pendingReviews = plans.rows.filter(
    (row) =>
      row.plan.status === "SUBMITTED" &&
      row.plan.createdBy !== plans.identity?.subject,
  ).length;

  if (planning)
    return (
      <PlanWizard
        key={planning.id}
        cluster={planning}
        onClose={() => {
          setPlanning(null);
          setTab("history");
        }}
      />
    );

  return (
    <div className="upgrade-workspace">
      <PageHeading
        title="Upgrades & Patching"
        description="Plan and govern platform lifecycle changes across managed clusters."
        icon={<CircleArrowUp />}
        action={
          <div className="upgrade-heading-actions">
            <Button variant="secondary" onClick={() => setTab("history")}>
              Plans & approvals
              {pendingReviews ? " (" + pendingReviews + " pending)" : ""}
            </Button>
            <Button onClick={() => setTab("readiness")}>
              <CircleArrowUp size={17} />
              Review live readiness
            </Button>
          </div>
        }
      />
      <LiveCapabilityNotice />
      <UpgradeTabs active={tab} onChange={setTab} />
      <div role="tabpanel">
        {tab === "readiness" ? (
          <LiveUpgradeCentre onPlan={setPlanning} />
        ) : (
          <SupportingTab tab={tab} onPlan={setPlanning} />
        )}
      </div>
    </div>
  );
}
