import { ArrowRight, CheckCircle2, Route, ChartPie } from "lucide-react";

import { PlatformIcon } from "./platform-icon";
import { SummaryDonut } from "@/shared/components/summary-donut";
import styles from "./migration-overview.module.css";

type Segment = { label: string; count: number; color: string };
type Path = {
  path: string;
  sourcePlatform: string;
  targetPlatform: string;
  count: number;
};

const colors: Record<string, string> = {
  draft: "#77818b",
  discovery: "#218b95",
  assessment: "#c18a27",
  review: "#8562b2",
  approved: "#267245",
  blocked: "#bf5555",
};

function Donut({
  label,
  total,
  value,
  caption,
  segments,
}: {
  label: string;
  total: number;
  value: string | number;
  caption: string;
  segments: Segment[];
}) {
  return (
    <SummaryDonut
      values={segments.map((segment) => segment.count)}
      total={total}
      center={String(value)}
      caption={caption}
      label={`${label}. ${segments.map((s) => `${s.label}: ${s.count}`).join(", ")}. Total: ${total}`}
      colors={segments.map((segment) => segment.color)}
    />
  );
}

export function MigrationPortfolioSummary({
  total,
  lifecycle,
  approved,
  paths,
  pending,
  error,
}: {
  total: number;
  lifecycle: { label: string; tone: string; count: number }[];
  approved: number;
  paths: Path[];
  pending: boolean;
  error: boolean;
}) {
  const segments = lifecycle.map((item) => ({
    ...item,
    color: colors[item.tone] ?? "#77818b",
  }));
  // Preserve every returned status in the chart, including statuses outside the workflow board.
  const other = total - segments.reduce((sum, item) => sum + item.count, 0);
  if (other > 0)
    segments.push({
      label: "Other statuses",
      tone: "other",
      count: other,
      color: "#48535e",
    });
  const pathColors = [
    "#218b95",
    "#1689d4",
    "#8562b2",
    "#c18a27",
    "#bf5555",
    "#267245",
  ];
  const pathTotal = paths.reduce((sum, item) => sum + item.count, 0);
  const pathSegments = paths.map((item, index) => ({
    label: `${item.sourcePlatform} to ${item.targetPlatform}`,
    count: item.count,
    color: pathColors[index % pathColors.length],
  }));
  const approvedPercent = total ? Math.round((approved / total) * 100) : 0;
  const unavailable = pending || error;
  const message = pending
    ? "Loading portfolio…"
    : "Portfolio summary unavailable. Use Refresh to try again.";
  return (
    <section
      className={styles.summary}
      aria-label="Migration portfolio metrics"
      aria-busy={pending}
    >
      <article className={styles.summaryCard}>
        <header>
          <ChartPie size={16} aria-hidden="true" />
          <h2>Assessment lifecycle</h2>
        </header>
        <p>All assessments · independent of list filters</p>
        {unavailable ? (
          <p className={styles.metricState}>{message}</p>
        ) : (
          <div className={styles.chartBody}>
            <Donut
              label="Assessment lifecycle"
              total={total}
              value={total}
              caption="assessments"
              segments={segments}
            />
            <ul className={styles.legend}>
              {segments.map((item) => (
                <li key={item.label}>
                  <span
                    className={styles.swatch}
                    style={{ background: item.color }}
                    aria-hidden="true"
                  />
                  <span>{item.label}</span>
                  <strong>{item.count}</strong>
                </li>
              ))}
            </ul>
          </div>
        )}
      </article>
      <article className={styles.summaryCard}>
        <header>
          <CheckCircle2 size={16} aria-hidden="true" />
          <h2>Approved assessments</h2>
        </header>
        <p>Governance approval · not deployment progress</p>
        {unavailable ? (
          <p className={styles.metricState}>{message}</p>
        ) : (
          <div className={styles.chartBody}>
            <Donut
              label="Approval coverage"
              total={total}
              value={`${approvedPercent}%`}
              caption="approved"
              segments={[
                { label: "Approved", count: approved, color: "#267245" },
                {
                  label: "Not approved",
                  count: total - approved,
                  color: "#d9dee2",
                },
              ]}
            />
            <div className={styles.approvalCopy}>
              <strong>
                {approved} of {total}
              </strong>
              <span>assessments approved</span>
              <span>
                {total
                  ? `${total - approved} not approved`
                  : "No assessments yet"}
              </span>
            </div>
          </div>
        )}
      </article>
      <article className={styles.summaryCard}>
        <header>
          <Route size={16} aria-hidden="true" />
          <h2>Migration paths</h2>
        </header>
        <p>Source → destination · assessment count</p>
        {unavailable ? (
          <p className={styles.metricState}>{message}</p>
        ) : paths.length ? (
          <div className={styles.chartBody}>
            <Donut
              label="Migration paths"
              total={pathTotal}
              value={pathTotal}
              caption="assessments"
              segments={pathSegments}
            />
            <ul className={styles.paths} aria-label="Migration path counts">
              {paths.map((item, index) => (
                <li key={item.path} className={styles.path}>
                  <span
                    className={styles.swatch}
                    style={{ background: pathSegments[index].color }}
                    aria-hidden="true"
                  />
                  <div className={styles.pathLabel}>
                    <PlatformIcon
                      size="summary"
                      platform={item.sourcePlatform}
                    />
                    <span>
                      {item.sourcePlatform.replaceAll("_", " ").toLowerCase()}
                    </span>
                    <ArrowRight size={12} aria-hidden="true" />
                    <PlatformIcon
                      size="summary"
                      platform={item.targetPlatform}
                    />
                    <span>
                      {item.targetPlatform.replaceAll("_", " ").toLowerCase()}
                    </span>
                  </div>
                  <strong>{item.count}</strong>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className={styles.metricState}>No migration paths yet.</p>
        )}
      </article>
    </section>
  );
}
