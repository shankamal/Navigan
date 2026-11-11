"use client";

import { ScopedUpgradePlanner } from "./scoped-upgrade-planner";
import { useUpgradePlans } from "./upgrade-plan-data";
import { containerIdentity, PlatformIdentity } from "./platform-identity";
import { useState } from "react";
import {
  CalendarDays,
  CircleArrowUp,
  History,
  ShieldAlert,
  Wrench,
} from "lucide-react";
import type { EksUpgradeReadiness } from "@/modules/cluster-management/model";
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
          <ScopedUpgradePlanner
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
