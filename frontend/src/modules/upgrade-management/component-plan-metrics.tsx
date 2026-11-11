import type { EksUpgradePlan } from "@/modules/cluster-management/model";
import { Doughnut } from "./upgrade-metrics";
import { planScopes, scopeTypes, type PlanScope } from "./plan-scope";
import { scheduleOverdue, useScheduleClock } from "./schedule-state";
export const planStage = (p: EksUpgradePlan, now: number) =>
  scheduleOverdue(p, now)
    ? "Overdue"
    : p.status === "SUBMITTED"
      ? "Awaiting approval"
      : ["APPROVED", "SCHEDULED"].includes(p.status)
        ? p.scheduledFor
          ? "Scheduled"
          : "Approved"
        : p.status === "EXECUTING"
          ? "Running"
          : p.status === "DRAFT"
            ? "Draft"
            : "History";
export const stageColors: Record<string, string> = {
  Draft: "#8795a5",
  "Awaiting approval": "#b87a14",
  Approved: "#426fa1",
  Scheduled: "#426fa1",
  Running: "#347535",
  Overdue: "#b14c45",
};
export function ComponentPlanMetrics({
  plans,
  loading,
  unavailable = false,
  selected,
  onSelect,
}: {
  plans: EksUpgradePlan[];
  loading: boolean;
  unavailable?: boolean;
  selected: string;
  onSelect: (type: PlanScope | "all") => void;
}) {
  const now = useScheduleClock();
  const active = plans.filter((p) => planStage(p, now) !== "History");
  return (
    <section
      className="upgrade-component-metrics"
      aria-label="Upgrade plans by component"
      aria-busy={loading}
    >
      <header>
        <h2>Upgrade plans by type</h2>
        <p>
          Counts show saved plans. One plan may affect multiple types. Kept
          versions are excluded.
        </p>
      </header>
      <div className="upgrade-component-metric-grid">
        {scopeTypes.map(({ id, label, Icon }) => {
          const matching = active.filter((p) => planScopes(p).includes(id));
          return (
            <button
              key={id}
              type="button"
              aria-pressed={selected === id}
              onClick={() => onSelect(selected === id ? "all" : id)}
            >
              <Icon size={18} aria-hidden="true" />
              <strong>{label}</strong>
              {unavailable ? (
                <p>Unavailable</p>
              ) : loading ? (
                <p>Loading plans…</p>
              ) : (
                <Doughnut
                  total={matching.length}
                  label="plans"
                  slices={Object.entries(stageColors).map(([stage, color]) => ({
                    label: stage,
                    color,
                    count: matching.filter((p) => planStage(p, now) === stage)
                      .length,
                  }))}
                />
              )}
            </button>
          );
        })}
      </div>
      <ul className="upgrade-stage-key">
        {Object.entries(stageColors).map(([stage, color]) => (
          <li key={stage}>
            <i style={{ backgroundColor: color }} />
            {stage}
          </li>
        ))}
      </ul>
    </section>
  );
}
