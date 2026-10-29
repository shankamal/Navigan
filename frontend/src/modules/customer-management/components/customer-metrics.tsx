import {
  SummaryDonut,
  CloudProviderChart,
} from "@/shared/components/summary-donut";

const colors = ["#65a449", "#94a3b8", "#b68c45", "#64748b", "#cbd5e1"];
export function CustomerMetrics({
  total,
  active,
  draft,
  submitted,
  review,
  failed,
  providerCounts,
  providerFailed = false,
}: {
  total?: number;
  active?: number;
  draft?: number;
  submitted?: number;
  review?: number;
  failed: boolean;
  providerCounts?: (number | undefined)[];
  providerFailed?: boolean;
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
  const providerTotal =
    providerCounts?.reduce<number>((sum, value) => sum + (value ?? 0), 0) ?? 0;
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
          <SummaryDonut
            values={values}
            total={count}
            center={String(count)}
            caption="Total"
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
      <div className="customer-cloud-footprint">
        <h2>Cloud provider footprint</h2>
        <p className="customer-cloud-caption">Customer associations by cloud</p>
        {providerFailed ? (
          <p role="status">Cloud metrics unavailable. Refresh to retry.</p>
        ) : !providerCounts ||
          providerCounts.some((value) => value === undefined) ? (
          <p role="status">Loading cloud footprint…</p>
        ) : (
          <CloudProviderChart
            counts={providerCounts.map((value) => value!)}
            caption="Associations"
            label={`Cloud provider footprint: ${providerTotal} customer-cloud associations`}
            legendLabel="Cloud provider associations"
          />
        )}
        <small>Customers can use multiple clouds.</small>
      </div>
      <div className="customer-active">
        <h2>Active customers</h2>
        <div className="customer-chart-content">
          <div
            role="progressbar"
            aria-label={`Active customers: ${active} of ${count}`}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent(active!)}
            aria-valuetext={`${active} of ${count} customers active`}
          >
            <SummaryDonut
              values={[active!, Math.max(0, count - active!)]}
              total={count}
              center={`${percent(active!)}%`}
              caption="Active"
              label={`Active customer coverage: ${active} of ${count}`}
              colors={[colors[0], colors[4]]}
            />
          </div>
          <ul aria-label="Active customer coverage">
            <li>
              <span
                className="customer-chart-dot"
                style={{ backgroundColor: colors[0] }}
              />
              <span>Active</span>
              <strong>{active}</strong>
            </li>
            <li>
              <span
                className="customer-chart-dot"
                style={{ backgroundColor: colors[4] }}
              />
              <span>Not active</span>
              <strong>{Math.max(0, count - active!)}</strong>
            </li>
          </ul>
        </div>
        <p>Active customer coverage</p>
        <small>Within your access scope</small>
      </div>
    </section>
  );
}
