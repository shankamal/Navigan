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
  Check,
  ChevronDown,
  CloudCog,
  EllipsisVertical,
  ExternalLink,
  KeyRound,
  Network,
  Plus,
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
          <div
            ref={popup}
            className="cluster-action-popover"
            role="menu"
            aria-label={`Actions for ${cluster.clusterName}`}
            style={position}
          >
            {items}
          </div>,
          document.body,
        )}
    </div>
  );
}

const initialStatusByMode: Record<ClusterAdminMode, string | undefined> = {
  directory: undefined,
  reviews: "SUBMITTED",
  operations: "PLAN_RUNNING",
};

export function ClusterAdminPage({
  mode = "directory",
}: ClusterAdminPageProps = {}) {
  const { identity } = useAuth();
  const queryClient = useQueryClient();
  const [actionError, setActionError] = useState<unknown>();
  const operation = useMutation({
    mutationFn: async ({
      cluster,
      action,
      reason,
    }: {
      cluster: Cluster;
      action: "stop" | "start" | "delete";
      reason: string;
    }) => clusters.action(cluster.clusterId, action, cluster.version, reason),
    onSuccess: async () => {
      setActionError(undefined);
      await queryClient.invalidateQueries({ queryKey: ["clusters"] });
      await queryClient.invalidateQueries({ queryKey: ["cluster-count"] });
    },
    onError: setActionError,
  });
  const [filters, setFilters] = useState<ClusterFilters>({
    page: 0,
    pageSize: 20,
    status: initialStatusByMode[mode],
  });
  const [search, setSearch] = useState("");
  useEffect(() => {
    const timeout = setTimeout(
      () =>
        setFilters((previous) => ({
          ...previous,
          page: 0,
          search: search.trim() || undefined,
        })),
      300,
    );
    return () => clearTimeout(timeout);
  }, [search]);
  const query = useClusters(filters);
  const total = useClusterCount(undefined, mode === "directory");
  const active = useClusterCount("ACTIVE", mode !== "reviews");
  const draft = useClusterCount("DRAFT", mode === "directory");
  const submitted = useClusterCount("SUBMITTED", mode !== "operations");
  const underReview = useClusterCount("UNDER_REVIEW", mode === "reviews");
  const planReady = useClusterCount("PLAN_READY", mode === "operations");
  const applying = useClusterCount("APPLYING", mode === "operations");
  const failed = useClusterCount("FAILED", mode === "operations");
  const metrics =
    mode === "reviews"
      ? [
          { label: "Submitted", value: submitted.data, icon: ShieldCheck },
          { label: "Under review", value: underReview.data, icon: Search },
        ]
      : mode === "operations"
        ? [
            { label: "Plan ready", value: planReady.data, icon: ShieldCheck },
            { label: "Applying", value: applying.data, icon: CloudCog },
            { label: "Failed", value: failed.data, icon: Network },
            { label: "Active", value: active.data, icon: Check },
          ]
        : [
            { label: "Total requests", value: total.data, icon: Network },
            { label: "Active", value: active.data, icon: Check },
            { label: "Submitted", value: submitted.data, icon: ShieldCheck },
            { label: "Drafts", value: draft.data, icon: CloudCog },
          ];
  const availableStatuses =
    mode === "reviews"
      ? ["SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED"]
      : mode === "operations"
        ? ["PLAN_RUNNING", "PLAN_READY", "APPLYING", "FAILED", "ACTIVE"]
        : Object.keys(statusLabels);
  const reset = () => {
    setSearch("");
    setFilters({
      page: 0,
      pageSize: 20,
      status: initialStatusByMode[mode],
    });
  };
  const filter = (values: Partial<ClusterFilters>) =>
    setFilters((old) => ({ ...old, ...values, page: 0 }));
  const runAction = (cluster: Cluster, action: ClusterAction) => {
    const operationCode = directOperations[action.code];
    if (!operationCode || !action.enabled) return;
    const reason =
      operationCode === "delete"
        ? window
            .prompt("Provide the required reason for deleting this cluster:")
            ?.trim()
        : clusterActionLabel(action);
    if (!reason) return;
    if (action.confirmation && !window.confirm(action.confirmation)) return;
    setActionError(undefined);
    operation.mutate({
      cluster,
      action: operationCode,
      reason,
    });
  };
  return (
    <>
      <PageHeading
        eyebrow="CONTAINER PROVISIONING"
        title={
          mode === "reviews"
            ? "Cluster Reviews"
            : mode === "operations"
              ? "Cluster Operations"
              : "Cluster Setup Requests"
        }
        description={
          mode === "reviews"
            ? "Review submitted cluster requests and record independent architecture decisions."
            : mode === "operations"
              ? "Monitor Terraform planning, certified plans, apply activity, failures, and active clusters."
              : "Track cluster setup requests across their complete governed lifecycle."
        }
        action={
          mode === "directory" &&
          hasPermission(identity, "cluster.create") && (
            <Link className="button button-primary" href="/clusters/new">
              <Plus size={18} /> New Cluster Setup
            </Link>
          )
        }
      />
      {actionError && <ErrorNotice error={actionError} />}
      <div className="metrics-grid">
        {metrics.map((metric) => (
          <div className="metric" key={metric.label}>
            <div className="metric-label">
              {metric.label}
              <metric.icon size={20} aria-hidden="true" />
            </div>
            <strong>{metric.value ?? "—"}</strong>
          </div>
        ))}
      </div>
      <section className="panel">
        <div className="list-heading">
          <div>
            <h2>
              {mode === "reviews"
                ? "Cluster review queue"
                : mode === "operations"
                  ? "Cluster execution queue"
                  : "Cluster setup requests"}
            </h2>
            <p className="muted">
              {mode === "reviews"
                ? "Submitted requests are shown first. Use the status filter to inspect requests already under review."
                : mode === "operations"
                  ? "Planning requests are shown first. Use the status filter to inspect ready, applying, failed, or active requests."
                  : "Requests pinned to an approved environment baseline."}
            </p>
          </div>
        </div>
        <div className="filter-bar">
          <label className="search-field">
            <Search size={18} aria-hidden="true" />
            <span className="sr-only">Search by cluster name or ID</span>
            <input
              value={search}
              maxLength={255}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search by cluster name or ID"
              type="search"
            />
          </label>
          <label className="filter-field">
            <span className="sr-only">Filter by status</span>
            <select
              aria-label="Filter by status"
              value={filters.status ?? ""}
              onChange={(event) =>
                filter({ status: event.target.value || undefined })
              }
            >
              {mode === "directory" && <option value="">All statuses</option>}
              {availableStatuses.map((value) => (
                <option key={value} value={value}>
                  {statusLabels[value]}
                </option>
              ))}
            </select>
          </label>
        </div>
        {query.isPending ? (
          <Loading label="Loading cluster setup requests…" />
        ) : query.isError ? (
          <div className="panel-padding">
            <ErrorNotice error={query.error} onRetry={() => query.refetch()} />
          </div>
        ) : query.data.items.length === 0 ? (
          <EmptyState
            icon={<Network size={28} />}
            title={
              mode === "reviews"
                ? "No cluster requests in this review state"
                : mode === "operations"
                  ? "No cluster executions in this state"
                  : filters.status || search
                    ? "No matching cluster setup requests"
                    : "No cluster setup requests yet"
            }
            action={
              filters.status || search ? (
                <Button variant="secondary" onClick={reset}>
                  Clear filters
                </Button>
              ) : mode === "directory" &&
                hasPermission(identity, "cluster.create") ? (
                <Link className="button button-primary" href="/clusters/new">
                  New Cluster Setup
                </Link>
              ) : undefined
            }
          >
            {filters.status || search
              ? mode === "directory"
                ? "Try another name, ID, or status."
                : "Choose another status or return when new work enters this queue."
              : "Create a cluster setup request against an approved environment."}
          </EmptyState>
        ) : (
          <>
            <div className="table-scroll">
              <table className="customer-table">
                <caption className="sr-only">
                  Cluster setup requests matching the current filters
                </caption>
                <thead>
                  <tr>
                    <th>Cluster</th>
                    <th>Environment</th>
                    <th>Customer</th>
                    <th>Status</th>
                    <th>Updated</th>
                    <th>
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {query.data.items.map((row) => (
                    <tr key={row.clusterId}>
                      <td>
                        <Link href={"/clusters/" + row.clusterId}>
                          <strong>{row.clusterName}</strong>
                        </Link>
                      </td>
                      <td>
                        {row.environmentName || row.environmentId}
                        <div className="metadata">
                          Approved v{row.environmentApprovedVersion}
                        </div>
                      </td>
                      <td>{row.customerName || row.customerId}</td>
                      <td>
                        <span
                          className={
                            "status-badge status-" + row.status.toLowerCase()
                          }
                        >
                          {clusterStatusLabel(row.status)}
                        </span>
                      </td>
                      <td>{formatDate(row.updatedAt)}</td>
                      <td className="cluster-actions-cell">
                        <ClusterActionMenu
                          cluster={row}
                          busy={
                            operation.isPending &&
                            operation.variables?.cluster.clusterId ===
                              row.clusterId
                          }
                          onAction={runAction}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="list-footer">
              <Pagination
                {...query.data.pagination}
                onChange={(page) => setFilters((old) => ({ ...old, page }))}
                disabled={query.isFetching}
              />
            </div>
          </>
        )}
      </section>
    </>
  );
}

const defaultNodeGroup = (
  index = 0,
  clusterName = "",
): ClusterNodeGroupInput => ({
  name: recommendedNodeGroupName(clusterName, index),
  purpose: index === 0 ? "SYSTEM" : "APPLICATION",
  instanceTypes: [],
  capacityType: "ON_DEMAND",
  minSize: 1,
  desiredSize: 1,
  maxSize: 2,
  diskSizeGiB: 50,
});

const defaults: ClusterInput = {
  environmentId: "",
  environmentApprovedVersion: 0,
  blueprintName: "",
  clusterName: "",
  kubernetesVersion: "",
  endpointAccess: "PRIVATE",
  nodeGroups: [defaultNodeGroup()],
  provisioningRoleArn: "",
  externalIdSecretArn: "",
  tags: {},
  description: "",
  githubOrganization: "",
};

export function NewClusterPage() {
  const router = useRouter();
  const [value, setValue] = useState(defaults);
  const [customerId, setCustomerId] = useState("");
  const [customerSearch, setCustomerSearch] = useState("");
  const [error, setError] = useState<unknown>();
  const [saving, setSaving] = useState(false);
  const customers = useQuery({
    queryKey: ["active-customers-for-cluster-setup", customerSearch],
    queryFn: () =>
      customersService.list({
        page: 0,
        pageSize: 100,
        sort: "name,asc",
        status: "ACTIVE",
        search: customerSearch || undefined,
      }),
    staleTime: 60000,
  });
  const envs = useQuery({
    queryKey: ["active-eks-environments", customerId],
    queryFn: () =>
      environments.list({
        page: 0,
        pageSize: 100,
        sort: "environmentName,asc",
        approvedStatus: "ACTIVE",
        cloudProvider: "AWS",
        customerId,
      }),
    enabled: Boolean(customerId),
    staleTime: 60000,
  });
  const selectedEnvironment = useQuery({
    queryKey: [
      "cluster-platform-environment-approved-version",
      value.environmentId,
      value.environmentApprovedVersion,
    ],
    queryFn: () =>
      environments.version(
        value.environmentId,
        value.environmentApprovedVersion,
      ),
    enabled: Boolean(value.environmentId && value.environmentApprovedVersion),
    staleTime: 60000,
  });
  const liveProvisioningOptions = useQuery({
    queryKey: ["cluster-provisioning-options", value.environmentId],
    queryFn: () => environments.provisioningOptions(value.environmentId),
    enabled: Boolean(value.environmentId),
    staleTime: 60000,
  });
  const baseline = objectValue(selectedEnvironment.data?.configuration);
  const account = objectValue(baseline.account);
  const location = objectValue(baseline.location);
  const network = objectValue(baseline.network);
  const vpc = objectValue(network.vpc);
  const extensions = objectValue(baseline.extensions);
  const discovery = objectValue(extensions.discovery);
  const contract = objectValue(extensions.provisioningContract);
  const clusterSubnets = Array.isArray(network.clusterSubnets)
    ? network.clusterSubnets
    : [];
  const nodeSubnets = Array.isArray(network.nodeSubnets)
    ? network.nodeSubnets
    : [];
  const approvedBlueprints = arrayValue(baseline.clusters);
  const approvedDefaultBlueprint =
    approvedBlueprints.find(
      (item) =>
        item.isDefault === true ||
        textValue(item.name, "").toLowerCase() === "default",
    ) || (approvedBlueprints.length === 1 ? approvedBlueprints[0] : undefined);
  const resolvedBlueprint = approvedDefaultBlueprint || {
    name: "environment-default",
    displayName: "Approved environment defaults",
    endpointAccess: "PRIVATE",
  };
  const legacyBlueprint =
    approvedBlueprints.find(
      (item) => textValue(item.name, "") === value.blueprintName,
    ) || approvedDefaultBlueprint;
  const legacyProvisioning = objectValue(legacyBlueprint?.provisioning);
  const blueprintKubernetesVersion =
    typeof legacyBlueprint?.kubernetesVersion === "string"
      ? legacyBlueprint.kubernetesVersion
      : "";
  const kubernetesVersions = Array.from(
    new Set([
      ...(Array.isArray(contract.kubernetesVersions)
        ? supportedEksVersions(contract.kubernetesVersions)
        : []),
      ...(blueprintKubernetesVersion ? [blueprintKubernetesVersion] : []),
    ]),
  ).sort((left, right) =>
    right.localeCompare(left, undefined, { numeric: true }),
  );
  const approvedEndpointAccess =
    textValue(legacyBlueprint?.endpointAccess, "PRIVATE") ===
    "PUBLIC_AND_PRIVATE"
      ? ["PRIVATE", "PUBLIC_AND_PRIVATE"]
      : ["PRIVATE"];
  const instanceTypes = Array.isArray(contract.instanceTypes)
    ? contract.instanceTypes
        .map((item) =>
          typeof item === "string" ? item : objectValue(item).instanceType,
        )
        .filter((item): item is string => typeof item === "string")
    : arrayValue(legacyBlueprint?.nodeGroups)
        .flatMap((group) =>
          Array.isArray(group.instanceTypes) ? group.instanceTypes : [],
        )
        .filter((item): item is string => typeof item === "string");
  const provisioningRoles = Array.isArray(contract.provisioningRoles)
    ? arrayValue(contract.provisioningRoles)
    : legacyProvisioning.roleArn
      ? [
          {
            roleArn: legacyProvisioning.roleArn,
            roleName: "NaviganProvisioningRole",
          },
        ]
      : [];
  const provisioningSecrets = approvedProvisioningSecrets(
    liveProvisioningOptions.data?.provisioningSecrets,
    contract.provisioningSecrets,
    discovery.provisioningSecrets,
    baseline.provisioningSecrets,
    legacyProvisioning.externalIdSecretArn
      ? [
          {
            arn: legacyProvisioning.externalIdSecretArn,
            name: "Provisioning external ID",
          },
        ]
      : [],
  );
  useEffect(() => {
    if (
      !selectedEnvironment.data ||
      value.blueprintName ||
      (approvedBlueprints.length > 1 && !approvedDefaultBlueprint)
    )
      return;
    const blueprint = resolvedBlueprint;
    const systemGroup = arrayValue(blueprint.nodeGroups)[0];
    setValue((current) => ({
      ...current,
      blueprintName: textValue(blueprint.name),
      kubernetesVersion:
        textValue(blueprint.kubernetesVersion, "") ||
        kubernetesVersions[0] ||
        "",
      endpointAccess:
        textValue(blueprint.endpointAccess, "PRIVATE") === "PUBLIC_AND_PRIVATE"
          ? "PUBLIC_AND_PRIVATE"
          : "PRIVATE",
      nodeGroups: systemGroup
        ? [
            {
              name: textValue(systemGroup.name, "system-ng"),
              purpose: "SYSTEM",
              instanceTypes: Array.isArray(systemGroup.instanceTypes)
                ? systemGroup.instanceTypes.filter(
                    (item): item is string => typeof item === "string",
                  )
                : [],
              capacityType: "ON_DEMAND",
              minSize: Number(systemGroup.minSize ?? 2),
              desiredSize: Number(systemGroup.desiredSize ?? 2),
              maxSize: Number(systemGroup.maxSize ?? 4),
              diskSizeGiB: Number(systemGroup.diskSizeGiB ?? 50),
            },
          ]
        : [
            {
              ...defaultNodeGroup(0, current.clusterName),
              minSize: 2,
              desiredSize: 2,
              maxSize: 4,
            },
          ],
    }));
  }, [selectedEnvironment.data, value.blueprintName]);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(undefined);
    try {
      const created = await clusters.create({
        ...value,
        description: value.description?.trim() || undefined,
      });
      router.push("/clusters/" + created.clusterId);
    } catch (caught) {
      setError(caught);
    } finally {
      setSaving(false);
    }
  };
  return (
    <>
      <PageHeading
        eyebrow="CONTAINER PROVISIONING"
        title="New Cluster Setup"
        description="Select an approved environment baseline, then define the Kubernetes control plane, worker capacity, scaling, storage and provisioning access for this cluster request."
      />
      {customers.error && (
        <ErrorNotice
          error={customers.error}
          onRetry={() => customers.refetch()}
        />
      )}
      {envs.error && (
        <ErrorNotice error={envs.error} onRetry={() => envs.refetch()} />
      )}
      {Boolean(error) && <ErrorNotice error={error} />}
      {error instanceof ApiError && Array.isArray(error.details?.fields) && (
        <ul className="notice notice-error cluster-validation-fields">
          {(
            error.details.fields as {
              field?: string;
              message?: string;
            }[]
          ).map((item, index) => (
            <li key={`${item.field}-${index}`}>
              <strong>{item.field || "Request"}:</strong>{" "}
              {item.message || "Invalid value"}
            </li>
          ))}
        </ul>
      )}
      <form
        className="panel panel-padding cluster-setup-form"
        onSubmit={submit}
      >
        <div className="cluster-setup-heading">
          <div>
            <span className="eyebrow">APPROVED BASELINE</span>
            <h2>Select the environment profile</h2>
            <p className="muted">
              Only profiles with an ACTIVE approved AWS/EKS baseline are
              available. The approved version is pinned permanently to this
              request.
            </p>
          </div>
          <span className="cluster-setup-heading-icon">
            <ShieldCheck aria-hidden="true" />
          </span>
        </div>
        <div className="cluster-setup-grid">
          <label className="field cluster-field-span">
            Find customer
            <input
              value={customerSearch}
              onChange={(event) => setCustomerSearch(event.target.value)}
              placeholder="Search active customers by name"
            />
          </label>
          <label className="field">
            Active customer *
            <select
              required
              value={customerId}
              onChange={(event) => {
                setCustomerId(event.target.value);
                setValue((current) => ({
                  ...current,
                  environmentId: "",
                  environmentApprovedVersion: 0,
                  blueprintName: "",
                  kubernetesVersion: "",
                  nodeGroups: [defaultNodeGroup()],
                  provisioningRoleArn: "",
                  externalIdSecretArn: "",
                  githubOrganization: "",
                }));
              }}
            >
              <option value="">Select ACTIVE customer</option>
              {customers.data?.items.map((c) => (
                <option value={c.customerId} key={c.customerId}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            Active environment *
            <select
              required
              disabled={!customerId}
              value={value.environmentId}
              onChange={(event) => {
                const env = envs.data?.items.find(
                  (item) => item.environmentId === event.target.value,
                );
                setValue((current) => ({
                  ...current,
                  environmentId: event.target.value,
                  environmentApprovedVersion: env?.approvedVersion || 0,
                  blueprintName: "",
                  kubernetesVersion: "",
                  nodeGroups: [defaultNodeGroup()],
                  provisioningRoleArn: "",
                  externalIdSecretArn: "",
                }));
              }}
            >
              <option value="">
                {customerId
                  ? "Select ACTIVE EKS environment"
                  : "Select a customer first"}
              </option>
              {envs.data?.items.map((env) => (
                <option value={env.environmentId} key={env.environmentId}>
                  {env.environmentName} · approved v{env.approvedVersion}
                  {env.status !== "ACTIVE"
                    ? ` · revision ${env.status.toLowerCase()}`
                    : ""}
                </option>
              ))}
            </select>
            {customerId && !envs.isPending && envs.data?.items.length === 0 && (
              <small className="muted">
                This customer has no active approved AWS/EKS baselines yet.
              </small>
            )}
          </label>
          {value.environmentId && (
            <div className="cluster-baseline-card cluster-field-span">
              {selectedEnvironment.isPending ? (
                <Loading label="Loading approved environment baseline…" />
              ) : selectedEnvironment.error ? (
                <ErrorNotice
                  error={selectedEnvironment.error}
                  onRetry={() => selectedEnvironment.refetch()}
                />
              ) : (
                <>
                  <div className="cluster-baseline-title">
                    <Check size={18} />
                    <strong>{selectedEnvironment.data?.environmentName}</strong>
                    <span>Approved v{value.environmentApprovedVersion}</span>
                  </div>
                  <dl className="cluster-baseline-grid">
                    <div>
                      <dt>AWS account</dt>
                      <dd>{textValue(account.accountId)}</dd>
                    </div>
                    <div>
                      <dt>Region</dt>
                      <dd>{textValue(location.region)}</dd>
                    </div>
                    <div>
                      <dt>VPC</dt>
                      <dd>{textValue(vpc.vpcId)}</dd>
                    </div>
                    <div>
                      <dt>Approved subnets</dt>
                      <dd>
                        {clusterSubnets.length} cluster · {nodeSubnets.length}{" "}
                        node
                      </dd>
                    </div>
                  </dl>
                  <span className="security-chip">
                    Reusable infrastructure baseline ready
                  </span>
                  <p className="metadata">
                    Terraform uses this immutable approved snapshot—not the
                    current editable environment record.
                  </p>
                </>
              )}
            </div>
          )}
          <div className="cluster-baseline-card cluster-field-span">
            <strong>Approved cluster configuration</strong>
            <p className="metadata">
              Navigan automatically applies system capacity, networking and
              security policy from approved environment revision{" "}
              {value.environmentApprovedVersion}.
            </p>
            <span className="security-chip">
              {textValue(
                resolvedBlueprint.displayName,
                textValue(resolvedBlueprint.name),
              )}
            </span>
            {approvedBlueprints.length > 1 && !approvedDefaultBlueprint && (
              <small className="field-error">
                Multiple blueprints exist without an approved default. Update
                the environment before requesting a cluster.
              </small>
            )}
          </div>
          <label className="field">
            Cluster name *
            <input
              required
              value={value.clusterName}
              onChange={(event) => {
                const clusterName = event.target.value;
                setValue((current) => ({
                  ...current,
                  clusterName,
                  nodeGroups: current.nodeGroups.map((group, index) => {
                    const previousRecommendation = recommendedNodeGroupName(
                      current.clusterName,
                      index,
                    );
                    return group.name === previousRecommendation
                      ? {
                          ...group,
                          name: recommendedNodeGroupName(clusterName, index),
                        }
                      : group;
                  }),
                }));
              }}
            />
          </label>
          <label className="field">
            Kubernetes version *
            <select
              required
              disabled={!value.blueprintName || kubernetesVersions.length === 0}
              value={value.kubernetesVersion}
              onChange={(event) =>
                setValue({ ...value, kubernetesVersion: event.target.value })
              }
            >
              <option value="">Select an available EKS version</option>
              {kubernetesVersions.map((version) => (
                <option value={version} key={version}>
                  {version}
                </option>
              ))}
            </select>
          </label>
          <div className="field">
            <span>API endpoint policy</span>
            <div className="cluster-baseline-card">
              <strong>
                {approvedEndpointAccess.includes("PUBLIC_AND_PRIVATE")
                  ? "Public and private"
                  : "Private only"}
              </strong>
              <small>
                Enforced by the approved environment security policy.
              </small>
            </div>
          </div>
          <label className="field">
            Description
            <textarea
              rows={3}
              maxLength={4000}
              value={value.description}
              placeholder="Why is this cluster needed? Add any context for the reviewing architect."
              onChange={(event) =>
                setValue({ ...value, description: event.target.value })
              }
            />
          </label>
          <fieldset className="cluster-field-span blueprint-section">
            <legend>System repository</legend>
            <p className="muted">
              Navigan creates one private GitOps repository for this cluster’s
              approved platform services. Organization authorization is
              completed through the Navigan GitHub App after the request is
              approved.
            </p>
            <div className="cluster-setup-grid">
              <label className="field">
                GitHub organization *
                <input
                  required
                  maxLength={39}
                  pattern="[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?"
                  value={value.githubOrganization}
                  placeholder="customer-github-org"
                  onChange={(event) =>
                    setValue({
                      ...value,
                      githubOrganization: event.target.value,
                    })
                  }
                />
                <small>
                  Do not enter a token. An organization owner installs the
                  GitHub App using GitHub’s authorization screen.
                </small>
              </label>
              <div className="cluster-baseline-card">
                <strong>Private repository</strong>
                <p className="metadata">
                  The repository name is derived from the customer and cluster,
                  ending in <code>-system</code>.
                </p>
                <span className="security-chip">
                  Short-lived GitHub App credentials
                </span>
              </div>
            </div>
          </fieldset>
          <fieldset className="cluster-field-span blueprint-section">
            <legend>System node group</legend>
            <p className="muted">
              Every cluster starts with one protected, on-demand worker pool for
              the connector and mandatory platform services. Application node
              groups are requested after cluster onboarding.
            </p>
            {value.nodeGroups.map((group, index) => (
              <div className="cluster-blueprint-card" key={index}>
                <div className="cluster-setup-grid">
                  <div className="field">
                    <span>Purpose</span>
                    <div className="cluster-policy-value">
                      <strong>System platform services</strong>
                      <small>Defined by the approved platform baseline</small>
                    </div>
                  </div>
                  <label className="field">
                    Node group name *
                    <input
                      required
                      value={group.name}
                      placeholder={recommendedNodeGroupName(
                        value.clusterName,
                        index,
                      )}
                      onChange={(event) =>
                        setValue((current) => ({
                          ...current,
                          nodeGroups: current.nodeGroups.map(
                            (item, itemIndex) =>
                              itemIndex === index
                                ? { ...item, name: event.target.value }
                                : item,
                          ),
                        }))
                      }
                    />
                  </label>
                  <label className="field">
                    EC2 instance type *
                    <select
                      required
                      value={group.instanceTypes[0] || ""}
                      onChange={(event) =>
                        setValue((current) => ({
                          ...current,
                          nodeGroups: current.nodeGroups.map(
                            (item, itemIndex) =>
                              itemIndex === index
                                ? {
                                    ...item,
                                    instanceTypes: event.target.value
                                      ? [event.target.value]
                                      : [],
                                  }
                                : item,
                          ),
                        }))
                      }
                    >
                      <option value="">Select a regional instance type</option>
                      {instanceTypes.map((instanceType) => (
                        <option value={instanceType} key={instanceType}>
                          {instanceType}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="field">
                    Capacity type *
                    <select
                      value={group.capacityType}
                      disabled
                      onChange={(event) =>
                        setValue((current) => ({
                          ...current,
                          nodeGroups: current.nodeGroups.map(
                            (item, itemIndex) =>
                              itemIndex === index
                                ? {
                                    ...item,
                                    capacityType: event.target.value as
                                      "ON_DEMAND" | "SPOT",
                                  }
                                : item,
                          ),
                        }))
                      }
                    >
                      <option value="ON_DEMAND">On-demand</option>
                      <option value="SPOT">Spot</option>
                    </select>
                  </label>
                  {(
                    [
                      ["minSize", "Minimum nodes"],
                      ["desiredSize", "Desired nodes"],
                      ["maxSize", "Maximum nodes"],
                      ["diskSizeGiB", "Disk size (GiB)"],
                    ] as const
                  ).map(([key, label]) => (
                    <label className="field" key={key}>
                      {label} *
                      <input
                        required
                        type="number"
                        min={
                          key === "diskSizeGiB" ? 20 : key === "maxSize" ? 1 : 0
                        }
                        max={key === "diskSizeGiB" ? 16384 : 1000}
                        value={group[key]}
                        onChange={(event) =>
                          setValue((current) => ({
                            ...current,
                            nodeGroups: current.nodeGroups.map(
                              (item, itemIndex) =>
                                itemIndex === index
                                  ? {
                                      ...item,
                                      [key]: Number(event.target.value),
                                    }
                                  : item,
                            ),
                          }))
                        }
                      />
                    </label>
                  ))}
                </div>
              </div>
            ))}
          </fieldset>
          <fieldset className="cluster-field-span blueprint-section">
            <legend>Provisioning access</legend>
            <div className="cluster-setup-grid">
              <label className="field">
                Provisioning role ARN *
                <select
                  required
                  value={value.provisioningRoleArn}
                  onChange={(event) =>
                    setValue({
                      ...value,
                      provisioningRoleArn: event.target.value,
                    })
                  }
                >
                  <option value="">Select an approved role</option>
                  {provisioningRoles.map((role) => (
                    <option
                      value={String(role.roleArn)}
                      key={String(role.roleArn)}
                    >
                      {String(role.roleName || role.roleArn)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                External ID secret ARN *
                <select
                  required
                  disabled={liveProvisioningOptions.isPending}
                  value={value.externalIdSecretArn}
                  onChange={(event) =>
                    setValue({
                      ...value,
                      externalIdSecretArn: event.target.value,
                    })
                  }
                >
                  <option value="">Select an approved secret</option>
                  {provisioningSecrets.map((secret) => (
                    <option value={String(secret.arn)} key={String(secret.arn)}>
                      {String(secret.name || secret.arn)}
                    </option>
                  ))}
                </select>
                {liveProvisioningOptions.isPending && (
                  <small className="muted">
                    Loading registered provisioning secrets…
                  </small>
                )}
                {!liveProvisioningOptions.isPending &&
                  provisioningSecrets.length === 0 && (
                    <small className="field-error">
                      No External ID secret is registered for this customer.
                      Complete or verify the environment bootstrap first.
                    </small>
                  )}
              </label>
            </div>
          </fieldset>
        </div>
        <div className="form-actions cluster-setup-actions">
          <Link className="button button-secondary" href="/clusters">
            Cancel
          </Link>
          <button
            className="button button-primary"
            disabled={
              saving ||
              !value.environmentApprovedVersion ||
              !value.kubernetesVersion ||
              !value.provisioningRoleArn ||
              !value.externalIdSecretArn ||
              !value.githubOrganization ||
              value.nodeGroups.some(
                (group) =>
                  !group.name ||
                  !group.instanceTypes.length ||
                  group.minSize > group.desiredSize ||
                  group.desiredSize > group.maxSize,
              ) ||
              selectedEnvironment.isPending
            }
          >
            {saving ? "Saving…" : "Save setup request draft"}
          </button>
        </div>
      </form>
    </>
  );
}

export function ClusterAccessPage({
  initialClusterId = "",
}: {
  initialClusterId?: string;
}) {
  const { identity } = useAuth();
  const queryClient = useQueryClient();
  const canManage = hasPermission(identity, "cluster.access.manage");
  const clusterId = initialClusterId;
  const cluster = useQuery({
    queryKey: ["cluster", clusterId],
    queryFn: () => clusters.get(clusterId),
    enabled: Boolean(clusterId) && canManage,
    retry: false,
  });
  const [subjectType, setSubjectType] = useState<"USER" | "GROUP">("GROUP");
  const [selectedSubjects, setSelectedSubjects] = useState<string[]>([]);
  const [subjectSearch, setSubjectSearch] = useState("");
  const [identityPickerOpen, setIdentityPickerOpen] = useState(false);
  const [profileCode, setProfileCode] = useState("");
  const [namespace, setNamespace] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<unknown>();
  const [connectorInstallation, setConnectorInstallation] = useState<{
    connectorId: string;
    executionId: string;
  }>();
  const access = useQuery({
    queryKey: ["cluster-access", clusterId],
    queryFn: () => clusters.access(clusterId),
    enabled: Boolean(clusterId) && canManage,
    retry: false,
    refetchInterval: (query) =>
      query.state.data?.assignments.some(
        (assignment) => assignment.status === "PENDING",
      )
        ? 5000
        : false,
  });
  const directory = useQuery({
    queryKey: ["cluster-access-subjects", clusterId],
    queryFn: () => clusters.accessSubjects(clusterId),
    enabled: Boolean(clusterId) && canManage,
    staleTime: 60_000,
    retry: false,
  });
  const selectedProfile = access.data?.profiles.find(
    (profile) => profile.profileCode === profileCode,
  );
  const namespaceInventory = useQuery({
    queryKey: ["cluster-access-namespaces", clusterId],
    queryFn: () => clusters.accessNamespaces(clusterId),
    enabled: Boolean(clusterId) && canManage,
    staleTime: 30_000,
    retry: false,
    refetchInterval: (query) =>
      connectorInstallation && query.state.data?.status !== "READY"
        ? 5000
        : false,
  });
  const hasPendingAssignments =
    access.data?.assignments.some(
      (assignment) => assignment.status === "PENDING",
    ) ?? false;
  const subjects =
    subjectType === "USER"
      ? (directory.data?.users ?? [])
      : (directory.data?.groups ?? []);
  const normalizedSearch = subjectSearch.trim().toLowerCase();
  const visibleSubjects = subjects.filter((subject) =>
    [
      subject.displayName,
      subject.email,
      subject.username,
      subject.description,
      ...subject.aliases,
    ]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(normalizedSearch)),
  );
  const assignmentsBySubject = new Map(
    access.data?.assignments.map((assignment) => [
      `${assignment.subjectType}:${assignment.subjectId}`,
      assignment,
    ]),
  );
  const subjectNames = new Map(
    [...(directory.data?.users ?? []), ...(directory.data?.groups ?? [])].map(
      (subject) => [
        `${subject.type}:${subject.id}`,
        identityDisplayName(subject),
      ],
    ),
  );
  const assign = useMutation({
    mutationFn: async () => {
      if (
        !clusterId ||
        !profileCode ||
        !selectedSubjects.length ||
        !reason.trim()
      )
        return;
      for (const subjectId of selectedSubjects) {
        await clusters.assignAccess(clusterId, {
          subjectType,
          subjectId,
          profileCode,
          namespace:
            selectedProfile?.scopeType === "NAMESPACE"
              ? namespace.trim()
              : undefined,
          reason: reason.trim(),
        });
      }
    },
    onSuccess: async () => {
      setError(undefined);
      setSelectedSubjects([]);
      setReason("");
      await queryClient.invalidateQueries({
        queryKey: ["cluster-access", clusterId],
      });
    },
    onError: setError,
  });
  const revoke = useMutation({
    mutationFn: async (assignmentId: string) => {
      const revokeReason = window
        .prompt("Why should this Kubernetes access be revoked?")
        ?.trim();
      if (!revokeReason) return;
      await clusters.revokeAccess(clusterId, assignmentId, revokeReason);
    },
    onSuccess: async () =>
      queryClient.invalidateQueries({
        queryKey: ["cluster-access", clusterId],
      }),
    onError: setError,
  });
  const installConnector = useMutation({
    mutationFn: async () => {
      if (!cluster.data) return;
      const reinstalling = Boolean(namespaceInventory.data?.connectorId);
      if (
        !window.confirm(
          reinstalling
            ? "Retry the secure platform bootstrap for this cluster?"
            : "Complete the one-time secure platform bootstrap for this legacy cluster?",
        )
      )
        return;
      return clusters.installConnector(
        clusterId,
        cluster.data.version,
        reinstalling
          ? "Authorized retry of secure platform bootstrap"
          : "Legacy cluster migration to automatic platform bootstrap",
      );
    },
    onSuccess: async (value) => {
      if (!value) return;
      setError(undefined);
      setConnectorInstallation({
        connectorId: value.connectorId,
        executionId: value.executionId,
      });
      await namespaceInventory.refetch();
    },
    onError: setError,
  });
  const toggleSubject = (subjectId: string) =>
    setSelectedSubjects((current) =>
      current.includes(subjectId)
        ? current.filter((item) => item !== subjectId)
        : [...current, subjectId],
    );
  if (!canManage) {
    return (
      <ErrorNotice
        error={{
          status: 403,
          code: "PERMISSION_DENIED",
          message: "You do not have permission to manage Kubernetes access.",
        }}
      />
    );
  }
  if (!clusterId) {
    return (
      <ErrorNotice
        error={{
          status: 400,
          code: "CLUSTER_REQUIRED",
          message:
            "Open Kubernetes access from a cluster's three-dot action menu.",
        }}
      />
    );
  }
  return (
    <>
      <PageHeading
        className="cluster-access-page-heading"
        eyebrow="KUBERNETES GOVERNANCE"
        title={
          cluster.data
            ? `Authorization · ${cluster.data.clusterName}`
            : "Kubernetes Authorization"
        }
        description={
          cluster.data
            ? `${cluster.data.customerName || cluster.data.customerId} · ${
                cluster.data.environmentName || cluster.data.environmentId
              }`
            : "Grant least-privilege access to people and teams."
        }
      />
      {error && <ErrorNotice error={error} />}
      {hasPendingAssignments &&
        namespaceInventory.data?.status === "READY" &&
        namespaceInventory.data.connectorId && (
          <div className="namespace-inventory-state connector-upgrade-notice">
            <strong>Access reconciliation update available</strong>
            <span>
              Update the cluster connector so pending Kubernetes access can be
              applied and confirmed automatically.
            </span>
            <Button
              type="button"
              variant="secondary"
              disabled={installConnector.isPending}
              onClick={() => installConnector.mutate()}
            >
              {installConnector.isPending
                ? "Starting connector update…"
                : "Update cluster connector"}
            </Button>
          </div>
        )}
      {cluster.error ? (
        <ErrorNotice error={cluster.error} onRetry={() => cluster.refetch()} />
      ) : (
        <div className="access-workspace-grid">
          <section className="panel panel-padding access-workspace">
            <div className="access-workspace-heading">
              <div className="access-step-number">1</div>
              <div>
                <h2>Choose people or teams</h2>
                <p className="muted">
                  Identities are loaded securely from the configured Cognito
                  user pool.
                </p>
              </div>
            </div>
            <div className="access-subject-tabs" role="tablist">
              <button
                type="button"
                role="tab"
                aria-selected={subjectType === "GROUP"}
                className={subjectType === "GROUP" ? "selected" : ""}
                onClick={() => {
                  setSubjectType("GROUP");
                  setSelectedSubjects([]);
                  setSubjectSearch("");
                  setIdentityPickerOpen(false);
                }}
              >
                <UsersRound size={18} /> Teams
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={subjectType === "USER"}
                className={subjectType === "USER" ? "selected" : ""}
                onClick={() => {
                  setSubjectType("USER");
                  setSelectedSubjects([]);
                  setSubjectSearch("");
                  setIdentityPickerOpen(false);
                }}
              >
                <UserRound size={18} /> Individual users
              </button>
            </div>
            {directory.isPending ? (
              <Loading label="Loading identity directory…" />
            ) : directory.error ? (
              <ErrorNotice
                error={directory.error}
                onRetry={() => directory.refetch()}
              />
            ) : (
              <div className="identity-multiselect">
                <button
                  type="button"
                  className="identity-multiselect-trigger"
                  aria-haspopup="listbox"
                  aria-expanded={identityPickerOpen}
                  onClick={() => setIdentityPickerOpen((open) => !open)}
                >
                  <span>
                    <strong>
                      {selectedSubjects.length
                        ? `${selectedSubjects.length} selected`
                        : `Select ${subjectType === "USER" ? "users" : "teams"}`}
                    </strong>
                    <small>
                      Search the Cognito directory and select one or more.
                    </small>
                  </span>
                  <ChevronDown
                    size={18}
                    className={identityPickerOpen ? "rotated" : ""}
                    aria-hidden="true"
                  />
                </button>
                {identityPickerOpen && (
                  <div className="identity-multiselect-popover">
                    <label className="search-field access-subject-search">
                      <Search size={18} aria-hidden="true" />
                      <span className="sr-only">Search identities</span>
                      <input
                        autoFocus
                        type="search"
                        value={subjectSearch}
                        onChange={(event) =>
                          setSubjectSearch(event.target.value)
                        }
                        placeholder={
                          subjectType === "USER"
                            ? "Search by name, email, or username"
                            : "Search teams"
                        }
                      />
                    </label>
                    <div
                      className="access-subject-list compact"
                      role="listbox"
                      aria-multiselectable="true"
                    >
                      {visibleSubjects.map((subject) => {
                        const existing = assignmentsBySubject.has(
                          `${subject.type}:${subject.id}`,
                        );
                        const disabled = existing || subject.enabled === false;
                        const checked = selectedSubjects.includes(subject.id);
                        return (
                          <label
                            className={`access-subject-option ${
                              checked ? "selected" : ""
                            } ${disabled ? "disabled" : ""}`}
                            key={`${subject.type}:${subject.id}`}
                            role="option"
                            aria-selected={checked}
                          >
                            <input
                              type="checkbox"
                              checked={checked}
                              disabled={disabled}
                              onChange={() => toggleSubject(subject.id)}
                            />
                            <span
                              className="access-subject-avatar"
                              aria-hidden="true"
                            >
                              {subject.type === "GROUP" ? (
                                <UsersRound size={17} />
                              ) : (
                                identityDisplayName(subject)
                                  .slice(0, 2)
                                  .toUpperCase()
                              )}
                            </span>
                            <span>
                              <strong>{identityDisplayName(subject)}</strong>
                              <small>
                                {subject.email ||
                                  subject.description ||
                                  subject.username ||
                                  "Cognito team"}
                              </small>
                            </span>
                            {existing && (
                              <span className="metadata">Assigned</span>
                            )}
                            {subject.enabled === false && (
                              <span className="metadata">Disabled</span>
                            )}
                          </label>
                        );
                      })}
                      {!visibleSubjects.length && (
                        <p className="identity-picker-empty">
                          No matching{" "}
                          {subjectType === "USER" ? "users" : "teams"}.
                        </p>
                      )}
                    </div>
                    <div className="identity-picker-footer">
                      <span>{selectedSubjects.length} selected</span>
                      <Button
                        type="button"
                        variant="secondary"
                        onClick={() => setIdentityPickerOpen(false)}
                      >
                        Done
                      </Button>
                    </div>
                  </div>
                )}
                {selectedSubjects.length > 0 && (
                  <div
                    className="identity-selection-chips"
                    aria-label="Selected identities"
                  >
                    {selectedSubjects.map((subjectId) => {
                      const subject = subjects.find(
                        (item) => item.id === subjectId,
                      );
                      return (
                        <button
                          type="button"
                          key={subjectId}
                          title="Remove selection"
                          onClick={() => toggleSubject(subjectId)}
                        >
                          {subject ? identityDisplayName(subject) : subjectId}
                          <span aria-hidden="true">×</span>
                        </button>
                      );
                    })}
                    <button
                      type="button"
                      className="clear"
                      onClick={() => setSelectedSubjects([])}
                    >
                      Clear
                    </button>
                  </div>
                )}
              </div>
            )}
          </section>

          <section className="panel panel-padding access-workspace access-grant-panel">
            <div className="access-workspace-heading">
              <div className="access-step-number">2</div>
              <div>
                <h2>Define their access</h2>
                <p className="muted">
                  Select an approved least-privilege profile and record the
                  purpose.
                </p>
              </div>
            </div>
            {access.isPending ? (
              <Loading label="Loading access profiles…" />
            ) : access.error ? (
              <ErrorNotice
                error={access.error}
                onRetry={() => access.refetch()}
              />
            ) : (
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  assign.mutate();
                }}
              >
                <fieldset className="access-profile-options">
                  <legend>Access level</legend>
                  {access.data?.profiles.map((profile) => (
                    <label
                      key={profile.profileCode}
                      className={
                        profileCode === profile.profileCode ? "selected" : ""
                      }
                    >
                      <input
                        type="radio"
                        name="access-profile"
                        value={profile.profileCode}
                        checked={profileCode === profile.profileCode}
                        onChange={() => {
                          setProfileCode(profile.profileCode);
                          setNamespace("");
                        }}
                      />
                      <KeyRound size={19} aria-hidden="true" />
                      <span>
                        <strong>{profile.profileName}</strong>
                        <small>{profile.description}</small>
                      </span>
                    </label>
                  ))}
                </fieldset>
                {selectedProfile?.scopeType === "NAMESPACE" && (
                  <label className="field">
                    Kubernetes namespace
                    {namespaceInventory.isPending ? (
                      <div className="namespace-inventory-state">
                        <Loading label="Loading cluster namespaces…" />
                      </div>
                    ) : namespaceInventory.error ? (
                      <div className="namespace-inventory-state warning">
                        <strong>Namespace inventory could not be loaded</strong>
                        <span>
                          Retry after confirming the Dev API is available.
                        </span>
                        <Button
                          type="button"
                          variant="secondary"
                          onClick={() => namespaceInventory.refetch()}
                        >
                          Try again
                        </Button>
                      </div>
                    ) : namespaceInventory.data?.status !== "READY" ? (
                      <div className="namespace-inventory-state">
                        {connectorInstallation ? (
                          <>
                            <strong>Connector installation started</strong>
                            <span>
                              Navigan is installing the connector through the
                              customer-side private installer.
                            </span>
                            <dl className="connector-credentials">
                              <div>
                                <dt>Connector ID</dt>
                                <dd>{connectorInstallation.connectorId}</dd>
                              </div>
                              <div>
                                <dt>Operation</dt>
                                <dd>{connectorInstallation.executionId}</dd>
                              </div>
                            </dl>
                          </>
                        ) : (
                          <>
                            <strong>
                              {namespaceInventory.data?.connectorId
                                ? "Platform bootstrap is in progress"
                                : cluster.data?.status === "ACTIVE"
                                  ? "Legacy cluster requires platform bootstrap"
                                  : "Waiting for automatic platform bootstrap"}
                            </strong>
                            <span>
                              {cluster.data?.status === "ACTIVE"
                                ? "Complete the one-time migration so this existing cluster can report namespaces and platform health."
                                : "Navigan installs the secure connector automatically after the system node group becomes ready."}
                            </span>
                            {(cluster.data?.status === "ACTIVE" ||
                              cluster.data?.status === "BOOTSTRAP_FAILED") && (
                              <Button
                                type="button"
                                variant="secondary"
                                disabled={installConnector.isPending}
                                onClick={() => installConnector.mutate()}
                              >
                                {installConnector.isPending
                                  ? "Starting bootstrap…"
                                  : namespaceInventory.data?.connectorId
                                    ? "Update cluster connector"
                                    : "Complete platform bootstrap"}
                              </Button>
                            )}
                          </>
                        )}
                      </div>
                    ) : (
                      <>
                        <select
                          required
                          value={namespace}
                          onChange={(event) => setNamespace(event.target.value)}
                        >
                          <option value="">Select a namespace</option>
                          {namespaceInventory.data.namespaces
                            .filter((item) => !item.isSystem)
                            .map((item) => (
                              <option
                                key={item.namespace}
                                value={item.namespace}
                              >
                                {item.namespace}
                              </option>
                            ))}
                        </select>
                        <small>
                          Verified from this cluster. System namespaces are
                          hidden.
                        </small>
                      </>
                    )}
                  </label>
                )}
                <label className="field">
                  Business justification
                  <textarea
                    required
                    minLength={3}
                    maxLength={2000}
                    rows={4}
                    value={reason}
                    onChange={(event) => setReason(event.target.value)}
                    placeholder="Explain why this access is needed and what work it supports."
                  />
                </label>
                <div className="access-grant-summary">
                  <strong>Assignment summary</strong>
                  <span>
                    {selectedSubjects.length || "No"}{" "}
                    {subjectType === "USER" ? "user(s)" : "team(s)"} selected
                  </span>
                  <span>
                    {selectedProfile?.profileName || "No access level selected"}
                  </span>
                  <span>
                    {selectedProfile?.scopeType === "NAMESPACE"
                      ? namespace
                        ? `Namespace: ${namespace}`
                        : "Namespace required"
                      : selectedProfile
                        ? "Entire cluster"
                        : ""}
                  </span>
                </div>
                <Button
                  disabled={
                    assign.isPending ||
                    !selectedSubjects.length ||
                    !profileCode ||
                    !reason.trim() ||
                    (selectedProfile?.scopeType === "NAMESPACE" &&
                      (!namespace.trim() ||
                        namespaceInventory.data?.status !== "READY"))
                  }
                >
                  {assign.isPending
                    ? "Creating assignments…"
                    : `Grant access to ${selectedSubjects.length || 0} selected`}
                </Button>
                <p className="metadata">
                  New assignments remain pending until Kubernetes RBAC
                  reconciliation succeeds.
                </p>
              </form>
            )}
          </section>
        </div>
      )}

      {access.data && (
        <section className="panel panel-padding access-workspace">
          <div className="access-workspace-heading">
            <ShieldCheck size={26} aria-hidden="true" />
            <div>
              <h2>Current access</h2>
              <p className="muted">
                Review active and pending Kubernetes access for this cluster.
              </p>
            </div>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Person or team</th>
                  <th>Access level</th>
                  <th>Scope</th>
                  <th>Status</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {access.data.assignments.map((assignment) => (
                  <tr key={assignment.assignmentId}>
                    <td className="access-subject-cell">
                      <strong>
                        {subjectNames.get(
                          `${assignment.subjectType}:${assignment.subjectId}`,
                        ) || assignment.subjectId}
                      </strong>
                      <span className="metadata">
                        {assignment.subjectType === "USER"
                          ? "Individual user"
                          : "Team"}
                      </span>
                    </td>
                    <td>{assignment.profileName}</td>
                    <td>
                      {assignment.scopeType === "NAMESPACE"
                        ? `Namespace: ${assignment.namespace}`
                        : "Entire cluster"}
                    </td>
                    <td>
                      <span
                        className={`status-badge status-${assignment.status.toLowerCase()}`}
                        title={
                          assignment.status === "PENDING"
                            ? "Waiting for the cluster connector to reconcile Kubernetes RBAC."
                            : undefined
                        }
                      >
                        {assignment.status === "PENDING"
                          ? "Awaiting sync"
                          : assignment.status === "ACTIVE"
                            ? "Enabled"
                            : assignment.status.toLowerCase()}
                      </span>
                    </td>
                    <td>
                      <Button
                        variant="danger"
                        disabled={revoke.isPending}
                        onClick={() => revoke.mutate(assignment.assignmentId)}
                      >
                        Revoke
                      </Button>
                    </td>
                  </tr>
                ))}
                {!access.data.assignments.length && (
                  <tr>
                    <td colSpan={5}>No Kubernetes access has been assigned.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  );
}

export function ClusterRequestPage({ id }: { id: string }) {
  const { identity } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const requestedTab = searchParams.get("tab") || "overview";
  const activeTab = [
    "overview",
    "compute",
    "access",
    "operations",
    "audit",
  ].includes(requestedTab)
    ? requestedTab
    : "overview";
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["cluster", id],
    queryFn: () => clusters.get(id),
    refetchInterval: (state) =>
      [
        "PLAN_RUNNING",
        "APPLYING",
        "STOPPING",
        "STARTING",
        "DELETING",
        "BOOTSTRAPPING",
      ].includes(state.state.data?.status || "")
        ? 5000
        : false,
  });
  const platformComponents = useQuery({
    queryKey: ["cluster-platform-components", id],
    queryFn: () => clusters.platformComponents(id),
    enabled: ["BOOTSTRAPPING", "BOOTSTRAP_FAILED", "ACTIVE"].includes(
      query.data?.status || "",
    ),
    refetchInterval: (state) =>
      state.state.data?.status === "READY" ? 30_000 : 5000,
    refetchIntervalInBackground: true,
    refetchOnMount: "always",
    refetchOnWindowFocus: "always",
    retry: false,
  });
  const toolAccess = useQuery({
    queryKey: ["cluster-tools", id],
    queryFn: () => clusters.tools(id),
    enabled: ["ACTIVE", "READY", "RUNNING"].includes(query.data?.status || ""),
    refetchInterval: (state) =>
      state.state.data?.tunnel.status === "READY" ? 30_000 : 5000,
    refetchIntervalInBackground: true,
    refetchOnMount: "always",
    refetchOnWindowFocus: "always",
    retry: false,
  });
  const logs = useQuery({
    queryKey: ["cluster-execution-logs", id, query.data?.providerExecutionId],
    queryFn: () => clusters.executionLogs(id),
    enabled: Boolean(query.data?.providerExecutionId),
    refetchInterval: (state) => (state.state.data?.complete ? false : 4000),
    retry: false,
  });
  const canViewAccess = hasPermission(identity, "cluster.access.view");
  const access = useQuery({
    queryKey: ["cluster-access", id],
    queryFn: () => clusters.access(id),
    enabled: canViewAccess,
    retry: false,
  });
  const nodeGroupRequests = useQuery({
    queryKey: ["cluster-node-group-requests", id],
    queryFn: () => clusters.nodeGroupRequests(id),
    enabled: Boolean(query.data),
    refetchInterval: (state) =>
      state.state.data?.items.some((item) =>
        ["PLAN_RUNNING", "APPLYING"].includes(item.status),
      )
        ? 5000
        : false,
  });
  const trackedNodeGroupRequest = nodeGroupRequests.data?.items.find(
    (item) =>
      Boolean(item.providerExecutionId) &&
      ["PLAN_RUNNING", "PLAN_READY", "APPLYING", "ACTIVE", "FAILED"].includes(
        item.status,
      ),
  );
  const nodeGroupLogs = useQuery({
    queryKey: [
      "cluster-node-group-execution-logs",
      id,
      trackedNodeGroupRequest?.requestId,
      trackedNodeGroupRequest?.providerExecutionId,
    ],
    queryFn: () =>
      clusters.nodeGroupExecutionLogs(id, trackedNodeGroupRequest!.requestId),
    enabled: Boolean(trackedNodeGroupRequest?.providerExecutionId),
    refetchInterval: (state) => (state.state.data?.complete ? false : 4000),
    retry: false,
  });
  const nodeGroupProviderRunning =
    nodeGroupLogs.data?.status === "IN_PROGRESS" ||
    ["PLAN_RUNNING", "APPLYING"].includes(
      trackedNodeGroupRequest?.status || "",
    );
  const nodeGroupDisplayStatus = nodeGroupProviderRunning
    ? nodeGroupLogs.data?.operation === "apply"
      ? "APPLYING"
      : "PLAN RUNNING"
    : trackedNodeGroupRequest?.status.replaceAll("_", " ");
  const nodeGroupExecutionFailed =
    trackedNodeGroupRequest?.status === "FAILED" &&
    nodeGroupLogs.data?.complete !== false;
  const nodeGroupLastEvent =
    nodeGroupLogs.data?.events[nodeGroupLogs.data.events.length - 1];
  const canViewAudit = hasPermission(identity, "cluster.audit.view");
  const auditLog = useQuery({
    queryKey: ["cluster-audit-log", id],
    queryFn: () => clusters.auditLog(id),
    enabled: canViewAudit,
    refetchInterval: activeTab === "audit" ? 10_000 : false,
    retry: false,
  });
  const pinnedEnvironment = useQuery({
    queryKey: [
      "cluster-node-group-baseline",
      query.data?.environmentId,
      query.data?.environmentApprovedVersion,
    ],
    queryFn: () =>
      environments.version(
        query.data!.environmentId,
        query.data!.environmentApprovedVersion,
      ),
    enabled: Boolean(
      query.data?.environmentId && query.data?.environmentApprovedVersion,
    ),
    staleTime: 60_000,
  });
  const currentEnvironment = useQuery({
    queryKey: [
      "cluster-node-group-current-environment",
      query.data?.environmentId,
    ],
    queryFn: () => environments.get(query.data!.environmentId),
    enabled: Boolean(query.data?.environmentId),
    staleTime: 60_000,
  });
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const [launchingTool, setLaunchingTool] = useState<ClusterToolCode>();
  const [actionComments, setActionComments] = useState("");
  const [planConfirmed, setPlanConfirmed] = useState(false);
  const [showNodeGroupForm, setShowNodeGroupForm] = useState(false);
  const [resourceCategory, setResourceCategory] = useState("All resources");
  const [resourceSearch, setResourceSearch] = useState("");
  const [resourcePage, setResourcePage] = useState(0);
  const [nodeGroupDraft, setNodeGroupDraft] = useState({
    name: "",
    instanceTypes: "",
    capacityType: "ON_DEMAND" as "ON_DEMAND" | "SPOT",
    minSize: 1,
    desiredSize: 1,
    maxSize: 3,
    diskSizeGiB: 50,
    reason: "",
  });
  if (query.isPending) return <Loading label="Loading cluster request…" />;
  if (query.error || !query.data)
    return <ErrorNotice error={query.error} onRetry={() => query.refetch()} />;
  const row = query.data;
  const canRequestNodeGroup = hasPermission(identity, "cluster.create");
  const canReviewNodeGroup = hasPermission(identity, "cluster.review");
  const canSubmitCluster = hasPermission(identity, "cluster.submit");
  const canReviewCluster = hasPermission(identity, "cluster.review");
  const canOperate = hasPermission(identity, "cluster.apply");
  const canDelete = hasPermission(identity, "cluster.decommission");
  const configuration = objectValue(row.configuration);
  const platformBaseline = objectValue(configuration.platformBaseline);
  const systemRepository = objectValue(platformBaseline.repository);
  const githubAuthorizationRequired =
    ["SUBMITTED", "UNDER_REVIEW", "APPROVED"].includes(row.status) &&
    textValue(systemRepository.connectionStatus, "AUTHORIZATION_REQUIRED") !==
      "ACTIVE";
  const nodeGroups = arrayValue(configuration.nodeGroups);
  const recordedSystemGroup = nodeGroups.find(
    (group, index) =>
      textValue(group.purpose, index === 0 ? "SYSTEM" : "APPLICATION") ===
      "SYSTEM",
  );
  const currentSystemGroupRecorded = nodeGroups.some((group) =>
    ["navigan-system-v1", recommendedNodeGroupName(row.clusterName)].includes(
      textValue(group.name, ""),
    ),
  );
  const configuredAddOns = arrayValue(
    configuration.addOns ?? configuration.addons,
  );
  const pinnedConfiguration = objectValue(
    pinnedEnvironment.data?.configuration,
  );
  const pinnedNetwork = objectValue(pinnedConfiguration.network);
  const pinnedSecurity = objectValue(pinnedConfiguration.security);
  const pinnedIam = objectValue(pinnedConfiguration.iam);
  const clusterSubnets = arrayValue(pinnedNetwork.clusterSubnets);
  const nodeSubnets = arrayValue(pinnedNetwork.nodeSubnets);
  const clusterSecurityGroups = arrayValue(
    pinnedSecurity.clusterSecurityGroups,
  );
  const nodeSecurityGroups = arrayValue(pinnedSecurity.nodeSecurityGroups);
  const pinnedExtensions = objectValue(pinnedConfiguration.extensions);
  const pinnedContract = objectValue(pinnedExtensions.provisioningContract);
  const currentConfiguration = objectValue(
    currentEnvironment.data?.configuration,
  );
  const currentExtensions = objectValue(currentConfiguration.extensions);
  const currentContract = objectValue(currentExtensions.provisioningContract);
  const pinnedBlueprint = arrayValue(pinnedConfiguration.clusters).find(
    (item) =>
      textValue(item.name, "") === textValue(configuration.blueprintName, ""),
  );
  const approvedApplicationInstanceTypes = [
    ...new Set(
      (Array.isArray(currentContract.instanceTypes)
        ? currentContract.instanceTypes.map((item) =>
            typeof item === "string" ? item : objectValue(item).instanceType,
          )
        : Array.isArray(pinnedContract.instanceTypes)
          ? pinnedContract.instanceTypes.map((item) =>
              typeof item === "string" ? item : objectValue(item).instanceType,
            )
          : arrayValue(pinnedBlueprint?.nodeGroups).flatMap((group) =>
              Array.isArray(group.instanceTypes) ? group.instanceTypes : [],
            )
      ).filter(
        (item): item is string => typeof item === "string" && Boolean(item),
      ),
    ),
  ].sort();
  const workflow = objectValue(row.workflow);
  const platformBootstrap = objectValue(workflow.platformBootstrap);
  const connectorReported =
    platformComponents.data?.components.some(
      (component) =>
        component.componentCode === "connector" && component.status === "READY",
    ) || false;
  const pendingPlatformComponents =
    platformComponents.data?.components.filter(
      (component) => component.status !== "READY",
    ) || [];
  const componentStatus = (code: string) =>
    platformComponents.data?.components.find(
      (component) => component.componentCode === code,
    );
  const componentLabel = (code: string) => {
    const component = componentStatus(code);
    if (!component) return "Not reported";
    if (component.status === "READY") return "Healthy";
    return [component.syncStatus, component.healthStatus]
      .filter(Boolean)
      .join(" · ");
  };
  const toolByCode = (code: string) =>
    toolAccess.data?.tools.find((tool) => tool.code === code);
  const openTool = async (code: ClusterToolCode) => {
    const popup = window.open("about:blank", "_blank");
    if (!popup) {
      setError(
        new Error(
          "Your browser blocked the tool window. Allow pop-ups for Navigan and try again.",
        ),
      );
      return;
    }
    popup.opener = null;
    popup.document.title = "Opening Navigan tool…";
    popup.document.body.textContent = "Preparing your secure tool session…";
    setLaunchingTool(code);
    setError(undefined);
    try {
      const session = await clusters.createToolSession(id, code);
      const targetName = `navigan-tool-${crypto.randomUUID()}`;
      popup.name = targetName;
      const form = document.createElement("form");
      form.method = "POST";
      form.action = session.exchangeUrl;
      form.target = targetName;
      for (const [name, value] of [
        ["sessionId", session.sessionId],
        ["exchangeToken", session.exchangeToken],
      ]) {
        const input = document.createElement("input");
        input.type = "hidden";
        input.name = name;
        input.value = value;
        form.appendChild(input);
      }
      document.body.appendChild(form);
      form.submit();
      form.remove();
    } catch (caught) {
      popup.close();
      setError(caught);
    } finally {
      setLaunchingTool(undefined);
    }
  };
  const toolLaunch = (code: ClusterToolCode, label: string) => {
    const tool = toolByCode(code);
    return tool?.launchUrl ? (
      <Button
        type="button"
        variant="secondary"
        disabled={Boolean(launchingTool)}
        onClick={() => openTool(code)}
      >
        {launchingTool === code ? `Opening ${label}…` : `Open ${label}`}
        <ExternalLink size={15} aria-hidden="true" />
      </Button>
    ) : (
      <Button
        type="button"
        variant="secondary"
        disabled
        title={
          tool?.disabledReason ||
          (toolAccess.error
            ? "Tool access status is temporarily unavailable."
            : "Checking tool access readiness.")
        }
      >
        Open {label}
      </Button>
    );
  };
  const monitoringReady = ["prometheus", "grafana"].every(
    (code) => componentStatus(code)?.status === "READY",
  );
  const runtimeInventory = platformComponents.data?.runtimeInventory;
  const runtimeResources = runtimeInventory?.resources || [];
  const runtimeMetrics = runtimeInventory?.metrics || {};
  const runtimeInventoryReady = runtimeInventory?.status === "READY";
  const telemetryReady = monitoringReady && runtimeInventoryReady;
  const resourceCategories = [
    { label: "All resources", kinds: [] },
    {
      label: "Workloads",
      kinds: ["Deployment", "StatefulSet", "DaemonSet", "Pod"],
    },
    { label: "Cluster", kinds: ["Node"] },
    { label: "Service and networking", kinds: ["Service"] },
  ];
  const selectedResourceKinds =
    resourceCategories.find((category) => category.label === resourceCategory)
      ?.kinds || [];
  const normalizedResourceSearch = resourceSearch.trim().toLowerCase();
  const filteredRuntimeResources = runtimeResources.filter(
    (resource) =>
      (!selectedResourceKinds.length ||
        selectedResourceKinds.includes(resource.kind)) &&
      (!normalizedResourceSearch ||
        [resource.name, resource.namespace, resource.kind, resource.status]
          .filter(Boolean)
          .some((value) =>
            String(value).toLowerCase().includes(normalizedResourceSearch),
          )),
  );
  const resourcePageSize = 12;
  const resourcePageCount = Math.max(
    1,
    Math.ceil(filteredRuntimeResources.length / resourcePageSize),
  );
  const visibleResourcePage = Math.min(resourcePage, resourcePageCount - 1);
  const visibleRuntimeResources = filteredRuntimeResources.slice(
    visibleResourcePage * resourcePageSize,
    (visibleResourcePage + 1) * resourcePageSize,
  );
  const nodeCount = Number(runtimeMetrics.nodeCount || 0);
  const readyNodeCount = Number(runtimeMetrics.readyNodeCount || 0);
  const podCount = Number(runtimeMetrics.podCount || 0);
  const readyPodCount = Number(runtimeMetrics.readyPodCount || 0);
  const readinessPercent = (ready: number, total: number) =>
    total > 0 ? Math.min(100, Math.round((ready / total) * 100)) : 0;
  const workloadResources = runtimeResources.filter((resource) =>
    ["Deployment", "StatefulSet", "DaemonSet", "Pod"].includes(resource.kind),
  );
  const workloadDesired = workloadResources.reduce(
    (total, resource) => total + resource.desired,
    0,
  );
  const workloadReady = workloadResources.reduce(
    (total, resource) => total + Math.min(resource.ready, resource.desired),
    0,
  );
  const resourceKindCounts = [
    "Node",
    "Deployment",
    "StatefulSet",
    "DaemonSet",
    "Pod",
    "Service",
  ]
    .map((kind) => ({
      kind,
      count: runtimeResources.filter((resource) => resource.kind === kind)
        .length,
    }))
    .filter((item) => item.count > 0);
  const largestResourceKindCount = Math.max(
    1,
    ...resourceKindCounts.map((item) => item.count),
  );
  const restartCountsByNamespace = Array.from(
    runtimeResources
      .filter((resource) => resource.kind === "Pod")
      .reduce((counts, resource) => {
        const namespace = resource.namespace || "Cluster-wide";
        counts.set(namespace, (counts.get(namespace) || 0) + resource.restarts);
        return counts;
      }, new Map<string, number>()),
  )
    .map(([namespace, restarts]) => ({ namespace, restarts }))
    .sort((left, right) => right.restarts - left.restarts)
    .slice(0, 6);
  const largestNamespaceRestartCount = Math.max(
    1,
    ...restartCountsByNamespace.map((item) => item.restarts),
  );
  const systemNodeGroupMigration = objectValue(
    configuration.systemNodeGroupMigration,
  );
  const showSystemNodeGroupMigration =
    Boolean(systemNodeGroupMigration.targetNodeGroupName) &&
    Boolean(row.providerExecutionId);
  const platformReadiness =
    row.status === "ACTIVE"
      ? "Ready"
      : row.status === "BOOTSTRAPPING"
        ? "Installing"
        : row.status === "BOOTSTRAP_FAILED"
          ? "Needs attention"
          : "Pending";
  const executionOperation =
    logs.data?.operation ||
    textValue(objectValue(workflow.currentExecution).mode, "") ||
    textValue(objectValue(workflow.lastExecution).mode, "");
  const executionCopy: Record<
    string,
    { eyebrow: string; title: string; description: string; steps: string[] }
  > = {
    plan: {
      eyebrow: "TERRAFORM PLANNING",
      title: "Plan progress",
      description:
        "Validation, security checks and Terraform planning for this request.",
      steps: ["Request approved", "Configuration validated", "Plan certified"],
    },
    apply: {
      eyebrow: "CLUSTER PROVISIONING",
      title: "Provisioning progress",
      description:
        "Terraform and AWS progress for this cluster provisioning operation.",
      steps: ["Plan certified", "Infrastructure applying", "Cluster active"],
    },
    stop: {
      eyebrow: "CLUSTER LIFECYCLE",
      title: "Stop operation",
      description:
        "AWS progress for scaling the cluster worker capacity to zero.",
      steps: [
        "Stop requested",
        "Node groups scaling down",
        "Worker capacity scaled to zero",
      ],
    },
    start: {
      eyebrow: "CLUSTER LIFECYCLE",
      title: "Start operation",
      description: "AWS progress for restoring the approved worker capacity.",
      steps: ["Start requested", "Node groups scaling up", "Cluster active"],
    },
    delete: {
      eyebrow: "CLUSTER LIFECYCLE",
      title: "Delete operation",
      description:
        "Terraform and AWS progress for decommissioning this cluster.",
      steps: [
        "Deletion requested",
        "Infrastructure destroying",
        "Removal confirmation pending",
      ],
    },
  };
  const executionPresentation =
    executionCopy[executionOperation] || executionCopy.apply;
  const executionTargetStatus: Record<string, string> = {
    plan: "PLAN_READY",
    apply: "ACTIVE",
    stop: "STOPPED",
    start: "ACTIVE",
    delete: "DELETED",
  };
  const executionReachedTarget =
    Boolean(executionOperation) &&
    row.status === executionTargetStatus[executionOperation];
  const executionFailed =
    logs.data?.complete &&
    (Boolean(logs.data.errorCode) ||
      textValue(objectValue(workflow.lastExecution).status, "") !==
        "SUCCEEDED") &&
    !executionReachedTarget;
  const historicalExecution =
    Boolean(logs.data?.complete) &&
    Boolean(executionOperation) &&
    !executionReachedTarget;
  const showExecutionPanel = shouldShowClusterExecutionPanel({
    hasExecutionId: Boolean(row.providerExecutionId),
    historicalExecution,
    status: row.status,
  });
  const executionTitle = historicalExecution
    ? `Previous ${executionPresentation.title.toLowerCase()}`
    : executionPresentation.title;
  const validation = objectValue(workflow.validation);
  const securityScan = objectValue(workflow.securityScan);
  const certification = objectValue(workflow.certification);
  const planSummary = objectValue(workflow.planSummary);
  const certificationPassed = certification.status === "PASSED";
  const planAvailable = ["PLAN_READY", "APPLYING", "ACTIVE"].includes(
    row.status,
  );
  const actions = clusterLifecycleActions({
    status: row.status,
    canSubmit: canSubmitCluster,
    canReview: canReviewCluster,
    canOperate,
    canDelete,
    certificationPassed,
  });
  const actionPanelTab = [
    "DRAFT",
    "REJECTED",
    "SUBMITTED",
    "UNDER_REVIEW",
  ].includes(row.status)
    ? "overview"
    : "operations";
  const act = async (action: (typeof actions)[number]) => {
    if (
      action === "apply" &&
      !window.confirm(
        "Apply the exact approved Terraform plan to the customer AWS account?",
      )
    )
      return;
    if (
      action === "stop" &&
      !window.confirm(
        "Stop this cluster's worker capacity? The EKS control plane remains active and billed.",
      )
    )
      return;
    if (
      action === "start" &&
      !window.confirm("Restore the approved worker capacity for this cluster?")
    )
      return;
    if (
      action === "delete" &&
      !window.confirm(
        "Permanently destroy this cluster through its recorded Terraform state? This cannot be undone.",
      )
    )
      return;
    const comments = actionComments.trim();
    if (["reject", "delete"].includes(action) && !comments) return;
    setBusy(true);
    setError(undefined);
    try {
      await clusters.action(id, action, row.version, comments);
      setActionComments("");
      setPlanConfirmed(false);
      await query.refetch();
    } catch (caught) {
      setError(caught);
    } finally {
      setBusy(false);
    }
  };
  const authorizeGitHubOrganization = async () => {
    setBusy(true);
    setError(undefined);
    try {
      const authorization = await clusters.beginGitHubAuthorization(
        id,
        row.version,
      );
      sessionStorage.setItem(
        "navigan.github.authorization",
        JSON.stringify({
          clusterId: id,
          version: row.version,
          state: authorization.state,
        }),
      );
      window.location.assign(authorization.authorizationUrl);
    } catch (caught) {
      setError(caught);
      setBusy(false);
    }
  };
  const createNodeGroup = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      await clusters.createNodeGroupRequest(
        id,
        {
          name: nodeGroupDraft.name.trim(),
          purpose: "APPLICATION",
          instanceTypes: nodeGroupDraft.instanceTypes
            .split(",")
            .map((item) => item.trim())
            .filter(Boolean),
          capacityType: nodeGroupDraft.capacityType,
          minSize: nodeGroupDraft.minSize,
          desiredSize: nodeGroupDraft.desiredSize,
          maxSize: nodeGroupDraft.maxSize,
          diskSizeGiB: nodeGroupDraft.diskSizeGiB,
        },
        nodeGroupDraft.reason.trim(),
      );
      setShowNodeGroupForm(false);
      setNodeGroupDraft({
        name: "",
        instanceTypes: "",
        capacityType: "ON_DEMAND",
        minSize: 1,
        desiredSize: 1,
        maxSize: 3,
        diskSizeGiB: 50,
        reason: "",
      });
      await nodeGroupRequests.refetch();
    } catch (caught) {
      setError(caught);
    } finally {
      setBusy(false);
    }
  };
  const migrateDefaultSystemGroup = async () => {
    const legacyName = textValue(recordedSystemGroup?.name, "");
    if (!legacyName || currentSystemGroupRecorded) return;
    if (
      !window.confirm(
        `Adopt navigan-system-v1 as the default system node group and generate a certified plan to retire ${legacyName}? Application node groups will not be changed.`,
      )
    )
      return;
    setBusy(true);
    setError(undefined);
    try {
      await clusters.migrateSystemNodeGroup(
        id,
        row.version,
        legacyName,
        {
          name: "navigan-system-v1",
          purpose: "SYSTEM",
          managementMode: "ADOPTED",
          instanceTypes: ["t3.medium"],
          capacityType: "ON_DEMAND",
          minSize: 2,
          desiredSize: 2,
          maxSize: 4,
          diskSizeGiB: 40,
        },
        "Adopt the verified Navigan system node group and retire the legacy system capacity",
      );
      const parameters = new URLSearchParams(searchParams.toString());
      parameters.set("tab", "operations");
      router.replace(`?${parameters.toString()}`, { scroll: false });
      await query.refetch();
    } catch (caught) {
      setError(caught);
    } finally {
      setBusy(false);
    }
  };
  const restartPlatformBootstrap = async () => {
    if (
      !window.confirm("Restart the secure platform bootstrap for this cluster?")
    )
      return;
    setBusy(true);
    setError(undefined);
    try {
      await clusters.installConnector(
        id,
        row.version,
        "Authorized retry of secure platform bootstrap",
      );
      await query.refetch();
    } catch (caught) {
      setError(caught);
    } finally {
      setBusy(false);
    }
  };
  const actOnNodeGroup = async (
    requestId: string,
    requestVersion: number,
    action: "submit" | "approve" | "reject" | "apply" | "retry",
  ) => {
    const comments =
      action === "reject"
        ? window.prompt("Provide the rejection reason:")?.trim() || ""
        : "";
    if (action === "reject" && !comments) return;
    if (
      action === "apply" &&
      !window.confirm("Apply this certified node-group plan to the cluster?")
    )
      return;
    setBusy(true);
    setError(undefined);
    try {
      await clusters.nodeGroupAction(
        id,
        requestId,
        action,
        requestVersion,
        comments,
      );
      await Promise.all([nodeGroupRequests.refetch(), query.refetch()]);
    } catch (caught) {
      setError(caught);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className={`cluster-workspace cluster-workspace-${activeTab}`}>
      <PageHeading
        eyebrow="CLUSTER MANAGEMENT"
        title={row.clusterName}
        description={
          row.platform +
          " pinned to " +
          (row.environmentName || row.environmentId) +
          ", approved version " +
          row.environmentApprovedVersion +
          "."
        }
        action={
          <span className={"status-badge status-" + row.status.toLowerCase()}>
            {clusterStatusLabel(row.status)}
          </span>
        }
      />
      {Boolean(error) && <ErrorNotice error={error} />}
      <nav className="cluster-workspace-tabs" aria-label="Cluster workspace">
        {[
          ["overview", "Overview"],
          ["compute", "Compute"],
          ["access", "Authorization"],
          ["operations", "Operations"],
          ...(canViewAudit ? [["audit", "Audit"]] : []),
        ].map(([code, label]) => (
          <button
            key={code}
            type="button"
            className={activeTab === code ? "active" : ""}
            aria-current={activeTab === code ? "page" : undefined}
            onClick={() => {
              const parameters = new URLSearchParams(searchParams.toString());
              parameters.set("tab", code);
              router.replace(`?${parameters.toString()}`, { scroll: false });
            }}
          >
            {label}
          </button>
        ))}
      </nav>
      <div
        className={`cluster-review-layout ${
          activeTab === actionPanelTab ? "has-action-panel" : ""
        }`}
      >
        <main className="cluster-review-main">
          <section className="panel panel-padding cluster-review-hero cluster-tab-panel cluster-tab-overview">
            <div className="cluster-review-status">
              <span
                className={"status-badge status-" + row.status.toLowerCase()}
              >
                {clusterStatusLabel(row.status)}
              </span>
              <span>Last updated {formatDate(row.updatedAt)}</span>
            </div>
            <h2>Cluster information</h2>
            <dl className="details-grid">
              <div>
                <dt>Status</dt>
                <dd>{clusterStatusLabel(row.status)}</dd>
              </div>
              <div>
                <dt>Kubernetes version</dt>
                <dd>{textValue(configuration.kubernetesVersion)}</dd>
              </div>
              <div>
                <dt>Provider</dt>
                <dd>{row.platform}</dd>
              </div>
              <div>
                <dt>Endpoint access</dt>
                <dd>{textValue(configuration.endpointAccess)}</dd>
              </div>
              <div>
                <dt>Environment</dt>
                <dd>{row.environmentName || row.environmentId}</dd>
              </div>
              <div>
                <dt>Cluster blueprint</dt>
                <dd>{textValue(configuration.blueprintName)}</dd>
              </div>
            </dl>
            {row.description && (
              <div className="cluster-review-description">
                <span className="metadata">REQUEST CONTEXT</span>
                <p className="preserve-lines">{row.description}</p>
              </div>
            )}
          </section>

          <section
            className="cluster-operational-summary cluster-tab-panel cluster-tab-overview"
            aria-label="Cluster operational summary"
          >
            <article className="panel">
              <span className="eyebrow">CLUSTER STATE</span>
              <strong>{clusterStatusLabel(row.status)}</strong>
              <span>Current lifecycle state</span>
              <small>Automatically refreshed during operations</small>
            </article>
            <article className="panel">
              <span className="eyebrow">DECLARED CAPACITY</span>
              <strong>{nodeGroups.length}</strong>
              <span>Managed node groups</span>
              <small>Open Compute for actual and requested capacity</small>
            </article>
            <article className="panel">
              <span className="eyebrow">KUBERNETES ACCESS</span>
              <strong>{access.data?.assignments.length ?? "—"}</strong>
              <span>Active or pending assignments</span>
              <small>Managed through approved access profiles</small>
            </article>
          </section>

          <section className="panel panel-padding cluster-tab-panel cluster-tab-overview cluster-overview-command-center">
            {platformComponents.error && (
              <ErrorNotice
                error={platformComponents.error}
                onRetry={() => platformComponents.refetch()}
              />
            )}
            <div className="cluster-review-section-heading">
              <div>
                <span className="eyebrow">PLATFORM WORKSPACE</span>
                <h2>Operate and observe</h2>
                <p className="muted">
                  Open the cluster&apos;s private management tools and review
                  its latest health snapshot from one place.
                </p>
              </div>
              <span
                className={`security-chip ${telemetryReady ? "" : "needs-review"}`}
              >
                {telemetryReady ? "All systems healthy" : "Health updating"}
              </span>
            </div>

            <dl className="overview-health-strip">
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
                <dt>Warning events</dt>
                <dd>{runtimeMetrics.warningEventCount ?? "—"}</dd>
              </div>
              <div>
                <dt>Container restarts</dt>
                <dd>{runtimeMetrics.containerRestartCount ?? "—"}</dd>
              </div>
            </dl>

            <div className="overview-tool-grid">
              {[
                {
                  code: "HEADLAMP" as ClusterToolCode,
                  component: "headlamp",
                  eyebrow: "CLUSTER DASHBOARD",
                  label: "Headlamp",
                  description:
                    "Browse Kubernetes workloads, objects and namespaces.",
                },
                {
                  code: "GRAFANA" as ClusterToolCode,
                  component: "grafana",
                  eyebrow: "VISUAL ANALYTICS",
                  label: "Grafana",
                  description:
                    "Explore dashboards for cluster and workload usage.",
                },
                {
                  code: "PROMETHEUS" as ClusterToolCode,
                  component: "prometheus",
                  eyebrow: "METRICS ENGINE",
                  label: "Prometheus",
                  description:
                    "Run metric queries and inspect targets and alerts.",
                },
                {
                  code: "ARGOCD" as ClusterToolCode,
                  component: "argocd",
                  eyebrow: "GITOPS CONTROL PLANE",
                  label: "Argo CD",
                  description:
                    "Review application synchronization and deployment health.",
                },
              ].map((tool) => (
                <article className="overview-tool-card" key={tool.code}>
                  <header>
                    <span className="eyebrow">{tool.eyebrow}</span>
                    <span
                      className={`overview-tool-status ${
                        componentStatus(tool.component)?.status === "READY"
                          ? "ready"
                          : ""
                      }`}
                    >
                      <span aria-hidden="true" />
                      {componentLabel(tool.component)}
                    </span>
                  </header>
                  <div>
                    <h3>{tool.label}</h3>
                    <p>{tool.description}</p>
                  </div>
                  <footer>
                    <small>
                      {toolByCode(tool.code)?.disabledReason ||
                        "Private access through the shared Navigan gateway."}
                    </small>
                    {toolLaunch(tool.code, tool.label)}
                  </footer>
                </article>
              ))}
            </div>

            <div className="overview-telemetry-grid">
              <article className="telemetry-chart">
                <header>
                  <div>
                    <span className="eyebrow">LIVE READINESS</span>
                    <h3>Cluster capacity</h3>
                  </div>
                  <strong>
                    {readinessPercent(workloadReady, workloadDesired)}%
                  </strong>
                </header>
                {[
                  { label: "Nodes", ready: readyNodeCount, total: nodeCount },
                  { label: "Pods", ready: readyPodCount, total: podCount },
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
                    <span className="eyebrow">RESOURCE MIX</span>
                    <h3>Reported Kubernetes objects</h3>
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
            </div>
          </section>

          <section className="panel cluster-context-panel cluster-tab-panel cluster-tab-resources">
            <aside
              className="resource-type-nav"
              aria-label="Kubernetes resource types"
            >
              <strong>Resource types</strong>
              {resourceCategories.map((category) => (
                <button
                  type="button"
                  className={
                    resourceCategory === category.label ? "active" : ""
                  }
                  key={category.label}
                  onClick={() => {
                    setResourceCategory(category.label);
                    setResourcePage(0);
                  }}
                >
                  <span>{category.label}</span>
                  <small>
                    {
                      runtimeResources.filter(
                        (resource) =>
                          !category.kinds.length ||
                          category.kinds.includes(resource.kind),
                      ).length
                    }
                  </small>
                </button>
              ))}
            </aside>
            <div className="resource-inventory">
              {platformComponents.error && (
                <ErrorNotice
                  error={platformComponents.error}
                  onRetry={() => platformComponents.refetch()}
                />
              )}
              <div className="cluster-review-section-heading">
                <div>
                  <span className="eyebrow">KUBERNETES INVENTORY</span>
                  <h2>Cluster resources</h2>
                  <p className="muted">
                    Read-only workloads and Kubernetes objects reported by the
                    in-cluster connector.
                  </p>
                </div>
                <span
                  className={`security-chip ${
                    runtimeInventory?.status === "READY" ? "" : "needs-review"
                  }`}
                >
                  {runtimeInventory?.status.replaceAll("_", " ") || "Loading"}
                </span>
              </div>
              <div className="resource-inventory-toolbar">
                <label>
                  <span className="sr-only">Search cluster resources</span>
                  <Search size={16} aria-hidden="true" />
                  <input
                    type="search"
                    value={resourceSearch}
                    placeholder="Search name, namespace, kind or status"
                    onChange={(event) => {
                      setResourceSearch(event.target.value);
                      setResourcePage(0);
                    }}
                  />
                </label>
                <span className="metadata">
                  {filteredRuntimeResources.length} of {runtimeResources.length}{" "}
                  resources
                </span>
              </div>
              {runtimeResources.length ? (
                <div>
                  <div className="table-scroll cluster-node-table resource-compact-table">
                    <table>
                      <thead>
                        <tr>
                          <th>Resource</th>
                          <th>Namespace</th>
                          <th>Status</th>
                          <th>Ready</th>
                          <th>Restarts</th>
                        </tr>
                      </thead>
                      <tbody>
                        {visibleRuntimeResources.map((resource) => (
                          <tr
                            key={`${resource.kind}:${resource.namespace}:${resource.name}`}
                          >
                            <td>
                              <strong>{resource.name}</strong>
                              <span className="metadata">{resource.kind}</span>
                            </td>
                            <td>{resource.namespace || "Cluster-wide"}</td>
                            <td>{resource.status}</td>
                            <td>
                              {resource.ready} / {resource.desired}
                            </td>
                            <td>{resource.restarts}</td>
                          </tr>
                        ))}
                        {!visibleRuntimeResources.length && (
                          <tr>
                            <td colSpan={5}>No resources match this view.</td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                  {resourcePageCount > 1 && (
                    <div className="resource-pagination">
                      <Button
                        type="button"
                        variant="secondary"
                        disabled={visibleResourcePage === 0}
                        onClick={() =>
                          setResourcePage((current) => Math.max(0, current - 1))
                        }
                      >
                        Previous
                      </Button>
                      <span>
                        Page {visibleResourcePage + 1} of {resourcePageCount}
                      </span>
                      <Button
                        type="button"
                        variant="secondary"
                        disabled={visibleResourcePage + 1 >= resourcePageCount}
                        onClick={() =>
                          setResourcePage((current) =>
                            Math.min(resourcePageCount - 1, current + 1),
                          )
                        }
                      >
                        Next
                      </Button>
                    </div>
                  )}
                </div>
              ) : (
                <EmptyState title="Waiting for runtime inventory">
                  The connector will report nodes, workloads, pods and services
                  without exposing the cluster API publicly.
                </EmptyState>
              )}
            </div>
          </section>

          <section className="panel panel-padding cluster-tab-panel cluster-tab-resources">
            <div className="cluster-review-section-heading">
              <div>
                <span className="eyebrow">CLUSTER DASHBOARD</span>
                <h2>Headlamp resource dashboard</h2>
                <p className="muted">
                  Read-only Kubernetes resource views provided by the
                  cluster&apos;s managed dashboard service.
                </p>
              </div>
              <span className="security-chip">
                {componentLabel("headlamp")}
              </span>
            </div>
            <div className="capability-list">
              <article>
                <div>
                  <strong>Dashboard access</strong>
                  <span>
                    Open the cluster&apos;s managed, read-only Headlamp
                    interface through the shared Navigan tools gateway.
                  </span>
                  <small>
                    {toolByCode("HEADLAMP")?.disabledReason ||
                      "Access is authenticated, authorized and routed without a public cluster endpoint."}
                  </small>
                </div>
                {toolLaunch("HEADLAMP", "dashboard")}
              </article>
            </div>
          </section>

          <section className="panel panel-padding cluster-tab-panel cluster-tab-networking">
            <div className="cluster-review-section-heading">
              <div>
                <span className="eyebrow">AWS NETWORK</span>
                <h2>Networking</h2>
                <p className="muted">
                  Network resources inherited from the pinned environment
                  revision.
                </p>
              </div>
              <span className="security-chip">
                {textValue(configuration.endpointAccess)}
              </span>
            </div>
            <dl className="compact-facts">
              <div>
                <dt>VPC</dt>
                <dd>{textValue(objectValue(pinnedNetwork.vpc).vpcId)}</dd>
              </div>
              <div>
                <dt>Cluster subnets</dt>
                <dd>{clusterSubnets.length}</dd>
              </div>
              <div>
                <dt>Node subnets</dt>
                <dd>{nodeSubnets.length}</dd>
              </div>
              <div>
                <dt>Security groups</dt>
                <dd>
                  {clusterSecurityGroups.length + nodeSecurityGroups.length}
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
