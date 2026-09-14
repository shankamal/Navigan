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
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  CloudCog,
  EllipsisVertical,
  Network,
  Plus,
  Search,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { useAuth } from "@/shared/auth/auth-provider";
import { hasPermission } from "@/shared/auth/permissions";
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

function versionTuple(version: string): number[] {
  return version.split(".").map((part) => Number(part) || 0);
}

function compareVersionsDescending(left: string, right: string): number {
  const a = versionTuple(left);
  const b = versionTuple(right);
  return (b[0] || 0) - (a[0] || 0) || (b[1] || 0) - (a[1] || 0);
}

function supportedEksVersions(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return [
    ...new Set(
      value
        .map((item) =>
          typeof item === "string"
            ? item
            : typeof objectValue(item).version === "string"
              ? String(objectValue(item).version)
              : "",
        )
        .filter(Boolean),
    ),
  ].toSorted(compareVersionsDescending);
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
  const workload = index === 0 ? "general" : `workload-${index + 1}`;
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

type ClusterAdminMode = "directory" | "reviews" | "operations";

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
      Math.max(56, cluster.allowedActions.length * 58),
    );
    const opensAbove =
      rect.bottom + estimatedHeight + 12 > window.innerHeight &&
      rect.top > estimatedHeight;
    setPosition({
      left: Math.max(12, Math.min(rect.right - width, window.innerWidth - width - 12)),
      top: opensAbove
        ? Math.max(12, rect.top - estimatedHeight - 4)
        : rect.bottom + 4,
      width,
    });
    setOpen(true);
  };
  const items =
    cluster.allowedActions.length > 0 ? (
      cluster.allowedActions.map((action) => {
        const operation = directOperations[action.code];
        if (!operation && action.enabled) {
          return (
            <Link
              key={action.code}
              href={`/clusters/${cluster.clusterId}`}
              role="menuitem"
              className="cluster-action-item"
              onClick={() => setOpen(false)}
            >
              {action.label}
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
            <span>{action.label}</span>
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
    }) =>
      clusters.action(
        cluster.clusterId,
        action,
        cluster.version,
        reason,
      ),
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
        ? window.prompt(
            "Provide the required reason for deleting this cluster:",
          )?.trim()
        : action.label;
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
  clusterName: "",
  kubernetesVersion: "",
  endpointAccess: "PRIVATE",
  nodeGroups: [defaultNodeGroup()],
  provisioningRoleArn: "",
  externalIdSecretArn: "",
  tags: {},
  description: "",
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
    queryKey: ["cluster-platform-environment", value.environmentId],
    queryFn: () => environments.get(value.environmentId),
    enabled: Boolean(value.environmentId),
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
  const legacyBlueprint = arrayValue(baseline.clusters)[0];
  const legacyProvisioning = objectValue(legacyBlueprint?.provisioning);
  const kubernetesVersions = Array.isArray(contract.kubernetesVersions)
    ? supportedEksVersions(contract.kubernetesVersions)
    : typeof legacyBlueprint?.kubernetesVersion === "string"
      ? [legacyBlueprint.kubernetesVersion]
      : [];
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
      ? [{ roleArn: legacyProvisioning.roleArn, roleName: "NaviganProvisioningRole" }]
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
        <ErrorNotice error={customers.error} onRetry={() => customers.refetch()} />
      )}
      {envs.error && (
        <ErrorNotice error={envs.error} onRetry={() => envs.refetch()} />
      )}
      {error && <ErrorNotice error={error} />}
      <form className="panel panel-padding cluster-setup-form" onSubmit={submit}>
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
                  kubernetesVersion: "",
                  nodeGroups: [defaultNodeGroup()],
                  provisioningRoleArn: "",
                  externalIdSecretArn: "",
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
                  {env.status !== "ACTIVE" ? ` · revision ${env.status.toLowerCase()}` : ""}
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
              disabled={!value.environmentId || selectedEnvironment.isPending}
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
          <label className="field">
            API endpoint access *
            <select
              required
              value={value.endpointAccess}
              onChange={(event) =>
                setValue({
                  ...value,
                  endpointAccess: event.target.value as
                    | "PRIVATE"
                    | "PUBLIC_AND_PRIVATE",
                })
              }
            >
              <option value="PRIVATE">Private only</option>
              <option value="PUBLIC_AND_PRIVATE">
                Public and private
              </option>
            </select>
            <small>Private-only access is the recommended baseline.</small>
          </label>
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
            <legend>Managed node groups, scaling and storage</legend>
            <p className="muted">
              Define the worker pools required by this cluster. A single
              instance type keeps every node in a pool uniform.
            </p>
            {value.nodeGroups.map((group, index) => (
              <div className="cluster-blueprint-card" key={index}>
                <div className="cluster-setup-grid">
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
                          nodeGroups: current.nodeGroups.map((item, itemIndex) =>
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
                          nodeGroups: current.nodeGroups.map((item, itemIndex) =>
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
                      onChange={(event) =>
                        setValue((current) => ({
                          ...current,
                          nodeGroups: current.nodeGroups.map((item, itemIndex) =>
                            itemIndex === index
                              ? {
                                  ...item,
                                  capacityType: event.target.value as
                                    | "ON_DEMAND"
                                    | "SPOT",
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
                        min={key === "diskSizeGiB" ? 20 : key === "maxSize" ? 1 : 0}
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
                {value.nodeGroups.length > 1 && (
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() =>
                      setValue((current) => ({
                        ...current,
                        nodeGroups: current.nodeGroups.filter(
                          (_, itemIndex) => itemIndex !== index,
                        ),
                      }))
                    }
                  >
                    <Trash2 size={16} /> Remove node group
                  </Button>
                )}
              </div>
            ))}
            <Button
              type="button"
              variant="secondary"
              onClick={() =>
                setValue((current) => ({
                  ...current,
                  nodeGroups: [
                    ...current.nodeGroups,
                    defaultNodeGroup(
                      current.nodeGroups.length,
                      current.clusterName,
                    ),
                  ],
                }))
              }
            >
              <Plus size={16} /> Add node group
            </Button>
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

export function ClusterRequestPage({ id }: { id: string }) {
  const { identity } = useAuth();
  const query = useQuery({
    queryKey: ["cluster", id],
    queryFn: () => clusters.get(id),
    refetchInterval: (state) =>
      ["PLAN_RUNNING", "APPLYING", "STOPPING", "STARTING", "DELETING"].includes(
        state.state.data?.status || "",
      )
        ? 5000
        : false,
  });
  const logs = useQuery({
    queryKey: ["cluster-execution-logs", id, query.data?.providerExecutionId],
    queryFn: () => clusters.executionLogs(id),
    enabled: Boolean(query.data?.providerExecutionId),
    refetchInterval: (state) => (state.state.data?.complete ? false : 4000),
    retry: false,
  });
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const [actionComments, setActionComments] = useState("");
  const [planConfirmed, setPlanConfirmed] = useState(false);
  if (query.isPending) return <Loading label="Loading cluster request…" />;
  if (query.error || !query.data)
    return <ErrorNotice error={query.error} onRetry={() => query.refetch()} />;
  const row = query.data;
  const engineer = identity?.roles.includes("CLOUD_ENGINEER");
  const architect = identity?.roles.includes("PLATFORM_ARCHITECT");
  const canOperate = hasPermission(identity, "cluster.apply");
  const canDelete = hasPermission(identity, "cluster.decommission");
  const configuration = objectValue(row.configuration);
  const nodeGroups = arrayValue(configuration.nodeGroups);
  const workflow = objectValue(row.workflow);
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
      description: "Validation, security checks and Terraform planning for this request.",
      steps: ["Request approved", "Configuration validated", "Plan certified"],
    },
    apply: {
      eyebrow: "CLUSTER PROVISIONING",
      title: "Provisioning progress",
      description: "Terraform and AWS progress for this cluster provisioning operation.",
      steps: ["Plan certified", "Infrastructure applying", "Cluster active"],
    },
    stop: {
      eyebrow: "CLUSTER LIFECYCLE",
      title: "Stop operation",
      description: "AWS progress for scaling the cluster worker capacity to zero.",
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
      description: "Terraform and AWS progress for decommissioning this cluster.",
      steps: ["Deletion requested", "Infrastructure destroying", "Cluster deleted"],
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
  const showExecutionPanel =
    Boolean(row.providerExecutionId) &&
    (!historicalExecution || row.status === "FAILED");
  const executionTitle = historicalExecution
    ? `Previous ${executionPresentation.title.toLowerCase()}`
    : executionPresentation.title;
  const validation = objectValue(workflow.validation);
  const securityScan = objectValue(workflow.securityScan);
  const certification = objectValue(workflow.certification);
  const planSummary = objectValue(workflow.planSummary);
  const certificationPassed = certification.status === "PASSED";
  const planAvailable = ["PLAN_READY", "APPLYING", "ACTIVE"].includes(row.status);
  const actions: Array<
    | "submit"
    | "review"
    | "approve"
    | "reject"
    | "plan"
    | "apply"
    | "stop"
    | "start"
    | "delete"
  > =
    engineer && ["DRAFT", "REJECTED"].includes(row.status)
      ? ["submit"]
        : architect && row.status === "SUBMITTED"
        ? ["approve", "reject"]
        : architect && row.status === "UNDER_REVIEW"
          ? ["approve", "reject"]
          : architect && row.status === "FAILED"
            ? ["plan"]
            : architect && row.status === "PLAN_READY"
              ? certificationPassed
                ? ["apply"]
                : ["plan"]
              : canOperate && row.status === "ACTIVE"
                ? canDelete
                  ? ["stop", "delete"]
                  : ["stop"]
                : canOperate && row.status === "STOPPED"
                  ? canDelete
                    ? ["start", "delete"]
                    : ["start"]
                  : canDelete && row.status === "FAILED"
                    ? ["delete"]
                    : [];
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
  return (
    <>
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
      />
      {error && <ErrorNotice error={error} />}
      <div className="cluster-review-layout">
        <main className="cluster-review-main">
          <section className="panel panel-padding cluster-review-hero">
            <div className="cluster-review-status">
              <span className={"status-badge status-" + row.status.toLowerCase()}>
                {clusterStatusLabel(row.status)}
              </span>
              <span>Request version {row.version}</span>
            </div>
            <h2>Request overview</h2>
            <dl className="details-grid">
              <div>
                <dt>Customer</dt>
                <dd>{row.customerName || row.customerId}</dd>
              </div>
              <div>
                <dt>Environment</dt>
                <dd>{row.environmentName || row.environmentId}</dd>
              </div>
              <div>
                <dt>Approved baseline</dt>
                <dd>Version {row.environmentApprovedVersion}</dd>
              </div>
              <div>
                <dt>Platform</dt>
                <dd>{row.platform}</dd>
              </div>
            </dl>
            {row.description && (
              <div className="cluster-review-description">
                <span className="metadata">REQUEST CONTEXT</span>
                <p className="preserve-lines">{row.description}</p>
              </div>
            )}
          </section>

          <section className="panel panel-padding">
            <div className="cluster-review-section-heading">
              <div>
                <span className="eyebrow">APPROVED CONFIGURATION</span>
                <h2>Cluster specification</h2>
                <p className="muted">
                  Cluster-owned values reviewed with the pinned, approved
                  environment baseline.
                </p>
              </div>
              <ShieldCheck aria-hidden="true" />
            </div>
            <dl className="details-grid cluster-spec-grid">
              <div>
                <dt>Kubernetes version</dt>
                <dd>{textValue(configuration.kubernetesVersion)}</dd>
              </div>
              <div>
                <dt>Endpoint access</dt>
                <dd>{textValue(configuration.endpointAccess)}</dd>
              </div>
              <div>
                <dt>Terraform module</dt>
                <dd>{row.terraformModuleVersion || "1.0.0"}</dd>
              </div>
              <div>
                <dt>Node groups</dt>
                <dd>{nodeGroups.length}</dd>
              </div>
            </dl>
            <div className="table-scroll cluster-node-table">
              <table>
                <thead>
                  <tr>
                    <th>Node group</th>
                    <th>Instance types</th>
                    <th>Capacity</th>
                    <th>Scaling</th>
                    <th>Disk</th>
                  </tr>
                </thead>
                <tbody>
                  {nodeGroups.map((group, index) => (
                    <tr key={String(group.name || index)}>
                      <td><strong>{textValue(group.name)}</strong></td>
                      <td>
                        {Array.isArray(group.instanceTypes)
                          ? group.instanceTypes.join(", ")
                          : "Not configured"}
                      </td>
                      <td>{textValue(group.capacityType)}</td>
                      <td>
                        {String(group.minSize)} / {String(group.desiredSize)} /{" "}
                        {String(group.maxSize)}
                        <span className="metadata"> min / desired / max</span>
                      </td>
                      <td>{String(group.diskSizeGiB || 50)} GiB</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {[
            "PLAN_RUNNING", "PLAN_READY", "FAILED", "APPLYING", "ACTIVE",
            "STOPPING", "STOPPED", "STARTING", "DELETING",
          ].includes(
            row.status,
          ) && (
            <section className="panel panel-padding cluster-certification">
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
                <div className={validation.valid === true ? "assurance-pass" : ""}>
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
                  <strong>{row.planSha256 ? "Hash verified" : "Pending"}</strong>
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
                        I reviewed this exact plan hash and confirm it is ready
                        to apply.
                      </span>
                    </label>
                  )}
                </>
              )}
            </section>
          )}
          {showExecutionPanel && (
            <section className="panel panel-padding execution-console">
              <header>
                <div>
                  <span className="eyebrow">{executionPresentation.eyebrow}</span>
                  <h2>{executionTitle}</h2>
                  <p className="muted">
                    {historicalExecution
                      ? `Historical execution record. The cluster's current lifecycle state is ${clusterStatusLabel(row.status)}.`
                      : executionPresentation.description}
                  </p>
                </div>
                <span className={`execution-state ${logs.data?.complete ? "complete" : "running"}`}>
                  <span aria-hidden="true" />
                  {logs.data?.complete ? "Execution finished" : "Live · refreshing"}
                </span>
              </header>
              <div className="execution-progress" aria-label="Execution progress">
                {executionPresentation.steps.map((label, index) => (
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
                    <strong>{label}</strong>
                  </div>
                ))}
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
        </main>

        <aside className="cluster-review-aside">
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
                {actions.some((action) => ["reject", "delete"].includes(action))
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
                          : action.replace(/^./, (letter) => letter.toUpperCase())}
                </button>
              ))}
            </div>
            {actions.length === 0 && (
              <p className="notice">
                {[
                  "PLAN_RUNNING", "APPLYING", "STOPPING", "STARTING", "DELETING",
                ].includes(row.status)
                  ? "This page refreshes automatically as the execution progresses."
                  : "No action is currently required from your role."}
              </p>
            )}
          </section>
        </aside>
      </div>
    </>
  );
}
