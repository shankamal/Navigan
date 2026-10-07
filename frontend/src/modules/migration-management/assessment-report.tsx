import {
  AlertOctagon,
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  CircleHelp,
  ClipboardCheck,
  Cloud,
  Server,
  WandSparkles,
  Wrench,
} from "lucide-react";

import type { Assessment } from "./model";

type Finding = Assessment["findings"][number];
type Disposition = Finding["disposition"];

const classifications = [
  {
    code: "SEAMLESS" as const,
    label: "Ready as-is",
    note: "No changes required",
    icon: CheckCircle2,
  },
  {
    code: "AUTOMATED_CHANGE" as const,
    label: "Auto-fix available",
    note: "Navigan can translate",
    icon: WandSparkles,
  },
  {
    code: "MANUAL_CHANGE" as const,
    label: "Manual action",
    note: "Engineering review needed",
    icon: Wrench,
  },
  {
    code: "BLOCKER" as const,
    label: "Blocked",
    note: "Must resolve first",
    icon: AlertOctagon,
  },
];

const dispositionDetails: Record<
  Disposition,
  { label: string; explanation: string; icon: typeof CheckCircle2 }
> = {
  SEAMLESS: {
    label: "Ready as-is",
    explanation: "These resources can move without compatibility changes.",
    icon: CheckCircle2,
  },
  AUTOMATED_CHANGE: {
    label: "Automated changes",
    explanation:
      "Navigan can generate the required target-specific translation.",
    icon: WandSparkles,
  },
  MANUAL_CHANGE: {
    label: "Manual changes",
    explanation: "An engineer must review and complete these changes.",
    icon: Wrench,
  },
  BLOCKER: {
    label: "Blockers",
    explanation: "Resolve these items before migration can be approved.",
    icon: AlertTriangle,
  },
};

function findingKey(finding: Finding, index: number) {
  return [
    finding.code,
    finding.namespace ?? "cluster",
    finding.resourceKind ?? finding.category,
    finding.resourceName ?? "unnamed",
    index,
  ].join("-");
}

function readableStatus(status: string) {
  return status.replaceAll("_", " ").toLowerCase();
}

function reportDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? value
    : new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
}

export function AssessmentReportCard({ report }: { report: Assessment }) {
  const target = report.inventorySummary.target;
  const resourceKinds = Object.entries(
    report.inventorySummary.resourceKinds,
  ).sort((left, right) => right[1] - left[1]);
  const blockerCount = report.inventorySummary.classification.BLOCKER;
  const changeCount =
    report.inventorySummary.classification.AUTOMATED_CHANGE +
    report.inventorySummary.classification.MANUAL_CHANGE;
  const verdict = report.containsBlockers
    ? "Requires remediation"
    : changeCount > 0
      ? "Conditionally feasible"
      : "Ready to migrate";
  const orderedClassifications = [...classifications].reverse();
  const firstVisibleDisposition = orderedClassifications.find(
    (classification) =>
      report.findings.some(
        (finding) => finding.disposition === classification.code,
      ),
  )?.code;

  return (
    <section
      className="panel migration-report"
      aria-labelledby="assessment-report-title"
    >
      <header className="migration-report-header">
        <div>
          <span className="eyebrow">MIGRATION FEASIBILITY REPORT</span>
          <h2 id="assessment-report-title">Migration feasibility report</h2>
          <p>
            What can move to{" "}
            <strong>{target.clusterName ?? "the selected EKS target"}</strong>,
            what needs adjustment, and what must be resolved.
          </p>
          <div className="migration-report-route">
            <span>
              <Server size={16} aria-hidden="true" />
              Kubernetes {report.sourceKubernetesVersion}
            </span>
            <ArrowRight size={16} aria-hidden="true" />
            <span>
              <Cloud size={16} aria-hidden="true" />
              {target.clusterName ?? "Amazon EKS"}
            </span>
          </div>
        </div>
        <div className="migration-report-date">
          Report generated
          <strong>{reportDate(report.createdAt)}</strong>
        </div>
      </header>

      <div className="migration-verdict-grid">
        <div className="migration-verdict">
          <span>Executive verdict</span>
          <strong
            className={
              report.containsBlockers
                ? "migration-verdict-blocked"
                : "migration-verdict-feasible"
            }
          >
            {verdict}
          </strong>
          <small>
            {report.containsBlockers
              ? `${blockerCount} blocker${blockerCount === 1 ? "" : "s"} must be resolved`
              : "No critical compatibility blockers found"}
          </small>
        </div>
        <div className="migration-score" aria-label="Compatibility score">
          <span>Compatibility score</span>
          <strong>
            {report.compatibilityScore}
            <small>/100</small>
          </strong>
          <div aria-hidden="true">
            <span style={{ width: `${report.compatibilityScore}%` }} />
          </div>
        </div>
        <div className="migration-verdict-stat">
          <span>Resources assessed</span>
          <strong>{report.inventorySummary.resourceCount}</strong>
          <small>{resourceKinds.length} Kubernetes resource types</small>
        </div>
        <div className="migration-verdict-stat">
          <span>Changes required</span>
          <strong>{changeCount}</strong>
          <small>Automated and manual actions</small>
        </div>
        <div className="migration-verdict-stat">
          <span>Target readiness</span>
          <strong className="migration-target-ready">
            {readableStatus(target.status)}
          </strong>
          <small>
            {target.readyNodeCount != null && target.nodeCount != null
              ? `${target.readyNodeCount} of ${target.nodeCount} nodes ready`
              : "Target cluster verified"}
          </small>
        </div>
      </div>

      <div className="migration-report-body">
        <main>
          <section className="migration-classification-section">
            <div className="migration-section-heading">
              <div>
                <h3>Assessment summary</h3>
                <p>Resources grouped by the action needed before migration.</p>
              </div>
            </div>
            <div className="migration-classification-grid">
              {classifications.map((item) => {
                const Icon = item.icon;
                const count = report.inventorySummary.classification[item.code];
                return (
                  <article
                    className={`migration-classification migration-classification-${item.code.toLowerCase()}`}
                    key={item.code}
                  >
                    <Icon size={21} aria-hidden="true" />
                    <div>
                      <strong>{count}</strong>
                      <span>{item.label}</span>
                      <small>{item.note}</small>
                    </div>
                  </article>
                );
              })}
            </div>
          </section>

          <section className="migration-findings-section">
            <div className="migration-section-heading">
              <div>
                <h3>Compatibility findings</h3>
                <p>
                  Start with blockers, then work through manual and automated
                  changes.
                </p>
              </div>
              <span>
                {report.findings.length} finding
                {report.findings.length === 1 ? "" : "s"}
              </span>
            </div>

            {report.findings.length === 0 ? (
              <div className="migration-report-empty">
                <CheckCircle2 size={32} aria-hidden="true" />
                <div>
                  <h3>No compatibility changes identified</h3>
                  <p>
                    All assessed resources match the current portability rules.
                  </p>
                </div>
              </div>
            ) : (
              <div className="migration-finding-groups">
                {orderedClassifications.map((classification) => {
                  const findings = report.findings.filter(
                    (finding) => finding.disposition === classification.code,
                  );
                  if (findings.length === 0) return null;

                  const details = dispositionDetails[classification.code];
                  const GroupIcon = details.icon;
                  return (
                    <details
                      className={`migration-finding-group migration-finding-group-${classification.code.toLowerCase()}`}
                      key={classification.code}
                      open={classification.code === firstVisibleDisposition}
                    >
                      <summary>
                        <GroupIcon size={19} aria-hidden="true" />
                        <div>
                          <h4>
                            {details.label} <span>{findings.length}</span>
                          </h4>
                          <p>{details.explanation}</p>
                        </div>
                      </summary>
                      <div className="migration-finding-list">
                        {findings.map((finding, index) => (
                          <article
                            key={findingKey(finding, index)}
                            className="migration-finding"
                          >
                            <div className="migration-finding-description">
                              <div>
                                <span
                                  className={`migration-severity migration-severity-${finding.severity.toLowerCase()}`}
                                >
                                  {finding.severity}
                                </span>
                                <span>
                                  {finding.category.replaceAll("_", " ")}
                                </span>
                              </div>
                              <h5>{finding.message}</h5>
                              <p>
                                {finding.namespace && (
                                  <span>Namespace: {finding.namespace}</span>
                                )}
                                {finding.resourceKind && (
                                  <span>Type: {finding.resourceKind}</span>
                                )}
                                {finding.resourceName && (
                                  <span>Resource: {finding.resourceName}</span>
                                )}
                              </p>
                            </div>
                            <div className="migration-finding-action">
                              <span>
                                <ClipboardCheck size={16} aria-hidden="true" />
                                Recommended action
                              </span>
                              <p>
                                {finding.remediation ??
                                  "Review this resource before migration planning."}
                              </p>
                            </div>
                          </article>
                        ))}
                      </div>
                    </details>
                  );
                })}
              </div>
            )}
          </section>
        </main>

        <aside className="migration-report-sidebar">
          <section>
            <h3>Target cluster</h3>
            <dl>
              <div>
                <dt>Name</dt>
                <dd>{target.clusterName ?? "Amazon EKS"}</dd>
              </div>
              <div>
                <dt>Status</dt>
                <dd>{readableStatus(target.status)}</dd>
              </div>
              <div>
                <dt>Ready nodes</dt>
                <dd>
                  {target.readyNodeCount ?? "—"} / {target.nodeCount ?? "—"}
                </dd>
              </div>
            </dl>
          </section>

          <section>
            <h3>Inventory coverage</h3>
            <div className="migration-resource-list">
              {resourceKinds.map(([kind, count]) => (
                <div key={kind}>
                  <span>{kind}</span>
                  <strong>{count}</strong>
                </div>
              ))}
            </div>
          </section>

          <section>
            <h3>Report evidence</h3>
            <dl>
              <div>
                <dt>Assessment version</dt>
                <dd>v{report.assessmentVersion}</dd>
              </div>
              <div>
                <dt>Migration version</dt>
                <dd>v{report.migrationVersion}</dd>
              </div>
              <div>
                <dt>Inventory hash</dt>
                <dd title={report.inventoryDigest}>
                  {report.inventoryDigest.slice(0, 12)}…
                </dd>
              </div>
              <div>
                <dt>Generated by</dt>
                <dd>{report.createdBy.replaceAll("_", " ").toLowerCase()}</dd>
              </div>
            </dl>
          </section>

          <section className="migration-report-help">
            <CircleHelp size={20} aria-hidden="true" />
            <div>
              <h3>How to read this report</h3>
              <p>
                “Ready as-is” can move directly. Automated and manual changes
                need remediation. Blockers prevent approval.
              </p>
            </div>
          </section>
        </aside>
      </div>
    </section>
  );
}
