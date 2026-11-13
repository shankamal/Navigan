import type { EksUpgradePlan } from "@/modules/cluster-management/model";
import { scheduleOverdue, useScheduleClock } from "./schedule-state";
type Slice = { label: string; count: number; color: string };
export function Doughnut({
  slices,
  total,
  label,
  centerValue,
}: {
  slices: Slice[];
  total: number;
  label: string;
  centerValue?: string;
}) {
  let offset = 0;
  return (
    <div className="upgrade-doughnut-layout">
      <div className="upgrade-doughnut">
        <svg
          viewBox="0 0 120 120"
          role="img"
          aria-label={`${label}. ${slices.map((s) => `${s.label}: ${s.count}`).join(", ")}`}
        >
          <circle
            cx="60"
            cy="60"
            r="46"
            fill="none"
            stroke="#e6ebf0"
            strokeWidth="13"
          />
          {slices
            .filter((s) => s.count > 0)
            .map((s) => {
              const percent = total ? (s.count / total) * 100 : 0,
                start = offset;
              offset += percent;
              return (
                <circle
                  key={s.label}
                  cx="60"
                  cy="60"
                  r="46"
                  pathLength="100"
                  fill="none"
                  stroke={s.color}
                  strokeWidth="13"
                  strokeDasharray={`${percent} ${100 - percent}`}
                  strokeDashoffset={-start}
                  transform="rotate(-90 60 60)"
                />
              );
            })}
        </svg>
        <div className="upgrade-doughnut-total">
          <strong>{centerValue ?? total}</strong>
          <span>{label}</span>
        </div>
      </div>
      <ul className="upgrade-doughnut-legend">
        {slices.map((s) => (
          <li key={s.label}>
            <i style={{ background: s.color }} />
            <span>{s.label}</span>
            <strong>{s.count}</strong>
          </li>
        ))}
      </ul>
    </div>
  );
}
export function UpgradeMetrics({
  ready,
  blocked,
  review,
  unknown,
  plans,
  loading,
}: {
  ready: number;
  blocked: number;
  review: number;
  unknown: number;
  plans: EksUpgradePlan[];
  loading: boolean;
}) {
  const now = useScheduleClock(),
    total = ready + blocked + review + unknown,
    active = plans.filter((p) =>
      ["DRAFT", "SUBMITTED", "APPROVED", "SCHEDULED", "EXECUTING"].includes(
        p.status,
      ),
    ),
    valid = active.filter((p) => !scheduleOverdue(p, now)),
    overdue = active.length - valid.length;
  const readiness = [
    { label: "Ready", count: ready, color: "#347535" },
    { label: "Blocked", count: blocked, color: "#b14c45" },
    { label: "Review required", count: review, color: "#c58b22" },
    { label: "Evidence unavailable", count: unknown, color: "#8795a5" },
  ];
  const stages = [
    {
      label: "Draft",
      count: valid.filter((p) => p.status === "DRAFT").length,
      color: "#73889b",
    },
    {
      label: "Awaiting approval",
      count: valid.filter((p) => p.status === "SUBMITTED").length,
      color: "#c58b22",
    },
    {
      label: "Approved / scheduled",
      count: valid.filter((p) => ["APPROVED", "SCHEDULED"].includes(p.status))
        .length,
      color: "#347535",
    },
    {
      label: "Executing",
      count: valid.filter((p) => p.status === "EXECUTING").length,
      color: "#26890d",
    },
    { label: "Overdue / inactive", count: overdue, color: "#b14c45" },
  ];
  return (
    <div
      className="upgrade-metrics"
      aria-label="Live upgrade metrics"
      aria-busy={loading}
    >
      <section>
        <header>
          <h2>Cluster readiness</h2>
          <strong>
            {ready} / {total} ready
          </strong>
        </header>
        <p>Latest EKS evidence across active managed clusters</p>
        <Doughnut slices={readiness} total={total} label="clusters" />
      </section>
      <section>
        <header>
          <h2>Plan pipeline</h2>
          <strong>{active.length} open requests</strong>
        </header>
        <p>Container and utility plans · {overdue} overdue / inactive</p>
        <Doughnut slices={stages} total={active.length} label="requests" />
      </section>
    </div>
  );
}
