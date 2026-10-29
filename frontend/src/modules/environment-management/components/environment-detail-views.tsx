"use client";

import Link from "next/link";
import { useState } from "react";
import {
  ArrowRight,
  Check,
  ChevronRight,
  Cloud,
  Code2,
  Copy,
  FileClock,
  History,
  Info,
  KeyRound,
  Layers3,
  MapPin,
  Network,
  ShieldCheck,
  Tags,
  X,
} from "lucide-react";
import { Button, Pagination, formatDateTime } from "@/shared/components/ui";
import { ProviderBadges } from "@/modules/customer-management/components/customer-badges";
import type { Environment, HistoryKind } from "../model/types";
import type { environments } from "../services/environments";
import styles from "./environment-details-studio.module.css";

type ObjectValue = Record<string, unknown>;
type Records = Awaited<ReturnType<typeof environments.records>>;
type RecordItem = Records["items"][number];
const object = (value: unknown): ObjectValue =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as ObjectValue)
    : {};
const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const text = (value: unknown) =>
  value === undefined || value === null || value === ""
    ? "Not recorded"
    : typeof value === "object"
      ? JSON.stringify(value)
      : String(value);
const fieldNames: Record<string, string> = {
  subnetId: "Subnet ID",
  vpcId: "VPC ID",
  cidrBlock: "CIDR block",
  availabilityZone: "Availability zone",
  availableIpAddressCount: "Available IPs",
  routeTableId: "Route table ID",
  egressTarget: "Egress target",
  roleArn: "Role ARN",
  keyArn: "Key ARN",
};
const title = (value: string) =>
  fieldNames[value] ||
  value
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replaceAll("_", " ")
    .replace(/^./, (letter) => letter.toUpperCase());
const roleName = (value: unknown) =>
  text(value).split("/").at(-1) || text(value);

export function SavedValue({
  value,
  label,
  compact = false,
}: {
  value: unknown;
  label: string;
  compact?: boolean;
}) {
  const [copyState, setCopyState] = useState("");
  const full = text(value);
  return (
    <span className={styles.savedValue}>
      <span className={styles.valueText} title={full}>
        {compact ? roleName(value) : full}
      </span>
      {value !== undefined && value !== null && value !== "" && (
        <button
          type="button"
          className={styles.iconButton}
          aria-label={`Copy ${label}`}
          title={copyState || `Copy ${label}`}
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(full);
              setCopyState("Copied");
            } catch {
              setCopyState("Copy unavailable. Select the value to copy.");
            }
          }}
        >
          {copyState === "Copied" ? <Check size={13} /> : <Copy size={13} />}
        </button>
      )}
      {copyState && (
        <span className={styles.srOnly} role="status">
          {copyState}
        </span>
      )}
    </span>
  );
}

/** Collections stay collapsed until requested; unknown configuration fields remain accessible. */
export function ConfigurationValue({
  value,
  label = "Configuration",
}: {
  value: unknown;
  label?: string;
}) {
  if (Array.isArray(value))
    return (
      <details className={styles.collection}>
        <summary>
          {label}{" "}
          <span>
            {value.length} {value.length === 1 ? "entry" : "entries"}
          </span>
        </summary>
        <div className={styles.collectionBody}>
          {!value.length ? (
            <p className={styles.muted}>No entries recorded.</p>
          ) : value.every((item) => !item || typeof item !== "object") ? (
            <ul className={styles.compactList}>
              {value.map((item, i) => (
                <li key={i}>{text(item)}</li>
              ))}
            </ul>
          ) : (
            value.map((item, i) => (
              <div className={styles.collectionItem} key={i}>
                <ConfigurationValue value={item} label={`${label} ${i + 1}`} />
              </div>
            ))
          )}
        </div>
      </details>
    );
  if (value && typeof value === "object") {
    const entries = Object.entries(object(value));
    return entries.length ? (
      <dl className={styles.fieldList}>
        {entries.map(([key, item]) => (
          <div key={key}>
            <dt>{title(key)}</dt>
            <dd>
              {item && typeof item === "object" && !Array.isArray(item) ? (
                <details className={styles.collection}>
                  <summary>View {title(key).toLowerCase()}</summary>
                  <ConfigurationValue value={item} label={title(key)} />
                </details>
              ) : (
                <ConfigurationValue value={item} label={title(key)} />
              )}
            </dd>
          </div>
        ))}
      </dl>
    ) : (
      <p className={styles.muted}>No details recorded.</p>
    );
  }
  return <span className={styles.breakValue}>{text(value)}</span>;
}

export function EnvironmentContext({ env }: { env: Environment }) {
  return (
    <section className={styles.context} aria-label="Environment context">
      <div>
        <Cloud size={19} />
        <span>
          <small>Customer</small>
          <Link href={`/customers/${env.customerId}`}>{env.customerName}</Link>
        </span>
      </div>
      <div>
        <ProviderBadges codes={[env.cloudProvider]} compact />
        <span>
          <small>Cloud provider</small>
          <strong>
            {env.cloudProvider} / {env.kubernetesDistribution}
          </strong>
        </span>
      </div>
      <div>
        <Layers3 size={19} />
        <span>
          <small>Environment type</small>
          <strong>{env.environmentType}</strong>
        </span>
      </div>
      <div>
        <span>
          <small>Cloud account</small>
          <strong>{text(object(env.configuration.account).accountId)}</strong>
        </span>
      </div>
      <div>
        <MapPin size={18} />
        <span>
          <small>Region</small>
          <strong>{text(object(env.configuration.location).region)}</strong>
        </span>
      </div>
      <div>
        <FileClock size={19} />
        <span>
          <small>Saved version</small>
          <strong>{env.version}</strong>
          <small>Saved configuration</small>
        </span>
      </div>
      <div>
        <ShieldCheck size={19} />
        <span>
          <small>Approved baseline</small>
          <strong>
            {env.approvedVersion
              ? `Version ${env.approvedVersion}`
              : "Not approved"}
          </strong>
          <small>
            {env.approvedStatus === "ACTIVE"
              ? "Available for cluster requests"
              : "Not active for cluster requests"}
          </small>
        </span>
      </div>
    </section>
  );
}

type Subnet = {
  id: string;
  value: ObjectValue;
  uses: string[];
  variants: { use: string; value: ObjectValue }[];
};
function subnetRows(network: ObjectValue): Subnet[] {
  const rows = new Map<string, Subnet>();
  for (const [key, use] of [
    ["nodeSubnets", "Nodes"],
    ["clusterSubnets", "Cluster"],
  ]) {
    list(network[key]).forEach((item, i) => {
      const value =
        typeof item === "string" ? { subnetId: item } : object(item);
      const id =
        typeof value.subnetId === "string" && value.subnetId.length > 0
          ? value.subnetId
          : `${key}-${i}`;
      const existing = rows.get(id);
      if (existing) {
        if (!existing.uses.includes(use)) existing.uses.push(use);
        existing.variants.push({ use, value });
      } else
        rows.set(id, { id, value, uses: [use], variants: [{ use, value }] });
    });
  }
  return Array.from(rows.values());
}

const categories = [
  { id: "network", name: "Network", help: "VPC & subnets", icon: Network },
  { id: "iam", name: "IAM roles", help: "", icon: KeyRound },
  {
    id: "security",
    name: "Security & encryption",
    help: "",
    icon: ShieldCheck,
  },
  { id: "tags", name: "Governance tags", help: "", icon: Tags },
  { id: "discovery", name: "Discovery", help: "", icon: Code2 },
  { id: "compute", name: "Compute & quotas", help: "", icon: Layers3 },
] as const;

export function EnvironmentExplorer({
  env,
  onVersion,
  onReviews,
}: {
  env: Environment;
  onVersion: (version: number) => void;
  onReviews: () => void;
}) {
  const [category, setCategory] = useState<string>("network");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const configuration = env.configuration;
  const network = object(configuration.network);
  const discovery = object(object(configuration.extensions).discovery);
  const contract = object(
    object(configuration.extensions).provisioningContract,
  );
  const subnets = subnetRows(network);
  const selected =
    selectedId === null
      ? subnets[0]
      : subnets.find((item) => item.id === selectedId);
  const extra = Object.fromEntries(
    Object.entries(configuration).filter(
      ([key]) =>
        ![
          "account",
          "location",
          "network",
          "iam",
          "security",
          "encryption",
          "tags",
          "extensions",
          "connectivity",
        ].includes(key),
    ),
  );
  const extraExtensions = Object.fromEntries(
    Object.entries(object(configuration.extensions)).filter(
      ([key]) => !["discovery", "provisioningContract"].includes(key),
    ),
  );
  const active = categories.find((item) => item.id === category);
  const categoryData: Record<string, unknown> = {
    iam: {
      ...object(configuration.iam),
      provisioningRoles: contract.provisioningRoles,
    },
    security: {
      ...object(configuration.security),
      ...object(configuration.encryption),
    },
    tags: configuration.tags,
    discovery: {
      discovery,
      connectivity: configuration.connectivity,
      extensions: extraExtensions,
    },
    compute: contract,
    other: extra,
  };
  const workflow = Object.entries(env.workflow).sort((a, b) =>
    b[1].at.localeCompare(a[1].at),
  );
  return (
    <>
      <section
        className={styles.explorer}
        aria-label="Saved environment configuration"
      >
        <nav
          className={styles.resourceNav}
          aria-label="Configuration categories"
        >
          {categories.map(({ id, name, help, icon: Icon }) => (
            <button
              type="button"
              key={id}
              aria-pressed={category === id}
              onClick={() => setCategory(id)}
            >
              <Icon size={19} />
              <span>
                {name}
                {help && <small>{help}</small>}
              </span>
            </button>
          ))}
          {!!Object.keys(extra).length && (
            <button
              type="button"
              aria-pressed={category === "other"}
              onClick={() => setCategory("other")}
            >
              <Code2 size={19} />
              Other settings
            </button>
          )}
        </nav>
        <div className={styles.resourceContent}>
          {category === "network" ? (
            <div
              className={`${styles.networkGrid} ${!selected ? styles.noSelection : ""}`}
            >
              <section className={styles.networkMain}>
                <h2>Network configuration</h2>
                <dl className={styles.networkMeta}>
                  <div>
                    <dt>VPC</dt>
                    <dd>
                      <SavedValue
                        value={object(network.vpc).vpcId}
                        label="VPC ID"
                      />
                    </dd>
                  </div>
                  <div>
                    <dt>NAT gateway</dt>
                    <dd>
                      {list(discovery.selectedNatGatewayIds).length
                        ? list(discovery.selectedNatGatewayIds).map((id, i) => (
                            <SavedValue
                              key={i}
                              value={id}
                              label={`NAT gateway ${i + 1}`}
                            />
                          ))
                        : "Not recorded"}
                    </dd>
                  </div>
                  <div>
                    <dt>Region</dt>
                    <dd>{text(object(configuration.location).region)}</dd>
                  </div>
                </dl>
                <h3>Selected subnets ({subnets.length})</h3>
                {subnets.length ? (
                  <div
                    className={styles.tableScroll}
                    tabIndex={0}
                    role="region"
                    aria-label="Selected subnet table"
                  >
                    <table>
                      <thead>
                        <tr>
                          <th>Subnet name / ID</th>
                          <th>Availability zone</th>
                          <th>CIDR block</th>
                          <th>Used by</th>
                          <th>
                            <span className={styles.srOnly}>Details</span>
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {subnets.map((subnet) => (
                          <tr
                            key={subnet.id}
                            className={
                              selected?.id === subnet.id
                                ? styles.selectedRow
                                : ""
                            }
                          >
                            <td>
                              <strong>
                                {text(
                                  subnet.value.name || subnet.value.subnetId,
                                )}
                              </strong>
                              <small>
                                {subnet.value.name
                                  ? text(subnet.value.subnetId)
                                  : text(subnet.value.type)}
                              </small>
                            </td>
                            <td>{text(subnet.value.availabilityZone)}</td>
                            <td>{text(subnet.value.cidrBlock)}</td>
                            <td>
                              {subnet.uses.length === 2
                                ? "Nodes + cluster"
                                : subnet.uses[0]}
                            </td>
                            <td>
                              <button
                                type="button"
                                className={styles.iconButton}
                                aria-label={`View ${text(subnet.value.name || subnet.value.subnetId)} details`}
                                aria-pressed={selected?.id === subnet.id}
                                onClick={() => setSelectedId(subnet.id)}
                              >
                                <ChevronRight size={16} />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className={styles.empty}>
                    No subnets recorded in this configuration.
                  </p>
                )}
                <div className={styles.savedNote}>
                  <Info size={16} />
                  <span>
                    Subnet assignments are shown once, with their node and
                    cluster usage.
                    <small>
                      Saved discovery
                      {discovery.fetchedAt
                        ? ` · ${formatDateTime(String(discovery.fetchedAt))}`
                        : " · Date not recorded"}
                    </small>
                  </span>
                </div>
                {Object.keys(network).some(
                  (key) =>
                    !["vpc", "nodeSubnets", "clusterSubnets"].includes(key),
                ) && (
                  <ConfigurationValue
                    label="Other network settings"
                    value={Object.fromEntries(
                      Object.entries(network).filter(
                        ([key]) =>
                          !["vpc", "nodeSubnets", "clusterSubnets"].includes(
                            key,
                          ),
                      ),
                    )}
                  />
                )}
                {Object.keys(object(network.vpc)).some(
                  (key) => key !== "vpcId",
                ) && (
                  <details className={styles.collection}>
                    <summary>VPC details</summary>
                    <ConfigurationValue value={network.vpc} />
                  </details>
                )}
              </section>
              {selected && (
                <aside
                  className={styles.selectedDetail}
                  aria-label="Subnet details"
                >
                  <header>
                    <h3>Subnet details</h3>
                    <button
                      type="button"
                      className={styles.iconButton}
                      aria-label="Close subnet details"
                      onClick={() => setSelectedId("")}
                    >
                      <X size={16} />
                    </button>
                  </header>
                  <h2>
                    {text(selected.value.name || selected.value.subnetId)}
                  </h2>
                  <dl className={styles.fieldList}>
                    {Object.entries(selected.value)
                      .filter(([key]) => key !== "name")
                      .map(([key, value]) => (
                        <div key={key}>
                          <dt>{title(key)}</dt>
                          <dd>
                            {value !== null && typeof value === "object" ? (
                              <ConfigurationValue
                                value={value}
                                label={title(key)}
                              />
                            ) : (
                              <SavedValue value={value} label={title(key)} />
                            )}
                          </dd>
                        </div>
                      ))}
                  </dl>
                  {selected.variants.some(
                    (item) =>
                      JSON.stringify(item.value) !==
                      JSON.stringify(selected.value),
                  ) && (
                    <details className={styles.collection}>
                      <summary>Assignment-specific saved details</summary>
                      {selected.variants.map((variant, i) => (
                        <section key={i}>
                          <h3>{variant.use}</h3>
                          <ConfigurationValue value={variant.value} />
                        </section>
                      ))}
                    </details>
                  )}
                </aside>
              )}
            </div>
          ) : (
            <section className={styles.categoryPanel} key={category}>
              <h2>{active?.name || "Other settings"}</h2>
              <p className={styles.muted}>
                Saved environment configuration · Version {env.version}
              </p>
              {category === "iam" ? (
                <>
                  <dl className={styles.fieldList}>
                    {Object.entries(object(configuration.iam)).map(
                      ([key, value]) => (
                        <div key={key}>
                          <dt>{title(key)}</dt>
                          <dd>
                            <ConfigurationValue
                              value={value}
                              label={title(key)}
                            />
                          </dd>
                        </div>
                      ),
                    )}
                  </dl>
                  <ConfigurationValue
                    label="Provisioning roles"
                    value={contract.provisioningRoles ?? []}
                  />
                </>
              ) : (
                <ConfigurationValue
                  value={categoryData[category]}
                  label={active?.name || "Other settings"}
                />
              )}
            </section>
          )}
        </div>
      </section>
      <section className={styles.facts} aria-label="Configuration summary">
        <div>
          <h3>
            <Tags size={17} />
            Governance tags
          </h3>
          <dl className={styles.factList}>
            {Object.entries(object(configuration.tags)).map(([key, value]) => (
              <div key={key}>
                <dt>{title(key)}</dt>
                <dd>{text(value)}</dd>
              </div>
            ))}
          </dl>
          {!Object.keys(object(configuration.tags)).length && (
            <p className={styles.muted}>No tags recorded.</p>
          )}
        </div>
        <div>
          <h3>
            <KeyRound size={17} />
            IAM roles
          </h3>
          {Object.entries(object(configuration.iam)).map(([key, value]) => (
            <p className={styles.factValue} key={key}>
              <small>{title(key)}</small>
              <SavedValue
                value={object(value).roleArn ?? value}
                label={title(key)}
                compact
              />
            </p>
          ))}
        </div>
        <div>
          <h3>
            <ShieldCheck size={17} />
            Security & encryption
          </h3>
          {["nodeSecurityGroups", "clusterSecurityGroups"].map((key) => (
            <p className={styles.factValue} key={key}>
              <small>{title(key)}</small>
              {list(object(configuration.security)[key]).length
                ? list(object(configuration.security)[key]).map((value, i) => (
                    <SavedValue
                      value={object(value).securityGroupId ?? value}
                      label={`${title(key)} ${i + 1}`}
                      key={i}
                    />
                  ))
                : "Not recorded"}
            </p>
          ))}
          <button
            className={styles.textButton}
            type="button"
            onClick={() => setCategory("security")}
          >
            View encryption details <ChevronRight size={13} />
          </button>
        </div>
        <div>
          <h3>
            <Code2 size={17} />
            Discovery metadata
          </h3>
          <p className={styles.factValue}>
            <small>Discovery role</small>
            <SavedValue
              value={discovery.roleArn}
              label="Discovery role ARN"
              compact
            />
          </p>
          <p className={styles.factValue}>
            <small>Fetched at</small>
            {discovery.fetchedAt
              ? formatDateTime(String(discovery.fetchedAt))
              : "Not recorded"}
          </p>
          <button
            className={styles.textButton}
            type="button"
            onClick={() => setCategory("discovery")}
          >
            View saved metadata <ChevronRight size={13} />
          </button>
        </div>
      </section>
      <footer className={styles.baselineFooter}>
        <span>
          <strong>
            {env.approvedVersion
              ? `Approved baseline v${env.approvedVersion}`
              : "Awaiting approval"}
          </strong>
          <small>
            {env.approvedStatus === "ACTIVE"
              ? "Available for cluster requests"
              : "An active baseline is required for cluster requests"}
          </small>
        </span>
        <span>
          <small>Last updated</small>
          {formatDateTime(env.updatedAt || env.createdAt)}
          <small>Created {formatDateTime(env.createdAt)}</small>
        </span>
        <span>
          <small>Latest workflow event</small>
          {workflow[0] ? title(workflow[0][0]) : "No events recorded"}
        </span>
        <details className={styles.workflowHistory}>
          <summary>Workflow events ({workflow.length})</summary>
          <ol>
            {workflow.map(([key, value]) => (
              <li key={key}>
                <strong>{title(key)}</strong>
                <p>{formatDateTime(value.at)}</p>
                <SavedValue value={value.by} label={`${title(key)} actor ID`} />
                {value.reason && <p>{value.reason}</p>}
                {value.comments && <p>{value.comments}</p>}
              </li>
            ))}
          </ol>
          {!workflow.length && <p>No workflow events recorded.</p>}
        </details>
        <button type="button" className={styles.textButton} onClick={onReviews}>
          View review history <ArrowRight size={14} />
        </button>
        {!!env.approvedVersion && (
          <Button
            variant="primary"
            onClick={() => onVersion(env.approvedVersion!)}
          >
            View approved version <ArrowRight size={14} />
          </Button>
        )}
      </footer>
    </>
  );
}

function snapshotLeaves(value: unknown, prefix = ""): Record<string, unknown> {
  const entries = Object.entries(object(value));
  return entries.length
    ? Object.assign(
        {},
        ...entries.map(([key, item]) =>
          snapshotLeaves(item, prefix ? `${prefix}.${key}` : key),
        ),
      )
    : { [prefix || "Value"]: value };
}
function AuditChanges({ before, after }: { before: unknown; after: unknown }) {
  const oldFields = snapshotLeaves(before);
  const newFields = snapshotLeaves(after);
  const changed = Array.from(
    new Set([...Object.keys(oldFields), ...Object.keys(newFields)]),
  ).filter(
    (key) => JSON.stringify(oldFields[key]) !== JSON.stringify(newFields[key]),
  );
  const display = (value: unknown) =>
    value === undefined
      ? "Not recorded"
      : value === null
        ? "null"
        : value === ""
          ? "Empty string"
          : text(value);
  return changed.length ? (
    <div
      className={`${styles.tableScroll} ${styles.auditChanges}`}
      role="region"
      aria-label="Changed fields"
      tabIndex={0}
    >
      <table>
        <thead>
          <tr>
            <th>Field</th>
            <th>Before</th>
            <th>After</th>
          </tr>
        </thead>
        <tbody>
          {changed.map((key) => (
            <tr key={key}>
              <td>{key.split(".").map(title).join(" / ")}</td>
              <td>{display(oldFields[key])}</td>
              <td>{display(newFields[key])}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  ) : (
    <p className={styles.muted}>
      No changed fields recorded in these snapshots.
    </p>
  );
}

const recordVersion = (record: RecordItem) =>
  record.version ?? record.environmentVersion;
const recordName = (record: RecordItem, kind: HistoryKind) =>
  kind === "versions"
    ? `Version ${record.version}`
    : title(
        record.newStatus ||
          record.reviewStatus ||
          record.action ||
          "Recorded event",
      );
const recordDate = (record: RecordItem) =>
  record.changedAt ||
  record.reviewedAt ||
  record.performedAt ||
  record.createdAt;
const recordActor = (record: RecordItem) =>
  record.changedBy ||
  record.reviewerId ||
  record.performedBy ||
  record.createdBy;
const names: Record<HistoryKind, string> = {
  "status-history": "Status History",
  versions: "Versions",
  reviews: "Reviews",
  "audit-log": "Audit Log",
};

export function EnvironmentRecordPanel({
  kind,
  records,
  env,
  onVersion,
  onPage,
}: {
  kind: HistoryKind;
  records: Records;
  env: Environment;
  onVersion: (version: number) => void;
  onPage: (page: number) => void;
}) {
  const [selected, setSelected] = useState(0);
  const current = records.items[selected];
  return (
    <section className={styles.recordsPanel} aria-label={names[kind]}>
      <header className={styles.recordsHeader}>
        <div>
          <h2>{names[kind]}</h2>
          <p className={styles.muted}>
            {kind === "status-history"
              ? "Environment lifecycle changes, actors and reasons."
              : kind === "reviews"
                ? "Recorded decisions and reviewer comments for each submitted revision."
                : kind === "audit-log"
                  ? "Recorded actions with their before and after snapshots."
                  : "Saved environment revisions and their configuration snapshots."}
          </p>
        </div>
        <span>{records.pagination.totalElements} records</span>
      </header>
      {!records.items.length ? (
        <p className={styles.empty}>
          No {names[kind].toLowerCase()} records yet.
        </p>
      ) : (
        <div className={styles.recordsGrid}>
          {kind === "status-history" ? (
            <ol className={styles.timeline} aria-label="Status changes">
              {records.items.map((record, i) => (
                <li
                  key={i}
                  className={selected === i ? styles.selectedEvent : ""}
                >
                  <History size={18} />
                  <div>
                    <button
                      className={styles.eventButton}
                      type="button"
                      aria-pressed={selected === i}
                      onClick={() => setSelected(i)}
                    >
                      {record.previousStatus && (
                        <>
                          <span>{title(record.previousStatus)}</span>
                          <ArrowRight size={13} />
                        </>
                      )}
                      {recordName(record, kind)}
                    </button>
                    <p className={styles.muted}>
                      {formatDateTime(recordDate(record))}
                    </p>
                    <p>
                      {record.reason ||
                        record.comments ||
                        "No reason recorded."}
                    </p>
                    <small title={recordActor(record)}>
                      {recordActor(record) || "Actor not recorded"}
                    </small>
                  </div>
                </li>
              ))}
            </ol>
          ) : (
            <div
              className={styles.tableScroll}
              role="region"
              aria-label={`${names[kind]} records`}
              tabIndex={0}
            >
              <table>
                <thead>
                  <tr>
                    <th>
                      {kind === "versions"
                        ? "Version"
                        : kind === "reviews"
                          ? "Decision"
                          : "Action"}
                    </th>
                    <th>When</th>
                    <th>{kind === "reviews" ? "Reviewer" : "Actor"}</th>
                    {kind !== "versions" && <th>Version</th>}
                    <th>Details</th>
                  </tr>
                </thead>
                <tbody>
                  {records.items.map((record, i) => (
                    <tr
                      key={i}
                      className={selected === i ? styles.selectedRow : ""}
                    >
                      <td>
                        <strong>{recordName(record, kind)}</strong>
                        {kind === "versions" && (
                          <small>
                            {record.version === env.approvedVersion
                              ? "Approved baseline"
                              : record.version === env.version
                                ? "Current saved configuration"
                                : "Historical revision"}
                          </small>
                        )}
                      </td>
                      <td>{formatDateTime(recordDate(record))}</td>
                      <td>
                        <span
                          className={styles.actor}
                          title={recordActor(record)}
                        >
                          {recordActor(record) || "Not recorded"}
                        </span>
                      </td>
                      {kind !== "versions" && (
                        <td>{recordVersion(record) ?? "Not recorded"}</td>
                      )}
                      <td>
                        <button
                          type="button"
                          className={styles.textButton}
                          aria-label={`View ${recordName(record, kind)} record ${i + 1}`}
                          aria-pressed={selected === i}
                          onClick={() => setSelected(i)}
                        >
                          View <ChevronRight size={13} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {current && (
            <aside
              className={styles.recordDetail}
              aria-label="Selected record details"
            >
              <h3>{recordName(current, kind)}</h3>
              <dl className={styles.fieldList}>
                <div>
                  <dt>Recorded at</dt>
                  <dd>{formatDateTime(recordDate(current))}</dd>
                </div>
                <div>
                  <dt>{kind === "reviews" ? "Reviewer ID" : "Actor ID"}</dt>
                  <dd>
                    <SavedValue
                      value={recordActor(current)}
                      label="Record actor ID"
                    />
                  </dd>
                </div>
                {recordVersion(current) !== undefined && (
                  <div>
                    <dt>Environment version</dt>
                    <dd>{recordVersion(current)}</dd>
                  </div>
                )}
              </dl>
              {current.reason && (
                <section>
                  <h3>Reason</h3>
                  <p>{current.reason}</p>
                </section>
              )}
              {current.comments && (
                <section>
                  <h3>Comments</h3>
                  <p>{current.comments}</p>
                </section>
              )}
              {current.changeReason && (
                <section>
                  <h3>Change reason</h3>
                  <p>{current.changeReason}</p>
                </section>
              )}
              {kind === "audit-log" && (
                <section>
                  <h3>Change snapshots</h3>
                  <AuditChanges
                    before={current.oldValue}
                    after={current.newValue}
                  />
                  <details className={styles.collection}>
                    <summary>View raw snapshots</summary>
                    <pre className={styles.raw}>
                      {JSON.stringify(
                        { before: current.oldValue, after: current.newValue },
                        null,
                        2,
                      )}
                    </pre>
                  </details>
                </section>
              )}
              {recordVersion(current) !== undefined && (
                <Button
                  variant="secondary"
                  onClick={() => onVersion(recordVersion(current)!)}
                >
                  View version {recordVersion(current)}
                </Button>
              )}
            </aside>
          )}
        </div>
      )}
      <Pagination {...records.pagination} onChange={onPage} />
    </section>
  );
}

export function EnvironmentVersionView({ env }: { env: Environment }) {
  return (
    <div className={styles.versionView}>
      <h3>
        {env.environmentName} · Version {env.version}
      </h3>
      <dl className={styles.versionMeta}>
        {[
          ["Status", env.status],
          ["Customer", env.customerName],
          [
            "Cloud / distribution",
            `${env.cloudProvider} / ${env.kubernetesDistribution}`,
          ],
          ["Environment type", env.environmentType],
          ["Updated", formatDateTime(env.updatedAt || env.createdAt)],
          ["Description", env.description || "Not provided"],
        ].map(([key, value]) => (
          <div key={key}>
            <dt>{key}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      <h3>Saved configuration</h3>
      <ConfigurationValue value={env.configuration} />
      <details className={styles.collection}>
        <summary>View complete version record</summary>
        <pre className={styles.raw}>{JSON.stringify(env, null, 2)}</pre>
      </details>
    </div>
  );
}
