import Link from "next/link";
import { Clock3, FileText, ShieldCheck, AlertTriangle } from "lucide-react";
import { EnvironmentRing } from "@/modules/environment-management/components/environment-metrics";
export function ClusterMetrics({
  total,
  active,
  draft,
  submitted,
  review,
  failed,
  error,
  planReady,
  applying,
  provisioningError = false,
  onFilter,
}: {
  total?: number;
  active?: number;
  draft?: number;
  submitted?: number;
  review?: number;
  failed?: number;
  error: boolean;
  planReady?: number;
  applying?: number;
  provisioningError?: boolean;
  onFilter: (status: string) => void;
}) {
  const values = [active, draft, submitted, review];
  const ready = total !== undefined && values.every((v) => v !== undefined);
  const other = ready
    ? Math.max(0, total! - values.reduce<number>((sum, v) => sum + (v ?? 0), 0))
    : 0;
  const entries = [
    { label: "Active", value: active, color: "#65a449" },
    { label: "Draft", value: draft, color: "#94a3b8" },
    { label: "Submitted", value: submitted, color: "#b68c45" },
    { label: "Under review", value: review, color: "#64748b" },
    { label: "Other stages", value: other, color: "#cbd5e1" },
  ];
  return (
    <div className="cluster-portfolio">
      <section className="panel cluster-lifecycle-chart">
        <h2>Clusters by lifecycle</h2>
        {error ? (
          <p role="status">Cluster metrics unavailable. Refresh to retry.</p>
        ) : !ready ? (
          <p role="status">Loading lifecycle metrics…</p>
        ) : (
          <div className="cluster-chart-content">
            <EnvironmentRing
              values={entries.map((entry) => entry.value!)}
              total={total!}
              center={String(total)}
              label={`Cluster lifecycle: ${total} total clusters`}
            />
            <ul>
              {entries
                .filter(
                  (entry) => entry.label !== "Other stages" || entry.value,
                )
                .map((entry) => (
                  <li key={entry.label}>
                    <span
                      className="cluster-chart-dot"
                      style={{ backgroundColor: entry.color }}
                    />
                    <span>{entry.label}</span>
                    <strong>{entry.value}</strong>
                  </li>
                ))}
            </ul>
          </div>
        )}
      </section>
      <section className="panel cluster-active-chart">
        <h2>Active clusters</h2>
        {error ? (
          <p role="status">Active metrics unavailable. Refresh to retry.</p>
        ) : total === undefined || active === undefined ? (
          <p role="status">Loading active metrics…</p>
        ) : (
          <>
            <div className="cluster-coverage-value">
              <strong>
                {active} of {total}
              </strong>
              <strong>{total ? Math.round((active / total) * 100) : 0}%</strong>
            </div>
            <progress
              max={100}
              value={total ? Math.min(100, (active / total) * 100) : 0}
              aria-label="Active cluster lifecycle coverage"
            />
            <div className="cluster-coverage-scale">
              <span>0%</span>
              <span>50%</span>
              <span>100%</span>
            </div>
            <p>Active lifecycle status</p>
          </>
        )}
      </section>
      <section className="panel cluster-provisioning-chart">
        <h2>Provisioning status</h2>
        {provisioningError ? (
          <p role="status">
            Provisioning metrics unavailable. Refresh to retry.
          </p>
        ) : [planReady, applying, failed].some((v) => v === undefined) ? (
          <p role="status">Loading provisioning metrics…</p>
        ) : (
          <>
            {[
              {
                label: "Plan ready",
                status: "PLAN_READY",
                value: planReady!,
                color: "#8298ae",
              },
              {
                label: "Applying",
                status: "APPLYING",
                value: applying!,
                color: "#65a449",
              },
              {
                label: "Failed",
                status: "FAILED",
                value: failed!,
                color: "#bf6666",
              },
            ].map((item) => (
              <button
                type="button"
                className="cluster-provisioning-row"
                key={item.status}
                onClick={() => onFilter(item.status)}
              >
                <span>{item.label}</span>
                <meter
                  min={0}
                  max={Math.max(1, planReady!, applying!, failed!)}
                  value={item.value}
                  aria-label={`${item.label} requests`}
                  style={
                    {
                      "--cluster-bar-color": item.color,
                    } as import("react").CSSProperties
                  }
                />
                <strong>{item.value}</strong>
              </button>
            ))}
            <p>Current request states</p>
          </>
        )}
      </section>
      <aside
        className="panel cluster-attention"
        aria-label="Cluster attention queue"
      >
        <header>
          <h2>Attention queue</h2>
          <Link href="/clusters/reviews">Reviews →</Link>
        </header>
        {[
          {
            label: "Under review",
            status: "UNDER_REVIEW",
            count: review,
            icon: ShieldCheck,
          },
          {
            label: "Submitted",
            status: "SUBMITTED",
            count: submitted,
            icon: Clock3,
          },
          {
            label: "Draft requests",
            status: "DRAFT",
            count: draft,
            icon: FileText,
          },
          {
            label: "Failed executions",
            status: "FAILED",
            count: failed,
            icon: AlertTriangle,
          },
        ].map((entry) => (
          <button
            type="button"
            key={entry.status}
            onClick={() => onFilter(entry.status)}
          >
            <entry.icon size={20} />
            <span>
              <strong>{entry.label}</strong>
              <small>{entry.count ?? "—"} requests</small>
            </span>
            <span aria-hidden="true">›</span>
          </button>
        ))}
      </aside>
    </div>
  );
}
