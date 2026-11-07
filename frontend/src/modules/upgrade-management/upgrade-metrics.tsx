import type { EksUpgradePlan } from "@/modules/cluster-management/model";
import { scheduleOverdue } from "./schedule-state";
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
  const total = ready + blocked + review + unknown,
    buckets = [
      { label: "Ready", count: ready, className: "ready" },
      { label: "Blocked", count: blocked, className: "blocked" },
      { label: "Review required", count: review, className: "review" },
      { label: "Evidence unavailable", count: unknown, className: "unknown" },
    ];
  const active = plans.filter((p) =>
      ["DRAFT", "SUBMITTED", "APPROVED", "SCHEDULED", "EXECUTING"].includes(
        p.status,
      ),
    ),
    overdue = active.filter((p) => scheduleOverdue(p, Date.now())).length;
  const stages = [
    {
      label: "Draft",
      count: active.filter((p) => p.status === "DRAFT").length,
    },
    {
      label: "Awaiting approval",
      count: active.filter((p) => p.status === "SUBMITTED").length,
    },
    {
      label: "Approved / scheduled",
      count: active.filter((p) => ["APPROVED", "SCHEDULED"].includes(p.status))
        .length,
    },
    {
      label: "Executing",
      count: active.filter((p) => p.status === "EXECUTING").length,
    },
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
        <div
          className="upgrade-readiness-bar"
          role="img"
          aria-label={buckets.map((b) => `${b.label}: ${b.count}`).join(", ")}
        >
          {buckets.map((b) => (
            <span
              key={b.label}
              className={b.className}
              style={{ width: `${total ? (b.count / total) * 100 : 0}%` }}
            />
          ))}
        </div>
        <ul className="upgrade-chart-legend">
          {buckets.map((b) => (
            <li key={b.label}>
              <i className={b.className} />
              {b.label}
              <strong>{b.count}</strong>
            </li>
          ))}
        </ul>
      </section>
      <section>
        <header>
          <h2>Plan pipeline</h2>
          <strong>{active.length} active</strong>
        </header>
        <p>Container and utility requests · {overdue} overdue / inactive</p>
        <div
          className="upgrade-pipeline-chart"
          role="img"
          aria-label={stages.map((b) => `${b.label}: ${b.count}`).join(", ")}
        >
          {stages.map((b) => (
            <div key={b.label}>
              <span>{b.label}</span>
              <div>
                <i
                  style={{
                    width: `${(b.count / Math.max(1, ...stages.map((s) => s.count))) * 100}%`,
                  }}
                />
              </div>
              <strong>{b.count}</strong>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
