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
import { customersService } from "@/modules/customer-management/services/customers";
import { useClusters } from "./hooks/queries";
import { clusters } from "./service";
import type { ClusterFilters, ClusterInput } from "./model";

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
  const visibleRequests = query.data?.items ?? [];
  const metrics = [
    {
      label: "Total requests",
      value: query.data?.pagination.totalElements,
      icon: Network,
    },
    {
      label: "Active on this page",
      value: query.data
        ? visibleRequests.filter((item) => item.status === "ACTIVE").length
        : undefined,
      icon: Check,
    },
    {
      label: "Submitted on this page",
      value: query.data
        ? visibleRequests.filter((item) => item.status === "SUBMITTED").length
        : undefined,
      icon: ShieldCheck,
    },
    {
      label: "Drafts on this page",
      value: query.data
        ? visibleRequests.filter((item) => item.status === "DRAFT").length
        : undefined,
      icon: CloudCog,
    },
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
  blueprintName: "",
  clusterName: "",
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
  const blueprints = arrayValue(baseline.clusters);
  const hasClusterConfig = blueprints.length > 0;
  const selectedBlueprint = blueprints.find(
    (b) => b.name === value.blueprintName,
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
        description="Select a customer, an approved environment, and one of its cluster blueprints, then name the cluster. Kubernetes version, node groups and provisioning credentials come from that blueprint."
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
                  <span
                    className={
                      hasClusterConfig
                        ? "security-chip"
                        : "security-chip needs-review"
                    }
                  >
                    {hasClusterConfig
                      ? `${blueprints.length} cluster blueprint${blueprints.length === 1 ? "" : "s"} available`
                      : "This environment has no cluster blueprints yet — edit and re-approve it before creating a cluster setup request."}
                  </span>
                  <p className="metadata">
                    Terraform uses this immutable approved snapshot—not the
                    current editable environment record.
                  </p>
                </>
              )}
            </div>
          )}
          {hasClusterConfig && (
            <label className="field cluster-field-span">
              Cluster blueprint *
              <select
                required
                value={value.blueprintName}
                onChange={(event) =>
                  setValue((current) => ({
                    ...current,
                    blueprintName: event.target.value,
                  }))
                }
              >
                <option value="">Select a cluster blueprint</option>
                {blueprints.map((blueprint) => (
                  <option value={String(blueprint.name)} key={String(blueprint.name)}>
                    {String(blueprint.name)} · {String(blueprint.kubernetesVersion)} ·{" "}
                    {arrayValue(blueprint.nodeGroups).length} node group
                    {arrayValue(blueprint.nodeGroups).length === 1 ? "" : "s"}
                  </option>
                ))}
              </select>
            </label>
          )}
          {selectedBlueprint && (
            <dl className="cluster-baseline-grid cluster-field-span">
              <div>
                <dt>Kubernetes version</dt>
                <dd>{textValue(selectedBlueprint.kubernetesVersion)}</dd>
              </div>
              <div>
                <dt>Endpoint access</dt>
                <dd>{textValue(selectedBlueprint.endpointAccess)}</dd>
              </div>
              <div>
                <dt>Node groups</dt>
                <dd>
                  {arrayValue(selectedBlueprint.nodeGroups)
                    .map((g) => String(g.name))
                    .join(", ")}
                </dd>
              </div>
            </dl>
          )}
          <label className="field">
            Cluster name *
            <input
              required
              value={value.clusterName}
              onChange={(event) =>
                setValue({ ...value, clusterName: event.target.value })
              }
            />
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
              !value.blueprintName ||
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
      ["PLAN_RUNNING", "APPLYING"].includes(state.state.data?.status || "")
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
  const configuration = objectValue(row.configuration);
  const nodeGroups = arrayValue(configuration.nodeGroups);
  const workflow = objectValue(row.workflow);
  const validation = objectValue(workflow.validation);
  const securityScan = objectValue(workflow.securityScan);
  const certification = objectValue(workflow.certification);
  const planSummary = objectValue(workflow.planSummary);
  const certificationPassed = certification.status === "PASSED";
  const planAvailable = ["PLAN_READY", "APPLYING", "ACTIVE"].includes(row.status);
  const actions: Array<
    "submit" | "review" | "approve" | "reject" | "plan" | "apply"
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
              : [];
  const act = async (action: (typeof actions)[number]) => {
    if (
      action === "apply" &&
      !window.confirm(
        "Apply the exact approved Terraform plan to the customer AWS account?",
      )
    )
      return;
    const comments = actionComments.trim();
    if (action === "reject" && !comments) return;
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
      <div className="cluster-review-layout">
        <main className="cluster-review-main">
          <section className="panel panel-padding cluster-review-hero">
            <div className="cluster-review-status">
              <span className={"status-badge status-" + row.status.toLowerCase()}>
                {row.status.replaceAll("_", " ")}
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
                <dt>Blueprint</dt>
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

          <section className="panel panel-padding">
            <div className="cluster-review-section-heading">
              <div>
                <span className="eyebrow">APPROVED CONFIGURATION</span>
                <h2>Cluster specification</h2>
                <p className="muted">
                  Read-only values copied from the approved environment
                  blueprint.
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

          {["PLAN_RUNNING", "PLAN_READY", "FAILED", "APPLYING", "ACTIVE"].includes(
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
          {row.providerExecutionId && (
            <section className="panel panel-padding execution-console">
              <header>
                <div>
                  <span className="eyebrow">LIVE EXECUTION</span>
                  <h2>Provisioning progress</h2>
                  <p className="muted">
                    Sanitized Terraform and AWS progress from this request only.
                  </p>
                </div>
                <span className={`execution-state ${logs.data?.complete ? "complete" : "running"}`}>
                  <span aria-hidden="true" />
                  {logs.data?.complete ? "Execution finished" : "Live · refreshing"}
                </span>
              </header>
              <div className="execution-progress" aria-label="Execution progress">
                {[
                  ["Request approved", true],
                  ["Plan certified", Boolean(row.planSha256)],
                  ["Infrastructure applied", row.status === "ACTIVE"],
                ].map(([label, complete]) => (
                  <div className={complete ? "complete" : ""} key={String(label)}>
                    <span aria-hidden="true" />
                    <strong>{label}</strong>
                  </div>
                ))}
              </div>
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
                Review comments {actions.includes("reject") ? "*" : ""}
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
                    (action === "reject" && !actionComments.trim()) ||
                    (action === "apply" && !planConfirmed)
                  }
                  className={
                    action === "reject"
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
                        : action === "approve"
                          ? "Approve and generate plan"
                          : action.replace(/^./, (letter) => letter.toUpperCase())}
                </button>
              ))}
            </div>
            {actions.length === 0 && (
              <p className="notice">
                {row.status === "PLAN_RUNNING" || row.status === "APPLYING"
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
