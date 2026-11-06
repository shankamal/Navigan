"use client";

import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  CalendarDays,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleArrowUp,
  Clock3,
  CloudCog,
  History,
  Info,
  Save,
  ShieldAlert,
  Wrench,
  X,
} from "lucide-react";
import { Button, PageHeading } from "@/shared/components/ui";
import type { EksUpgradeReadiness } from "@/modules/cluster-management/model";
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

const planSteps = [
  "Scope",
  "Target version",
  "Readiness",
  "Strategy",
  "Schedule",
  "Review & approve",
] as const;

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
  const [step, setStep] = useState(1);
  const [target, setTarget] = useState(cluster.targetVersion);
  const [scheduledFor, setScheduledFor] = useState("");
  const [changeReason, setChangeReason] = useState("");
  const [createdPlan, setCreatedPlan] = useState<Awaited<
    ReturnType<typeof clusters.createUpgradePlan>
  > | null>(null);
  const targetChoices = cluster.path.slice(1);
  const evidence = cluster.evidence;
  const createPlan = useMutation({
    mutationFn: () =>
      clusters.createUpgradePlan(cluster.id, {
        targetVersion: target,
        strategy: "PROVIDER_MANAGED_ROLLING",
        ...(scheduledFor
          ? { scheduledFor: new Date(scheduledFor).toISOString() }
          : {}),
        changeReason,
      }),
    onSuccess: setCreatedPlan,
  });
  const submitPlan = useMutation({
    mutationFn: () =>
      clusters.changeUpgradePlan(
        cluster.id,
        createdPlan!.planId,
        "submit",
        createdPlan!.version,
        "Ready for independent platform approval.",
      ),
    onSuccess: setCreatedPlan,
  });

  const planStages = useMemo(
    () => [
      "Pre-flight evidence",
      "Backup & recovery checkpoint",
      ...cluster.path
        .slice(1)
        .flatMap((version) => [
          `Control plane ${version}`,
          `Nodes & add-ons ${version}`,
          `Validation gate for ${version}`,
        ]),
      "Final validation",
    ],
    [cluster.path],
  );

  return (
    <div className="upgrade-plan-workspace">
      <div className="upgrade-plan-header">
        <button type="button" className="upgrade-back-link" onClick={onClose}>
          <ArrowLeft size={16} aria-hidden="true" />
          Upgrades & Patching
        </button>
        <div className="upgrade-plan-heading-row">
          <div>
            <h1>Create upgrade plan</h1>
            <p>
              {cluster.providerLabel} · {cluster.name} · {cluster.environment}
            </p>
          </div>
          <Button
            variant="secondary"
            disabled={
              step !== planSteps.length ||
              changeReason.trim().length < 8 ||
              createPlan.isPending ||
              Boolean(createdPlan)
            }
            onClick={() => createPlan.mutate()}
          >
            <Save size={16} aria-hidden="true" />
            {createdPlan
              ? `Draft ${createdPlan.planId}`
              : createPlan.isPending
                ? "Saving draft"
                : "Save governed draft"}
          </Button>
        </div>
      </div>

      <LiveCapabilityNotice />

      <ol className="upgrade-plan-steps" aria-label="Upgrade plan progress">
        {planSteps.map((label, index) => {
          const number = index + 1;
          return (
            <li
              key={label}
              className={
                number === step ? "active" : number < step ? "complete" : ""
              }
            >
              <button type="button" onClick={() => setStep(number)}>
                <span>{number < step ? <Check size={15} /> : number}</span>
                <strong>{label}</strong>
              </button>
            </li>
          );
        })}
      </ol>

      <div className="upgrade-plan-layout">
        <section className="upgrade-plan-main">
          {step === 1 && (
            <>
              <p className="eyebrow">Step 1 of 6</p>
              <h2>Confirm upgrade scope</h2>
              <p className="upgrade-step-description">
                Confirm the platform and environment that this governed change
                will cover.
              </p>
              <dl className="upgrade-scope-list">
                <div>
                  <dt>Cluster</dt>
                  <dd>{cluster.name}</dd>
                </div>
                <div>
                  <dt>Environment</dt>
                  <dd>{cluster.environment}</dd>
                </div>
                <div>
                  <dt>Distribution</dt>
                  <dd>{cluster.providerLabel}</dd>
                </div>
                <div>
                  <dt>Current version</dt>
                  <dd>{cluster.currentVersion}</dd>
                </div>
              </dl>
            </>
          )}
          {step === 2 && (
            <>
              <p className="eyebrow">Step 2 of 6</p>
              <h2>Select a supported target</h2>
              <p className="upgrade-step-description">
                Choose the intended target and review every required version
                hop.
              </p>
              <div className="upgrade-current-strip">
                <div>
                  <span>Control plane</span>
                  <strong>{cluster.currentVersion}</strong>
                </div>
                <div>
                  <span>Managed nodes</span>
                  <strong>{cluster.currentVersion}</strong>
                </div>
                <div>
                  <span>Support</span>
                  <strong>
                    {cluster.support === "SUPPORTED" ? "Supported" : "Extended"}
                  </strong>
                </div>
                <div>
                  <span>Managed add-ons</span>
                  <strong>{evidence?.addons.length ?? 0}</strong>
                </div>
              </div>
              <h3>Upgrade path</h3>
              <p className="upgrade-path-note">
                <Info size={16} /> Provider constraints determine whether
                intermediate versions are mandatory.
              </p>
              <div
                className="upgrade-version-path"
                aria-label="Version upgrade path"
              >
                {cluster.path.map((version, index) => (
                  <div key={version}>
                    {index > 0 && <ChevronRight aria-hidden="true" />}
                    <span
                      className={
                        index === 0
                          ? "current"
                          : version === target
                            ? "target"
                            : "required"
                      }
                    >
                      {version}
                    </span>
                  </div>
                ))}
              </div>
              <fieldset className="upgrade-target-options">
                <legend>Select target</legend>
                {targetChoices.map((version, index) => (
                  <label
                    key={version}
                    className={target === version ? "selected" : ""}
                  >
                    <input
                      type="radio"
                      name="target-version"
                      value={version}
                      checked={target === version}
                      onChange={() => setTarget(version)}
                    />
                    <span>
                      <strong>
                        {index === targetChoices.length - 1
                          ? `Continue to ${version}`
                          : `Stop at ${version}`}
                      </strong>
                      <small>
                        {index === targetChoices.length - 1
                          ? "Provider-supported sequential target"
                          : "Complete this hop and plan the next version later"}
                      </small>
                    </span>
                  </label>
                ))}
              </fieldset>
              <div className="upgrade-release-impact">
                <h3>Release impact</h3>
                <ul>
                  {(evidence?.addons ?? []).map((addon) => (
                    <li
                      key={addon.name}
                      className={addon.targetVersion ? "" : "warning"}
                    >
                      {addon.targetVersion ? (
                        <CheckCircle2 size={16} />
                      ) : (
                        <AlertTriangle size={16} />
                      )}
                      <strong>{addon.name}</strong>
                      <span>
                        {addon.targetVersion
                          ? `${addon.version ?? "Unknown"} → ${addon.targetVersion}`
                          : "Compatible target requires review"}
                      </span>
                    </li>
                  ))}
                  <li>
                    <Clock3 size={16} />
                    <strong>Managed node groups</strong>
                    <span>
                      {evidence?.nodeGroups.length ?? 0} rolling updates after
                      the control plane
                    </span>
                  </li>
                </ul>
              </div>
            </>
          )}
          {step === 3 && (
            <>
              <p className="eyebrow">Step 3 of 6</p>
              <h2>Review readiness evidence</h2>
              <p className="upgrade-step-description">
                Resolve blocking findings before an upgrade can be approved.
              </p>
              <div className="upgrade-readiness-list">
                {[
                  ...(evidence?.readiness.blockers ?? []),
                  ...(evidence?.readiness.warnings ?? []),
                ].map((finding) => (
                  <div
                    key={`${finding.code}-${finding.message}`}
                    className={
                      evidence?.readiness.blockers.some(
                        (item) => item.code === finding.code,
                      )
                        ? "blocked"
                        : "warning"
                    }
                  >
                    <ShieldAlert />
                    <span>
                      <strong>{finding.code.replaceAll("_", " ")}</strong>
                      <small>{finding.message}</small>
                    </span>
                    <b>
                      {evidence?.readiness.blockers.some(
                        (item) => item.code === finding.code,
                      )
                        ? "Blocked"
                        : "Warning"}
                    </b>
                  </div>
                ))}
                {evidence?.readiness.status === "READY" && (
                  <div>
                    <CheckCircle2 />
                    <span>
                      <strong>Live EKS readiness</strong>
                      <small>
                        {evidence.nodeGroups.length} node groups,{" "}
                        {evidence.addons.length} add-ons and{" "}
                        {evidence.insights.length} insights passed the plan
                        gate.
                      </small>
                    </span>
                    <b>Ready</b>
                  </div>
                )}
              </div>
            </>
          )}
          {step === 4 && (
            <>
              <p className="eyebrow">Step 4 of 6</p>
              <h2>Confirm the upgrade strategy</h2>
              <p className="upgrade-step-description">
                Use the provider-supported rolling strategy by default and
                document any exception.
              </p>
              <div className="upgrade-strategy-option selected">
                <CheckCircle2 />
                <div>
                  <strong>Provider-managed rolling upgrade</strong>
                  <p>
                    Respect disruption budgets, drain nodes safely and validate
                    each stage.
                  </p>
                </div>
              </div>
            </>
          )}
          {step === 5 && (
            <>
              <p className="eyebrow">Step 5 of 6</p>
              <h2>Set maintenance windows</h2>
              <p className="upgrade-step-description">
                Schedule each immutable version hop in an approved operating
                window.
              </p>
              <div className="upgrade-schedule-preview">
                <CalendarDays />
                <div>
                  <strong>Approved maintenance start</strong>
                  <p>
                    Select a future time, or leave empty for approval without
                    scheduling.
                  </p>
                  <input
                    aria-label="Maintenance start"
                    type="datetime-local"
                    value={scheduledFor}
                    min={new Date(Date.now() + 60_000)
                      .toISOString()
                      .slice(0, 16)}
                    onChange={(event) => setScheduledFor(event.target.value)}
                  />
                </div>
              </div>
            </>
          )}
          {step === 6 && (
            <>
              <p className="eyebrow">Step 6 of 6</p>
              <h2>Review and approve</h2>
              <p className="upgrade-step-description">
                The final plan will become immutable after submission for
                approval.
              </p>
              <dl className="upgrade-scope-list">
                <div>
                  <dt>Cluster</dt>
                  <dd>{cluster.name}</dd>
                </div>
                <div>
                  <dt>Version change</dt>
                  <dd>
                    {cluster.currentVersion} → {target}
                  </dd>
                </div>
                <div>
                  <dt>Strategy</dt>
                  <dd>Provider-managed rolling</dd>
                </div>
                <div>
                  <dt>Approval state</dt>
                  <dd>{createdPlan?.status ?? "Not created"}</dd>
                </div>
              </dl>
              <label className="upgrade-live-field">
                <span>Change reason</span>
                <textarea
                  aria-label="Change reason"
                  value={changeReason}
                  onChange={(event) => setChangeReason(event.target.value)}
                  placeholder="Describe the business reason and expected outcome."
                  rows={4}
                />
              </label>
              {createdPlan && (
                <div className="upgrade-submit-boundary">
                  <CheckCircle2 />
                  <p>
                    Governed draft <strong>{createdPlan.planId}</strong> is
                    persisted with live evidence version {createdPlan.version}.
                  </p>
                </div>
              )}
              {(createPlan.isError || submitPlan.isError) && (
                <div className="upgrade-blocker-notice" role="alert">
                  <strong>
                    <AlertTriangle size={17} /> Plan request failed
                  </strong>
                  <p>{(createPlan.error ?? submitPlan.error)?.message}</p>
                </div>
              )}
              <div className="upgrade-submit-boundary">
                <Info />
                <p>
                  Creating a draft does not call an EKS update API. Submission
                  requires an independent authorized approver before execution.
                </p>
              </div>
            </>
          )}
        </section>

        <aside className="upgrade-plan-preview" aria-label="Plan preview">
          <h2>Plan preview</h2>
          <p>Immutable, staged sequence for this change.</p>
          <ol>
            {planStages.map((stage, index) => (
              <li key={`${stage}-${index}`}>
                <span>{index + 1}</span>
                <strong>{stage}</strong>
              </li>
            ))}
          </ol>
          <div className="upgrade-rollback-note">
            <AlertTriangle size={18} />
            <div>
              <strong>Recovery is provider-dependent</strong>
              <p>
                Navigan will show only the rollback or recovery actions
                supported for each completed stage.
              </p>
            </div>
          </div>
          <div className="upgrade-duration">
            <Clock3 size={18} />
            <span>Execution stages</span>
            <strong>{planStages.length} resumable gates</strong>
          </div>
        </aside>
      </div>

      <div className="upgrade-plan-actions">
        <Button
          variant="secondary"
          onClick={() =>
            step === 1 ? onClose() : setStep((value) => value - 1)
          }
        >
          <ArrowLeft size={16} />
          Back
        </Button>
        {step < planSteps.length ? (
          <Button onClick={() => setStep((value) => value + 1)}>
            Continue to {planSteps[step].toLowerCase()}
            <ChevronRight size={16} />
          </Button>
        ) : (
          <Button
            disabled={
              changeReason.trim().length < 8 ||
              createPlan.isPending ||
              submitPlan.isPending ||
              createdPlan?.status === "SUBMITTED"
            }
            onClick={() =>
              createdPlan ? submitPlan.mutate() : createPlan.mutate()
            }
          >
            {createdPlan?.status === "SUBMITTED"
              ? "Submitted for independent approval"
              : createdPlan
                ? submitPlan.isPending
                  ? "Submitting"
                  : "Submit for approval"
                : createPlan.isPending
                  ? "Creating draft"
                  : "Create governed draft"}
          </Button>
        )}
      </div>
    </div>
  );
}

export function UpgradeWorkspace() {
  const [tab, setTab] = useState<WorkspaceTab>("readiness");
  const [planning, setPlanning] = useState<UpgradeCluster | null>(null);

  if (planning)
    return <PlanWizard cluster={planning} onClose={() => setPlanning(null)} />;

  return (
    <div className="upgrade-workspace">
      <PageHeading
        title="Upgrades & Patching"
        description="Plan and govern platform lifecycle changes across managed clusters."
        icon={<CircleArrowUp />}
        action={
          <Button onClick={() => setTab("readiness")}>
            <CircleArrowUp size={17} />
            Review live readiness
          </Button>
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
