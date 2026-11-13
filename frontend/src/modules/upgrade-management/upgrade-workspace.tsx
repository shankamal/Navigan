"use client";

import { useState } from "react";
import {
  CalendarDays,
  CircleArrowUp,
  PackageCheck,
  Plus,
  Wrench,
} from "lucide-react";
import type { EksUpgradeReadiness } from "@/modules/cluster-management/model";
import { Button } from "@/shared/components/ui";
import { ScopedUpgradePlanner } from "./scoped-upgrade-planner";
import { useUpgradePlans } from "./upgrade-plan-data";
import { containerIdentity, PlatformIdentity } from "./platform-identity";
import { LiveUpgradeInventory } from "./live-upgrade-inventory";
import { LiveUpgradeCentre } from "./live-upgrade-centre";
import { UpgradePlansWorkspace } from "./upgrade-plans-workspace";
import { PatchingWorkspace } from "./patching-workspace";
import "./upgrade-workspace.css";

type WorkspaceTab = "readiness" | "utilities" | "patching" | "schedule";
type CentreView = "plans" | "available";

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
  { id: "readiness", label: "Upgrade Centre", icon: CircleArrowUp },
  { id: "utilities", label: "System Utilities", icon: Wrench },
  { id: "patching", label: "Patching", icon: PackageCheck },
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
  onReview,
  onCreate,
  requestedDate,
}: {
  onCreate: (kind: "containers" | "utilities", date: string) => void;
  requestedDate?: string;
  tab: Exclude<WorkspaceTab, "readiness">;
  onReview: (planId: string | null, reschedule?: boolean) => void;
  onPlan: (cluster: UpgradeCluster) => void;
}) {
  if (tab === "utilities") {
    return (
      <LiveUpgradeInventory
        mode="utilities"
        onPlan={onPlan}
        onReview={onReview}
        requestedDate={requestedDate}
      />
    );
  }

  if (tab === "patching") return <PatchingWorkspace />;

  return (
    <UpgradePlansWorkspace
      mode="schedule"
      onCreate={onCreate}
      rescheduleRequested={false}
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
  const [centreView, setCentreView] = useState<CentreView>("plans");
  const [reviewPlanId, setReviewPlanId] = useState<string>();
  const [rescheduleRequested, setRescheduleRequested] = useState(false);
  const [plannerOrigin, setPlannerOrigin] = useState<WorkspaceTab>("readiness");
  const [planning, setPlanning] = useState<UpgradeCluster | null>(null);

  const openPlan = (planId: string | null, reschedule = false) => {
    setReviewPlanId(planId ?? undefined);
    setRescheduleRequested(reschedule);
    setPlanning(null);
  };

  const changeTab = (value: WorkspaceTab) => {
    setRequestedDate(undefined);
    setPlanning(null);
    setReviewPlanId(undefined);
    setRescheduleRequested(false);
    setCentreView("plans");
    setTab(value);
  };

  const openAvailableUpgrades = () => {
    setRequestedDate(undefined);
    setPlanning(null);
    setReviewPlanId(undefined);
    setRescheduleRequested(false);
    setCentreView("available");
    setTab("readiness");
  };

  return (
    <div
      className={
        planning ? "upgrade-workspace is-planning" : "upgrade-workspace"
      }
    >
      <header className="upgrade-page-heading">
        <div className="upgrade-page-heading-copy">
          <h1>Upgrade &amp; Patching</h1>
          <p>
            Plan, approve and execute governed EKS upgrades, same-version
            patching and utility lifecycle actions.
          </p>
        </div>
        <div className="upgrade-heading-actions">
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
          <Button onClick={openAvailableUpgrades}>
            <Plus size={16} aria-hidden="true" />
            Create Upgrade Plan
          </Button>
        </div>
      </header>

      <UpgradeTabs
        active={planning ? "readiness" : tab}
        onChange={changeTab}
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
          <LiveUpgradeCentre
            key={centreView + (requestedDate ?? "")}
            initialView={centreView}
            onPlan={setPlanning}
            onReview={openPlan}
          />
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
              setCentreView(kind === "containers" ? "available" : "plans");
              setTab(kind === "containers" ? "readiness" : "utilities");
            }}
            onPlan={setPlanning}
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
