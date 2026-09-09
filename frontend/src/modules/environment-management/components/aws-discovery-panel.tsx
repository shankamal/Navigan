"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  CloudCog,
  KeyRound,
  LockKeyhole,
  Network,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { Button, ErrorNotice, formatDate } from "@/shared/components/ui";
import { environments } from "../services/environments";
import type {
  AwsDiscovery,
  AwsDiscoveryInput,
  JsonValue,
} from "../model/types";

interface Selection {
  vpcId: string;
  subnetIds: string[];
  securityGroupIds: string[];
  clusterRoleArn: string;
  nodeRoleArn: string;
  kmsKeyArn: string;
}

function defaultSelection(discovery: AwsDiscovery): Selection {
  const region = discovery.regions[0];
  const vpc = region.vpcs.find((item) => !item.isDefault) || region.vpcs[0];
  const privateSubnets = region.subnets
    .filter((item) => item.vpcId === vpc?.vpcId && item.type === "PRIVATE")
    .slice(0, 3);
  const subnets =
    privateSubnets.length >= 2
      ? privateSubnets
      : region.subnets.filter((item) => item.vpcId === vpc?.vpcId).slice(0, 3);
  const groups = region.securityGroups
    .filter((item) => item.vpcId === vpc?.vpcId)
    .slice(0, 2);
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
  return {
    vpcId: vpc?.vpcId || "",
    subnetIds: subnets.map((item) => item.subnetId),
    securityGroupIds: groups.map((item) => item.securityGroupId),
    clusterRoleArn: clusterRole?.roleArn || "",
    nodeRoleArn: nodeRole?.roleArn || "",
    kmsKeyArn: region.kmsKeys[0]?.keyArn || "",
  };
}

function baselineFrom(
  discovery: AwsDiscovery,
  selection: Selection,
  environmentType: string,
  owner: string,
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
  const groups = region.securityGroups
    .filter((item) => selection.securityGroupIds.includes(item.securityGroupId))
    .map((item) => ({
      securityGroupId: item.securityGroupId,
      vpcId: item.vpcId || selection.vpcId,
    }));
  const selectedVpcEndpoints = region.vpcEndpoints.map(
    (item) => item.serviceName,
  );
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
      clusterSecurityGroups: groups,
      nodeSecurityGroups: groups,
    },
    iam: {
      clusterRole: { roleArn: selection.clusterRoleArn },
      nodeRole: { roleArn: selection.nodeRoleArn },
    },
    encryption: { nodeVolumeKmsKey: { keyArn: selection.kmsKeyArn } },
    connectivity: {
      egressMode:
        selectedVpcEndpoints.length >= 3 ? "PRIVATE_ENDPOINTS" : "NAT",
    },
    tags: { Owner: owner, CostCenter: "", Environment: environmentType },
    extensions: {
      discovery: {
        fetchedAt: discovery.fetchedAt,
        roleArn: discovery.roleArn,
        selectedVpcEndpointServices: selectedVpcEndpoints,
        selectedNatGatewayIds: selectedNatGateways.map(
          (item) => item.natGatewayId,
        ),
      },
      provisioningContract: {
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

export function AwsDiscoveryPanel({
  customerId,
  environmentType,
  owner,
  disabled,
  onApply,
}: {
  customerId: string;
  environmentType: string;
  owner: string;
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
  const [selection, setSelection] = useState<Selection>();
  const mutation = useMutation({
    mutationFn: () => environments.discoverAws({ ...input, customerId }),
    onSuccess: (value) => {
      const selected = defaultSelection(value);
      setResult(value);
      setSelection(selected);
      onApply(baselineFrom(value, selected, environmentType, owner));
    },
  });
  const region = result?.regions[0];
  const count = result
    ? Object.values(result.counts).reduce((sum, value) => sum + value, 0)
    : 0;
  const warnings = result
    ? Number(result.iamRoles.length < 2) +
      Number((region?.kmsKeys.length || 0) === 0)
    : 0;
  const set = (key: keyof AwsDiscoveryInput, value: string | string[]) =>
    setInput((current) => ({ ...current, [key]: value }));
  const select = (change: Partial<Selection>) => {
    if (!result || !selection) return;
    const next = { ...selection, ...change };
    setSelection(next);
    onApply(baselineFrom(result, next, environmentType, owner));
  };
  return (
    <section className="panel panel-padding aws-discovery-panel">
      <div className="environment-section-heading">
        <div>
          <p className="eyebrow">READ-ONLY CLOUD DISCOVERY</p>
          <h2>AWS account connection</h2>
          <p className="muted">
            Assume a customer-owned role to retrieve eligible infrastructure
            references. Navigan never stores the external ID or temporary AWS
            credentials.
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
          <small>
            The first AWS discovery release supports one region per profile
          </small>
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
          <small>
            For least privilege, the cross-account role name must be
            NaviganDiscoveryRole
          </small>
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
          <small>Sent only to AWS STS for confused-deputy protection</small>
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
              ? "Refresh details"
              : "Fetch details"}
        </Button>
        <span className="muted">
          No resources will be created, changed, or deleted.
        </span>
      </div>
      {mutation.error && (
        <ErrorNotice error={mutation.error} onRetry={() => mutation.mutate()} />
      )}
      {result && region && (
        <div className="discovery-results" aria-live="polite">
          <div className="notice notice-success discovery-success">
            <CheckCircle2 size={22} aria-hidden="true" />
            <div>
              <strong>
                Connected to AWS account {result.account.accountId}
              </strong>
              <p>
                {count} resource references discovered ·{" "}
                {warnings
                  ? `${warnings} checks need review`
                  : "all readiness checks passed"}
              </p>
            </div>
            <span className="metadata">
              Fetched {formatDate(result.fetchedAt)}
            </span>
          </div>
          <div className="discovery-summary-grid">
            <article>
              <Network size={20} />
              <span>Network</span>
              <strong>
                {region.vpcs.length} VPCs · {region.subnets.length} subnets
              </strong>
            </article>
            <article>
              <KeyRound size={20} />
              <span>Identity</span>
              <strong>{result.iamRoles.length} eligible IAM roles</strong>
            </article>
            <article>
              <ShieldCheck size={20} />
              <span>Security</span>
              <strong>
                {region.securityGroups.length} groups · {region.kmsKeys.length}{" "}
                KMS keys
              </strong>
            </article>
            <article className={warnings ? "needs-review" : ""}>
              {warnings ? (
                <AlertTriangle size={20} />
              ) : (
                <CheckCircle2 size={20} />
              )}
              <span>Readiness</span>
              <strong>{warnings ? `${warnings} warnings` : "Ready"}</strong>
            </article>
          </div>
          {selection && (
            <section
              className="discovery-selection"
              aria-labelledby="aws-baseline-selection"
            >
              <div className="environment-section-heading">
                <div>
                  <p className="eyebrow">SELECTED PROVISIONING BASELINE</p>
                  <h3 id="aws-baseline-selection">
                    Review the exact resources clusters may use
                  </h3>
                </div>
                <span className="security-chip">
                  <ShieldCheck size={15} /> Draft populated
                </span>
              </div>
              <div className="environment-identity-grid discovery-connection-grid">
                <label className="field">
                  VPC *
                  <select
                    value={selection.vpcId}
                    onChange={(event) => {
                      const vpcId = event.target.value;
                      const scoped = region.subnets
                        .filter(
                          (item) =>
                            item.vpcId === vpcId && item.type === "PRIVATE",
                        )
                        .slice(0, 3);
                      select({
                        vpcId,
                        subnetIds: scoped.map((item) => item.subnetId),
                        securityGroupIds: region.securityGroups
                          .filter((item) => item.vpcId === vpcId)
                          .slice(0, 2)
                          .map((item) => item.securityGroupId),
                      });
                    }}
                  >
                    {region.vpcs.map((item) => (
                      <option key={item.vpcId} value={item.vpcId}>
                        {item.name || item.vpcId} · {item.cidrBlock}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  Cluster IAM role *
                  <select
                    value={selection.clusterRoleArn}
                    onChange={(event) =>
                      select({ clusterRoleArn: event.target.value })
                    }
                  >
                    <option value="">Select a role</option>
                    {result.iamRoles.map((item) => (
                      <option key={item.roleArn} value={item.roleArn}>
                        {item.roleName}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  Node IAM role *
                  <select
                    value={selection.nodeRoleArn}
                    onChange={(event) =>
                      select({ nodeRoleArn: event.target.value })
                    }
                  >
                    <option value="">Select a role</option>
                    {result.iamRoles.map((item) => (
                      <option key={item.roleArn} value={item.roleArn}>
                        {item.roleName}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  Node-volume KMS key *
                  <select
                    value={selection.kmsKeyArn}
                    onChange={(event) =>
                      select({ kmsKeyArn: event.target.value })
                    }
                  >
                    <option value="">Select a customer-managed key</option>
                    {region.kmsKeys.map((item) => (
                      <option key={item.keyArn} value={item.keyArn}>
                        {item.aliasName || item.keyArn}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <fieldset className="discovery-options">
                <legend>
                  Private subnets * · select at least two availability zones
                </legend>
                <div className="discovery-option-grid">
                  {region.subnets
                    .filter((item) => item.vpcId === selection.vpcId)
                    .map((item) => (
                      <label
                        key={item.subnetId}
                        className={
                          selection.subnetIds.includes(item.subnetId)
                            ? "discovery-option selected"
                            : "discovery-option"
                        }
                      >
                        <input
                          type="checkbox"
                          checked={selection.subnetIds.includes(item.subnetId)}
                          onChange={(event) =>
                            select({
                              subnetIds: event.target.checked
                                ? [...selection.subnetIds, item.subnetId]
                                : selection.subnetIds.filter(
                                    (id) => id !== item.subnetId,
                                  ),
                            })
                          }
                        />
                        <span>
                          <strong>{item.name || item.subnetId}</strong>
                          <small>
                            {item.availabilityZone} · {item.type} ·{" "}
                            {item.availableIpAddressCount} IPs
                          </small>
                        </span>
                      </label>
                    ))}
                </div>
              </fieldset>
              <fieldset className="discovery-options">
                <legend>Security groups *</legend>
                <div className="discovery-option-grid">
                  {region.securityGroups
                    .filter((item) => item.vpcId === selection.vpcId)
                    .map((item) => (
                      <label
                        key={item.securityGroupId}
                        className={
                          selection.securityGroupIds.includes(
                            item.securityGroupId,
                          )
                            ? "discovery-option selected"
                            : "discovery-option"
                        }
                      >
                        <input
                          type="checkbox"
                          checked={selection.securityGroupIds.includes(
                            item.securityGroupId,
                          )}
                          onChange={(event) =>
                            select({
                              securityGroupIds: event.target.checked
                                ? [
                                    ...selection.securityGroupIds,
                                    item.securityGroupId,
                                  ]
                                : selection.securityGroupIds.filter(
                                    (id) => id !== item.securityGroupId,
                                  ),
                            })
                          }
                        />
                        <span>
                          <strong>{item.name || item.securityGroupId}</strong>
                          <small>{item.securityGroupId}</small>
                        </span>
                      </label>
                    ))}
                </div>
              </fieldset>
            </section>
          )}
          <div
            className="discovery-resource-table"
            role="region"
            aria-label="Discovered AWS resource readiness"
          >
            <div className="discovery-resource-row discovery-resource-head">
              <span>Resource type</span>
              <span>Status</span>
              <span>Details</span>
            </div>
            {[
              [
                "VPC",
                region.vpcs.length > 0,
                `${region.vpcs.length} VPCs found`,
              ],
              [
                "Private subnets",
                region.subnets.filter((item) => item.type === "PRIVATE")
                  .length >= 2,
                `${region.subnets.length} subnets across ${new Set(region.subnets.map((item) => item.availabilityZone)).size} AZs`,
              ],
              [
                "IAM roles",
                result.iamRoles.length >= 2,
                `${result.iamRoles.length} EKS/EC2 trust roles found`,
              ],
              [
                "KMS keys",
                region.kmsKeys.length > 0,
                `${region.kmsKeys.length} customer-managed keys found`,
              ],
              [
                "ECR repositories",
                true,
                `${region.ecrRepositories.length} repositories found`,
              ],
              [
                "VPC endpoints",
                region.vpcEndpoints.length >= 3,
                `${region.vpcEndpoints.length} endpoints found`,
              ],
              [
                "NAT gateways",
                region.natGateways.some((item) => item.state === "available"),
                `${region.natGateways.length} NAT gateways found`,
              ],
              [
                "Service quotas",
                region.serviceQuotas.length > 0,
                `${region.serviceQuotas.length} EKS/EC2 quota limits captured`,
              ],
              [
                "EBS encryption",
                region.ebsEncryptionByDefault,
                region.ebsEncryptionByDefault
                  ? "Encryption by default is enabled"
                  : "Encryption by default requires review",
              ],
            ].map(([label, passed, details]) => (
              <div className="discovery-resource-row" key={String(label)}>
                <strong>{label}</strong>
                <span
                  className={passed ? "readiness-pass" : "readiness-warning"}
                >
                  {passed ? (
                    <CheckCircle2 size={16} />
                  ) : (
                    <AlertTriangle size={16} />
                  )}
                  {passed ? "Passed" : "Review"}
                </span>
                <span>{details}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
