"use client";

import { useMemo, useState } from "react";
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
  RefreshCw,
  Save,
  ShieldAlert,
  Wrench,
  X,
} from "lucide-react";
import { Button, PageHeading } from "@/shared/components/ui";
import { LiveUpgradeInventory } from "./live-upgrade-inventory";
import "./upgrade-workspace.css";

type WorkspaceTab =
  "readiness" | "containers" | "utilities" | "schedule" | "history";

type Readiness = "READY" | "WARNING" | "BLOCKED";

interface UpgradeCluster {
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
}

const previewClusters: UpgradeCluster[] = [
  {
    id: "preview-eks-payments",
    name: "payments-prod-eu",
    environment: "Production",
    provider: "EKS",
    providerLabel: "Amazon EKS",
    currentVersion: "1.33",
    targetVersion: "1.35",
    path: ["1.33", "1.34", "1.35"],
    support: "EXTENDED_SUPPORT",
    readiness: "BLOCKED",
    findings: "2 blockers",
    window: "Sat 22:00 IST",
  },
  {
    id: "preview-aks-retail",
    name: "retail-aks-prod",
    environment: "Production",
    provider: "AKS",
    providerLabel: "Azure AKS",
    currentVersion: "1.34.6",
    targetVersion: "1.35.3",
    path: ["1.34.6", "1.35.3"],
    support: "SUPPORTED",
    readiness: "READY",
    findings: "Ready",
    window: "Sun 01:00 IST",
  },
  {
    id: "preview-gke-analytics",
    name: "analytics-gke",
    environment: "Non-production",
    provider: "GKE",
    providerLabel: "GKE Regular",
    currentVersion: "1.34.8",
    targetVersion: "1.35 channel target",
    path: ["1.34.8", "1.35 channel target"],
    support: "SUPPORTED",
    readiness: "WARNING",
    findings: "1 warning",
    window: "Managed window",
  },
  {
    id: "preview-ocp-orders",
    name: "orders-ocp",
    environment: "Non-production",
    provider: "OPENSHIFT",
    providerLabel: "OpenShift stable",
    currentVersion: "4.20.8",
    targetVersion: "4.21.3",
    path: ["4.20.8", "4.21.3"],
    support: "SUPPORTED",
    readiness: "READY",
    findings: "Ready",
    window: "Fri 23:30 IST",
  },
];

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

function ProviderMark({ provider }: { provider: UpgradeCluster["provider"] }) {
  return (
    <span
      className={`upgrade-provider-mark provider-${provider.toLowerCase()}`}
    >
      {provider === "OPENSHIFT" ? "OC" : provider}
    </span>
  );
}

function ReadinessBadge({ value }: { value: Readiness }) {
  const Icon =
    value === "READY"
      ? CheckCircle2
      : value === "BLOCKED"
        ? ShieldAlert
        : AlertTriangle;
  return (
    <span
      className={`upgrade-readiness-badge readiness-${value.toLowerCase()}`}
    >
      <Icon size={15} aria-hidden="true" />
      {value === "READY"
        ? "Ready"
        : value === "BLOCKED"
          ? "Blocked"
          : "Warning"}
    </span>
  );
}

function PreviewNotice({ live = false }: { live?: boolean }) {
  return (
    <div className="upgrade-preview-notice" role="note">
      <Info size={17} aria-hidden="true" />
      {live ? (
        <p>
          <strong>Live read-only inventory.</strong> Cluster records, Amazon EKS
          version readiness and connector-reported utility health are connected.
          Plan persistence, approvals and execution remain disabled.
        </p>
      ) : (
        <p>
          <strong>Experience preview.</strong> Values on this page are sample
          data. Provider discovery, approvals and execution are not connected,
          and no cluster changes can be started from this increment.
        </p>
      )}
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

function ReadinessWorkspace({
  selected,
  onSelect,
  onPlan,
}: {
  selected: UpgradeCluster;
  onSelect: (cluster: UpgradeCluster) => void;
  onPlan: (cluster: UpgradeCluster) => void;
}) {
  return (
    <div className="upgrade-readiness-layout">
      <section className="upgrade-fleet" aria-labelledby="upgrade-fleet-title">
        <div className="upgrade-summary-strip">
          <div>
            <strong>12</strong>
            <span>Clusters require action</span>
          </div>
          <div>
            <strong>4</strong>
            <span>Approaching end of support</span>
          </div>
          <div>
            <strong>3</strong>
            <span>Blocked by readiness findings</span>
          </div>
        </div>
        <div className="upgrade-fleet-heading">
          <div>
            <h2 id="upgrade-fleet-title">Fleet upgrade exposure</h2>
            <p>Review support risk, valid targets and readiness evidence.</p>
          </div>
          <Button
            variant="secondary"
            disabled
            title="Live inventory is not connected yet"
          >
            <RefreshCw size={16} aria-hidden="true" />
            Refresh inventory
          </Button>
        </div>
        <div className="table-scroll">
          <table className="upgrade-fleet-table">
            <thead>
              <tr>
                <th>Cluster</th>
                <th>Platform</th>
                <th>Current</th>
                <th>Recommended target</th>
                <th>Support</th>
                <th>Readiness</th>
                <th>Maintenance window</th>
                <th>
                  <span className="sr-only">Action</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {previewClusters.map((cluster) => (
                <tr
                  key={cluster.id}
                  className={selected.id === cluster.id ? "selected" : ""}
                >
                  <td>
                    <button
                      type="button"
                      className="upgrade-cluster-link"
                      onClick={() => onSelect(cluster)}
                    >
                      <strong>{cluster.name}</strong>
                      <span>{cluster.environment}</span>
                    </button>
                  </td>
                  <td>
                    <span className="upgrade-provider-cell">
                      <ProviderMark provider={cluster.provider} />
                      {cluster.providerLabel}
                    </span>
                  </td>
                  <td>{cluster.currentVersion}</td>
                  <td>{cluster.targetVersion}</td>
                  <td>
                    <span
                      className={`upgrade-support support-${cluster.support.toLowerCase()}`}
                    >
                      {cluster.support === "SUPPORTED"
                        ? "Supported"
                        : "Extended support"}
                    </span>
                  </td>
                  <td>
                    <ReadinessBadge value={cluster.readiness} />
                  </td>
                  <td>{cluster.window}</td>
                  <td>
                    <button
                      type="button"
                      className="upgrade-row-action"
                      onClick={() => {
                        onSelect(cluster);
                        onPlan(cluster);
                      }}
                    >
                      {cluster.readiness === "READY" ? "Plan" : "Review"}
                      <ChevronRight size={15} aria-hidden="true" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <aside
        className="upgrade-cluster-drawer"
        aria-label={`${selected.name} upgrade details`}
      >
        <div className="upgrade-drawer-title">
          <div>
            <p>{selected.providerLabel}</p>
            <h2>{selected.name}</h2>
          </div>
          <ReadinessBadge value={selected.readiness} />
        </div>
        <dl className="upgrade-version-summary">
          <div>
            <dt>Current</dt>
            <dd>{selected.currentVersion}</dd>
          </div>
          <div>
            <dt>Target</dt>
            <dd>{selected.targetVersion}</dd>
          </div>
        </dl>
        <div className="upgrade-path">
          <h3>Recommended upgrade path</h3>
          <ol>
            <li className="complete">
              <span>
                <Check size={14} />
              </span>
              <div>
                <strong>Pre-flight checks</strong>
                <p>Capture configuration, capacity and workload evidence.</p>
              </div>
            </li>
            {selected.path.slice(1).flatMap((version) => [
              <li key={`control-${version}`}>
                <span />
                <div>
                  <strong>Control plane {version}</strong>
                  <p>Apply the provider-supported control-plane update.</p>
                </div>
              </li>,
              <li key={`nodes-${version}`}>
                <span />
                <div>
                  <strong>Nodes & add-ons {version}</strong>
                  <p>Roll nodes and align compatible platform components.</p>
                </div>
              </li>,
            ])}
            <li>
              <span />
              <div>
                <strong>Validation</strong>
                <p>Confirm health, workloads, policies and integrations.</p>
              </div>
            </li>
          </ol>
        </div>
        {selected.readiness === "BLOCKED" && (
          <div className="upgrade-blocker-notice">
            <strong>
              <ShieldAlert size={17} /> 2 blockers
            </strong>
            <ul>
              <li>
                Deprecated APIs must be remediated before the selected target.
              </li>
              <li>
                Two disruption budgets currently prevent safe node draining.
              </li>
            </ul>
          </div>
        )}
        {selected.readiness === "WARNING" && (
          <div className="upgrade-warning-notice">
            <AlertTriangle size={17} />
            Release-channel timing needs confirmation before scheduling.
          </div>
        )}
        <Button
          className="upgrade-drawer-action"
          onClick={() => onPlan(selected)}
        >
          {selected.readiness === "READY"
            ? "Create upgrade plan"
            : "Open readiness assessment"}
        </Button>
      </aside>
    </div>
  );
}

function SupportingTab({ tab }: { tab: Exclude<WorkspaceTab, "readiness"> }) {
  if (tab === "containers" || tab === "utilities") {
    return <LiveUpgradeInventory mode={tab} />;
  }
  const content = {
    schedule: {
      icon: CalendarDays,
      title: "Maintenance schedule",
      description:
        "Coordinate approved plans through sandbox, non-production and production windows while respecting freezes, dependencies and promotion gates.",
    },
    history: {
      icon: History,
      title: "Plans and execution history",
      description:
        "Track draft, approved, scheduled, running and completed plans with immutable stage evidence and audit history.",
    },
  }[tab as "schedule" | "history"];
  const Icon = content.icon;
  return (
    <section className="upgrade-coming-soon" aria-labelledby={`${tab}-title`}>
      <Icon size={28} aria-hidden="true" />
      <div>
        <p className="eyebrow">Next delivery increment</p>
        <h2 id={`${tab}-title`}>{content.title}</h2>
        <p>{content.description}</p>
      </div>
    </section>
  );
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
  const [saved, setSaved] = useState(false);
  const targetChoices = cluster.path.slice(1);

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
          <Button variant="secondary" onClick={() => setSaved(true)}>
            <Save size={16} aria-hidden="true" />
            {saved ? "Draft saved locally" : "Save draft"}
          </Button>
        </div>
      </div>

      <PreviewNotice />

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
                  <strong>4</strong>
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
                          ? "Recommended preview target"
                          : "Complete this hop and plan the next version later"}
                      </small>
                    </span>
                  </label>
                ))}
              </fieldset>
              <div className="upgrade-release-impact">
                <h3>Release impact</h3>
                <ul>
                  <li className="warning">
                    <AlertTriangle size={16} />
                    <strong>Removed APIs detected</strong>
                    <span>3 API usages need review</span>
                  </li>
                  <li>
                    <CheckCircle2 size={16} />
                    <strong>CoreDNS</strong>
                    <span>Compatibility check required</span>
                  </li>
                  <li>
                    <CheckCircle2 size={16} />
                    <strong>Network plugin</strong>
                    <span>Compatibility check required</span>
                  </li>
                  <li>
                    <Clock3 size={16} />
                    <strong>Estimated maintenance</strong>
                    <span>Two maintenance windows</span>
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
                <div className="blocked">
                  <ShieldAlert />
                  <span>
                    <strong>Deprecated API compatibility</strong>
                    <small>
                      Three API usages require remediation or evidence.
                    </small>
                  </span>
                  <b>Blocked</b>
                </div>
                <div className="blocked">
                  <ShieldAlert />
                  <span>
                    <strong>Pod disruption budgets</strong>
                    <small>
                      Two workloads currently prevent safe draining.
                    </small>
                  </span>
                  <b>Blocked</b>
                </div>
                <div>
                  <CheckCircle2 />
                  <span>
                    <strong>Capacity headroom</strong>
                    <small>
                      Surge capacity is available for rolling replacement.
                    </small>
                  </span>
                  <b>Ready</b>
                </div>
              </div>
            </>
          )}
          {step === 4 && (
            <>
              <p className="eyebrow">Step 4 of 6</p>
              <h2>Choose an upgrade strategy</h2>
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
              <div className="upgrade-strategy-option">
                <CloudCog />
                <div>
                  <strong>Blue/green cluster migration</strong>
                  <p>
                    Plan a separate target cluster where in-place risk is
                    unacceptable.
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
                  <strong>Window 1 · Saturday 22:00 IST</strong>
                  <p>
                    Control plane, nodes and add-ons for the first required hop.
                  </p>
                </div>
              </div>
              <div className="upgrade-schedule-preview">
                <CalendarDays />
                <div>
                  <strong>Window 2 · Following Saturday 22:00 IST</strong>
                  <p>Final target stages and post-upgrade validation.</p>
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
                  <dd>Draft preview</dd>
                </div>
              </dl>
              <div className="upgrade-submit-boundary">
                <Info />
                <p>
                  Submission remains unavailable until identity, provider
                  discovery and approval APIs are connected.
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
            <span>Estimated duration</span>
            <strong>2h 40m across 2 windows</strong>
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
          <Button disabled title="Approval API is not connected">
            Submit for approval
          </Button>
        )}
      </div>
    </div>
  );
}

export function UpgradeWorkspace() {
  const [tab, setTab] = useState<WorkspaceTab>("readiness");
  const [selected, setSelected] = useState(previewClusters[0]);
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
          <Button onClick={() => setPlanning(selected)}>
            <CircleArrowUp size={17} />
            Create upgrade plan
          </Button>
        }
      />
      <PreviewNotice live={tab === "containers" || tab === "utilities"} />
      <UpgradeTabs active={tab} onChange={setTab} />
      <div role="tabpanel">
        {tab === "readiness" ? (
          <ReadinessWorkspace
            selected={selected}
            onSelect={setSelected}
            onPlan={setPlanning}
          />
        ) : (
          <SupportingTab tab={tab} />
        )}
      </div>
    </div>
  );
}
