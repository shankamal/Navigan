"use client";

import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  CloudCog,
  KeyRound,
  LockKeyhole,
  Network,
  RefreshCw,
  Search,
  ShieldCheck,
  X,
} from "lucide-react";
import { Button, ErrorNotice, formatDate } from "@/shared/components/ui";
import { environments } from "../services/environments";
import type {
  AwsDiscovery,
  AwsDiscoveryInput,
  JsonValue,
} from "../model/types";

export interface AwsBaselineSelection {
  vpcId: string;
  subnetIds: string[];
  clusterSecurityGroupIds: string[];
  nodeSecurityGroupIds: string[];
  clusterRoleArn: string;
  nodeRoleArn: string;
  kmsKeyArn: string;
  egressMode: "NAT" | "PRIVATE_ENDPOINTS" | "";
}

interface ReadinessCheck {
  id: string;
  label: string;
  passed: boolean;
  details: string;
}

function privateSubnetsForVpc(discovery: AwsDiscovery, vpcId: string) {
  return discovery.regions[0].subnets.filter(
    (item) => item.vpcId === vpcId && item.type === "PRIVATE",
  );
}

function preferredSubnets(discovery: AwsDiscovery, vpcId: string) {
  const byZone = new Map<string, (typeof discovery.regions)[0]["subnets"][0]>();
  for (const subnet of privateSubnetsForVpc(discovery, vpcId)) {
    const current = byZone.get(subnet.availabilityZone);
    if (
      !current ||
      subnet.availableIpAddressCount > current.availableIpAddressCount
    )
      byZone.set(subnet.availabilityZone, subnet);
  }
  return [...byZone.values()]
    .sort((a, b) => b.availableIpAddressCount - a.availableIpAddressCount)
    .slice(0, 3);
}

export function defaultAwsBaselineSelection(
  discovery: AwsDiscovery,
): AwsBaselineSelection {
  const region = discovery.regions[0];
  const rankedVpcs = region.vpcs
    .map((vpc) => ({
      vpc,
      zones: new Set(
        privateSubnetsForVpc(discovery, vpc.vpcId).map(
          (item) => item.availabilityZone,
        ),
      ).size,
      addresses: privateSubnetsForVpc(discovery, vpc.vpcId).reduce(
        (sum, item) => sum + item.availableIpAddressCount,
        0,
      ),
    }))
    .sort(
      (a, b) =>
        Number(b.zones >= 2) - Number(a.zones >= 2) ||
        b.zones - a.zones ||
        b.addresses - a.addresses ||
        Number(a.vpc.isDefault) - Number(b.vpc.isDefault),
    );
  const vpcId = rankedVpcs[0]?.vpc.vpcId || "";
  const groups = region.securityGroups.filter((item) => item.vpcId === vpcId);
  const clusterRole =
    discovery.iamRoles.find((item) =>
      item.roleName.toLowerCase().includes("cluster"),
    ) || discovery.iamRoles[0];
  const nodeRole =
    discovery.iamRoles.find((item) =>
      item.roleName.toLowerCase().includes("node"),
    ) ||
    discovery.iamRoles[1] ||
    discovery.iamRoles[0];
  const hasNat = region.natGateways.some(
    (item) => item.vpcId === vpcId && item.state === "available",
  );
  return {
    vpcId,
    subnetIds: preferredSubnets(discovery, vpcId).map(
      (item) => item.subnetId,
    ),
    clusterSecurityGroupIds: groups[0]
      ? [groups[0].securityGroupId]
      : [],
    nodeSecurityGroupIds: groups[1]
      ? [groups[1].securityGroupId]
      : groups[0]
        ? [groups[0].securityGroupId]
        : [],
    clusterRoleArn: clusterRole?.roleArn || "",
    nodeRoleArn: nodeRole?.roleArn || "",
    kmsKeyArn: region.kmsKeys[0]?.keyArn || "",
    egressMode: hasNat
      ? "NAT"
      : region.vpcEndpoints.length >= 3
        ? "PRIVATE_ENDPOINTS"
        : "",
  };
}

export function validateAwsBaselineSelection(
  discovery: AwsDiscovery,
  selection: AwsBaselineSelection,
  costCenter: string,
) {
  const region = discovery.regions[0];
  const selectedSubnets = region.subnets.filter((item) =>
    selection.subnetIds.includes(item.subnetId),
  );
  const selectedZones = new Set(
    selectedSubnets.map((item) => item.availabilityZone),
  );
  const allPrivate = selectedSubnets.every(
    (item) => item.type === "PRIVATE" && item.vpcId === selection.vpcId,
  );
  const clusterGroupsValid = selection.clusterSecurityGroupIds.every((id) =>
    region.securityGroups.some(
      (item) => item.securityGroupId === id && item.vpcId === selection.vpcId,
    ),
  );
  const nodeGroupsValid = selection.nodeSecurityGroupIds.every((id) =>
    region.securityGroups.some(
      (item) => item.securityGroupId === id && item.vpcId === selection.vpcId,
    ),
  );
  const checks: ReadinessCheck[] = [
    {
      id: "vpc",
      label: "VPC",
      passed: region.vpcs.some((item) => item.vpcId === selection.vpcId),
      details: selection.vpcId
        ? "Selected from the discovered account and region"
        : "Select one VPC",
    },
    {
      id: "subnets",
      label: "Private subnets",
      passed:
        selectedSubnets.length >= 2 && selectedZones.size >= 2 && allPrivate,
      details: `${selectedSubnets.length} selected across ${selectedZones.size} availability zones`,
    },
    {
      id: "roles",
      label: "EKS IAM roles",
      passed: Boolean(selection.clusterRoleArn && selection.nodeRoleArn),
      details:
        selection.clusterRoleArn && selection.nodeRoleArn
          ? "Cluster and node roles selected"
          : "Select both cluster and node roles",
    },
    {
      id: "security-groups",
      label: "Security groups",
      passed:
        selection.clusterSecurityGroupIds.length > 0 &&
        selection.nodeSecurityGroupIds.length > 0 &&
        clusterGroupsValid &&
        nodeGroupsValid,
      details: `${selection.clusterSecurityGroupIds.length} cluster · ${selection.nodeSecurityGroupIds.length} node`,
    },
    {
      id: "kms",
      label: "Node-volume encryption",
      passed: Boolean(selection.kmsKeyArn),
      details: selection.kmsKeyArn
        ? "Customer-managed KMS key selected"
        : "Select a customer-managed KMS key",
    },
    {
      id: "egress",
      label: "Private connectivity",
      passed: Boolean(selection.egressMode),
      details:
        selection.egressMode === "NAT"
          ? "Outbound access through an available NAT gateway"
          : selection.egressMode === "PRIVATE_ENDPOINTS"
            ? "Outbound access through VPC endpoints"
            : "No eligible egress option discovered",
    },
    {
      id: "tags",
      label: "Required tags",
      passed: Boolean(costCenter.trim()),
      details: costCenter.trim()
        ? `Cost center ${costCenter.trim()} included`
        : "Enter the customer cost center",
    },
  ];
  return {
    checks,
    ready: checks.every((item) => item.passed),
  };
}

function baselineFrom(
  discovery: AwsDiscovery,
  selection: AwsBaselineSelection,
  environmentType: string,
  owner: string,
  costCenter: string,
) {
  const region = discovery.regions[0];
  const subnets = region.subnets
    .filter((item) => selection.subnetIds.includes(item.subnetId))
    .map((item) => ({
      subnetId: item.subnetId,
      vpcId: item.vpcId,
      availabilityZone: item.availabilityZone,
      name: item.name || item.subnetId,
      cidrBlock: item.cidrBlock || undefined,
      type: item.type,
      routeTableId: item.routeTableId,
      egressTarget: item.egressTarget,
      availableIpAddressCount: item.availableIpAddressCount,
    }));
  const securityGroups = (ids: string[]) =>
    region.securityGroups
      .filter((item) => ids.includes(item.securityGroupId))
      .map((item) => ({
        securityGroupId: item.securityGroupId,
        vpcId: item.vpcId || selection.vpcId,
      }));
  const selectedNatGateways = region.natGateways.filter(
    (item) => item.vpcId === selection.vpcId && item.state === "available",
  );
  return {
    account: { accountId: discovery.account.accountId },
    location: { region: region.region },
    network: {
      vpc: { vpcId: selection.vpcId },
      clusterSubnets: subnets,
      nodeSubnets: subnets,
    },
    security: {
      clusterSecurityGroups: securityGroups(
        selection.clusterSecurityGroupIds,
      ),
      nodeSecurityGroups: securityGroups(selection.nodeSecurityGroupIds),
    },
    iam: {
      clusterRole: { roleArn: selection.clusterRoleArn },
      nodeRole: { roleArn: selection.nodeRoleArn },
    },
    encryption: { nodeVolumeKmsKey: { keyArn: selection.kmsKeyArn } },
    connectivity: { egressMode: selection.egressMode },
    tags: {
      Owner: owner,
      CostCenter: costCenter.trim(),
      Environment: environmentType,
    },
    extensions: {
      discovery: {
        fetchedAt: discovery.fetchedAt,
        roleArn: discovery.roleArn,
        selectedVpcEndpointServices:
          selection.egressMode === "PRIVATE_ENDPOINTS"
            ? region.vpcEndpoints.map((item) => item.serviceName)
            : [],
        selectedNatGatewayIds:
          selection.egressMode === "NAT"
            ? selectedNatGateways.map((item) => item.natGatewayId)
            : [],
      },
      provisioningContract: {
        contractVersion: "1.0",
        platform: "EKS",
        clusterRequestOwns: [
          "kubernetesVersion",
          "endpointAccess",
          "nodePools",
          "addons",
        ],
        profileOwns: [
          "account",
          "region",
          "network",
          "security",
          "iam",
          "encryption",
          "connectivity",
        ],
        discoveredQuotaLimits: region.serviceQuotas,
        ebsEncryptionByDefault: region.ebsEncryptionByDefault,
      },
    },
  } as Record<string, JsonValue>;
}

function ChoiceList({
  legend,
  help,
  items,
  selected,
  onChange,
}: {
  legend: string;
  help: string;
  items: { id: string; name: string; metadata: string }[];
  selected: string[];
  onChange: (ids: string[]) => void;
}) {
  return (
    <fieldset className="discovery-options">
      <legend>{legend}</legend>
      <p className="discovery-help">{help}</p>
      <div className="discovery-option-grid">
        {items.map((item) => {
          const checked = selected.includes(item.id);
          return (
            <label
              key={item.id}
              className={
                checked ? "discovery-option selected" : "discovery-option"
              }
            >
              <input
                type="checkbox"
                checked={checked}
                onChange={(event) =>
                  onChange(
                    event.target.checked
                      ? [...selected, item.id]
                      : selected.filter((id) => id !== item.id),
                  )
                }
              />
              <span>
                <strong>{item.name}</strong>
                <small>{item.metadata}</small>
              </span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

function CompactMultiSelect({
  legend,
  help,
  items,
  selected,
  onChange,
}: {
  legend: string;
  help: string;
  items: { id: string; name: string; metadata: string }[];
  selected: string[];
  onChange: (ids: string[]) => void;
}) {
  const [query, setQuery] = useState("");
  const normalizedQuery = query.trim().toLowerCase();
  const available = items.filter(
    (item) =>
      !selected.includes(item.id) &&
      (!normalizedQuery ||
        `${item.name} ${item.id} ${item.metadata}`
          .toLowerCase()
          .includes(normalizedQuery)),
  );
  const selectedItems = selected
    .map((id) => items.find((item) => item.id === id))
    .filter((item): item is (typeof items)[number] => Boolean(item));

  return (
    <fieldset className="compact-selector">
      <legend>{legend}</legend>
      <p className="discovery-help">{help}</p>
      <div className="compact-selector-search">
        <Search size={16} aria-hidden="true" />
        <input
          aria-label={`Search ${legend}`}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search by name, ID or description"
        />
      </div>
      <select
        aria-label={`Add ${legend}`}
        value=""
        onChange={(event) => {
          if (!event.target.value) return;
          onChange([...selected, event.target.value]);
          setQuery("");
        }}
      >
        <option value="">
          {available.length
            ? `Select from ${available.length} matching groups…`
            : "No matching groups available"}
        </option>
        {available.map((item) => (
          <option key={item.id} value={item.id}>
            {item.name} · {item.id}
          </option>
        ))}
      </select>
      <div className="compact-selected" aria-live="polite">
        {selectedItems.length ? (
          selectedItems.map((item) => (
            <span className="compact-chip" key={item.id}>
              <span>
                <strong>{item.name}</strong>
                <small>{item.id}</small>
              </span>
              <button
                type="button"
                aria-label={`Remove ${item.name}`}
                onClick={() => onChange(selected.filter((id) => id !== item.id))}
              >
                <X size={14} aria-hidden="true" />
              </button>
            </span>
          ))
        ) : (
          <span className="compact-empty">No security groups selected</span>
        )}
      </div>
    </fieldset>
  );
}

export function AwsDiscoveryPanel({
  customerId,
  environmentType,
  owner,
  costCenter,
  disabled,
  onApply,
}: {
  customerId: string;
  environmentType: string;
  owner: string;
  costCenter: string;
  disabled: boolean;
  onApply: (configuration: Record<string, JsonValue>) => void;
}) {
  const [input, setInput] = useState<AwsDiscoveryInput>({
    customerId,
    accountId: "",
    roleArn: "",
    externalId: "",
    regions: ["ap-south-1"],
  });
  const [result, setResult] = useState<AwsDiscovery>();
  const [selection, setSelection] = useState<AwsBaselineSelection>();
  const [applied, setApplied] = useState(false);
  const mutation = useMutation({
    mutationFn: () => environments.discoverAws({ ...input, customerId }),
    onSuccess: (value) => {
      setResult(value);
      setSelection(defaultAwsBaselineSelection(value));
      setApplied(false);
    },
  });
  const region = result?.regions[0];
  const readiness = useMemo(
    () =>
      result && selection
        ? validateAwsBaselineSelection(result, selection, costCenter)
        : undefined,
    [result, selection, costCenter],
  );
  const count = result
    ? Object.values(result.counts).reduce((sum, value) => sum + value, 0)
    : 0;
  const set = (key: keyof AwsDiscoveryInput, value: string | string[]) => {
    setInput((current) => ({ ...current, [key]: value }));
    setApplied(false);
  };
  const select = (change: Partial<AwsBaselineSelection>) => {
    setSelection((current) => (current ? { ...current, ...change } : current));
    setApplied(false);
  };
  const apply = () => {
    if (!result || !selection || !readiness?.ready) return;
    onApply(
      baselineFrom(result, selection, environmentType, owner, costCenter),
    );
    setApplied(true);
  };
  const availableEgress = region && selection
    ? {
        nat: region.natGateways.some(
          (item) =>
            item.vpcId === selection.vpcId && item.state === "available",
        ),
        endpoints: region.vpcEndpoints.length >= 3,
      }
    : { nat: false, endpoints: false };
  return (
    <section className="panel panel-padding aws-discovery-panel">
      <div className="environment-section-heading">
        <div>
          <p className="eyebrow">READ-ONLY CLOUD DISCOVERY</p>
          <h2>AWS account connection</h2>
          <p className="muted">
            Discover eligible infrastructure, then approve only the resources
            this EKS environment profile may use.
          </p>
        </div>
        <span className="security-chip">
          <LockKeyhole size={15} /> STS temporary access
        </span>
      </div>
      <div className="environment-identity-grid discovery-connection-grid">
        <label className="field">
          AWS account ID *
          <input
            required
            inputMode="numeric"
            pattern="[0-9]{12}"
            maxLength={12}
            value={input.accountId}
            onChange={(event) => set("accountId", event.target.value)}
            placeholder="123456789012"
          />
          <small>12-digit customer AWS account identifier</small>
        </label>
        <label className="field">
          Primary region *
          <select
            value={input.regions[0]}
            onChange={(event) => set("regions", [event.target.value])}
          >
            {[
              "ap-south-1",
              "ap-southeast-1",
              "eu-west-1",
              "us-east-1",
              "us-west-2",
            ].map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
          <small>One AWS region per environment profile</small>
        </label>
        <label className="field discovery-wide-field">
          Discovery role ARN *
          <input
            required
            maxLength={2048}
            value={input.roleArn}
            onChange={(event) => set("roleArn", event.target.value)}
            placeholder="arn:aws:iam::123456789012:role/NaviganDiscoveryRole"
          />
          <small>Read-only role trusted by the Navigan discovery Lambda</small>
        </label>
        <label className="field discovery-wide-field">
          External ID *
          <input
            required
            type="password"
            maxLength={1224}
            value={input.externalId}
            onChange={(event) => set("externalId", event.target.value)}
            autoComplete="new-password"
          />
          <small>Sent only to AWS STS and never stored by Navigan</small>
        </label>
      </div>
      <div className="environment-actions discovery-actions">
        <Button
          type="button"
          disabled={
            disabled ||
            mutation.isPending ||
            !customerId ||
            !input.accountId ||
            !input.roleArn ||
            !input.externalId
          }
          onClick={() => mutation.mutate()}
        >
          {mutation.isPending ? (
            <RefreshCw className="animate-spin" size={17} />
          ) : (
            <CloudCog size={17} />
          )}
          {mutation.isPending
            ? "Fetching AWS resources…"
            : result
              ? "Refresh inventory"
              : "Fetch AWS inventory"}
        </Button>
        <span className="muted">Discovery makes no changes in AWS.</span>
      </div>
      {mutation.error && (
        <ErrorNotice error={mutation.error} onRetry={() => mutation.mutate()} />
      )}
      {result && region && selection && readiness && (
        <div className="discovery-results" aria-live="polite">
          <div className="notice notice-success discovery-success">
            <CheckCircle2 size={22} aria-hidden="true" />
            <div>
              <strong>AWS account {result.account.accountId} connected</strong>
              <p>
                {count} references discovered · {readiness.checks.filter((item) => item.passed).length}
                /{readiness.checks.length} baseline checks passed
              </p>
            </div>
            <span className="metadata">Fetched {formatDate(result.fetchedAt)}</span>
          </div>
          <div className="discovery-summary-grid">
            <article>
              <Network size={20} />
              <span>Network</span>
              <strong>{region.vpcs.length} VPCs · {region.subnets.length} subnets</strong>
            </article>
            <article>
              <KeyRound size={20} />
              <span>Identity</span>
              <strong>{result.iamRoles.length} eligible IAM roles</strong>
            </article>
            <article>
              <ShieldCheck size={20} />
              <span>Security</span>
              <strong>{region.securityGroups.length} groups · {region.kmsKeys.length} KMS keys</strong>
            </article>
            <article className={readiness.ready ? "" : "needs-review"}>
              {readiness.ready ? <CheckCircle2 size={20} /> : <AlertTriangle size={20} />}
              <span>Selected baseline</span>
              <strong>{readiness.ready ? "Ready to apply" : "Selection required"}</strong>
            </article>
          </div>
          <section className="discovery-selection" aria-labelledby="aws-baseline-selection">
            <div className="environment-section-heading">
              <div>
                <p className="eyebrow">EKS PROVISIONING BASELINE</p>
                <h3 id="aws-baseline-selection">Select the exact resources EKS may use</h3>
                <p className="muted">Only this approved baseline is saved in the environment profile. Cluster version, capacity and add-ons remain part of the later cluster request.</p>
              </div>
              <span className={readiness.ready ? "security-chip" : "security-chip needs-review"}>
                {readiness.ready ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />}
                {readiness.ready ? "Baseline ready" : "Review required"}
              </span>
            </div>
            <div className="baseline-group">
              <div className="baseline-group-heading">
                <Network size={19} />
                <div><h4>1. Network</h4><p>Select one VPC and private subnets in at least two availability zones.</p></div>
              </div>
              <label className="field baseline-primary-field">
                VPC *
                <select
                  value={selection.vpcId}
                  onChange={(event) => {
                    const vpcId = event.target.value;
                    const groups = region.securityGroups.filter((item) => item.vpcId === vpcId);
                    const nat = region.natGateways.some((item) => item.vpcId === vpcId && item.state === "available");
                    select({
                      vpcId,
                      subnetIds: preferredSubnets(result, vpcId).map((item) => item.subnetId),
                      clusterSecurityGroupIds: groups[0] ? [groups[0].securityGroupId] : [],
                      nodeSecurityGroupIds: groups[1] ? [groups[1].securityGroupId] : groups[0] ? [groups[0].securityGroupId] : [],
                      egressMode: nat ? "NAT" : region.vpcEndpoints.length >= 3 ? "PRIVATE_ENDPOINTS" : "",
                    });
                  }}
                >
                  {region.vpcs.map((item) => (
                    <option key={item.vpcId} value={item.vpcId}>{item.name || item.vpcId} · {item.vpcId} · {item.cidrBlock}</option>
                  ))}
                </select>
              </label>
              <ChoiceList
                legend="Approved private subnets *"
                help="Select at least two subnets in different availability zones. Public subnets are excluded."
                items={privateSubnetsForVpc(result, selection.vpcId).map((item) => ({
                  id: item.subnetId,
                  name: item.name || item.subnetId,
                  metadata: `${item.subnetId} · ${item.availabilityZone} · ${item.cidrBlock || "CIDR unavailable"} · ${item.availableIpAddressCount} IPs`,
                }))}
                selected={selection.subnetIds}
                onChange={(subnetIds) => select({ subnetIds })}
              />
            </div>
            <div className="baseline-group">
              <div className="baseline-group-heading">
                <KeyRound size={19} />
                <div><h4>2. IAM and encryption</h4><p>Pin the roles and KMS key that the future cluster request may reference.</p></div>
              </div>
              <div className="baseline-field-grid">
                <label className="field">EKS cluster role *
                  <select value={selection.clusterRoleArn} onChange={(event) => select({ clusterRoleArn: event.target.value })}>
                    <option value="">Select a cluster role</option>
                    {result.iamRoles.map((item) => <option key={item.roleArn} value={item.roleArn}>{item.roleName}</option>)}
                  </select>
                </label>
                <label className="field">EKS node role *
                  <select value={selection.nodeRoleArn} onChange={(event) => select({ nodeRoleArn: event.target.value })}>
                    <option value="">Select a node role</option>
                    {result.iamRoles.map((item) => <option key={item.roleArn} value={item.roleArn}>{item.roleName}</option>)}
                  </select>
                </label>
                <label className="field">Node-volume KMS key *
                  <select value={selection.kmsKeyArn} onChange={(event) => select({ kmsKeyArn: event.target.value })}>
                    <option value="">Select a customer-managed key</option>
                    {region.kmsKeys.map((item) => <option key={item.keyArn} value={item.keyArn}>{item.aliasName || item.keyArn}</option>)}
                  </select>
                </label>
              </div>
            </div>
            <div className="baseline-group">
              <div className="baseline-group-heading">
                <ShieldCheck size={19} />
                <div><h4>3. Security groups</h4><p>Keep control-plane and worker-node access independently selectable.</p></div>
              </div>
              <div className="baseline-field-grid baseline-field-grid-two">
                <CompactMultiSelect
                  legend="Cluster security groups *"
                  help="Applied to EKS control-plane network interfaces."
                  items={region.securityGroups.filter((item) => item.vpcId === selection.vpcId).map((item) => ({ id: item.securityGroupId, name: item.name || item.securityGroupId, metadata: `${item.securityGroupId} · ${item.description}` }))}
                  selected={selection.clusterSecurityGroupIds}
                  onChange={(clusterSecurityGroupIds) => select({ clusterSecurityGroupIds })}
                />
                <CompactMultiSelect
                  legend="Node security groups *"
                  help="Applied to managed node groups created later."
                  items={region.securityGroups.filter((item) => item.vpcId === selection.vpcId).map((item) => ({ id: item.securityGroupId, name: item.name || item.securityGroupId, metadata: `${item.securityGroupId} · ${item.description}` }))}
                  selected={selection.nodeSecurityGroupIds}
                  onChange={(nodeSecurityGroupIds) => select({ nodeSecurityGroupIds })}
                />
              </div>
            </div>
            <div className="baseline-group">
              <div className="baseline-group-heading">
                <CloudCog size={19} />
                <div><h4>4. Private connectivity</h4><p>Select an egress path already discovered for the selected VPC.</p></div>
              </div>
              <label className="field baseline-primary-field">Approved egress *
                <select value={selection.egressMode} onChange={(event) => select({ egressMode: event.target.value as AwsBaselineSelection["egressMode"] })}>
                  <option value="">No eligible path discovered</option>
                  {availableEgress.nat && <option value="NAT">NAT gateway</option>}
                  {availableEgress.endpoints && <option value="PRIVATE_ENDPOINTS">VPC endpoints</option>}
                </select>
              </label>
            </div>
            <div className="baseline-review">
              <div>
                <h4>Provisioning readiness</h4>
                <p className="muted">Resolve every failed check before applying this baseline to the draft.</p>
              </div>
              <div className="baseline-checks">
                {readiness.checks.map((item) => (
                  <div key={item.id} className={item.passed ? "baseline-check passed" : "baseline-check failed"}>
                    {item.passed ? <CheckCircle2 size={17} /> : <AlertTriangle size={17} />}
                    <span><strong>{item.label}</strong><small>{item.details}</small></span>
                  </div>
                ))}
              </div>
              <div className="environment-actions baseline-apply-actions">
                {applied && <span className="readiness-pass"><CheckCircle2 size={17} /> Baseline applied to draft</span>}
                <Button type="button" disabled={disabled || !readiness.ready} onClick={apply}>
                  {applied ? "Reapply selected baseline" : "Apply selected baseline"}
                </Button>
              </div>
            </div>
          </section>
          <details className="discovery-inventory-details">
            <summary><ChevronDown size={17} /> Review complete discovery inventory</summary>
            <div className="discovery-resource-table" role="region" aria-label="Discovered AWS resource inventory">
              <div className="discovery-resource-row discovery-resource-head"><span>Resource type</span><span>Discovered</span><span>Profile relevance</span></div>
              {[
                ["VPCs", region.vpcs.length, "Select exactly one"],
                ["Private subnets", region.subnets.filter((item) => item.type === "PRIVATE").length, "Select two or more availability zones"],
                ["IAM roles", result.iamRoles.length, "Select cluster and node roles"],
                ["Security groups", region.securityGroups.length, "Select cluster and node groups"],
                ["KMS keys", region.kmsKeys.length, "Select one node-volume key"],
                ["VPC endpoints", region.vpcEndpoints.length, "Optional private egress path"],
                ["NAT gateways", region.natGateways.filter((item) => item.state === "available").length, "Optional managed egress path"],
                ["ECR repositories", region.ecrRepositories.length, "Inventory only; not stored in baseline"],
                ["Service quotas", region.serviceQuotas.length, "Revalidated before provisioning"],
              ].map(([label, discovered, relevance]) => (
                <div className="discovery-resource-row" key={String(label)}><strong>{label}</strong><span>{discovered}</span><span>{relevance}</span></div>
              ))}
            </div>
          </details>
        </div>
      )}
    </section>
  );
}
