"use client";
import { WorkspaceHeading } from "@/shared/components/workspace-heading";
import { useRouter } from "next/navigation";

import { useEffect, useState } from "react";
import { CalendarDays, CircleArrowUp, RefreshCw } from "lucide-react";
import type { EksUpgradeReadiness } from "@/modules/cluster-management/model";
import { Button } from "@/shared/components/ui";
import { ScopedUpgradePlanner } from "./scoped-upgrade-planner";
import { useUpgradePlans } from "./upgrade-plan-data";
import { SystemUtilitiesWorkspace } from "./system-utilities-workspace";
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
  customerId?: string;
  customerName?: string;
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
      <SystemUtilitiesWorkspace
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

export function UpgradeWorkspace({
  initialTab = "readiness",
}: {
  initialTab?: WorkspaceTab;
}) {
  const fleetData = useUpgradePlans();
  const router = useRouter();
  const dedicated = initialTab === "utilities" || initialTab === "patching";
  const [requestedDate, setRequestedDate] = useState<string>();
  const [tab, setTab] = useState<WorkspaceTab>(initialTab);
  const [centreView, setCentreView] = useState<CentreView>("plans");
  const [reviewPlanId, setReviewPlanId] = useState<string>();
  const [rescheduleRequested, setRescheduleRequested] = useState(false);
  const [plannerOrigin, setPlannerOrigin] = useState<WorkspaceTab>(initialTab);
  const [planning, setPlanning] = useState<UpgradeCluster | null>(null);

  const openPlan = (planId: string | null, reschedule = false) => {
    setReviewPlanId(planId ?? undefined);
    setRescheduleRequested(reschedule);
    setPlanning(null);
  };

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const requestedPlan = params.get("plan");
    if (requestedPlan) setReviewPlanId(requestedPlan);
    const requestedTab = params.get("tab");
    if (!dedicated && ["readiness", "schedule"].includes(requestedTab ?? ""))
      setTab(requestedTab as WorkspaceTab);
    const date = params.get("date");
    if (initialTab === "utilities" && date && /^\d{4}-\d{2}-\d{2}$/.test(date))
      setRequestedDate(date);
  }, [dedicated, initialTab]);

  const changeTab = (value: WorkspaceTab) => {
    setRequestedDate(undefined);
    setPlanning(null);
    setReviewPlanId(undefined);
    setRescheduleRequested(false);
    setCentreView("plans");
    setTab(value);
  };

  return (
    <div
      className={
        planning ? "upgrade-workspace is-planning" : "upgrade-workspace"
      }
    >
      {!planning && (
        <>
          <WorkspaceHeading>
            <header className="upgrade-page-heading">
              <div className="upgrade-page-heading-copy">
                <h1>
                  {tab === "readiness"
                    ? "Upgrade Centre"
                    : tab === "utilities"
                      ? "System Utilities"
                      : tab === "patching"
                        ? "Patching"
                        : "Maintenance Calendar"}
                </h1>
                <p>
                  {tab === "readiness"
                    ? "Plan, approve and execute governed Kubernetes upgrades with safety gates and IaC synchronization."
                    : tab === "utilities"
                      ? "Review installed services, plan upgrades and track utility changes."
                      : tab === "patching"
                        ? "Manage same-version node, AMI, security and runtime patching."
                        : "Plan and review approved maintenance windows across upgrade activities."}
                </p>
              </div>
              {tab === "readiness" && (
                <div className="upgrade-heading-actions">
                  <Button variant="secondary" onClick={fleetData.refresh}>
                    <RefreshCw size={16} aria-hidden="true" />
                    Refresh
                  </Button>
                </div>
              )}
            </header>
          </WorkspaceHeading>

          {!dedicated && <UpgradeTabs active={tab} onChange={changeTab} />}
        </>
      )}

      <div
        role={dedicated ? "region" : "tabpanel"}
        aria-label={
          dedicated
            ? `${initialTab === "utilities" ? "System Utilities" : "Patching"} content`
            : undefined
        }
        id="upgrade-tabpanel"
        aria-labelledby={
          dedicated
            ? undefined
            : "upgrade-tab-" + (planning ? "readiness" : tab)
        }
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
            key={`${tab}-${requestedDate ?? ""}`}
            tab={tab}
            requestedDate={requestedDate}
            onCreate={(kind, date) => {
              if (kind === "utilities") {
                router.push(
                  `/upgrades/utilities?date=${encodeURIComponent(date)}`,
                );
                return;
              }
              setPlanning(null);
              setPlannerOrigin("schedule");
              setRequestedDate(date);
              setReviewPlanId(undefined);
              setRescheduleRequested(false);
              setCentreView("available");
              setTab("readiness");
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
