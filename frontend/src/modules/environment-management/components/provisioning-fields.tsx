"use client";
import { useState } from "react";
import {
  Boxes,
  Cpu,
  Database,
  Plus,
  ServerCog,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { Button } from "@/shared/components/ui";
import { ConfigurationFields } from "./configuration-fields";
import type {
  AwsDiscovery,
  ConfigurationSchema,
  JsonValue,
} from "../model/types";

function objectValue(value: unknown): Record<string, JsonValue> {
  return value != null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, JsonValue>)
    : {};
}

function stringValue(value: JsonValue | undefined) {
  return typeof value === "string" ? value : "";
}

function numberValue(value: JsonValue | undefined) {
  return typeof value === "number" ? value : "";
}

function nodeGroupsOf(blueprint: Record<string, JsonValue>) {
  return Array.isArray(blueprint.nodeGroups)
    ? (blueprint.nodeGroups as Record<string, JsonValue>[])
    : [];
}

function defaultNodeGroup(index: number): Record<string, JsonValue> {
  return {
    name: index ? `workers-${index + 1}` : "general",
    instanceTypes: ["m6i.large"],
    capacityType: "ON_DEMAND",
    minSize: 1,
    desiredSize: 2,
    maxSize: 4,
    diskSizeGiB: 50,
  };
}

function defaultBlueprint(index: number): Record<string, JsonValue> {
  return {
    name: index ? `cluster-${index + 1}` : "general",
    kubernetesVersion: "",
    endpointAccess: "PRIVATE",
    nodeGroups: [defaultNodeGroup(0)],
    provisioning: {},
  };
}

type DiscoveredInstanceType = NonNullable<
  AwsDiscovery["regions"][number]["instanceTypes"]
>[number];

function InstanceTypeSelector({
  options,
  selected,
  onChange,
}: {
  options: DiscoveredInstanceType[];
  selected: string[];
  onChange: (values: string[]) => void;
}) {
  const [search, setSearch] = useState("");
  const normalized = search.trim().toLowerCase();
  const filtered = options.filter((item) => {
    const memoryGiB = item.memoryMiB / 1024;
    return (
      !normalized ||
      item.instanceType.toLowerCase().includes(normalized) ||
      `${item.vCpu} vcpu`.includes(normalized) ||
      `${memoryGiB} gib`.includes(normalized) ||
      item.architectures.some((architecture) =>
        architecture.toLowerCase().includes(normalized),
      )
    );
  });
  const toggle = (instanceType: string) =>
    onChange(
      selected.includes(instanceType)
        ? selected.filter((item) => item !== instanceType)
        : [...selected, instanceType].sort(),
    );
  return (
    <div className="instance-type-selector">
      <input
        type="search"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        placeholder="Search by type, vCPU, memory or architecture"
        aria-label="Search available EC2 instance types"
      />
      <div className="instance-type-options" role="group" aria-label="Available EC2 instance types">
        {filtered.map((item) => (
          <label key={item.instanceType} className="instance-type-option">
            <input
              type="checkbox"
              checked={selected.includes(item.instanceType)}
              onChange={() => toggle(item.instanceType)}
            />
            <span>
              <strong>{item.instanceType}</strong>
              <small>
                {item.vCpu} vCPU · {(item.memoryMiB / 1024).toFixed(
                  item.memoryMiB % 1024 ? 1 : 0,
                )}{" "}
                GiB · {item.architectures.join(", ")}
                {item.currentGeneration ? " · Current generation" : ""}
              </small>
            </span>
          </label>
        ))}
        {!filtered.length && <p className="muted">No matching instance types.</p>}
      </div>
      <small>
        Selected: {selected.length ? selected.join(", ") : "none"}. One type
        keeps every node uniform; additional compatible types improve capacity
        resilience.
      </small>
    </div>
  );
}

function ProvisioningRoleAndSecretFields({
  provisioning,
  discovery,
  onChange,
}: {
  provisioning: Record<string, JsonValue>;
  discovery?: AwsDiscovery;
  onChange: (next: Record<string, JsonValue>) => void;
}) {
  const roles = discovery?.provisioningRoles ?? [];
  const secrets = discovery?.provisioningSecrets ?? [];
  const roleValue =
    typeof provisioning.roleArn === "string" ? provisioning.roleArn : "";
  const secretValue =
    typeof provisioning.externalIdSecretArn === "string"
      ? provisioning.externalIdSecretArn
      : "";
  const roleAvailable = roles.length > 0;
  const secretAvailable = secrets.length > 0;
  return (
    <fieldset className="blueprint-section">
      <legend>
        <ShieldCheck size={17} aria-hidden="true" />
        Provisioning access
      </legend>
      <p className="blueprint-section-help">
        Select the approved automation role and the secret containing its
        external ID.
      </p>
      <div className="blueprint-field-grid blueprint-field-grid-two">
        <label className="field">
          Provisioning role ARN *
          <select
            required
            value={roleValue}
            disabled={!roleAvailable}
            onChange={(e) =>
              onChange({ ...provisioning, roleArn: e.target.value })
            }
          >
            <option value="">
              {roleAvailable
                ? "Select an eligible provisioning role"
                : "No eligible provisioning role discovered"}
            </option>
            {roles.map((role) => (
              <option value={role.roleArn} key={role.roleArn}>
                ● Ready · {role.roleName}
              </option>
            ))}
          </select>
          {!roleAvailable && (
            <div className="resource-remediation">
              <strong>Provisioning role required</strong>
              <span>
                Run the Navigan provisioning bootstrap in this AWS account. It
                must create NaviganProvisioningRole with the approved trust
                policy, then run Fetch details again.
              </span>
            </div>
          )}
        </label>
        <label className="field">
          External ID secret ARN *
          <select
            required
            value={secretValue}
            disabled={!secretAvailable}
            onChange={(e) =>
              onChange({
                ...provisioning,
                externalIdSecretArn: e.target.value,
              })
            }
          >
            <option value="">
              {secretAvailable
                ? "Select an eligible external ID secret"
                : "No eligible external ID secret discovered"}
            </option>
            {secrets.map((secret) => (
              <option value={secret.arn} key={secret.arn}>
                ● Ready · {secret.name}
              </option>
            ))}
          </select>
          {!secretAvailable && (
            <div className="resource-remediation">
              <strong>External ID secret required</strong>
              <span>
                Create it through the Navigan bootstrap under
                navigan/provisioning/&lt;customer-id&gt;/, then run Fetch
                details again.
              </span>
            </div>
          )}
        </label>
      </div>
    </fieldset>
  );
}

export function ProvisioningFields({
  schema,
  configuration,
  discovery,
  onChange,
}: {
  schema: ConfigurationSchema;
  configuration: Record<string, JsonValue>;
  discovery?: AwsDiscovery;
  onChange: (configuration: Record<string, JsonValue>) => void;
}) {
  const clustersSchema = schema.properties?.clusters;
  const blueprintSchema = clustersSchema?.items;
  if (!clustersSchema || !blueprintSchema) return null;
  const blueprints = Array.isArray(configuration.clusters)
    ? (configuration.clusters as Record<string, JsonValue>[])
    : [];
  const tagsSchema = blueprintSchema.properties?.tags;
  const configuredLocation = objectValue(configuration.location);
  const configuredRegion = stringValue(configuredLocation.region);
  const discoveredRegion =
    discovery?.regions.find((item) => item.region === configuredRegion) ??
    discovery?.regions[0];
  const discoveredVersions = discoveredRegion?.kubernetesVersions ?? [];
  const discoveredInstanceTypes = discoveredRegion?.instanceTypes ?? [];
  const setBlueprint = (index: number, next: Record<string, JsonValue>) =>
    onChange({
      ...configuration,
      clusters: blueprints.map((b, i) => (i === index ? next : b)),
    });
  const setNodeGroups = (
    blueprintIndex: number,
    groups: Record<string, JsonValue>[],
  ) =>
    setBlueprint(blueprintIndex, {
      ...blueprints[blueprintIndex],
      nodeGroups: groups,
    });
  return (
    <section className="panel panel-padding environment-provisioning">
      <div className="blueprint-page-heading">
        <div>
          <p className="eyebrow">CLUSTER CATALOGUE</p>
          <h2>Cluster blueprints</h2>
          <p className="muted">
            Define reusable EKS shapes for this environment. Cluster requests
            select a blueprint by name instead of re-entering infrastructure
            settings.
          </p>
        </div>
        <span className="security-chip">
          <Boxes size={15} aria-hidden="true" />
          {blueprints.length}{" "}
          {blueprints.length === 1 ? "blueprint" : "blueprints"}
        </span>
      </div>
      {blueprints.map((blueprint, index) => (
        <article className="cluster-blueprint-card" key={index}>
          <header className="cluster-blueprint-header">
            <span className="blueprint-number">{index + 1}</span>
            <div>
              <h3>
                {stringValue(blueprint.name) ||
                  `Cluster blueprint ${index + 1}`}
              </h3>
              <p>Reusable Kubernetes and worker capacity configuration</p>
            </div>
            <Button
              type="button"
              variant="ghost"
              aria-label={`Remove cluster blueprint ${index + 1}`}
              onClick={() =>
                onChange({
                  ...configuration,
                  clusters: blueprints.filter((_, i) => i !== index),
                })
              }
            >
              <Trash2 size={16} aria-hidden="true" />
              Remove
            </Button>
          </header>

          <fieldset className="blueprint-section">
            <legend>
              <ServerCog size={17} aria-hidden="true" />
              Cluster identity
            </legend>
            <p className="blueprint-section-help">
              Give the blueprint a clear name and choose the Kubernetes control
              plane settings.
            </p>
            <div className="blueprint-field-grid">
              <label className="field">
                Blueprint name *
                <input
                  required
                  maxLength={63}
                  value={stringValue(blueprint.name)}
                  placeholder="e.g. dev-general"
                  onChange={(event) =>
                    setBlueprint(index, {
                      ...blueprint,
                      name: event.target.value,
                    })
                  }
                />
                <small>Shown when creating a new cluster setup request.</small>
              </label>
              <label className="field">
                Kubernetes version *
                <select
                  required
                  value={stringValue(blueprint.kubernetesVersion)}
                  onChange={(event) =>
                    setBlueprint(index, {
                      ...blueprint,
                      kubernetesVersion: event.target.value,
                    })
                  }
                >
                  <option value="">Select a supported EKS version</option>
                  {discoveredVersions.map((item) => (
                    <option key={item.version} value={item.version}>
                      {item.version}
                      {item.default ? " · AWS default" : ""}
                      {item.support === "STANDARD_SUPPORT"
                        ? " · Standard support"
                        : " · Extended support"}
                    </option>
                  ))}
                  {stringValue(blueprint.kubernetesVersion) &&
                    !discoveredVersions.some(
                      (item) =>
                        item.version ===
                        stringValue(blueprint.kubernetesVersion),
                    ) && (
                      <option value={stringValue(blueprint.kubernetesVersion)}>
                        {stringValue(blueprint.kubernetesVersion)} · Current
                        draft value
                      </option>
                    )}
                </select>
                {!discoveredVersions.length && (
                  <div className="resource-remediation">
                    <strong>No supported versions discovered</strong>
                    <span>
                      Grant NaviganDiscoveryRole
                      eks:DescribeClusterVersions permission, then run Fetch
                      details again.
                    </span>
                  </div>
                )}
              </label>
              <label className="field">
                API endpoint access *
                <select
                  required
                  value={stringValue(blueprint.endpointAccess)}
                  onChange={(event) =>
                    setBlueprint(index, {
                      ...blueprint,
                      endpointAccess: event.target.value,
                    })
                  }
                >
                  <option value="">Select endpoint access</option>
                  <option value="PRIVATE">Private only</option>
                  <option value="PUBLIC_AND_PRIVATE">Public and private</option>
                </select>
              </label>
            </div>
          </fieldset>

          <fieldset className="blueprint-section">
            <legend>
              <Cpu size={17} aria-hidden="true" />
              Managed node groups
            </legend>
            <p className="blueprint-section-help">
              Configure independent worker pools for applications with different
              capacity or scaling needs.
            </p>
            <div className="node-group-list">
              {nodeGroupsOf(blueprint).map((group, groupIndex) => {
                const groups = nodeGroupsOf(blueprint);
                const updateGroup = (patch: Record<string, JsonValue>) =>
                  setNodeGroups(
                    index,
                    groups.map((item, itemIndex) =>
                      itemIndex === groupIndex ? { ...item, ...patch } : item,
                    ),
                  );
                return (
                  <article className="node-group-card" key={groupIndex}>
                    <header>
                      <div>
                        <strong>
                          {stringValue(group.name) ||
                            `Node group ${groupIndex + 1}`}
                        </strong>
                        <span>Worker pool {groupIndex + 1}</span>
                      </div>
                      <Button
                        type="button"
                        variant="ghost"
                        aria-label={`Remove node group ${groupIndex + 1}`}
                        disabled={groups.length === 1}
                        onClick={() =>
                          setNodeGroups(
                            index,
                            groups.filter((_, i) => i !== groupIndex),
                          )
                        }
                      >
                        <Trash2 size={15} aria-hidden="true" />
                        Remove
                      </Button>
                    </header>
                    <div className="blueprint-field-grid">
                      <label className="field">
                        Node group name *
                        <input
                          required
                          maxLength={63}
                          value={stringValue(group.name)}
                          onChange={(event) =>
                            updateGroup({ name: event.target.value })
                          }
                        />
                      </label>
                      <label className="field">
                        Capacity type *
                        <select
                          required
                          value={stringValue(group.capacityType)}
                          onChange={(event) =>
                            updateGroup({ capacityType: event.target.value })
                          }
                        >
                          <option value="ON_DEMAND">On-demand</option>
                          <option value="SPOT">Spot</option>
                        </select>
                      </label>
                      <label className="field blueprint-wide-field">
                        EC2 instance types *
                        <small>
                          Available instance types discovered in{" "}
                          <strong>{configuredRegion || "the selected region"}</strong>.
                        </small>
                        {discoveredInstanceTypes.length ? (
                          <InstanceTypeSelector
                            options={discoveredInstanceTypes}
                            selected={
                              Array.isArray(group.instanceTypes)
                                ? group.instanceTypes.filter(
                                    (value): value is string =>
                                      typeof value === "string",
                                  )
                                : []
                            }
                            onChange={(instanceTypes) =>
                              updateGroup({ instanceTypes })
                            }
                          />
                        ) : (
                          <div className="resource-remediation">
                            <strong>
                              No instance types discovered for{" "}
                              {configuredRegion || "the selected region"}
                            </strong>
                            <span>
                              Grant NaviganDiscoveryRole
                              ec2:DescribeInstanceTypeOfferings and
                              ec2:DescribeInstanceTypes, then fetch AWS
                              inventory again.
                            </span>
                          </div>
                        )}
                      </label>
                    </div>
                    <div className="node-scaling-heading">
                      <Database size={16} aria-hidden="true" />
                      <strong>Scaling and storage</strong>
                    </div>
                    <div className="node-scaling-grid">
                      {(
                        [
                          ["minSize", "Minimum nodes", 0],
                          ["desiredSize", "Desired nodes", 0],
                          ["maxSize", "Maximum nodes", 1],
                          ["diskSizeGiB", "Disk size (GiB)", 20],
                        ] as const
                      ).map(([key, label, minimum]) => (
                        <label className="field" key={key}>
                          {label} *
                          <input
                            required
                            type="number"
                            min={minimum}
                            max={key === "diskSizeGiB" ? 16384 : 1000}
                            value={numberValue(group[key])}
                            onChange={(event) =>
                              updateGroup({
                                [key]:
                                  event.target.value === ""
                                    ? ""
                                    : Number(event.target.value),
                              })
                            }
                          />
                        </label>
                      ))}
                    </div>
                  </article>
                );
              })}
            </div>
            <Button
              type="button"
              variant="secondary"
              disabled={nodeGroupsOf(blueprint).length >= 20}
              onClick={() =>
                setNodeGroups(index, [
                  ...nodeGroupsOf(blueprint),
                  defaultNodeGroup(nodeGroupsOf(blueprint).length),
                ])
              }
            >
              <Plus size={16} aria-hidden="true" />
              Add node group
            </Button>
          </fieldset>

          <ProvisioningRoleAndSecretFields
            provisioning={objectValue(blueprint.provisioning)}
            discovery={discovery}
            onChange={(next) =>
              setBlueprint(index, { ...blueprint, provisioning: next })
            }
          />
          {tagsSchema && (
            <details className="blueprint-advanced">
              <summary>Optional cluster tags</summary>
              <ConfigurationFields
                schema={tagsSchema}
                value={blueprint.tags}
                path={`configuration.clusters.${index}.tags`}
                onChange={(next) =>
                  setBlueprint(index, { ...blueprint, tags: next })
                }
              />
            </details>
          )}
        </article>
      ))}
      <div className="blueprint-add-panel">
        <div>
          <strong>Add another cluster shape</strong>
          <p>
            Use a separate blueprint when worker capacity, endpoint access, or
            provisioning credentials differ.
          </p>
        </div>
        <Button
          type="button"
          variant="secondary"
          disabled={blueprints.length >= 20}
          onClick={() =>
            onChange({
              ...configuration,
              clusters: [...blueprints, defaultBlueprint(blueprints.length)],
            })
          }
        >
          <Plus size={17} aria-hidden="true" />
          Add cluster blueprint
        </Button>
      </div>
    </section>
  );
}
