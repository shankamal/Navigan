import { SummaryDonut } from "@/shared/components/summary-donut";
const colors = ["#65a449", "#94a3b8", "#b68c45", "#64748b", "#cbd5e1"];
export function EnvironmentRing({
  values,
  total,
  center,
  label,
  caption,
  palette,
}: {
  values: number[];
  total: number;
  center: string;
  label: string;
  caption?: string;
  palette?: string[];
}) {
  return (
    <SummaryDonut
      values={values}
      total={total}
      center={center}
      label={label}
      caption={
        caption ?? (label.startsWith("Active") ? "of " + total : "Total")
      }
      colors={palette ?? colors}
    />
  );
}
export function EnvironmentMetrics({
  total,
  active,
  draft,
  submitted,
  review,
  failed,
}: {
  total?: number;
  active?: number;
  draft?: number;
  submitted?: number;
  review?: number;
  failed: boolean;
}) {
  if (failed)
    return (
      <div className="environment-metrics-message" role="status">
        Environment metrics unavailable. Refresh to retry.
      </div>
    );
  if (
    [total, active, draft, submitted, review].some(
      (value) => value === undefined,
    )
  )
    return (
      <div className="environment-metrics-message" role="status">
        Loading environment metrics…
      </div>
    );
  const count = total!;
  const data = [active!, draft!, submitted!, review!];
  const other = Math.max(
    0,
    count - data.reduce((sum, value) => sum + value, 0),
  );
  const values = [...data, other];
  const labels = [
    "Active",
    "Draft",
    "Submitted",
    "Under review",
    "Other statuses",
  ];
  const percent = (value: number) =>
    count ? Math.round((value / count) * 100) : 0;
  return (
    <section
      className="environment-metrics"
      aria-label="Environment lifecycle metrics"
    >
      <div className="environment-lifecycle">
        <h2>Environment lifecycle</h2>
        <div className="environment-chart-content">
          <EnvironmentRing
            values={values}
            total={count}
            center={String(count)}
            label={`Environment lifecycle: ${count} total environments`}
          />
          <ul>
            {values.map((value, index) =>
              index === 4 && !value ? null : (
                <li key={labels[index]}>
                  <span
                    className="environment-chart-dot"
                    style={{ backgroundColor: colors[index] }}
                  />
                  <span>{labels[index]}</span>
                  <strong>
                    {value} ({percent(value)}%)
                  </strong>
                </li>
              ),
            )}
          </ul>
        </div>
      </div>
      <div className="environment-active">
        <h2>Approved for cluster requests</h2>
        <div className="environment-chart-content">
          <EnvironmentRing
            values={[active!]}
            total={count}
            center={String(active)}
            label={`Active environments: ${active} of ${count}`}
          />
          <div>
            <strong className="environment-active-percent">
              {percent(active!)}%
            </strong>
            <p>Active</p>
            <small>Within your access scope</small>
          </div>
        </div>
      </div>
    </section>
  );
}
