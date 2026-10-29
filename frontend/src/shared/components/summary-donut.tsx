import "./summary-donut.css";

const lifecycleColors = ["#65a449", "#94a3b8", "#b68c45", "#64748b", "#cbd5e1"];
const cloudColors = ["#f59e0b", "#1689d4", "#4f7fe9", "#d43b2f"];

export function SummaryDonut({
  values,
  total,
  center,
  caption,
  label,
  colors = lifecycleColors,
}: {
  values: number[];
  total: number;
  center: string;
  caption: string;
  label: string;
  colors?: string[];
}) {
  let offset = 0;
  return (
    <div className="summary-donut">
      <svg viewBox="0 0 120 120" role="img" aria-label={label}>
        <circle
          cx="60"
          cy="60"
          r="48"
          fill="none"
          stroke="#e8ecf0"
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
      <div className="summary-donut-center">
        <strong>{center}</strong>
        <span>{caption}</span>
      </div>
    </div>
  );
}

export function CloudProviderChart({
  counts,
  label,
  caption,
  legendLabel,
  labels = ["AWS", "Azure", "Google Cloud", "OCI"],
}: {
  counts: number[];
  label: string;
  caption: string;
  legendLabel: string;
  labels?: string[];
}) {
  const total = counts.reduce((sum, value) => sum + value, 0);
  return (
    <div className="cloud-provider-chart">
      <SummaryDonut
        values={counts}
        total={total}
        center={String(total)}
        caption={caption}
        label={label}
        colors={cloudColors}
      />
      <ul className="cloud-provider-legend" aria-label={legendLabel}>
        {labels.map((name, index) => (
          <li key={name}>
            <span
              className="summary-chart-dot"
              style={{ backgroundColor: cloudColors[index] }}
            />
            <img
              src={`/logos/${["amazonwebservices", "microsoftazure", "googlecloud", "oracle"][index]}.svg`}
              width={20}
              height={20}
              alt=""
            />
            <span>{name}</span>
            <strong>
              {counts[index]} (
              {total ? Math.round((counts[index] / total) * 100) : 0}%)
            </strong>
          </li>
        ))}
      </ul>
    </div>
  );
}
