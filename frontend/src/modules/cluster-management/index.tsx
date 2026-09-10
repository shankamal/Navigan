"use client";
import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Check, CloudCog, Plus, ShieldCheck } from "lucide-react";
import { useAuth } from "@/shared/auth/auth-provider";
import { ErrorNotice, Loading, PageHeading, formatDate } from "@/shared/components/ui";
import { environments } from "@/modules/environment-management/services/environments";
import { clusters } from "./service";
import type { ClusterInput } from "./model";

export function ClusterAdminPage() {
  const query = useQuery({ queryKey: ["clusters"], queryFn: clusters.list, refetchInterval: 15000 });
  return <>
    <PageHeading eyebrow="CONTAINER PROVISIONING" title="Environment Admin"
      description="Review cluster requests and track Terraform plan and apply executions."
      action={<Link className="button button-primary" href="/clusters/new"><Plus size={18}/> New Container Env</Link>}/>
    {query.isPending ? <Loading label="Loading container environments…"/> :
      query.error ? <ErrorNotice error={query.error} onRetry={() => query.refetch()}/> :
      <section className="panel"><div className="table-scroll"><table className="customer-table">
        <thead><tr><th>Cluster</th><th>Environment</th><th>Customer</th><th>Status</th><th>Updated</th></tr></thead>
        <tbody>{query.data?.items.map((row) => <tr key={row.clusterId}>
          <td><Link href={"/clusters/" + row.clusterId}><strong>{row.clusterName}</strong></Link></td>
          <td>{row.environmentName || row.environmentId}<div className="metadata">Approved v{row.environmentApprovedVersion}</div></td>
          <td>{row.customerName || row.customerId}</td>
          <td><span className={"status-badge status-" + row.status.toLowerCase()}>{row.status.replaceAll("_", " ")}</span></td>
          <td>{formatDate(row.updatedAt)}</td>
        </tr>)}</tbody>
      </table></div></section>}
  </>;
}

const defaults: ClusterInput = {
  environmentId: "", environmentApprovedVersion: 0, platform: "EKS", clusterName: "",
  provisioningRoleArn: "", externalIdSecretArn: "", terraformModuleVersion: "1.0.0",
  configuration: {
    kubernetesVersion: "1.33", endpointAccess: "PRIVATE",
    nodeGroups: [{name: "general", instanceTypes: ["m6i.large"], capacityType: "ON_DEMAND",
      desiredSize: 2, minSize: 2, maxSize: 4, diskSizeGiB: 50}],
    tags: {},
  },
};

function objectValue(value: unknown): Record<string, unknown> {
  return value != null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : {};
}

function textValue(value: unknown, fallback = "Not configured") {
  return typeof value === "string" && value ? value : fallback;
}

export function NewClusterPage() {
  const router = useRouter();
  const [value, setValue] = useState(defaults);
  const [error, setError] = useState<unknown>();
  const [saving, setSaving] = useState(false);
  const envs = useQuery({
    queryKey: ["active-eks-environments"],
    queryFn: () => environments.list({page: 0, pageSize: 100, sort: "environmentName,asc",
      status: "ACTIVE", cloudProvider: "AWS"}),
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
  const clusterSubnets = Array.isArray(network.clusterSubnets) ? network.clusterSubnets : [];
  const nodeSubnets = Array.isArray(network.nodeSubnets) ? network.nodeSubnets : [];
  const group = value.configuration.nodeGroups[0];
  const setGroup = (change: Partial<typeof group>) => setValue((current) => ({
    ...current, configuration: {...current.configuration,
      nodeGroups: [{...current.configuration.nodeGroups[0], ...change}]},
  }));
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setSaving(true); setError(undefined);
    try {
      const created = await clusters.create(value);
      router.push("/clusters/" + created.clusterId);
    } catch (caught) { setError(caught); } finally { setSaving(false); }
  };
  return <>
    <PageHeading eyebrow="CONTAINER PROVISIONING" title="Cluster Platform Setup Request"
      description="Select an approved environment profile, define EKS capacity, and submit it through maker-checker approval."/>
    <ol className="cluster-request-steps" aria-label="Cluster provisioning workflow">
      {[
        "Select environment", "Configure platform", "Submit and approve", "Terraform plan and apply",
      ].map((label, index) => <li key={label}>
        <span>{index + 1}</span>{label}
      </li>)}
    </ol>
    {envs.error && <ErrorNotice error={envs.error} onRetry={() => envs.refetch()}/>}
    {error && <ErrorNotice error={error}/>}
    <form className="panel panel-padding" onSubmit={submit}>
      <div className="section-heading"><div><span className="eyebrow">APPROVED BASELINE</span>
        <h2>Select the environment profile</h2>
        <p>Only ACTIVE AWS/EKS profiles are available. The approved version is pinned permanently to this request.</p>
      </div><ShieldCheck aria-hidden="true"/></div>
      <div className="form-grid">
      <label className="field field-span">Active environment *
        <select required value={value.environmentId} onChange={(event) => {
          const env = envs.data?.items.find((item) => item.environmentId === event.target.value);
          setValue((current) => ({...current, environmentId: event.target.value,
            environmentApprovedVersion: env?.approvedVersion || 0}));
        }}><option value="">Select ACTIVE EKS environment</option>
          {envs.data?.items.map((env) => <option value={env.environmentId} key={env.environmentId}>
            {env.environmentName} · {env.customerName} · approved v{env.approvedVersion}
          </option>)}
        </select>
      </label>
      {value.environmentId && <div className="cluster-baseline-card field-span">
        {selectedEnvironment.isPending ? <Loading label="Loading approved environment baseline…"/> :
          selectedEnvironment.error ? <ErrorNotice error={selectedEnvironment.error}
            onRetry={() => selectedEnvironment.refetch()}/> : <>
            <div className="cluster-baseline-title"><Check size={18}/>
              <strong>{selectedEnvironment.data?.environmentName}</strong>
              <span>Approved v{value.environmentApprovedVersion}</span>
            </div>
            <dl className="cluster-baseline-grid">
              <div><dt>AWS account</dt><dd>{textValue(account.accountId)}</dd></div>
              <div><dt>Region</dt><dd>{textValue(location.region)}</dd></div>
              <div><dt>VPC</dt><dd>{textValue(vpc.vpcId)}</dd></div>
              <div><dt>Approved subnets</dt><dd>{clusterSubnets.length} cluster · {nodeSubnets.length} node</dd></div>
            </dl>
            <p className="metadata">Terraform uses this immutable approved snapshot—not the current editable environment record.</p>
          </>}
      </div>}
      <div className="section-heading field-span cluster-config-heading"><div>
        <span className="eyebrow">EKS CONFIGURATION</span><h2>Define the cluster platform</h2>
        <p>These settings are workload-specific; network, IAM, security groups, and KMS come from the approved profile.</p>
      </div><CloudCog aria-hidden="true"/></div>
      <label className="field">EKS cluster name *<input required value={value.clusterName}
        onChange={(event) => setValue({...value, clusterName: event.target.value})}/></label>
      <label className="field">Kubernetes version *<input required value={value.configuration.kubernetesVersion}
        onChange={(event) => setValue({...value, configuration: {...value.configuration,
          kubernetesVersion: event.target.value}})}/></label>
      <label className="field">Endpoint access *<select value={value.configuration.endpointAccess}
        onChange={(event) => setValue({...value, configuration: {...value.configuration,
          endpointAccess: event.target.value as "PRIVATE" | "PUBLIC_AND_PRIVATE"}})}>
        <option value="PRIVATE">Private only</option><option value="PUBLIC_AND_PRIVATE">Public and private</option>
      </select></label>
      <label className="field">Node group *<input required value={group.name}
        onChange={(event) => setGroup({name: event.target.value})}/></label>
      <label className="field">Instance type *<input required value={group.instanceTypes[0]}
        onChange={(event) => setGroup({instanceTypes: [event.target.value]})}/></label>
      <label className="field">Capacity *<select value={group.capacityType}
        onChange={(event) => setGroup({capacityType: event.target.value as "ON_DEMAND" | "SPOT"})}>
        <option value="ON_DEMAND">On-Demand</option><option value="SPOT">Spot</option>
      </select></label>
      {(["minSize", "desiredSize", "maxSize", "diskSizeGiB"] as const).map((name) =>
        <label className="field" key={name}>{name.replace(/([A-Z])/g, " $1")} *
          <input required type="number" min={name === "diskSizeGiB" ? 20 : 0} value={group[name]}
            onChange={(event) => setGroup({[name]: Number(event.target.value)})}/>
        </label>)}
      <label className="field field-span">Provisioning role ARN *<input required
        placeholder="arn:aws:iam::123456789012:role/NaviganProvisioningRole"
        value={value.provisioningRoleArn}
        onChange={(event) => setValue({...value, provisioningRoleArn: event.target.value})}/></label>
      <label className="field field-span">External ID secret ARN *<input required
        placeholder="arn:aws:secretsmanager:REGION:ACCOUNT:secret:navigan/provisioning/..."
        value={value.externalIdSecretArn}
        onChange={(event) => setValue({...value, externalIdSecretArn: event.target.value})}/></label>
    </div><div className="form-actions">
      <Link className="button button-secondary" href="/clusters">Cancel</Link>
      <button className="button button-primary" disabled={saving || !value.environmentApprovedVersion || selectedEnvironment.isPending}>
        {saving ? "Saving…" : "Save setup request draft"}
      </button>
    </div></form>
  </>;
}

export function ClusterRequestPage({id}: {id: string}) {
  const {identity} = useAuth();
  const query = useQuery({queryKey: ["cluster", id], queryFn: () => clusters.get(id), refetchInterval: 15000});
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  if (query.isPending) return <Loading label="Loading cluster request…"/>;
  if (query.error || !query.data) return <ErrorNotice error={query.error} onRetry={() => query.refetch()}/>;
  const row = query.data;
  const engineer = identity?.roles.includes("CLOUD_ENGINEER");
  const architect = identity?.roles.includes("PLATFORM_ARCHITECT");
  const actions: Array<"submit"|"review"|"approve"|"reject"|"plan"|"apply"> =
    engineer && ["DRAFT","REJECTED"].includes(row.status) ? ["submit"] :
    architect && row.status === "SUBMITTED" ? ["review"] :
    architect && row.status === "UNDER_REVIEW" ? ["approve","reject"] :
    architect && row.status === "FAILED" ? ["plan"] :
    architect && row.status === "PLAN_READY" ? ["apply"] : [];
  const act = async (action: typeof actions[number]) => {
    if (action === "apply" && !window.confirm(
      "Apply the exact approved Terraform plan to the customer AWS account?"
    )) return;
    const comments = action === "reject" ? window.prompt("Rejection reason") || "" : "";
    if (action === "reject" && !comments) return;
    setBusy(true); setError(undefined);
    try { await clusters.action(id, action, row.version, comments); await query.refetch(); }
    catch (caught) { setError(caught); } finally { setBusy(false); }
  };
  return <>
    <PageHeading eyebrow="CONTAINER PROVISIONING" title={row.clusterName}
      description={row.platform + " pinned to " + (row.environmentName || row.environmentId) +
        ", approved version " + row.environmentApprovedVersion + "."}/>
    {error && <ErrorNotice error={error}/>}
    <section className="panel panel-padding">
      <dl className="summary-grid">
        <div><dt>Status</dt><dd>{row.status.replaceAll("_", " ")}</dd></div>
        <div><dt>Request version</dt><dd>{row.version}</dd></div>
        <div><dt>Terraform plan</dt><dd>{row.planSha256 ? "Ready" : "Not generated"}</dd></div>
        <div><dt>Execution</dt><dd>{row.providerExecutionId || "Not started"}</dd></div>
      </dl>
      {row.workflow?.planSummary != null && <details className="configuration-tree">
        <summary>Terraform plan summary</summary>
        <pre>{JSON.stringify(row.workflow.planSummary, null, 2)}</pre>
      </details>}
      <div className="form-actions">{actions.map((action) =>
        <button key={action} disabled={busy} className="button button-primary"
          onClick={() => void act(action)}>
          {action === "plan" ? "Generate Terraform plan" :
            action === "apply" ? "Apply approved Terraform plan" :
            action.replace(/^./, (letter) => letter.toUpperCase())}
        </button>)}
      </div>
    </section>
  </>;
}
