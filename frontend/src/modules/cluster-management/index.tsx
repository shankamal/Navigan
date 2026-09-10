"use client";
import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  Check,
  CloudCog,
  Network,
  Plus,
  Search,
  ShieldCheck,
} from "lucide-react";
import { useAuth } from "@/shared/auth/auth-provider";
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
import { useClusterCount, useClusters } from "./hooks/queries";
import { clusters } from "./service";
import type { ClusterFilters, ClusterInput } from "./model";

function objectValue(value: unknown): Record<string, unknown> {
  return value != null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function textValue(value: unknown, fallback = "Not configured") {
  return typeof value === "string" && value ? value : fallback;
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
  FAILED: "Failed",
  REJECTED: "Rejected",
};

export function ClusterAdminPage() {
  const [filters, setFilters] = useState<ClusterFilters>({
    page: 0,
    pageSize: 20,
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
  const total = useClusterCount();
  const active = useClusterCount("ACTIVE");
  const awaiting = useClusterCount("SUBMITTED");
  const draft = useClusterCount("DRAFT");
  const metrics = [
    { label: "Total requests", value: total.data, icon: Network },
    { label: "Active", value: active.data, icon: Check },
    { label: "Submitted", value: awaiting.data, icon: ShieldCheck },
    { label: "Drafts", value: draft.data, icon: CloudCog },
  ];
  const reset = () => {
    setSearch("");
    setFilters({ page: 0, pageSize: 20 });
  };
  const filter = (values: Partial<ClusterFilters>) =>
    setFilters((old) => ({ ...old, ...values, page: 0 }));
  return (
    <>
      <PageHeading
        eyebrow="CONTAINER PROVISIONING"
        title="Cluster Setup Requests"
        description="Review cluster setup requests and track Terraform plan and apply executions."
        action={
          <Link className="button button-primary" href="/clusters/new">
            <Plus size={18} /> New Cluster Setup
          </Link>
        }
      />
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
            <h2>Cluster setup requests</h2>
            <p className="muted">
              Requests pinned to an approved environment baseline.
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
              <option value="">All statuses</option>
              {Object.entries(statusLabels).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
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
              filters.status || search
                ? "No matching cluster setup requests"
                : "No cluster setup requests yet"
            }
            action={
              filters.status || search ? (
                <Button variant="secondary" onClick={reset}>
                  Clear filters
                </Button>
              ) : (
                <Link className="button button-primary" href="/clusters/new">
                  New Cluster Setup
                </Link>
              )
            }
          >
            {filters.status || search
              ? "Try another name, ID, or status."
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
                          {row.status.replaceAll("_", " ")}
                        </span>
                      </td>
                      <td>{formatDate(row.updatedAt)}</td>
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

const defaults: ClusterInput = {
  environmentId: "",
  environmentApprovedVersion: 0,
  clusterName: "",
};

export function NewClusterPage() {
  const router = useRouter();
  const [value, setValue] = useState(defaults);
  const [error, setError] = useState<unknown>();
  const [saving, setSaving] = useState(false);
  const envs = useQuery({
    queryKey: ["active-eks-environments"],
    queryFn: () =>
      environments.list({
        page: 0,
        pageSize: 100,
        sort: "environmentName,asc",
        status: "ACTIVE",
        cloudProvider: "AWS",
      }),
    staleTime: 60000,
  });
  const selectedEnvironment = useQuery({
    queryKey: ["cluster-platform-environment", value.environmentId],
    queryFn: () => environments.get(value.environmentId),
    enabled: Boolean(value.environmentId),
    staleTime: 60000,
  });
  const baseline = objectValue(selectedEnvironment.data?.configuration);
  const account = objectValue(baseline.account);
  const location = objectValue(baseline.location);
  const network = objectValue(baseline.network);
  const vpc = objectValue(network.vpc);
  const clusterSubnets = Array.isArray(network.clusterSubnets)
    ? network.clusterSubnets
    : [];
  const nodeSubnets = Array.isArray(network.nodeSubnets)
    ? network.nodeSubnets
    : [];
  const clusterBlock = objectValue(baseline.cluster);
  const provisioningBlock = objectValue(baseline.provisioning);
  const hasClusterConfig = Boolean(
    clusterBlock.kubernetesVersion && provisioningBlock.roleArn,
  );
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(undefined);
    try {
      const created = await clusters.create(value);
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
        description="Select an approved environment profile and name the cluster. Kubernetes version, node groups and provisioning credentials come from that environment."
      />
      {envs.error && (
        <ErrorNotice error={envs.error} onRetry={() => envs.refetch()} />
      )}
      {error && <ErrorNotice error={error} />}
      <form className="panel panel-padding" onSubmit={submit}>
        <div className="section-heading">
          <div>
            <span className="eyebrow">APPROVED BASELINE</span>
            <h2>Select the environment profile</h2>
            <p>
              Only ACTIVE AWS/EKS profiles are available. The approved version
              is pinned permanently to this request.
            </p>
          </div>
          <ShieldCheck aria-hidden="true" />
        </div>
        <div className="form-grid">
          <label className="field field-span">
            Active environment *
            <select
              required
              value={value.environmentId}
              onChange={(event) => {
                const env = envs.data?.items.find(
                  (item) => item.environmentId === event.target.value,
                );
                setValue((current) => ({
                  ...current,
                  environmentId: event.target.value,
                  environmentApprovedVersion: env?.approvedVersion || 0,
                }));
              }}
            >
              <option value="">Select ACTIVE EKS environment</option>
              {envs.data?.items.map((env) => (
                <option value={env.environmentId} key={env.environmentId}>
                  {env.environmentName} · {env.customerName} · approved v
                  {env.approvedVersion}
                </option>
              ))}
            </select>
          </label>
          {value.environmentId && (
            <div className="cluster-baseline-card field-span">
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
                  <span
                    className={
                      hasClusterConfig
                        ? "security-chip"
                        : "security-chip needs-review"
                    }
                  >
                    {hasClusterConfig
                      ? "Cluster configuration ready"
                      : "This environment has no cluster/provisioning configuration yet — edit and re-approve it before creating a cluster setup request."}
                  </span>
                  <p className="metadata">
                    Terraform uses this immutable approved snapshot—not the
                    current editable environment record.
                  </p>
                </>
              )}
            </div>
          )}
          <label className="field field-span">
            Cluster name *
            <input
              required
              value={value.clusterName}
              onChange={(event) =>
                setValue({ ...value, clusterName: event.target.value })
              }
            />
          </label>
        </div>
        <div className="form-actions">
          <Link className="button button-secondary" href="/clusters">
            Cancel
          </Link>
          <button
            className="button button-primary"
            disabled={
              saving ||
              !value.environmentApprovedVersion ||
              !hasClusterConfig ||
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
    refetchInterval: 15000,
  });
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  if (query.isPending) return <Loading label="Loading cluster request…" />;
  if (query.error || !query.data)
    return <ErrorNotice error={query.error} onRetry={() => query.refetch()} />;
  const row = query.data;
  const engineer = identity?.roles.includes("CLOUD_ENGINEER");
  const architect = identity?.roles.includes("PLATFORM_ARCHITECT");
  const actions: Array<
    "submit" | "review" | "approve" | "reject" | "plan" | "apply"
  > =
    engineer && ["DRAFT", "REJECTED"].includes(row.status)
      ? ["submit"]
      : architect && row.status === "SUBMITTED"
        ? ["review"]
        : architect && row.status === "UNDER_REVIEW"
          ? ["approve", "reject"]
          : architect && row.status === "FAILED"
            ? ["plan"]
            : architect && row.status === "PLAN_READY"
              ? ["apply"]
              : [];
  const act = async (action: (typeof actions)[number]) => {
    if (
      action === "apply" &&
      !window.confirm(
        "Apply the exact approved Terraform plan to the customer AWS account?",
      )
    )
      return;
    const comments =
      action === "reject" ? window.prompt("Rejection reason") || "" : "";
    if (action === "reject" && !comments) return;
    setBusy(true);
    setError(undefined);
    try {
      await clusters.action(id, action, row.version, comments);
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
        eyebrow="CONTAINER PROVISIONING"
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
      <section className="panel panel-padding">
        <dl className="details-grid">
          <div>
            <dt>Status</dt>
            <dd>{row.status.replaceAll("_", " ")}</dd>
          </div>
          <div>
            <dt>Request version</dt>
            <dd>{row.version}</dd>
          </div>
          <div>
            <dt>Terraform plan</dt>
            <dd>{row.planSha256 ? "Ready" : "Not generated"}</dd>
          </div>
          <div>
            <dt>Execution</dt>
            <dd>{row.providerExecutionId || "Not started"}</dd>
          </div>
        </dl>
        {row.workflow?.planSummary != null && (
          <details className="panel-padding">
            <summary>Terraform plan summary</summary>
            <pre>{JSON.stringify(row.workflow.planSummary, null, 2)}</pre>
          </details>
        )}
        <div className="form-actions">
          {actions.map((action) => (
            <button
              key={action}
              disabled={busy}
              className="button button-primary"
              onClick={() => void act(action)}
            >
              {action === "plan"
                ? "Generate Terraform plan"
                : action === "apply"
                  ? "Apply approved Terraform plan"
                  : action.replace(/^./, (letter) => letter.toUpperCase())}
            </button>
          ))}
        </div>
      </section>
    </>
  );
}
