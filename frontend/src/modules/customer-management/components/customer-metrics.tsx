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
    <div className="customer-ring">
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
export function CustomerMetrics({
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
      <div className="customer-metrics-message" role="status">
        Customer metrics unavailable. Refresh to retry.
      </div>
    );
  if (
    [total, active, draft, submitted, review].some(
      (value) => value === undefined,
    )
  )
    return (
      <div className="customer-metrics-message" role="status">
        Loading customer metrics…
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
      className="customer-metrics"
      aria-label="Customer lifecycle metrics"
    >
      <div className="customer-lifecycle">
        <h2>Customer lifecycle</h2>
        <div className="customer-chart-content">
          <Ring
            values={values}
            total={count}
            center={String(count)}
            label={`Customer lifecycle: ${count} total customers`}
          />
          <ul>
            {values.map((value, index) =>
              index === 4 && !value ? null : (
                <li key={labels[index]}>
                  <span
                    className="customer-chart-dot"
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
      <div className="customer-active">
        <h2>Active customers</h2>
        <div className="customer-chart-content">
          <Ring
            values={[active!]}
            total={count}
            center={String(active)}
            label={`Active customers: ${active} of ${count}`}
          />
          <div>
            <strong className="customer-active-percent">
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
