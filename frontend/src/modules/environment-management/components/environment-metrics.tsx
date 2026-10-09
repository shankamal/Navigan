const colors = ["#65a449", "#94a3b8", "#b68c45", "#64748b", "#cbd5e1"];
function Ring({
  values,
  total,
  center,
  label,
}: {
  values: number[];
  total: number;
  center: string;
  label: string;
}) {
  let offset = 0;
  return (
    <div className="environment-ring">
      <svg viewBox="0 0 120 120" role="img" aria-label={label}>
        <circle
          cx="60"
          cy="60"
          r="48"
          fill="none"
          stroke="#e8ece8"
          strokeWidth="13"
        />
        {values.map((value, index) => {
          const length = total > 0 ? (value / total) * 100 : 0;
          const start = offset;
          offset += length;
          return (
            <circle
              key={index}
              cx="60"
              cy="60"
              r="48"
              fill="none"
              stroke={colors[index]}
              strokeWidth="13"
              pathLength="100"
              strokeDasharray={`${length} ${100 - length}`}
              strokeDashoffset={-start}
              transform="rotate(-90 60 60)"
            />
          );
        })}
      </svg>
      <div>
        <strong>{center}</strong>
        <span>{label.startsWith("Active") ? "of " + total : "Total"}</span>
      </div>
    </div>
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
          <Ring
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
          <Ring
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
