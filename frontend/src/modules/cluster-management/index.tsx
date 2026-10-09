"use client";
import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
} from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Building2,
  Check,
  ChevronDown,
  Clock3,
  CloudCog,
  EllipsisVertical,
  ExternalLink,
  Filter,
  KeyRound,
  Layers3,
  Network,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
  UserRound,
  UsersRound,
} from "lucide-react";
import { useAuth } from "@/shared/auth/auth-provider";
import { hasPermission } from "@/shared/auth/permissions";
import { ApiError } from "@/shared/api/client";
import {
  Button,
  EmptyState,
  ErrorNotice,
  Loading,
  PageHeading,
  Pagination,
  formatDate,
} from "@/shared/components/ui";
import { environments } from "@/modules/environment-management/services/environments";
import { customersService } from "@/modules/customer-management/services/customers";
import { useClusterCount, useClusters } from "./hooks/queries";
import { clusters } from "./service";
import {
  clusterLifecycleActions,
  shouldShowClusterExecutionPanel,
  supportedEksVersions,
} from "./model";
import type {
  Cluster,
  ClusterAction,
  ClusterFilters,
  ClusterInput,
  ClusterNodeGroupInput,
} from "./model";
import "./cluster-directory.css";

function objectValue(value: unknown): Record<string, unknown> {
  return value != null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function arrayValue(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? (value as Record<string, unknown>[]) : [];
}

function textValue(value: unknown, fallback = "Not configured") {
  return typeof value === "string" && value ? value : fallback;
}

function approvedProvisioningSecrets(...values: unknown[]) {
  return values
    .flatMap((value) => (Array.isArray(value) ? value : []))
    .map((item) => {
      if (typeof item === "string") return { arn: item, name: item };
      const record = objectValue(item);
      const arn = record.arn || record.ARN || record.secretArn;
      return {
        arn: typeof arn === "string" ? arn : "",
        name:
          typeof record.name === "string"
            ? record.name
            : typeof record.secretName === "string"
              ? record.secretName
              : typeof arn === "string"
                ? arn
                : "",
      };
    })
    .filter(
      (item, index, items) =>
        Boolean(item.arn) &&
        items.findIndex((candidate) => candidate.arn === item.arn) === index,
    );
}

function recommendedNodeGroupName(clusterName: string, index = 0): string {
  const clusterPrefix = clusterName
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48);
  const workload = index === 0 ? "system" : `workload-${index + 1}`;
  return clusterPrefix ? `${clusterPrefix}-${workload}-ng` : `${workload}-ng`;
}

const statusLabels: Record<string, string> = {
  DRAFT: "Draft",
  SUBMITTED: "Submitted",
  UNDER_REVIEW: "Under review",
  APPROVED: "Approved",
  PLAN_RUNNING: "Plan running",
  PLAN_READY: "Plan ready",
  APPLYING: "Applying",
  BOOTSTRAPPING: "Installing platform services",
  BOOTSTRAP_FAILED: "Platform bootstrap failed",
  ACTIVE: "Active",
  STOPPING: "Scaling workers to zero",
  STOPPED: "Worker capacity stopped",
  STARTING: "Restoring worker capacity",
  DELETING: "Deleting",
  DELETED: "Deleted",
  FAILED: "Failed",
  REJECTED: "Rejected",
};

function clusterStatusLabel(status: string): string {
  return statusLabels[status] || status.replaceAll("_", " ");
}

const clusterStatusDescriptions: Record<string, string> = {
  DRAFT: "Configuration in progress",
  SUBMITTED: "Awaiting architecture review",
  UNDER_REVIEW: "Architecture review in progress",
  APPROVED: "Approved for planning",
  PLAN_RUNNING: "Generating Terraform plan",
  PLAN_READY: "Certified plan ready to apply",
  APPLYING: "Provisioning cloud resources",
  BOOTSTRAPPING: "Installing Navigan platform services",
  BOOTSTRAP_FAILED: "Platform service installation failed",
  ACTIVE: "Cluster is operational",
  STOPPING: "Scaling worker capacity down",
  STOPPED: "Worker capacity is stopped",
  STARTING: "Restoring worker capacity",
  DELETING: "Cluster deletion in progress",
  DELETED: "Cluster has been removed",
  FAILED: "Provisioning requires remediation",
  REJECTED: "Returned for changes",
};

function identityDisplayName(subject: {
  type: "USER" | "GROUP";
  displayName: string;
}): string {
  if (subject.type !== "GROUP" || !subject.displayName.startsWith("NAVIGAN_")) {
    return subject.displayName;
  }
  return subject.displayName
    .replace(/^NAVIGAN_/, "")
    .split("_")
    .filter(Boolean)
    .map((part) => part.slice(0, 1).toUpperCase() + part.slice(1).toLowerCase())
    .join(" ");
}

type ClusterAdminMode = "directory" | "reviews" | "operations";
type ClusterToolCode =
  "HEADLAMP" | "GRAFANA" | "PROMETHEUS" | "ARGOCD" | "WEBKUBECTL";

interface ClusterAdminPageProps {
  mode?: ClusterAdminMode;
}

const directOperations: Partial<
  Record<ClusterAction["code"], "stop" | "start" | "delete">
> = {
  STOP: "stop",
  START: "start",
  DELETE: "delete",
};
const actionLinks: Partial<
  Record<ClusterAction["code"], (cluster: Cluster) => string>
> = {
  MANAGE_ACCESS: (cluster) =>
    `/clusters/access?cluster=${encodeURIComponent(cluster.clusterId)}`,
};

const actionLabels: Partial<Record<ClusterAction["code"], string>> = {
  MANAGE: "Manage Cluster",
  MANAGE_ACCESS: "Authorization",
};
const hiddenDirectoryActions = new Set<ClusterAction["code"]>([
  "DASHBOARD",
  "WEBKUBECTL",
]);

function clusterActionLabel(action: ClusterAction) {
  return actionLabels[action.code] || action.label;
}

function ClusterActionMenu({
  cluster,
  busy,
  onAction,
}: {
  cluster: Cluster;
  busy: boolean;
  onAction: (cluster: Cluster, action: ClusterAction) => void;
}) {
  const trigger = useRef<HTMLButtonElement>(null);
  const popup = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<CSSProperties>();
  const menuActions = cluster.allowedActions.filter(
    (action) => !hiddenDirectoryActions.has(action.code),
  );
  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      const target = event.target as Node;
      if (
        !trigger.current?.contains(target) &&
        !popup.current?.contains(target)
      ) {
        setOpen(false);
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        trigger.current?.focus();
      }
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", closeOnEscape);
    window.addEventListener("resize", () => setOpen(false), { once: true });
    window.addEventListener("scroll", () => setOpen(false), {
      capture: true,
      once: true,
    });
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);
  const toggle = () => {
    if (open) {
      setOpen(false);
      return;
    }
    const rect = trigger.current?.getBoundingClientRect();
    if (!rect) return;
    const width = 260;
    const estimatedHeight = Math.min(
      360,
      Math.max(56, menuActions.length * 58),
    );
    const opensAbove =
      rect.bottom + estimatedHeight + 12 > window.innerHeight &&
      rect.top > estimatedHeight;
    setPosition({
      left: Math.max(
        12,
        Math.min(rect.right - width, window.innerWidth - width - 12),
      ),
      top: opensAbove
        ? Math.max(12, rect.top - estimatedHeight - 4)
        : rect.bottom + 4,
      width,
    });
    setOpen(true);
  };
  const items =
    menuActions.length > 0 ? (
      menuActions.map((action) => {
        const operation = directOperations[action.code];
        const actionHref = actionLinks[action.code]?.(cluster);
        if (!operation && action.enabled) {
          return (
            <Link
              key={action.code}
              href={actionHref || `/clusters/${cluster.clusterId}`}
              role="menuitem"
              className="cluster-action-item"
              onClick={() => setOpen(false)}
            >
              {clusterActionLabel(action)}
            </Link>
          );
        }
        return (
          <button
            key={action.code}
            type="button"
            role="menuitem"
            className={`cluster-action-item ${
              action.destructive ? "danger" : ""
            }`}
            disabled={!action.enabled || busy}
            title={action.disabledReason || undefined}
            onClick={() => {
              setOpen(false);
              onAction(cluster, action);
            }}
          >
            <span>{clusterActionLabel(action)}</span>
            {!action.enabled && action.disabledReason && (
              <small>{action.disabledReason}</small>
            )}
          </button>
        );
      })
    ) : (
      <div className="cluster-action-empty" role="status">
        Actions are unavailable until the Dev backend capability update is
        deployed.
      </div>
    );
  return (
    <div className="cluster-action-menu">
      <button
        ref={trigger}
        type="button"
        className="cluster-action-trigger"
        aria-label={`Actions for ${cluster.clusterName}`}
        aria-haspopup="menu"
        aria-expanded={open}
        title={`Actions for ${cluster.clusterName}`}
        onClick={toggle}
      >
        <EllipsisVertical size={20} aria-hidden="true" />
      </button>
      {open &&
        position &&
        createPortal(
 …31109 tokens truncated…{clusterSecurityGroups.length + nodeSecurityGroups.length}
                </dd>
              </div>
            </dl>
            <div className="compact-inventory-grid">
              <section>
                <h3>Approved subnets</h3>
                {[...clusterSubnets, ...nodeSubnets].map((subnet, index) => (
                  <div key={`${textValue(subnet.subnetId, "subnet")}-${index}`}>
                    <strong>{textValue(subnet.subnetId)}</strong>
                    <span>
                      {textValue(
                        subnet.availabilityZone ?? subnet.AvailabilityZone,
                        "Availability zone not reported",
                      )}
                    </span>
                  </div>
                ))}
              </section>
              <section>
                <h3>Security groups</h3>
                {[...clusterSecurityGroups, ...nodeSecurityGroups].map(
                  (group, index) => (
                    <div
                      key={`${textValue(group.securityGroupId, "security-group")}-${index}`}
                    >
                      <strong>{textValue(group.securityGroupId)}</strong>
                      <span>
                        {index < clusterSecurityGroups.length
                          ? "Control plane"
                          : "Worker nodes"}
                      </span>
                    </div>
                  ),
                )}
              </section>
            </div>
          </section>

          <section className="panel panel-padding cluster-tab-panel cluster-tab-observability">
            {platformComponents.error && (
              <ErrorNotice
                error={platformComponents.error}
                onRetry={() => platformComponents.refetch()}
              />
            )}
            <div className="cluster-review-section-heading">
              <div>
                <span className="eyebrow">OBSERVABILITY</span>
                <h2>Health and telemetry</h2>
                <p className="muted">
                  Cluster signals exposed through approved platform
                  integrations.
                </p>
              </div>
              <span
                className={`security-chip ${telemetryReady ? "" : "needs-review"}`}
              >
                {telemetryReady
                  ? "Healthy"
                  : runtimeInventory?.status === "STALE"
                    ? "Refreshing telemetry"
                    : "Needs attention"}
              </span>
            </div>
            {!platformComponents.error &&
              runtimeInventory?.status !== "READY" && (
                <div className="notice">
                  <strong>
                    {runtimeInventory?.status === "STALE"
                      ? "The last runtime snapshot has expired."
                      : "Runtime telemetry has not been reported yet."}
                  </strong>{" "}
                  Navigan will refresh automatically, or you can request it now.
                  <div className="action-row">
                    <Button
                      type="button"
                      variant="secondary"
                      disabled={platformComponents.isFetching}
                      onClick={() => platformComponents.refetch()}
                    >
                      {platformComponents.isFetching
                        ? "Refreshing telemetry…"
                        : "Refresh telemetry"}
                    </Button>
                  </div>
                </div>
              )}
            <dl className="compact-facts">
              <div>
                <dt>Ready nodes</dt>
                <dd>
                  {runtimeMetrics.readyNodeCount ?? "—"} /{" "}
                  {runtimeMetrics.nodeCount ?? "—"}
                </dd>
              </div>
              <div>
                <dt>Ready pods</dt>
                <dd>
                  {runtimeMetrics.readyPodCount ?? "—"} /{" "}
                  {runtimeMetrics.podCount ?? "—"}
                </dd>
              </div>
              <div>
                <dt>Container restarts</dt>
                <dd>{runtimeMetrics.containerRestartCount ?? "—"}</dd>
              </div>
              <div>
                <dt>Warning events</dt>
                <dd>{runtimeMetrics.warningEventCount ?? "—"}</dd>
              </div>
              <div>
                <dt>Prometheus</dt>
                <dd>{componentLabel("prometheus")}</dd>
              </div>
              <div>
                <dt>Grafana</dt>
                <dd>{componentLabel("grafana")}</dd>
              </div>
              <div>
                <dt>Falco</dt>
                <dd>{componentLabel("falco")}</dd>
              </div>
              <div>
                <dt>Connector</dt>
                <dd>{componentLabel("connector")}</dd>
              </div>
            </dl>
            <div className="telemetry-visual-grid">
              <article className="telemetry-chart">
                <header>
                  <div>
                    <span className="eyebrow">PROMETHEUS SNAPSHOT</span>
                    <h3>Readiness</h3>
                  </div>
                  <strong>
                    {readinessPercent(workloadReady, workloadDesired)}%
                  </strong>
                </header>
                {[
                  {
                    label: "Nodes",
                    ready: readyNodeCount,
                    total: nodeCount,
                  },
                  {
                    label: "Pods",
                    ready: readyPodCount,
                    total: podCount,
                  },
                  {
                    label: "Workload replicas",
                    ready: workloadReady,
                    total: workloadDesired,
                  },
                ].map((metric) => (
                  <div className="telemetry-progress-row" key={metric.label}>
                    <div>
                      <span>{metric.label}</span>
                      <strong>
                        {metric.ready} / {metric.total}
                      </strong>
                    </div>
                    <span className="telemetry-progress-track">
                      <span
                        style={{
                          width: `${readinessPercent(metric.ready, metric.total)}%`,
                        }}
                      />
                    </span>
                  </div>
                ))}
              </article>
              <article className="telemetry-chart">
                <header>
                  <div>
                    <span className="eyebrow">GRAFANA OVERVIEW</span>
                    <h3>Resource mix</h3>
                  </div>
                  <strong>{runtimeResources.length}</strong>
                </header>
                <div className="telemetry-bars">
                  {resourceKindCounts.map((item) => (
                    <div key={item.kind}>
                      <span>{item.kind}</span>
                      <span className="telemetry-bar-track">
                        <span
                          style={{
                            width: `${Math.max(
                              5,
                              (item.count / largestResourceKindCount) * 100,
                            )}%`,
                          }}
                        />
                      </span>
                      <strong>{item.count}</strong>
                    </div>
                  ))}
                </div>
              </article>
              <article className="telemetry-chart telemetry-chart-wide">
                <header>
                  <div>
                    <span className="eyebrow">POD STABILITY</span>
                    <h3>Container restarts by namespace</h3>
                  </div>
                  <strong>
                    {Number(runtimeMetrics.containerRestartCount || 0)}
                  </strong>
                </header>
                <div className="telemetry-bars">
                  {restartCountsByNamespace.map((item) => (
                    <div key={item.namespace}>
                      <span title={item.namespace}>{item.namespace}</span>
                      <span className="telemetry-bar-track restart">
                        <span
                          style={{
                            width: `${Math.max(
                              item.restarts ? 5 : 0,
                              (item.restarts / largestNamespaceRestartCount) *
                                100,
                            )}%`,
                          }}
                        />
                      </span>
                      <strong>{item.restarts}</strong>
                    </div>
                  ))}
                </div>
              </article>
            </div>
            {runtimeInventory?.warningEvents.length ? (
              <div className="compact-inventory-grid">
                <section>
                  <h3>Recent warning events</h3>
                  {runtimeInventory.warningEvents
                    .slice(-10)
                    .reverse()
                    .map((event, index) => (
                      <div
                        key={`${event.resourceKind}:${event.resourceName}:${index}`}
                      >
                        <strong>{event.reason}</strong>
                        <span>
                          {event.resourceKind} {event.resourceName}:{" "}
                          {event.message}
                        </span>
                      </div>
                    ))}
                </section>
              </div>
            ) : null}
            <div className="capability-list">
              {[
                ["GRAFANA", "Grafana", "dashboards and metric exploration"],
                ["PROMETHEUS", "Prometheus", "queries, targets and alerts"],
              ].map(([code, label, description]) => (
                <article key={code}>
                  <div>
                    <strong>{label}</strong>
                    <span>Use the real {description} interface.</span>
                    <small>
                      {toolByCode(code)?.disabledReason ||
                        "The service remains private and is reached through the shared Navigan gateway."}
                    </small>
                  </div>
                  {toolLaunch(code as ClusterToolCode, label)}
                </article>
              ))}
            </div>
          </section>

          <section className="panel panel-padding cluster-tab-panel cluster-tab-addons">
            <div className="cluster-review-section-heading">
              <div>
                <span className="eyebrow">PLATFORM BASELINE</span>
                <h2>Mandatory cluster services</h2>
                <p className="muted">
                  Protected services installed on the system node group and
                  managed as part of cluster readiness.
                </p>
              </div>
              <span className="security-chip">{platformReadiness}</span>
            </div>
            <div className="platform-service-grid">
              {[
                [
                  "Navigan connector",
                  platformBootstrap.connectorId ? "Ready" : platformReadiness,
                ],
                ["Argo CD cluster registration", "Not reported"],
                ["Falco", "Planned"],
                ["AWS Private CA connector", "Planned"],
                ["Observability", "Planned"],
                ["Cluster dashboard services", "Planned"],
              ].map(([name, status]) => (
                <article key={name}>
                  <strong>{name}</strong>
                  <span>{String(status)}</span>
                </article>
              ))}
            </div>
          </section>

          <section className="panel panel-padding cluster-tab-panel cluster-tab-compute">
            <div className="cluster-review-section-heading">
              <div>
                <span className="eyebrow">COMPUTE MANAGEMENT</span>
                <h2>Application node-group requests</h2>
                <p className="muted">
                  Network, IAM, encryption and subnet constraints are inherited
                  from the cluster&apos;s pinned environment blueprint.
                </p>
              </div>
              <div className="cluster-heading-action">
                <Button
                  type="button"
                  variant="secondary"
                  disabled={!canRequestNodeGroup || row.status !== "ACTIVE"}
                  title={
                    !canRequestNodeGroup
                      ? "Cloud Engineer or Platform Administrator permission is required"
                      : row.status === "ACTIVE"
                        ? "Request application capacity"
                        : "Node groups can be requested when the cluster is Active"
                  }
                  onClick={() => setShowNodeGroupForm((current) => !current)}
                >
                  <Plus size={16} />
                  New node group
                </Button>
                {!canRequestNodeGroup && (
                  <small>Cloud Engineer permission required</small>
                )}
                {canRequestNodeGroup && row.status !== "ACTIVE" && (
                  <small>Available when the cluster is Active</small>
                )}
              </div>
            </div>

            <section
              className="compute-baseline"
              aria-label="Compute provisioning baseline"
            >
              <div>
                <span className="eyebrow">ENVIRONMENT</span>
                <strong>{row.environmentName || row.environmentId}</strong>
                <small>{row.environmentId}</small>
              </div>
              <div>
                <span className="eyebrow">APPROVED REVISION</span>
                <strong>Version {row.environmentApprovedVersion}</strong>
                <small>Pinned at cluster creation</small>
              </div>
              <div>
                <span className="eyebrow">CLUSTER BLUEPRINT</span>
                <strong>{textValue(configuration.blueprintName)}</strong>
                <small>Source of inherited compute constraints</small>
              </div>
            </section>

            <div className="table-scroll cluster-node-table">
              <table>
                <thead>
                  <tr>
                    <th>Current node group</th>
                    <th>Purpose</th>
                    <th>Instance types</th>
                    <th>Capacity</th>
                    <th>Scaling</th>
                  </tr>
                </thead>
                <tbody>
                  {nodeGroups.map((group, index) => (
                    <tr key={`compute-${String(group.name || index)}`}>
                      <td>
                        <strong>{textValue(group.name)}</strong>
                      </td>
                      <td>
                        {textValue(
                          group.purpose,
                          index === 0 ? "SYSTEM" : "APPLICATION",
                        ) === "SYSTEM"
                          ? "System"
                          : "Application"}
                      </td>
                      <td>
                        {Array.isArray(group.instanceTypes)
                          ? group.instanceTypes.join(", ")
                          : "Not configured"}
                      </td>
                      <td>{textValue(group.capacityType)}</td>
                      <td>
                        {String(group.minSize)} / {String(group.desiredSize)} /{" "}
                        {String(group.maxSize)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {!currentSystemGroupRecorded &&
              recordedSystemGroup &&
              row.status === "ACTIVE" &&
              canOperate && (
                <div className="compute-migration-action">
                  <div>
                    <strong>Default system node-group migration</strong>
                    <small>
                      Adopt navigan-system-v1 and retire{" "}
                      {textValue(recordedSystemGroup.name)} through a certified
                      Terraform plan.
                    </small>
                  </div>
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={busy}
                    onClick={migrateDefaultSystemGroup}
                  >
                    Migrate system node group
                  </Button>
                </div>
              )}

            {showNodeGroupForm && (
              <form
                className="node-group-request-form"
                onSubmit={createNodeGroup}
              >
                <label>
                  Node-group name
                  <input
                    required
                    pattern="[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?"
                    value={nodeGroupDraft.name}
                    onChange={(event) =>
                      setNodeGroupDraft((current) => ({
                        ...current,
                        name: event.target.value,
                      }))
                    }
                    placeholder="checkout-workers"
                  />
                </label>
                <label>
                  Instance types
                  <select
                    required
                    disabled={
                      pinnedEnvironment.isPending ||
                      currentEnvironment.isPending ||
                      approvedApplicationInstanceTypes.length === 0
                    }
                    value={nodeGroupDraft.instanceTypes}
                    onChange={(event) =>
                      setNodeGroupDraft((current) => ({
                        ...current,
                        instanceTypes: event.target.value,
                      }))
                    }
                  >
                    <option value="">
                      {pinnedEnvironment.isPending ||
                      currentEnvironment.isPending
                        ? "Loading approved instance types…"
                        : approvedApplicationInstanceTypes.length
                          ? "Select an approved instance type"
                          : "No approved instance types available"}
                    </option>
                    {approvedApplicationInstanceTypes.map((instanceType) => (
                      <option key={instanceType} value={instanceType}>
                        {instanceType}
                      </option>
                    ))}
                  </select>
                  <small>
                    Loaded from the approved environment catalogue, with the
                    pinned cluster blueprint as fallback.
                  </small>
                </label>
                <label>
                  Capacity
                  <select
                    value={nodeGroupDraft.capacityType}
                    onChange={(event) =>
                      setNodeGroupDraft((current) => ({
                        ...current,
                        capacityType: event.target.value as
                          "ON_DEMAND" | "SPOT",
                      }))
                    }
                  >
                    <option value="ON_DEMAND">On demand</option>
                    <option value="SPOT">Spot</option>
                  </select>
                </label>
                {(
                  ["minSize", "desiredSize", "maxSize", "diskSizeGiB"] as const
                ).map((field) => (
                  <label key={field}>
                    {field === "minSize"
                      ? "Minimum"
                      : field === "desiredSize"
                        ? "Desired"
                        : field === "maxSize"
                          ? "Maximum"
                          : "Disk (GiB)"}
                    <input
                      type="number"
                      min={field === "diskSizeGiB" ? 20 : 0}
                      required
                      value={nodeGroupDraft[field]}
                      onChange={(event) =>
                        setNodeGroupDraft((current) => ({
                          ...current,
                          [field]: Number(event.target.value),
                        }))
                      }
                    />
                  </label>
                ))}
                <label className="node-group-request-reason">
                  Application onboarding justification
                  <textarea
                    required
                    minLength={3}
                    value={nodeGroupDraft.reason}
                    onChange={(event) =>
                      setNodeGroupDraft((current) => ({
                        ...current,
                        reason: event.target.value,
                      }))
                    }
                  />
                </label>
                <div className="node-group-request-actions">
                  <Button type="submit" disabled={busy}>
                    Save request
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => setShowNodeGroupForm(false)}
                  >
                    Cancel
                  </Button>
                </div>
              </form>
            )}

            {nodeGroupRequests.isPending ? (
              <Loading label="Loading node-group requests…" />
            ) : nodeGroupRequests.data?.items.length ? (
              <div className="table-scroll cluster-node-table">
                <table>
                  <thead>
                    <tr>
                      <th>Requested group</th>
                      <th>Compute</th>
                      <th>Scaling</th>
                      <th>Status</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {nodeGroupRequests.data.items.map((request) => (
                      <tr key={request.requestId}>
                        <td>
                          <strong>{request.nodeGroup.name}</strong>
                          <span className="metadata">{request.reason}</span>
                        </td>
                        <td>
                          {request.nodeGroup.instanceTypes.join(", ")}
                          <span className="metadata">
                            {request.nodeGroup.capacityType}
                          </span>
                        </td>
                        <td>
                          {request.nodeGroup.minSize} /{" "}
                          {request.nodeGroup.desiredSize} /{" "}
                          {request.nodeGroup.maxSize}
                        </td>
                        <td>
                          <span
                            className={
                              "status-badge status-" +
                              request.status.toLowerCase()
                            }
                          >
                            {request.status.replaceAll("_", " ")}
                          </span>
                        </td>
                        <td>
                          {canRequestNodeGroup &&
                            ["DRAFT", "REJECTED"].includes(request.status) && (
                              <Button
                                type="button"
                                disabled={busy}
                                onClick={() =>
                                  actOnNodeGroup(
                                    request.requestId,
                                    request.version,
                                    "submit",
                                  )
                                }
                              >
                                Submit
                              </Button>
                            )}
                          {canReviewNodeGroup &&
                            request.status === "SUBMITTED" && (
                              <div className="node-group-request-actions">
                                <Button
                                  type="button"
                                  disabled={busy}
                                  onClick={() =>
                                    actOnNodeGroup(
                                      request.requestId,
                                      request.version,
                                      "approve",
                                    )
                                  }
                                >
                                  Approve
                                </Button>
                                <Button
                                  type="button"
                                  variant="secondary"
                                  disabled={busy}
                                  onClick={() =>
                                    actOnNodeGroup(
                                      request.requestId,
                                      request.version,
                                      "reject",
                                    )
                                  }
                                >
                                  Reject
                                </Button>
                              </div>
                            )}
                          {canReviewNodeGroup &&
                            request.status === "PLAN_READY" && (
                              <Button
                                type="button"
                                disabled={
                                  busy ||
                                  objectValue(request.workflow.certification)
                                    .status !== "PASSED"
                                }
                                onClick={() =>
                                  actOnNodeGroup(
                                    request.requestId,
                                    request.version,
                                    "apply",
                                  )
                                }
                              >
                                Apply plan
                              </Button>
                            )}
                          {canReviewNodeGroup &&
                            request.status === "FAILED" && (
                              <Button
                                type="button"
                                disabled={busy}
                                onClick={() =>
                                  actOnNodeGroup(
                                    request.requestId,
                                    request.version,
                                    "retry",
                                  )
                                }
                              >
                                Retry plan
                              </Button>
                            )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState title="No application node groups requested">
                The protected system node group remains the only cluster
                capacity.
              </EmptyState>
            )}
          </section>

          <section className="panel panel-padding cluster-tab-panel cluster-tab-addons">
            <div className="cluster-review-section-heading">
              <div>
                <span className="eyebrow">OPTIONAL EXTENSIONS</span>
                <h2>Cluster add-ons</h2>
                <p className="muted">
                  Govern optional capabilities separately from the mandatory
                  platform baseline. Versions, configuration and lifecycle
                  changes remain auditable.
                </p>
              </div>
              <span className="security-chip">
                {configuredAddOns.length} configured
              </span>
            </div>

            {configuredAddOns.length ? (
              <div className="addon-inventory-grid">
                {configuredAddOns.map((addOn, index) => (
                  <article key={textValue(addOn.name, `add-on-${index}`)}>
                    <div>
                      <CloudCog size={20} aria-hidden="true" />
                      <strong>{textValue(addOn.name)}</strong>
                    </div>
                    <span
                      className={`status-badge status-${textValue(
                        addOn.status,
                        "configured",
                      ).toLowerCase()}`}
                    >
                      {textValue(addOn.status, "Configured")}
                    </span>
                    <dl>
                      <div>
                        <dt>Version</dt>
                        <dd>{textValue(addOn.version, "Managed")}</dd>
                      </div>
                      <div>
                        <dt>Source</dt>
                        <dd>{textValue(addOn.source, "Approved catalog")}</dd>
                      </div>
                    </dl>
                  </article>
                ))}
              </div>
            ) : (
              <>
                <EmptyState title="No optional add-ons installed">
                  This cluster currently contains only its mandatory platform
                  baseline. Optional extensions will appear here when requested
                  through the approved add-on catalog.
                </EmptyState>
                <div
                  className="addon-category-grid"
                  aria-label="Planned add-on categories"
                >
                  {[
                    ["Networking", "Ingress controllers, DNS and service mesh"],
                    ["Security", "Policy engines and secrets integrations"],
                    ["Observability", "Metrics, logging and tracing agents"],
                    ["Data protection", "Backup and recovery extensions"],
                  ].map(([name, description]) => (
                    <article key={name}>
                      <strong>{name}</strong>
                      <span>{description}</span>
                      <small>Catalog integration planned</small>
                    </article>
                  ))}
                </div>
              </>
            )}
          </section>

          {canViewAccess && (
            <section className="panel panel-padding cluster-access-summary cluster-tab-panel cluster-tab-access">
              <div className="cluster-review-section-heading">
                <div>
                  <span className="eyebrow">AUTHORIZATION & RBAC</span>
                  <h2>Access assignments and Kubernetes scope</h2>
                  <p className="muted">
                    Review effective access and assignments awaiting connector
                    reconciliation.
                  </p>
                </div>
                {hasPermission(identity, "cluster.access.manage") ? (
                  <Link
                    className="button button-primary"
                    href={`/clusters/access?cluster=${row.clusterId}`}
                  >
                    Manage Authorization
                  </Link>
                ) : (
                  <span className="security-chip">View only</span>
                )}
              </div>
              <div className="cluster-operational-summary cluster-access-metrics">
                <article>
                  <span className="eyebrow">TOTAL</span>
                  <strong>{access.data?.assignments.length ?? "—"}</strong>
                  <span>Assignments</span>
                  <small>Active, pending and historical access</small>
                </article>
                <article>
                  <span className="eyebrow">ENABLED</span>
                  <strong>
                    {access.data?.assignments.filter(
                      (item) => item.status === "ACTIVE",
                    ).length ?? "—"}
                  </strong>
                  <span>Active access</span>
                  <small>Successfully reconciled to Kubernetes</small>
                </article>
                <article>
                  <span className="eyebrow">ATTENTION</span>
                  <strong>
                    {access.data?.assignments.filter(
                      (item) => item.status === "PENDING",
                    ).length ?? "—"}
                  </strong>
                  <span>Awaiting sync</span>
                  <small>Pending connector reconciliation</small>
                </article>
              </div>
              <div className="capability-list">
                <article>
                  <div>
                    <strong>WebKubectl</strong>
                    <span>
                      Start a short-lived interactive Kubernetes session using
                      the current approved access assignment.
                    </span>
                    <small>
                      {toolByCode("WEBKUBECTL")?.disabledReason ||
                        "Sessions are user-bound, time-limited and audited."}
                    </small>
                  </div>
                  {toolLaunch("WEBKUBECTL", "WebKubectl")}
                </article>
              </div>
              {access.data?.assignments.length ? (
                <div className="table-scroll cluster-node-table cluster-access-table">
                  <table>
                    <thead>
                      <tr>
                        <th>Person or team</th>
                        <th>Access profile</th>
                        <th>Scope</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {access.data.assignments.map((assignment) => (
                        <tr key={assignment.assignmentId}>
                          <td>
                            <strong>{assignment.subjectId}</strong>
                            <span className="metadata">
                              {assignment.subjectType === "GROUP"
                                ? "Team"
                                : "Individual user"}
                            </span>
                          </td>
                          <td>{assignment.profileName}</td>
                          <td>
                            {assignment.scopeType === "CLUSTER"
                              ? "Entire cluster"
                              : `Namespace: ${assignment.namespace || "Not set"}`}
                          </td>
                          <td>
                            <span
                              className={`status-badge status-${assignment.status.toLowerCase()}`}
                            >
                              {assignment.status === "ACTIVE"
                                ? "Enabled"
                                : assignment.status}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <EmptyState
                  title={
                    access.isPending
                      ? "Loading access assignments"
                      : "No access assignments"
                  }
                >
                  {access.error
                    ? "Access information is temporarily unavailable."
                    : "No Kubernetes access has been granted for this cluster."}
                </EmptyState>
              )}
            </section>
          )}

          {trackedNodeGroupRequest?.providerExecutionId &&
            !showSystemNodeGroupMigration && (
              <section className="panel panel-padding execution-console cluster-tab-panel cluster-tab-operations">
                <header>
                  <div>
                    <span className="eyebrow">NODE-GROUP EXECUTION</span>
                    <h2>{trackedNodeGroupRequest.nodeGroup.name}</h2>
                    <p className="muted">
                      Follow this governed request from approval through
                      certified planning and applied EKS capacity.
                    </p>
                  </div>
                  <span
                    className={`execution-state ${
                      nodeGroupProviderRunning ? "running" : "complete"
                    }`}
                  >
                    <span aria-hidden="true" />
                    {nodeGroupProviderRunning
                      ? `${nodeGroupDisplayStatus} · refreshing`
                      : nodeGroupDisplayStatus}
                  </span>
                </header>
                <dl className="operation-facts" aria-label="Execution summary">
                  <div>
                    <dt>Operation</dt>
                    <dd>
                      {nodeGroupLogs.data?.operation === "apply"
                        ? "Apply certified plan"
                        : "Generate certified plan"}
                    </dd>
                  </div>
                  <div>
                    <dt>Provider status</dt>
                    <dd>{nodeGroupDisplayStatus || "Loading"}</dd>
                  </div>
                  <div>
                    <dt>Last activity</dt>
                    <dd>
                      {nodeGroupLastEvent
                        ? new Date(
                            nodeGroupLastEvent.timestamp,
                          ).toLocaleTimeString([], {
                            hour: "2-digit",
                            minute: "2-digit",
                            second: "2-digit",
                          })
                        : "Waiting for events"}
                    </dd>
                  </div>
                </dl>
                <div
                  className="execution-progress"
                  aria-label="Node-group progress"
                >
                  {[
                    "Request approved",
                    "Plan certified",
                    "Capacity applied",
                  ].map((label, index) => {
                    const completed =
                      index === 0 ||
                      (index === 1 &&
                        !["SUBMITTED", "PLAN_RUNNING"].includes(
                          trackedNodeGroupRequest.status,
                        )) ||
                      (index === 2 &&
                        ["ACTIVE", "SUCCEEDED"].includes(
                          trackedNodeGroupRequest.status,
                        ));
                    const running =
                      index === 2 &&
                      nodeGroupProviderRunning &&
                      nodeGroupLogs.data?.operation === "apply";
                    return (
                      <div
                        className={
                          completed ? "complete" : running ? "running" : ""
                        }
                        key={label}
                      >
                        <span aria-hidden="true" />
                        <strong>{running ? "Capacity applying" : label}</strong>
                      </div>
                    );
                  })}
                </div>
                {nodeGroupExecutionFailed && (
                  <div
                    className="operation-outcome operation-outcome-failed"
                    role="alert"
                  >
                    <strong>Capacity was not fully applied</strong>
                    <span>
                      The certified plan started, but the provider execution did
                      not finish successfully. Review the final diagnostic
                      events before retrying.
                    </span>
                  </div>
                )}
                <details
                  className="execution-diagnostics"
                  open={nodeGroupProviderRunning}
                >
                  <summary>
                    <span>Technical execution log</span>
                    <small>
                      {nodeGroupLogs.data?.events.length || 0} provider events
                    </small>
                  </summary>
                  <div className="execution-log" role="log" aria-live="polite">
                    {nodeGroupLogs.isPending && (
                      <p>Connecting to the execution log…</p>
                    )}
                    {nodeGroupLogs.error && (
                      <p>
                        Node-group execution logs are temporarily unavailable.
                      </p>
                    )}
                    {nodeGroupLogs.data?.events.map((event, index) => (
                      <p key={`${event.timestamp}-${index}`}>
                        <time>
                          {new Date(event.timestamp).toLocaleTimeString([], {
                            hour: "2-digit",
                            minute: "2-digit",
                            second: "2-digit",
                          })}
                        </time>
                        <span>{event.message}</span>
                      </p>
                    ))}
                    {nodeGroupLogs.data &&
                      !nodeGroupLogs.data.events.length && (
                        <p>Waiting for the first execution event…</p>
                      )}
                  </div>
                </details>
              </section>
            )}
          {["ACTIVE", "BOOTSTRAPPING", "BOOTSTRAP_FAILED"].includes(
            row.status,
          ) && (
            <section className="panel panel-padding execution-console cluster-tab-panel cluster-tab-operations">
              <header>
                <div>
                  <span className="eyebrow">PLATFORM BOOTSTRAP</span>
                  <h2>
                    {row.status === "BOOTSTRAP_FAILED"
                      ? "Platform service installation failed"
                      : row.status === "ACTIVE"
                        ? "Platform services"
                        : "Installing platform services"}
                  </h2>
                  <p className="muted">
                    Navigan is installing the connector and waiting for the
                    approved platform components to report healthy.
                  </p>
                </div>
                <span
                  className={`execution-state ${
                    row.status === "BOOTSTRAP_FAILED" ? "complete" : "running"
                  }`}
                >
                  <span aria-hidden="true" />
                  {row.status === "BOOTSTRAP_FAILED"
                    ? "Installation failed"
                    : connectorReported
                      ? "Live · verifying platform health"
                      : "Live · awaiting connector"}
                </span>
              </header>
              <dl
                className="operation-facts"
                aria-label="Platform bootstrap summary"
              >
                <div>
                  <dt>Installer execution</dt>
                  <dd>{textValue(platformBootstrap.executionId, "Pending")}</dd>
                </div>
                <div>
                  <dt>Connector</dt>
                  <dd>{textValue(platformBootstrap.connectorId, "Pending")}</dd>
                </div>
                <div>
                  <dt>Started</dt>
                  <dd>
                    {typeof platformBootstrap.startedAt === "string"
                      ? formatDate(platformBootstrap.startedAt)
                      : "Pending"}
                  </dd>
                </div>
                <div>
                  <dt>Failure code</dt>
                  <dd>
                    {textValue(platformBootstrap.failureCode, "None reported")}
                  </dd>
                </div>
              </dl>
              <div
                className="execution-progress"
                aria-label="Platform bootstrap progress"
              >
                <div className="complete">
                  <span aria-hidden="true" />
                  <strong>Cluster infrastructure provisioned</strong>
                </div>
                <div
                  className={
                    connectorReported
                      ? "complete"
                      : row.status === "BOOTSTRAP_FAILED"
                        ? ""
                        : "running"
                  }
                >
                  <span aria-hidden="true" />
                  <strong>Connector installation</strong>
                </div>
                <div className={connectorReported ? "running" : ""}>
                  <span aria-hidden="true" />
                  <strong>Platform health verified</strong>
                </div>
              </div>
              {connectorReported && pendingPlatformComponents.length > 0 && (
                <div className="notice">
                  <strong>Waiting for platform components:</strong>{" "}
                  {pendingPlatformComponents
                    .map(
                      (component) =>
                        `${component.componentCode} (${component.syncStatus || component.status}, ${component.healthStatus || component.status})`,
                    )
                    .join(", ")}
                </div>
              )}
              {hasPermission(identity, "cluster.access.manage") && (
                <div className="action-row">
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={busy}
                    onClick={restartPlatformBootstrap}
                  >
                    {busy
                      ? "Restarting bootstrap…"
                      : row.status === "ACTIVE"
                        ? "Refresh platform services"
                        : "Restart platform bootstrap"}
                  </Button>
                </div>
              )}
              <p className="notice">
                The installer runs in the customer AWS account. Detailed
                customer CodeBuild events are not exposed through Navigan yet;
                use the installer execution ID above for provider-side
                diagnostics.
              </p>
            </section>
          )}
          {[
            "PLAN_RUNNING",
            "PLAN_READY",
            "FAILED",
            "APPLYING",
            "ACTIVE",
            "STOPPING",
            "STOPPED",
            "STARTING",
            "DELETING",
          ].includes(row.status) &&
            (!trackedNodeGroupRequest?.providerExecutionId ||
              showSystemNodeGroupMigration) && (
              <section className="panel panel-padding cluster-certification cluster-tab-panel cluster-tab-operations">
                <div className="cluster-review-section-heading">
                  <div>
                    <span className="eyebrow">TERRAFORM ASSURANCE</span>
                    <h2>Plan validation and certification</h2>
                    <p className="muted">
                      Apply is permitted only after the saved plan passes all
                      blocking checks.
                    </p>
                  </div>
                  <span
                    className={
                      certificationPassed
                        ? "security-chip"
                        : "security-chip needs-review"
                    }
                  >
                    {row.status === "PLAN_RUNNING"
                      ? "Checks running"
                      : certificationPassed
                        ? "Certified for apply"
                        : "Not certified"}
                  </span>
                </div>
                <div className="cluster-assurance-grid">
                  <div
                    className={
                      validation.valid === true ? "assurance-pass" : ""
                    }
                  >
                    <Check size={20} aria-hidden="true" />
                    <span>Terraform validation</span>
                    <strong>
                      {validation.valid === true
                        ? "Passed"
                        : row.status === "PLAN_RUNNING"
                          ? "Running"
                          : "Not passed"}
                    </strong>
                  </div>
                  <div
                    className={
                      securityScan.status === "PASSED" ? "assurance-pass" : ""
                    }
                  >
                    <ShieldCheck size={20} aria-hidden="true" />
                    <span>Security policy checks</span>
                    <strong>
                      {securityScan.status === "PASSED"
                        ? "No blocking findings"
                        : row.status === "PLAN_RUNNING"
                          ? "Running"
                          : `${String(securityScan.blockingFindings || 0)} blocking`}
                    </strong>
                  </div>
                  <div className={row.planSha256 ? "assurance-pass" : ""}>
                    <Network size={20} aria-hidden="true" />
                    <span>Immutable plan artifact</span>
                    <strong>
                      {row.planSha256 ? "Hash verified" : "Pending"}
                    </strong>
                  </div>
                </div>
                {planAvailable && (
                  <>
                    <dl className="details-grid cluster-plan-summary">
                      <div>
                        <dt>Planned resources</dt>
                        <dd>{String(planSummary.resourceCount || 0)}</dd>
                      </div>
                      <div>
                        <dt>Validation warnings</dt>
                        <dd>{String(validation.warningCount || 0)}</dd>
                      </div>
                      <div>
                        <dt>Blocking findings</dt>
                        <dd>{String(securityScan.blockingFindings || 0)}</dd>
                      </div>
                      <div>
                        <dt>Plan SHA-256</dt>
                        <dd className="plan-hash">{row.planSha256}</dd>
                      </div>
                    </dl>
                    {certificationPassed && row.status === "PLAN_READY" && (
                      <label className="plan-confirmation">
                        <input
                          type="checkbox"
                          checked={planConfirmed}
                          onChange={(event) =>
                            setPlanConfirmed(event.target.checked)
                          }
                        />
                        <span>
                          I reviewed this exact plan hash and confirm it is
                          ready to apply.
                        </span>
                      </label>
                    )}
                  </>
                )}
              </section>
            )}
          {showExecutionPanel &&
            (!trackedNodeGroupRequest?.providerExecutionId ||
              showSystemNodeGroupMigration) && (
              <section className="panel panel-padding execution-console cluster-tab-panel cluster-tab-operations">
                <header>
                  <div>
                    <span className="eyebrow">
                      {executionPresentation.eyebrow}
                    </span>
                    <h2>{executionTitle}</h2>
                    <p className="muted">
                      {historicalExecution
                        ? `Historical execution record. The cluster's current lifecycle state is ${clusterStatusLabel(row.status)}.`
                        : executionPresentation.description}
                    </p>
                  </div>
                  <span
                    className={`execution-state ${logs.data?.complete ? "complete" : "running"}`}
                  >
                    <span aria-hidden="true" />
                    {logs.data?.complete
                      ? "Execution finished"
                      : "Live · refreshing"}
                  </span>
                </header>
                <div
                  className="execution-progress"
                  aria-label="Execution progress"
                >
                  {executionPresentation.steps.map((label, index) => {
                    const displayLabel =
                      executionOperation === "delete" &&
                      index === 2 &&
                      executionReachedTarget
                        ? "Cluster removed"
                        : label;
                    return (
                      <div
                        className={
                          index === 0 ||
                          (index === 1 &&
                            (!logs.data?.complete || executionReachedTarget)) ||
                          (index === 2 && executionReachedTarget)
                            ? "complete"
                            : ""
                        }
                        key={label}
                      >
                        <span aria-hidden="true" />
                        <strong>{displayLabel}</strong>
                      </div>
                    );
                  })}
                </div>
                {executionFailed && (
                  <div className="error-notice" role="alert">
                    <strong>{executionPresentation.title} failed.</strong>
                    <span>
                      {logs.data?.errorCode
                        ? ` AWS reported ${logs.data.errorCode}. Review the latest execution events below.`
                        : " Review the latest execution events below for the failure reason."}
                    </span>
                  </div>
                )}
                <div className="execution-log" role="log" aria-live="polite">
                  {logs.isPending && <p>Connecting to the execution log…</p>}
                  {logs.error && <p>Live log is temporarily unavailable.</p>}
                  {logs.data?.events.map((event, index) => (
                    <p key={`${event.timestamp}-${index}`}>
                      <time>
                        {new Date(event.timestamp).toLocaleTimeString([], {
                          hour: "2-digit",
                          minute: "2-digit",
                          second: "2-digit",
                        })}
                      </time>
                      <span>{event.message}</span>
                    </p>
                  ))}
                  {logs.data && !logs.data.events.length && (
                    <p>Waiting for the first execution event…</p>
                  )}
                </div>
              </section>
            )}

          {canViewAudit && (
            <section className="panel panel-padding cluster-tab-panel cluster-tab-audit">
              <div className="cluster-review-section-heading">
                <div>
                  <span className="eyebrow">IMMUTABLE HISTORY</span>
                  <h2>Cluster audit trail</h2>
                  <p className="muted">
                    Recorded lifecycle, node-group, connector and governance
                    events with actor and correlation references.
                  </p>
                </div>
                <span className="security-chip">
                  {auditLog.data?.items.length ?? 0} events
                </span>
              </div>
              {auditLog.isPending ? (
                <Loading label="Loading audit history…" />
              ) : auditLog.error ? (
                <ErrorNotice
                  error={auditLog.error}
                  onRetry={() => auditLog.refetch()}
                />
              ) : auditLog.data?.items.length ? (
                <ol className="cluster-audit-timeline">
                  {auditLog.data.items.map((event) => (
                    <li key={event.auditId}>
                      <span
                        className="cluster-audit-marker"
                        aria-hidden="true"
                      />
                      <div className="cluster-audit-content">
                        <div>
                          <strong>
                            {event.action
                              .replace(/([a-z])([A-Z])/g, "$1 $2")
                              .replaceAll("_", " ")}
                          </strong>
                          <time>{formatDate(event.occurredAt)}</time>
                        </div>
                        <p>
                          Performed by <strong>{event.performedBy}</strong>
                        </p>
                        <small>Correlation: {event.correlationId}</small>
                      </div>
                    </li>
                  ))}
                </ol>
              ) : (
                <EmptyState title="No audit events recorded">
                  Cluster activity will appear here as governed actions occur.
                </EmptyState>
              )}
            </section>
          )}
        </main>

        {(!trackedNodeGroupRequest?.providerExecutionId ||
          showSystemNodeGroupMigration) && (
          <aside
            className={`cluster-review-aside cluster-tab-panel cluster-tab-${actionPanelTab}`}
          >
            <section className="panel panel-padding cluster-action-panel">
              <span className="eyebrow">NEXT ACTION</span>
              <h2>
                {row.status === "DRAFT"
                  ? "Submit for architecture review"
                  : row.status === "SUBMITTED"
                    ? "Begin independent review"
                    : row.status === "UNDER_REVIEW"
                      ? "Record review decision"
                      : row.status === "PLAN_RUNNING"
                        ? "Terraform checks are running"
                        : row.status === "PLAN_READY"
                          ? certificationPassed
                            ? "Confirm and apply"
                            : "Generate a certified plan"
                          : row.status === "APPLYING"
                            ? "Applying approved plan"
                            : "Request status"}
              </h2>
              <p className="muted">
                Comments are saved in the request audit history.
              </p>
              {actions.length > 0 && (
                <label className="field">
                  Action comments{" "}
                  {actions.some((action) =>
                    ["reject", "delete"].includes(action),
                  )
                    ? "*"
                    : ""}
                  <textarea
                    rows={4}
                    maxLength={4000}
                    value={actionComments}
                    onChange={(event) => setActionComments(event.target.value)}
                    placeholder="Add the reason, review notes, or implementation context."
                  />
                </label>
              )}
              <div className="cluster-action-buttons">
                {canReviewCluster && githubAuthorizationRequired && (
                  <button
                    type="button"
                    disabled={busy}
                    className="button button-primary"
                    onClick={() => void authorizeGitHubOrganization()}
                  >
                    Connect{" "}
                    {textValue(
                      systemRepository.organization,
                      "GitHub organization",
                    )}
                  </button>
                )}
                {actions.map((action) => (
                  <button
                    key={action}
                    disabled={
                      busy ||
                      (["reject", "delete"].includes(action) &&
                        !actionComments.trim()) ||
                      (action === "apply" && !planConfirmed)
                    }
                    className={
                      ["reject", "delete"].includes(action)
                        ? "button button-danger"
                        : "button button-primary"
                    }
                    onClick={() => void act(action)}
                  >
                    {action === "plan"
                      ? "Generate certified plan"
                      : action === "apply"
                        ? "Apply certified plan"
                        : action === "review"
                          ? "Start review"
                          : action === "stop"
                            ? "Stop worker capacity"
                            : action === "start"
                              ? "Start worker capacity"
                              : action === "delete"
                                ? "Delete cluster"
                                : action === "approve"
                                  ? "Approve and generate plan"
                                  : action.replace(/^./, (letter) =>
                                      letter.toUpperCase(),
                                    )}
                  </button>
                ))}
              </div>
              {actions.length === 0 && (
                <p className="notice">
                  {[
                    "PLAN_RUNNING",
                    "APPLYING",
                    "STOPPING",
                    "STARTING",
                    "DELETING",
                  ].includes(row.status)
                    ? "This page refreshes automatically as the execution progresses."
                    : "No action is currently required from your role."}
                </p>
              )}
            </section>
          </aside>
        )}
      </div>
    </div>
  );
}
