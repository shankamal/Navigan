import {
  AlertTriangle,
  CheckCircle2,
  CircleHelp,
  WandSparkles,
} from "lucide-react";

import type { Assessment } from "./model";

const classifications = [
  {
    code: "SEAMLESS" as const,
    label: "Seamless",
    icon: CheckCircle2,
  },
  {
    code: "AUTOMATED_CHANGE" as const,
    label: "Automated changes",
    icon: WandSparkles,
  },
  {
    code: "MANUAL_CHANGE" as const,
    label: "Manual changes",
    icon: CircleHelp,
  },
  {
    code: "BLOCKER" as const,
    label: "Blockers",
    icon: AlertTriangle,
  },
];

export function AssessmentReportCard({ report }: { report: Assessment }) {
  return (
    <section className="panel" aria-labelledby="assessment-report-title">
      <div className="list-heading">
        <div>
          <span className="eyebrow">FEASIBILITY REPORT</span>
          <h2 id="assessment-report-title">Migration feasibility report</h2>
          <p className="muted">
            Trusted analysis against{" "}
            {report.inventorySummary.target.clusterName ??
              "the selected EKS target"}
            .
          </p>
        </div>
        <strong aria-label="Compatibility score">
          {report.compatibilityScore}/100
        </strong>
      </div>

      <div className="metrics-grid">
        {classifications.map((item) => {
          const Icon = item.icon;
          return (
            <div className="metric" key={item.code}>
              <div className="metric-label">
                {item.label}
                <Icon size={19} aria-hidden="true" />
              </div>
              <strong>
                {report.inventorySummary.classification[item.code]}
              </strong>
              <p>Discovered resources</p>
            </div>
          );
        })}
      </div>

      <div className="list-heading">
        <div>
          <h3>Assessment summary</h3>
          <p className="muted">
            {report.inventorySummary.resourceCount} resources assessed · target
            status {report.inventorySummary.target.status}
          </p>
        </div>
        <span className="status-badge">
          {report.containsBlockers
            ? "Action required"
            : "Feasible with recommendations"}
        </span>
      </div>

      {report.findings.length === 0 ? (
        <div className="empty-state">
          <CheckCircle2 size={30} aria-hidden="true" />
          <h3>No compatibility changes identified</h3>
          <p>All resources match the current EKS portability rules.</p>
        </div>
      ) : (
        <div>
          {report.findings.map((finding, index) => (
            <article
              key={`${finding.code}-${finding.resourceName ?? index}`}
              className="list-row"
            >
              <div>
                <strong>{finding.message}</strong>
                <p className="muted">
                  {finding.resourceKind ?? finding.category}
                  {finding.namespace ? ` · ${finding.namespace}` : ""}
                  {finding.resourceName ? ` · ${finding.resourceName}` : ""}
                </p>
                {finding.remediation && <p>{finding.remediation}</p>}
              </div>
              <span className="status-badge">
                {finding.disposition.replaceAll("_", " ")}
              </span>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
