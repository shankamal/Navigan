import {
  AlertOctagon,
  AlertTriangle,
  CalendarDays,
  CheckCircle2,
  CircleHelp,
  ClipboardCheck,
  Database,
  FileText,
  Network,
  Server,
  ShieldCheck,
  UserRound,
  WandSparkles,
  Wrench,
} from "lucide-react";
import { useMemo, useState } from "react";

import type {
  Assessment,
  SourceInventory,
  SourceInventoryResource,
} from "./model";

type Finding = Assessment["findings"][number];
type Disposition = Finding["disposition"];
type ReportTab =
  | "summary"
  | "advanced"
  | "coverage"
  | "findings"
  | "cluster"
  | "configuration"
  | "workloads"
  | "networking"
  | "storage"
  | "scaling"
  | "images"
  | "extensions"
  | "evidence";

type SourceSummary = {
  name?: string | null;
  nodeCount?: number | null;
  namespaceCount?: number | null;
  namespaces?: string[];
  architectures?: string[];
};

type AdvancedReadinessStatus = "complete" | "review" | "not-detected";

type AdvancedReadinessCheck = {
  id: string;
  title: string;
  description: string;
  status: AdvancedReadinessStatus;
  statusLabel: string;
  evidence: string[];
  nextAction: string;
  icon: typeof CheckCircle2;
};

const classifications = [
  {
    code: "SEAMLESS" as const,
    label: "Ready",
    note: "Can migrate directly",
    color: "#74b816",
    icon: CheckCircle2,
  },
  {
    code: "AUTOMATED_CHANGE" as const,
    label: "Automated",
    note: "Navigan can translate",
    color: "#3984d6",
    icon: WandSparkles,
  },
  {
    code: "MANUAL_CHANGE" as const,
    label: "Remediate",
    note: "Engineering action",
    color: "#efa914",
    icon: Wrench,
  },
  {
    code: "BLOCKER" as const,
    label: "Blocked",
    note: "Must resolve first",
    color: "#df4a4a",
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

function reportDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? value
    : new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
}

function pieGradient(
  segments: Array<{ value: number; color: string }>,
  total: number,
) {
  if (total <= 0) return "conic-gradient(#e4e9e2 0 100%)";

  let cursor = 0;
  const stops = segments
    .filter((segment) => segment.value > 0)
    .map((segment) => {
      const start = cursor;
      cursor += (segment.value / total) * 100;
      return `${segment.color} ${start}% ${cursor}%`;
    });

  return `conic-gradient(${stops.join(", ")})`;
}

function DonutChart({
  value,
  label,
  background,
  ariaLabel,
}: {
  value: string | number;
  label: string;
  background: string;
  ariaLabel: string;
}) {
  return (
    <div className="migration-donut-block">
      <div
        className="migration-donut"
        style={{ background }}
        role="img"
        aria-label={ariaLabel}
      >
        <span>{value}</span>
      </div>
      <strong>{label}</strong>
    </div>
  );
}

function severityIcon(category: string) {
  const normalized = category.toUpperCase();
  if (normalized.includes("STORAGE")) return Database;
  if (normalized.includes("NETWORK")) return Network;
  if (normalized.includes("SECURITY")) return ShieldCheck;
  return Server;
}

function findingOwner(finding: Finding) {
  if (finding.owner || finding.ownerTeam)
    return finding.owner ?? finding.ownerTeam ?? "Unassigned";

  const category = finding.category.toUpperCase();
  if (category.includes("STORAGE")) return "Data platform";
  if (category.includes("NETWORK")) return "Networking";
  if (category.includes("SECURITY")) return "Platform security";
  return "Unassigned";
}

function findingStatus(finding: Finding) {
  if (finding.remediationStatus) return finding.remediationStatus;
  if (finding.disposition === "SEAMLESS") return "Ready";
  if (finding.disposition === "AUTOMATED_CHANGE") return "Automated";
  return "Open";
}

const inventoryTabs: Array<{
  id: ReportTab;
  label: string;
  icon: typeof CheckCircle2;
  kinds?: string[];
}> = [
  { id: "summary", label: "Summary", icon: FileText },
  {
    id: "advanced",
    label: "Advanced readiness",
    icon: WandSparkles,
  },
  { id: "coverage", label: "Inventory coverage", icon: Database },
  { id: "findings", label: "Findings", icon: AlertTriangle },
  {
    id: "cluster",
    label: "Nodes & namespaces",
    icon: Server,
    kinds: ["Node", "Namespace"],
  },
  {
    id: "configuration",
    label: "Configuration & secrets",
    icon: ClipboardCheck,
    kinds: ["ConfigMap", "Secret"],
  },
  {
    id: "workloads",
    label: "Workloads",
    icon: Server,
    kinds: ["Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"],
  },
  {
    id: "networking",
    label: "Networking",
    icon: Network,
    kinds: ["Service", "Ingress", "NetworkPolicy"],
  },
  {
    id: "storage",
    label: "Storage",
    icon: Database,
    kinds: ["PersistentVolumeClaim", "StorageClass"],
  },
  {
    id: "scaling",
    label: "Scaling & resilience",
    icon: Wrench,
    kinds: ["HorizontalPodAutoscaler", "PodDisruptionBudget"],
  },
  {
    id: "images",
    label: "Images & security",
    icon: ShieldCheck,
    kinds: ["Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"],
  },
  {
    id: "extensions",
    label: "Extensions & access",
    icon: UserRound,
    kinds: [
      "CustomResourceDefinition",
      "ServiceAccount",
      "Role",
      "RoleBinding",
      "ClusterRole",
      "ClusterRoleBinding",
      "MutatingWebhookConfiguration",
      "ValidatingWebhookConfiguration",
    ],
  },
  { id: "evidence", label: "Evidence", icon: CheckCircle2 },
];

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function resourceContainers(resource: SourceInventoryResource) {
  const pod = objectValue(resource.pod);
  return [...arrayValue(pod.containers), ...arrayValue(pod.initContainers)].map(
    objectValue,
  );
}

function metadataKeys(resource: SourceInventoryResource) {
  return [
    ...arrayValue(resource.annotationKeys),
    ...arrayValue(resource.labelKeys),
  ].filter((value): value is string => typeof value === "string");
}

function countResources(resources: SourceInventoryResource[], kinds: string[]) {
  const acceptedKinds = new Set(kinds);
  return resources.filter((resource) => acceptedKinds.has(resource.kind))
    .length;
}

function advancedReadinessChecks(
  resources: SourceInventoryResource[],
  findings: Finding[],
  source?: SourceSummary,
): AdvancedReadinessCheck[] {
  const workloads = resources.filter((resource) =>
    ["Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"].includes(
      resource.kind,
    ),
  );
  const containers = workloads.flatMap(resourceContainers);
  const images = containers
    .map((container) => container.image)
    .filter((value): value is string => typeof value === "string" && !!value);
  const immutableImages = images.filter((image) => image.includes("@sha256:"));
  const resourceProfiles = containers.filter((container) => {
    const resourcesValue = objectValue(container.resources);
    return (
      Object.keys(objectValue(resourcesValue.requests)).length > 0 ||
      Object.keys(objectValue(resourcesValue.limits)).length > 0
    );
  });
  const provenanceMarkers = resources.filter((resource) =>
    metadataKeys(resource).some((key) =>
      /(helm|argocd|fluxcd|gitops|kustomize)/i.test(key),
    ),
  );
  const dependencyReferences = containers.reduce(
    (total, container) =>
      total +
      arrayValue(container.environment).filter((item) => {
        const sourceType = objectValue(item).source;
        return (
          typeof sourceType === "string" &&
          sourceType !== "LITERAL" &&
          sourceType !== "fieldRef" &&
          sourceType !== "resourceFieldRef"
        );
      }).length,
    0,
  );
  const dependencyFindings = findings.filter(
    (finding) =>
      finding.category.toUpperCase().includes("DEPEND") ||
      finding.dependencies?.length,
  ).length;
  const addOnCount = countResources(resources, [
    "CustomResourceDefinition",
    "MutatingWebhookConfiguration",
    "ValidatingWebhookConfiguration",
    "StorageClass",
  ]);
  const accessCount = countResources(resources, [
    "ServiceAccount",
    "Role",
    "RoleBinding",
    "ClusterRole",
    "ClusterRoleBinding",
  ]);
  const privilegedContainers = containers.filter(
    (container) => objectValue(container.security).privileged === true,
  ).length;
  const pvcCount = countResources(resources, ["PersistentVolumeClaim"]);
  const statefulCount = countResources(resources, ["StatefulSet"]);
  const schedulingProfiles = workloads.filter((resource) => {
    const pod = objectValue(resource.pod);
    return (
      arrayValue(pod.tolerations).length > 0 ||
      Object.keys(objectValue(pod.affinity)).length > 0 ||
      arrayValue(pod.topologySpreadConstraints).length > 0 ||
      arrayValue(pod.nodeSelectorKeys).length > 0
    );
  }).length;

  return [
    {
      id: "provenance",
      title: "Helm & GitOps provenance",
      description:
        "Identifies deployment ownership markers without collecting repository credentials or values.",
      status: provenanceMarkers.length > 0 ? "complete" : "not-detected",
      statusLabel:
        provenanceMarkers.length > 0
          ? `${provenanceMarkers.length} resources detected`
          : "No markers detected",
      evidence: [
        `${provenanceMarkers.length} resources contain Helm, Argo CD, Flux or Kustomize metadata`,
        "Repository credentials and Helm values remain excluded",
      ],
      nextAction:
        provenanceMarkers.length > 0
          ? "Confirm the detected release or GitOps owner before artifact collection."
          : "Record the chart or Git repository manually when the application is managed outside the cluster.",
      icon: FileText,
    },
    {
      id: "images",
      title: "Container image portability",
      description:
        "Checks image references, immutable digests and source node architecture for target portability.",
      status:
        images.length > 0 && immutableImages.length === images.length
          ? "complete"
          : "review",
      statusLabel:
        images.length === 0
          ? "No image references"
          : `${immutableImages.length}/${images.length} digest pinned`,
      evidence: [
        `${images.length} container image references across ${workloads.length} workloads`,
        `Source architecture: ${source?.architectures?.join(", ") || "not reported"}`,
      ],
      nextAction:
        immutableImages.length === images.length && images.length > 0
          ? "Validate target registry access and retain the immutable digests."
          : "Resolve image tags to immutable digests and verify target registry access.",
      icon: Server,
    },
    {
      id: "capacity",
      title: "Capacity & scheduling",
      description:
        "Reviews declared compute profiles and Kubernetes scheduling constraints used for target sizing.",
      status:
        containers.length > 0 && resourceProfiles.length === containers.length
          ? "complete"
          : "review",
      statusLabel: `${resourceProfiles.length}/${containers.length} containers sized`,
      evidence: [
        `${schedulingProfiles}/${workloads.length} workloads declare scheduling constraints`,
        "Declared requests and limits are shown; live utilization requires a metrics integration",
      ],
      nextAction:
        resourceProfiles.length === containers.length
          ? "Compare declared capacity with target node groups before migration planning."
          : "Add missing CPU and memory requests/limits, then compare them with observed utilization.",
      icon: WandSparkles,
    },
    {
      id: "dependencies",
      title: "Application dependencies",
      description:
        "Surfaces configuration references and assessment findings that can indicate application dependencies.",
      status:
        dependencyReferences + dependencyFindings > 0
          ? "review"
          : "not-detected",
      statusLabel: `${dependencyReferences + dependencyFindings} signals`,
      evidence: [
        `${dependencyReferences} Secret or ConfigMap references`,
        `${dependencyFindings} dependency-related findings`,
      ],
      nextAction:
        "Confirm external databases, DNS, certificates, queues and APIs with the application owner.",
      icon: Network,
    },
    {
      id: "platform",
      title: "Platform add-ons & extensions",
      description:
        "Reviews cluster extensions that commonly require an EKS-specific replacement or configuration.",
      status: addOnCount > 0 ? "review" : "not-detected",
      statusLabel: `${addOnCount} extensions detected`,
      evidence: [
        `${countResources(resources, ["CustomResourceDefinition"])} CRD definitions`,
        `${countResources(resources, ["MutatingWebhookConfiguration", "ValidatingWebhookConfiguration"])} admission webhooks`,
        `${countResources(resources, ["StorageClass"])} storage classes`,
      ],
      nextAction:
        "Validate CNI, CSI, ingress controllers, operators and admission webhooks against the EKS target.",
      icon: Wrench,
    },
    {
      id: "identity",
      title: "Identity & workload security",
      description:
        "Summarizes Kubernetes identities and security-context signals needed for EKS IAM planning.",
      status:
        accessCount > 0 && privilegedContainers === 0 ? "complete" : "review",
      statusLabel:
        privilegedContainers > 0
          ? `${privilegedContainers} privileged containers`
          : `${accessCount} access resources`,
      evidence: [
        `${accessCount} service-account and RBAC resources`,
        `${privilegedContainers} privileged containers detected`,
      ],
      nextAction:
        "Map service accounts to approved EKS Pod Identity or IAM roles and review privileged workloads.",
      icon: ShieldCheck,
    },
    {
      id: "data",
      title: "Persistent data protection",
      description:
        "Identifies stateful workloads and claims that require an approved backup, restore and cutover plan.",
      status: pvcCount + statefulCount > 0 ? "review" : "complete",
      statusLabel:
        pvcCount + statefulCount > 0
          ? `${pvcCount} claims · ${statefulCount} stateful sets`
          : "No persistent workloads",
      evidence: [
        `${pvcCount} persistent volume claims`,
        `${statefulCount} StatefulSets`,
      ],
      nextAction:
        pvcCount + statefulCount > 0
          ? "Document storage mapping, backup validation, RPO/RTO and rollback before artifact collection."
          : "No data-transfer plan is required for the currently selected scope.",
      icon: Database,
    },
  ];
}

function inventoryValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "string" || typeof value === "number")
    return String(value);
  if (Array.isArray(value)) {
    if (value.length === 0) return "None";
    if (value.every((item) => ["string", "number"].includes(typeof item))) {
      return value.join(", ");
    }
    return `${value.length} item${value.length === 1 ? "" : "s"}`;
  }
  return `${Object.keys(value as Record<string, unknown>).length} fields`;
}

function ResourceDetails({ resource }: { resource: SourceInventoryResource }) {
  const entries = Object.entries(resource).filter(
    ([key]) => !["apiVersion", "kind", "namespace", "name"].includes(key),
  );
  return (
    <details className="migration-inventory-resource">
      <summary>
        <span className="migration-inventory-kind">{resource.kind}</span>
        <strong>{resource.name ?? "Cluster-level resource"}</strong>
        <span>{resource.namespace ?? "Cluster scoped"}</span>
        <span>{resource.apiVersion}</span>
      </summary>
      <div className="migration-inventory-detail-grid">
        {entries.map(([key, value]) => (
          <div key={key}>
            <dt>{key.replaceAll(/([A-Z])/g, " $1")}</dt>
            <dd>{inventoryValue(value)}</dd>
            {typeof value === "object" &&
              value !== null &&
              (Array.isArray(value)
                ? value.some((item) => typeof item === "object")
                : true) && <pre>{JSON.stringify(value, null, 2)}</pre>}
          </div>
        ))}
      </div>
    </details>
  );
}

function InventoryPanel({
  title,
  description,
  resources,
  loading,
  error,
}: {
  title: string;
  description: string;
  resources: SourceInventoryResource[];
  loading?: boolean;
  error?: boolean;
}) {
  return (
    <section className="migration-inventory-panel">
      <div className="migration-section-heading">
        <div>
          <h3>{title}</h3>
          <p>{description}</p>
        </div>
        <span>{resources.length} resources</span>
      </div>
      {loading && (
        <p className="migration-inventory-state">Loading inventory…</p>
      )}
      {error && (
        <p className="migration-inventory-state" role="alert">
          Detailed inventory could not be loaded.
        </p>
      )}
      {!loading && !error && resources.length === 0 && (
        <p className="migration-inventory-state">
          No resources of this type were found in the selected scope.
        </p>
      )}
      {resources.length > 0 && (
        <div className="migration-inventory-list">
          <div className="migration-inventory-list-header">
            <span>Type</span>
            <span>Resource</span>
            <span>Namespace</span>
            <span>API version</span>
          </div>
          {resources.map((resource, index) => (
            <ResourceDetails
              resource={resource}
              key={`${resource.kind}-${resource.namespace ?? "cluster"}-${resource.name ?? index}`}
            />
          ))}
        </div>
      )}
    </section>
  );
}

export function AssessmentReportCard({
  report,
  inventory,
  inventoryLoading,
  inventoryError,
  source,
  governance,
}: {
  report: Assessment;
  inventory?: SourceInventory | null;
  inventoryLoading?: boolean;
  inventoryError?: boolean;
  source?: SourceSummary;
  governance?: {
    status?: string;
  };
}) {
  const [activeTab, setActiveTab] = useState<ReportTab>("summary");
  const target = report.inventorySummary.target;
  const resourceKinds = Object.entries(
    report.inventorySummary.resourceKinds,
  ).sort((left, right) => right[1] - left[1]);
  const classification = report.inventorySummary.classification;
  const assessedCount =
    classification.SEAMLESS +
    classification.AUTOMATED_CHANGE +
    classification.MANUAL_CHANGE +
    classification.BLOCKER;
  const blockedResourceCount = classification.BLOCKER;
  const changeCount =
    classification.AUTOMATED_CHANGE + classification.MANUAL_CHANGE;
  const mappedCount = assessedCount - blockedResourceCount;
  const mappingCoverage =
    assessedCount > 0 ? Math.round((mappedCount / assessedCount) * 100) : 0;
  const severityCounts = report.findings.reduce(
    (counts, finding) => {
      counts[finding.severity] += 1;
      return counts;
    },
    { INFO: 0, WARNING: 0, BLOCKER: 0 },
  );
  const criticalFindingCount = severityCounts.BLOCKER;
  const hasCriticalFindings = criticalFindingCount > 0;
  const orderedClassifications = [...classifications].reverse();
  const firstVisibleDisposition = orderedClassifications.find((item) =>
    report.findings.some((finding) => finding.disposition === item.code),
  )?.code;
  const priorityFindings = [...report.findings]
    .sort((left, right) => {
      const rank = { BLOCKER: 3, WARNING: 2, INFO: 1 };
      return rank[right.severity] - rank[left.severity];
    })
    .slice(0, 4);
  const evidenceCount = report.findings.reduce(
    (total, finding) =>
      total +
      (finding.evidenceCount ??
        finding.evidenceReferences?.length ??
        (finding.resourceName || finding.namespace ? 1 : 0)),
    0,
  );
  const policyChecks = [
    {
      label: "Compatibility rules",
      value:
        criticalFindingCount > 0
          ? `${criticalFindingCount} critical`
          : "Passed",
    },
    {
      label: "Target mapping",
      value:
        mappingCoverage === 100 ? "Complete" : `${mappingCoverage}% complete`,
    },
    ...Object.entries(report.governance?.policyChecks ?? {}).map(
      ([label, value]) => ({
        label: label.replaceAll("_", " "),
        value,
      }),
    ),
  ];
  const approvalConditions = report.governance?.approvalConditions ?? [
    ...(criticalFindingCount > 0
      ? [`Resolve all critical findings (${criticalFindingCount} remaining)`]
      : []),
    ...(classification.MANUAL_CHANGE > 0
      ? [
          `Assign owners for ${classification.MANUAL_CHANGE} manual remediation items`,
        ]
      : []),
    ...(mappedCount < assessedCount
      ? ["Complete target mapping for all assessed resources"]
      : []),
    "Complete independent architecture review",
  ];
  const inventoryResources = inventory?.resources ?? [];
  const inventoryCountForKinds = (kinds: string[] | undefined) =>
    kinds?.reduce(
      (total, kind) =>
        total + (report.inventorySummary.resourceKinds[kind] ?? 0),
      0,
    );
  const activeInventoryTab = inventoryTabs.find((tab) => tab.id === activeTab);
  const visibleInventory = useMemo(() => {
    if (!activeInventoryTab?.kinds) return inventoryResources;
    const kinds = new Set(activeInventoryTab.kinds);
    return inventoryResources.filter((resource) => kinds.has(resource.kind));
  }, [activeInventoryTab, inventoryResources]);
  const advancedChecks = useMemo(
    () => advancedReadinessChecks(inventoryResources, report.findings, source),
    [inventoryResources, report.findings, source],
  );
  const advancedCompleteCount = advancedChecks.filter(
    (check) => check.status === "complete",
  ).length;
  const advancedReviewCount = advancedChecks.filter(
    (check) => check.status === "review",
  ).length;
  const advancedNotDetectedCount = advancedChecks.filter(
    (check) => check.status === "not-detected",
  ).length;

  return (
    <section
      className="migration-report migration-report-workspace"
      aria-labelledby="assessment-report-title"
    >
      <h2 id="assessment-report-title" className="visually-hidden">
        Migration feasibility overview
      </h2>

      <div
        className={`migration-decision-banner ${
          hasCriticalFindings
            ? "migration-decision-banner-blocked"
            : "migration-decision-banner-ready"
        }`}
      >
        <div className="migration-decision-icon" aria-hidden="true">
          {hasCriticalFindings ? (
            <AlertOctagon size={28} />
          ) : (
            <CheckCircle2 size={28} />
          )}
        </div>
        <div className="migration-decision-copy">
          <span>
            {hasCriticalFindings ? "Action required" : "Ready for review"}
          </span>
          <h3>
            {hasCriticalFindings
              ? "Approval requires remediation"
              : "Migration assessment is ready"}
          </h3>
          <p>
            {criticalFindingCount > 0
              ? `Approval is blocked by ${criticalFindingCount} critical finding${criticalFindingCount === 1 ? "" : "s"}. Resolve the blocker and review ${changeCount} additional remediation item${changeCount === 1 ? "" : "s"} before approval.`
              : changeCount > 0
                ? `${changeCount} planned remediation item${changeCount === 1 ? "" : "s"} should be assigned before migration planning.`
                : `${mappedCount} assessed resources have supported target treatments.`}
          </p>
        </div>
        <DonutChart
          value={`${report.compatibilityScore}%`}
          label="Compatibility"
          background={pieGradient(
            [
              {
                value: report.compatibilityScore,
                color: hasCriticalFindings ? "#df4a4a" : "#74b816",
              },
              {
                value: 100 - report.compatibilityScore,
                color: "#e5e9e4",
              },
            ],
            100,
          )}
          ariaLabel={`Compatibility score ${report.compatibilityScore} out of 100`}
        />
        <div className="migration-decision-summary">
          <div>
            <i className="migration-dot-critical" />
            <span>{criticalFindingCount} critical</span>
          </div>
          <div>
            <i className="migration-dot-warning" />
            <span>{classification.MANUAL_CHANGE} remediation</span>
          </div>
          <div>
            <i className="migration-dot-automated" />
            <span>{classification.AUTOMATED_CHANGE} automated</span>
          </div>
        </div>
      </div>

      <div className="migration-kpi-strip" aria-label="Assessment summary">
        {[
          {
            label: "Assessed",
            value: assessedCount,
            icon: ClipboardCheck,
            tone: "neutral",
          },
          {
            label: "Ready",
            value: classification.SEAMLESS,
            icon: CheckCircle2,
            tone: "ready",
          },
          {
            label: "Automated",
            value: classification.AUTOMATED_CHANGE,
            icon: WandSparkles,
            tone: "automated",
          },
          {
            label: "Remediation",
            value: classification.MANUAL_CHANGE,
            icon: Wrench,
            tone: "warning",
          },
          {
            label: "Critical",
            value: criticalFindingCount,
            icon: AlertOctagon,
            tone: "critical",
          },
          {
            label: "Mapped",
            value: mappedCount,
            icon: Server,
            tone: "ready",
          },
          {
            label: "Unresolved",
            value: assessedCount - mappedCount,
            icon: CircleHelp,
            tone: "critical",
          },
        ].map((item) => {
          const MetricIcon = item.icon;
          return (
            <div
              className={`migration-kpi migration-kpi-${item.tone}`}
              key={item.label}
            >
              <MetricIcon size={20} aria-hidden="true" />
              <div>
                <strong>{item.value}</strong>
                <span>{item.label}</span>
              </div>
            </div>
          );
        })}
      </div>

      <nav
        className="migration-report-tabs"
        aria-label="Report sections"
        role="tablist"
      >
        {inventoryTabs.map((tab) => {
          const TabIcon = tab.icon;
          const countLabel =
            tab.id === "coverage"
              ? `${report.inventorySummary.resourceCount}`
              : tab.id === "findings"
                ? `${report.findings.length}`
                : tab.id === "evidence"
                  ? `${evidenceCount}`
                  : tab.id === "cluster"
                    ? `${report.inventorySummary.resourceKinds.Node ?? 0} nodes · ${
                        report.inventorySummary.resourceKinds.Namespace ?? 0
                      } namespaces`
                    : tab.kinds
                      ? `${inventoryCountForKinds(tab.kinds) ?? 0}`
                      : undefined;
          return (
            <button
              type="button"
              className={activeTab === tab.id ? "active" : undefined}
              id={`migration-report-tab-${tab.id}`}
              role="tab"
              aria-selected={activeTab === tab.id}
              aria-controls="migration-report-panel"
              aria-label={`${tab.label}${
                countLabel !== undefined ? ` (${countLabel})` : ""
              }`}
              onClick={() => setActiveTab(tab.id)}
              key={tab.id}
            >
              <span className="migration-report-tab-icon" aria-hidden="true">
                <TabIcon size={18} />
              </span>
              <span className="migration-report-tab-label">{tab.label}</span>
              {countLabel !== undefined && (
                <span className="migration-report-tab-count">{countLabel}</span>
              )}
            </button>
          );
        })}
      </nav>

      <div
        className="migration-report-body"
        id="migration-report-panel"
        role="tabpanel"
        aria-labelledby={`migration-report-tab-${activeTab}`}
      >
        <main>
          {activeTab === "summary" && (
            <>
              <section className="migration-review-guide">
                <div className="migration-section-heading">
                  <div>
                    <h3>
                      How to review this self-managed Kubernetes → Amazon EKS
                      assessment
                    </h3>
                    <p>
                      Use these checks to decide whether the selected workloads
                      are ready for migration planning.
                    </p>
                  </div>
                </div>
                <div className="migration-review-steps">
                  <article>
                    <span>1</span>
                    <div>
                      <strong>Confirm inventory coverage</strong>
                      <p>
                        {assessedCount} resources across{" "}
                        {source?.namespaces?.length ??
                          source?.namespaceCount ??
                          "the selected"}{" "}
                        namespaces were assessed from Kubernetes{" "}
                        {report.sourceKubernetesVersion}.
                      </p>
                    </div>
                  </article>
                  <article>
                    <span>2</span>
                    <div>
                      <strong>Review target treatment</strong>
                      <p>
                        Green is ready, blue can be automated, amber needs an
                        engineering change, and red must be resolved before
                        approval.
                      </p>
                    </div>
                  </article>
                  <article>
                    <span>3</span>
                    <div>
                      <strong>Validate approval conditions</strong>
                      <p>
                        Confirm critical findings are closed, remediation has an
                        owner, evidence is sufficient, and every workload has an
                        EKS target mapping.
                      </p>
                    </div>
                  </article>
                </div>
                <div className="migration-path-considerations">
                  <strong>Path-specific considerations</strong>
                  <span>Persistent storage and CSI mapping</span>
                  <span>Ingress and load balancer translation</span>
                  <span>RBAC and AWS IAM integration</span>
                  <span>Node architecture and scheduling</span>
                  <span>Container image accessibility</span>
                </div>
              </section>

              <section className="migration-priority-section">
                <div className="migration-section-heading">
                  <div>
                    <h3>Key findings</h3>
                    <p>
                      Findings that affect approval, ordered by severity and
                      remediation effort.
                    </p>
                  </div>
                  <span>
                    {report.findings.length} finding
                    {report.findings.length === 1 ? "" : "s"}
                  </span>
                </div>

                {priorityFindings.length === 0 ? (
                  <div className="migration-report-empty">
                    <CheckCircle2 size={32} aria-hidden="true" />
                    <div>
                      <h3>No compatibility changes identified</h3>
                      <p>
                        All assessed resources match the current portability
                        rules.
                      </p>
                    </div>
                  </div>
                ) : (
                  <div className="migration-findings-table" role="table">
                    <div className="migration-findings-table-header" role="row">
                      <span>Finding</span>
                      <span>Affected resource</span>
                      <span>Severity</span>
                      <span>Evidence</span>
                      <span>Suggested remediation</span>
                      <span>Owner</span>
                      <span>Status</span>
                    </div>
                    {priorityFindings.map((finding, index) => {
                      const FindingIcon = severityIcon(finding.category);
                      const rowEvidenceCount =
                        finding.evidenceCount ??
                        finding.evidenceReferences?.length ??
                        (finding.resourceName || finding.namespace ? 1 : 0);
                      return (
                        <article
                          className="migration-findings-table-row"
                          key={findingKey(finding, index)}
                          role="row"
                        >
                          <div className="migration-table-finding">
                            <FindingIcon size={17} aria-hidden="true" />
                            <div>
                              <strong>{finding.message}</strong>
                              <small>{finding.ruleId ?? finding.code}</small>
                            </div>
                          </div>
                          <div>
                            <strong>
                              {finding.resourceName ?? "Cluster-level finding"}
                            </strong>
                            <small>
                              {[finding.resourceKind, finding.namespace]
                                .filter(Boolean)
                                .join(" · ") ||
                                finding.category.replaceAll("_", " ")}
                            </small>
                          </div>
                          <span
                            className={`migration-severity migration-severity-${finding.severity.toLowerCase()}`}
                          >
                            {finding.severity === "BLOCKER"
                              ? "Critical"
                              : finding.severity}
                          </span>
                          <span className="migration-evidence-count">
                            <FileText size={14} aria-hidden="true" />
                            {rowEvidenceCount > 0
                              ? `${rowEvidenceCount} item${rowEvidenceCount === 1 ? "" : "s"}`
                              : "Pending"}
                          </span>
                          <p>
                            {finding.targetTreatment ??
                              finding.remediation ??
                              "Remediation guidance pending rule enrichment."}
                          </p>
                          <span>{findingOwner(finding)}</span>
                          <span
                            className={`migration-remediation-status migration-remediation-status-${findingStatus(
                              finding,
                            )
                              .toLowerCase()
                              .replaceAll(" ", "-")}`}
                          >
                            {findingStatus(finding)}
                          </span>
                        </article>
                      );
                    })}
                  </div>
                )}
              </section>
            </>
          )}

          {activeTab === "findings" && report.findings.length > 0 && (
            <section className="migration-findings-section">
              <div className="migration-section-heading">
                <div>
                  <h3>Detailed compatibility findings</h3>
                  <p>
                    Expand a category to review evidence and recommended action.
                  </p>
                </div>
              </div>
              <div className="migration-finding-groups">
                {orderedClassifications.map((item) => {
                  const findings = report.findings.filter(
                    (finding) => finding.disposition === item.code,
                  );
                  if (findings.length === 0) return null;

                  const details = dispositionDetails[item.code];
                  const GroupIcon = details.icon;
                  return (
                    <details
                      className={`migration-finding-group migration-finding-group-${item.code.toLowerCase()}`}
                      key={item.code}
                      open={item.code === firstVisibleDisposition}
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
                                {finding.targetTreatment ??
                                  finding.remediation ??
                                  "Review this resource before migration planning."}
                              </p>
                              {finding.automationLevel && (
                                <small>
                                  Delivery:{" "}
                                  {finding.automationLevel
                                    .toLowerCase()
                                    .replaceAll("_", " ")}
                                </small>
                              )}
                              {finding.resolutionSteps &&
                                finding.resolutionSteps.length > 0 && (
                                  <div className="migration-resolution-guide">
                                    <strong>Resolution steps</strong>
                                    <ol>
                                      {finding.resolutionSteps.map((step) => (
                                        <li key={step}>{step}</li>
                                      ))}
                                    </ol>
                                  </div>
                                )}
                              {finding.validationSteps &&
                                finding.validationSteps.length > 0 && (
                                  <div className="migration-resolution-guide">
                                    <strong>Validation</strong>
                                    <ul>
                                      {finding.validationSteps.map((step) => (
                                        <li key={step}>{step}</li>
                                      ))}
                                    </ul>
                                  </div>
                                )}
                            </div>
                          </article>
                        ))}
                      </div>
                    </details>
                  );
                })}
              </div>
            </section>
          )}

          {activeTab === "findings" && report.findings.length === 0 && (
            <section className="migration-inventory-panel">
              <div className="migration-report-empty">
                <CheckCircle2 size={32} aria-hidden="true" />
                <div>
                  <h3>No compatibility findings</h3>
                  <p>
                    The selected inventory passed the current assessment rules.
                  </p>
                </div>
              </div>
            </section>
          )}

          {activeTab === "coverage" && (
            <section className="migration-inventory-panel">
              <div className="migration-section-heading">
                <div>
                  <h3>Inventory coverage</h3>
                  <p>
                    All sanitized Kubernetes resource kinds included in this
                    assessment. Select the related tabs to inspect each
                    resource.
                  </p>
                </div>
                <span>{report.inventorySummary.resourceCount} resources</span>
              </div>
              <div className="migration-resource-list">
                {resourceKinds.map(([kind, count]) => (
                  <div key={kind}>
                    <span>{kind}</span>
                    <strong>{count}</strong>
                  </div>
                ))}
              </div>
            </section>
          )}

          {activeTab === "advanced" && (
            <section className="migration-advanced-readiness">
              <div className="migration-section-heading">
                <div>
                  <h3>Advanced Step 1 readiness</h3>
                  <p>
                    A demo-ready view of the deeper checks required before
                    artifact collection or migration execution. Every result is
                    derived from the sanitized inventory; unavailable
                    integrations are clearly identified.
                  </p>
                </div>
                <span>{advancedChecks.length} assessment areas</span>
              </div>

              <div
                className="migration-advanced-summary"
                aria-label="Advanced readiness summary"
              >
                <div>
                  <CheckCircle2 size={18} aria-hidden="true" />
                  <strong>{advancedCompleteCount}</strong>
                  <span>Complete</span>
                </div>
                <div>
                  <AlertTriangle size={18} aria-hidden="true" />
                  <strong>{advancedReviewCount}</strong>
                  <span>Needs review</span>
                </div>
                <div>
                  <CircleHelp size={18} aria-hidden="true" />
                  <strong>{advancedNotDetectedCount}</strong>
                  <span>Not detected</span>
                </div>
                <p>
                  “Not detected” means the inventory contains no reliable
                  signal. It does not automatically mean the capability or
                  dependency is absent.
                </p>
              </div>

              <div className="migration-advanced-grid">
                {advancedChecks.map((check) => {
                  const CheckIcon = check.icon;
                  return (
                    <article
                      className={`migration-advanced-card migration-advanced-card-${check.status}`}
                      key={check.id}
                    >
                      <header>
                        <span className="migration-advanced-icon">
                          <CheckIcon size={19} aria-hidden="true" />
                        </span>
                        <div>
                          <h4>{check.title}</h4>
                          <span
                            className={`migration-advanced-status migration-advanced-status-${check.status}`}
                          >
                            {check.statusLabel}
                          </span>
                        </div>
                      </header>
                      <p>{check.description}</p>
                      <ul>
                        {check.evidence.map((evidence) => (
                          <li key={evidence}>{evidence}</li>
                        ))}
                      </ul>
                      <div className="migration-advanced-action">
                        <strong>Before Step 2</strong>
                        <p>{check.nextAction}</p>
                      </div>
                    </article>
                  );
                })}
              </div>

              <div className="migration-advanced-boundary">
                <ShieldCheck size={21} aria-hidden="true" />
                <div>
                  <h4>Assessment security boundary</h4>
                  <p>
                    This phase uses read-only metadata. Secret and ConfigMap
                    values, repository credentials, application data and
                    persistent-volume contents remain excluded until a
                    separately approved Step 2 workflow.
                  </p>
                </div>
              </div>
            </section>
          )}

          {activeInventoryTab?.kinds && (
            <InventoryPanel
              title={activeInventoryTab.label}
              description={`Sanitized read-only ${activeInventoryTab.label.toLowerCase()} metadata collected from the selected source scope.`}
              resources={visibleInventory}
              loading={inventoryLoading}
              error={inventoryError}
            />
          )}

          {activeTab === "evidence" && (
            <section className="migration-inventory-panel">
              <div className="migration-section-heading">
                <div>
                  <h3>Inventory evidence and security boundary</h3>
                  <p>
                    Verify when the inventory was collected, its integrity, and
                    which sensitive information was excluded.
                  </p>
                </div>
              </div>
              <dl className="migration-evidence-grid">
                <div>
                  <dt>Inventory version</dt>
                  <dd>{inventory?.inventoryVersion ?? "Unavailable"}</dd>
                </div>
                <div>
                  <dt>Observed</dt>
                  <dd>
                    {inventory?.observedAt
                      ? reportDate(inventory.observedAt)
                      : "Unavailable"}
                  </dd>
                </div>
                <div>
                  <dt>Kubernetes version</dt>
                  <dd>
                    {inventory?.sourceKubernetesVersion ??
                      report.sourceKubernetesVersion}
                  </dd>
                </div>
                <div>
                  <dt>Resources collected</dt>
                  <dd>{inventory?.resourceCount ?? assessedCount}</dd>
                </div>
                <div>
                  <dt>Source architectures</dt>
                  <dd>{source?.architectures?.join(", ") || "Unavailable"}</dd>
                </div>
                <div>
                  <dt>Target pods ready</dt>
                  <dd>
                    {target.readyPodCount ?? "—"} / {target.podCount ?? "—"}
                  </dd>
                </div>
                <div>
                  <dt>Target warning events</dt>
                  <dd>{target.warningEventCount ?? "Unavailable"}</dd>
                </div>
                <div>
                  <dt>Target container restarts</dt>
                  <dd>{target.containerRestartCount ?? "Unavailable"}</dd>
                </div>
                <div>
                  <dt>Inventory digest</dt>
                  <dd className="migration-evidence-digest">
                    {inventory?.inventoryDigest ?? report.inventoryDigest}
                  </dd>
                </div>
                <div>
                  <dt>Sensitive values included</dt>
                  <dd>
                    {inventory?.sensitiveDataIncluded === false
                      ? "No — Secret and ConfigMap values excluded"
                      : "Not verified"}
                  </dd>
                </div>
              </dl>
            </section>
          )}
        </main>

        <aside className="migration-report-sidebar">
          <section className="migration-governance-card">
            <div className="migration-sidebar-heading">
              <h3>Governance &amp; decision</h3>
              <ShieldCheck size={18} aria-hidden="true" />
            </div>
            {governance?.status && (
              <span className="migration-governance-status">
                {governance.status.replaceAll("_", " ")}
              </span>
            )}
            <dl>
              <div>
                <dt>Checkpoint</dt>
                <dd>
                  {report.governance?.checkpoint ??
                    "Independent assessment review"}
                </dd>
              </div>
              <div>
                <dt>
                  <UserRound size={13} aria-hidden="true" /> Reviewer
                </dt>
                <dd>
                  {report.governance?.reviewerName ?? "Not assigned"}
                  {report.governance?.reviewerRole
                    ? ` · ${report.governance.reviewerRole}`
                    : ""}
                </dd>
              </div>
              <div>
                <dt>
                  <CalendarDays size={13} aria-hidden="true" /> Due date
                </dt>
                <dd>{report.governance?.dueDate ?? "Not assigned"}</dd>
              </div>
            </dl>

            <div className="migration-governance-section">
              <h4>Policy checks</h4>
              {policyChecks.map((check) => (
                <div key={check.label}>
                  <span>{check.label}</span>
                  <strong
                    className={
                      check.value === "Passed"
                        ? "migration-policy-passed"
                        : check.value === "Pending integration"
                          ? "migration-policy-pending"
                          : "migration-policy-issue"
                    }
                  >
                    {check.value}
                  </strong>
                </div>
              ))}
            </div>

            <div className="migration-governance-section">
              <h4>Approval conditions</h4>
              <ul>
                {approvalConditions.map((condition) => (
                  <li key={condition}>{condition}</li>
                ))}
              </ul>
            </div>
          </section>

          <section className="migration-next-action">
            <h3>Recommended next action</h3>
            <p>
              {criticalFindingCount > 0
                ? `Resolve ${criticalFindingCount} blocker${criticalFindingCount === 1 ? "" : "s"}, confirm the remediation owners, and rerun the assessment.`
                : changeCount > 0
                  ? `Review ${changeCount} planned change${changeCount === 1 ? "" : "s"} and submit the report for approval.`
                  : "Submit this assessment for independent architecture approval."}
            </p>
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
            <h3>Audit metadata</h3>
            <dl>
              <div>
                <dt>Report ID</dt>
                <dd>
                  {report.auditMetadata?.reportId ?? "Pending integration"}
                </dd>
              </div>
              <div>
                <dt>Report version</dt>
                <dd>
                  {report.auditMetadata?.reportVersion ??
                    `v${report.assessmentVersion}`}
                </dd>
              </div>
              <div>
                <dt>Inventory hash</dt>
                <dd title={report.inventoryDigest}>
                  {report.inventoryDigest.slice(0, 12)}…
                </dd>
              </div>
              <div>
                <dt>Generated by</dt>
                <dd>{report.auditMetadata?.generatedBy ?? report.createdBy}</dd>
              </div>
              <div>
                <dt>Generated</dt>
                <dd>{reportDate(report.createdAt)}</dd>
              </div>
            </dl>
          </section>

          <section className="migration-report-help">
            <CircleHelp size={20} aria-hidden="true" />
            <div>
              <h3>How to read this report</h3>
              <p>
                Review inventory coverage first, then resolve critical findings,
                assign remediation owners, verify the EKS target treatment, and
                confirm supporting evidence before approval.
              </p>
            </div>
          </section>
        </aside>
      </div>
    </section>
  );
}
