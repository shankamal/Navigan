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
  onFilter,
}: {
  total?: number;
  active?: number;
  draft?: number;
  submitted?: number;
  review?: number;
  failed?: number;
  error: boolean;
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
            <div className="cluster-active-summary">
              <strong>
                {total ? Math.round((active! / total) * 100) : 0}%
              </strong>
              <span>Active clusters</span>
              <small>Within your access scope</small>
            </div>
          </div>
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
