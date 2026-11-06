"use client";

import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  CloudCog,
  RefreshCw,
  ShieldCheck,
  Wrench,
} from "lucide-react";
import { clusters } from "@/modules/cluster-management/service";
import type { Cluster } from "@/modules/cluster-management/model";
import { Button } from "@/shared/components/ui";
import type { UpgradeCluster } from "./upgrade-workspace";

type InventoryMode = "containers" | "utilities";

function objectValue(value: unknown): Record<string, unknown> {
  return value != null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function declaredVersion(cluster?: Cluster): string {
  const configuration = objectValue(cluster?.configuration);
  const outputs = objectValue(cluster?.outputs);
  const value =
    configuration.kubernetesVersion ??
    outputs.kubernetesVersion ??
    outputs.clusterVersion;
  return typeof value === "string" && value ? value : "Not reported";
}

function componentLabel(code: string): string {
  const labels: Record<string, string> = {
    argocd: "Argo CD",
    connector: "Navigan connector",
    falco: "Falco",
    grafana: "Grafana",
    headlamp: "Headlamp",
    prometheus: "Prometheus",
  };
  return (
    labels[code.toLowerCase()] ??
    code.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase())
  );
}

function InventoryMessage({
  kind,
  children,
}: {
  kind: "loading" | "error" | "empty";
  children: ReactNode;
}) {
  return (
    <div className={`upgrade-live-message ${kind}`} role="status">
      {kind === "error" ? <AlertTriangle /> : <RefreshCw />}
      <p>{children}</p>
    </div>
  );
}

function ClusterPicker({
  items,
  selectedId,
  onSelect,
}: {
  items: Cluster[];
  selectedId: string;
  onSelect: (value: string) => void;
}) {
  return (
    <label className="upgrade-live-field">
      <span>Managed cluster</span>
      <select
        aria-label="Managed cluster"
        value={selectedId}
        onChange={(event) => onSelect(event.target.value)}
      >
        {items.map((cluster) => (
          <option key={cluster.clusterId} value={cluster.clusterId}>
            {cluster.clusterName} · {cluster.environmentName ?? "Environment"}
          </option>
        ))}
      </select>
    </label>
  );
}

function ContainerInventory({
  clusters: fleet,
  selected,
  selectedId,
  onSelect,
  isFetching,
  onRefresh,
  onPlan,
}: {
  clusters: Cluster[];
  selected?: Cluster;
  selectedId: string;
  onSelect: (value: string) => void;
  isFetching: boolean;
  onRefresh: () => void;
  onPlan: (cluster: UpgradeCluster) => void;
}) {
  const readiness = useQuery({
    queryKey: ["eks-upgrade-readiness", selectedId],
    queryFn: () => clusters.upgradeReadiness(selectedId),
    enabled: Boolean(selectedId),
    staleTime: 30_000,
    retry: false,
  });
  const evidence = readiness.data;
  const version = evidence?.controlPlane.version ?? declaredVersion(selected);
  const targetVersion = evidence?.recommendedTarget?.version;
  const hasVersion = version !== "Not reported";
  const refreshing = isFetching || readiness.isFetching;
  const findings = [
    ...(evidence?.readiness.blockers ?? []),
    ...(evidence?.readiness.warnings ?? []),
  ];
  return (
    <section
      className="upgrade-live-capability"
      aria-labelledby="containers-title"
    >
      <header className="upgrade-live-header">
        <div>
          <p className="eyebrow">Live managed inventory</p>
          <h2 id="containers-title">Container distribution upgrades</h2>
          <p>
            Select a managed cluster and inspect live EKS control-plane,
            node-group, add-on and upgrade-insight evidence.
          </p>
        </div>
        <Button
          variant="secondary"
          onClick={() => {
            onRefresh();
            void readiness.refetch();
          }}
          disabled={refreshing}
        >
          <RefreshCw size={16} className={refreshing ? "spin" : ""} />
          {refreshing ? "Refreshing" : "Refresh EKS evidence"}
        </Button>
      </header>

      <div className="upgrade-live-summary">
        <div>
          <strong>{fleet.length}</strong>
          <span>Active managed clusters</span>
        </div>
        <div>
          <strong>{evidence?.controlPlane.version ?? "—"}</strong>
          <span>Live control-plane version</span>
        </div>
        <div>
          <strong>{evidence?.readiness.status ?? "Discovering"}</strong>
          <span>Upgrade readiness</span>
        </div>
      </div>

      <div className="upgrade-live-grid">
        <div className="upgrade-live-form">
          <ClusterPicker
            items={fleet}
            selectedId={selectedId}
            onSelect={onSelect}
          />
          <label className="upgrade-live-field">
            <span>Distribution</span>
            <input value="Amazon EKS" readOnly />
          </label>
          <label className="upgrade-live-field">
            <span>Current control-plane version</span>
            <input value={version} readOnly />
          </label>
          <label className="upgrade-live-field">
            <span>Recommended next target</span>
            <select aria-label="Target version" disabled={!targetVersion}>
              <option>
                {targetVersion
                  ? `Kubernetes ${targetVersion}`
                  : "No supported sequential target reported"}
              </option>
            </select>
          </label>
          {evidence && (
            <dl className="upgrade-eks-meta">
              <div>
                <dt>Region</dt>
                <dd>{evidence.region}</dd>
              </div>
              <div>
                <dt>Platform</dt>
                <dd>
                  {evidence.controlPlane.platformVersion ?? "Not reported"}
                </dd>
              </div>
              <div>
                <dt>Support</dt>
                <dd>
                  {evidence.controlPlane.support?.supportStatus ?? "Unknown"}
                </dd>
              </div>
              <div>
                <dt>Observed</dt>
                <dd>{new Date(evidence.observedAt).toLocaleString()}</dd>
              </div>
            </dl>
          )}
        </div>

        <aside
          className="upgrade-live-readiness"
          aria-label="Container upgrade readiness"
        >
          <div
            className={
              evidence?.readiness.status === "BLOCKED"
                ? "blocked"
                : evidence?.readiness.status === "WARNING"
                  ? "warning"
                  : hasVersion
                    ? "ready"
                    : "pending"
            }
          >
            {evidence?.readiness.status === "READY" ? (
              <CheckCircle2 />
            ) : (
              <AlertTriangle />
            )}
            <span>
              <strong>
                {readiness.isPending
                  ? "Collecting EKS evidence"
                  : readiness.isError
                    ? "Live discovery unavailable"
                    : evidence?.readiness.status === "READY"
                      ? "Ready for planning"
                      : evidence?.readiness.status === "WARNING"
                        ? "Planning warnings detected"
                        : evidence?.readiness.status === "BLOCKED"
                          ? "Upgrade blockers detected"
                          : "Version evidence missing"}
              </strong>
              <small>
                {readiness.isError
                  ? "Check the customer provisioning role and the registered EKS account and Region."
                  : evidence
                    ? `${evidence.readiness.blockers.length} blockers and ${evidence.readiness.warnings.length} warnings were reported.`
                    : `Reading ${selected?.clusterName ?? "the selected cluster"} without changing it.`}
              </small>
            </span>
          </div>
          <div
            className={
              evidence?.readiness.checks.nodeGroupsAligned ? "ready" : "pending"
            }
          >
            <CloudCog />
            <span>
              <strong>Managed nodes</strong>
              <small>
                {evidence
                  ? `${evidence.nodeGroups.length} node groups discovered; version alignment is ${evidence.readiness.checks.nodeGroupsAligned ? "verified" : "not ready"}.`
                  : "Waiting for live managed node-group evidence."}
              </small>
            </span>
          </div>
          <div
            className={
              evidence?.readiness.checks.upgradeInsightsPassing
                ? "ready"
                : "pending"
            }
          >
            <ShieldCheck />
            <span>
              <strong>Upgrade insights</strong>
              <small>
                {evidence
                  ? `${evidence.insights.length} EKS upgrade insights evaluated. No update API is called.`
                  : "Waiting for EKS upgrade-readiness insights."}
              </small>
            </span>
          </div>
          <Button
            disabled={
              !selected ||
              evidence?.readiness.status !== "READY" ||
              !evidence?.recommendedTarget
            }
            title={
              evidence?.readiness.status === "READY" &&
              evidence.recommendedTarget
                ? undefined
                : "READY evidence and a supported sequential target are required"
            }
            onClick={() => {
              if (!selected || !evidence?.recommendedTarget) return;
              onPlan({
                id: selected.clusterId,
                name: selected.clusterName,
                environment: selected.environmentName ?? "Environment",
                provider: "EKS",
                providerLabel: "Amazon EKS",
                currentVersion: evidence.controlPlane.version,
                targetVersion: evidence.recommendedTarget.version,
                path: [
                  evidence.controlPlane.version,
                  evidence.recommendedTarget.version,
                ],
                support:
                  evidence.controlPlane.support?.supportStatus ===
                  "EXTENDED_SUPPORT"
                    ? "EXTENDED_SUPPORT"
                    : "SUPPORTED",
                readiness: evidence.readiness.status,
                findings: `${evidence.readiness.blockers.length + evidence.readiness.warnings.length} findings`,
                window: "Not scheduled",
                evidence,
              });
            }}
          >
            Create container upgrade plan
          </Button>
        </aside>
      </div>

      {evidence && (
        <div className="upgrade-eks-evidence">
          {findings.length > 0 && (
            <section
              className="upgrade-eks-findings"
              aria-labelledby="eks-findings-title"
            >
              <h3 id="eks-findings-title">Readiness findings</h3>
              <ul>
                {findings.slice(0, 12).map((finding, index) => (
                  <li key={`${finding.code}-${index}`}>
                    <AlertTriangle />
                    <span>
                      <strong>{finding.code.replaceAll("_", " ")}</strong>
                      <small>{finding.message}</small>
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}
          <section aria-labelledby="eks-components-title">
            <h3 id="eks-components-title">EKS component evidence</h3>
            <div className="upgrade-eks-tables">
              <table>
                <caption>Managed node groups</caption>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Version</th>
                    <th>Status</th>
                    <th>Health</th>
                  </tr>
                </thead>
                <tbody>
                  {evidence.nodeGroups.length ? (
                    evidence.nodeGroups.map((node) => (
                      <tr key={node.name}>
                        <td>{node.name}</td>
                        <td>{node.version ?? "Unknown"}</td>
                        <td>{node.status}</td>
                        <td>
                          {node.healthIssues.length
                            ? `${node.healthIssues.length} issues`
                            : "Healthy"}
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={4}>No EKS managed node groups reported.</td>
                    </tr>
                  )}
                </tbody>
              </table>
              <table>
                <caption>Managed add-ons</caption>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Installed</th>
                    <th>Target compatible</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {evidence.addons.length ? (
                    evidence.addons.map((addon) => (
                      <tr key={addon.name}>
                        <td>{addon.name}</td>
                        <td>{addon.version ?? "Unknown"}</td>
                        <td>{addon.targetVersion ?? "Review required"}</td>
                        <td>{addon.status}</td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={4}>No EKS managed add-ons reported.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      )}
    </section>
  );
}

function UtilityInventory({
  fleet,
  selected,
  selectedId,
  onSelect,
}: {
  fleet: Cluster[];
  selected?: Cluster;
  selectedId: string;
  onSelect: (value: string) => void;
}) {
  const [componentCode, setComponentCode] = useState("");
  const [targetVersion, setTargetVersion] = useState("");
  const inventory = useQuery({
    queryKey: ["upgrade-utility-inventory", selectedId],
    queryFn: () => clusters.platformComponents(selectedId),
    enabled: Boolean(selectedId),
    staleTime: 30_000,
  });
  const components = inventory.data?.components ?? [];
  const selectedComponent =
    components.find((item) => item.componentCode === componentCode) ??
    components[0];
  const effectiveCode = selectedComponent?.componentCode ?? "";
  const reported = components.filter((item) => item.version).length;

  return (
    <section
      className="upgrade-live-capability"
      aria-labelledby="utilities-title"
    >
      <header className="upgrade-live-header">
        <div>
          <p className="eyebrow">Connector-reported inventory</p>
          <h2 id="utilities-title">System utility upgrades</h2>
          <p>
            Choose a cluster and installed utility, then define the intended
            version change for a governed GitOps plan.
          </p>
        </div>
        <Button
          variant="secondary"
          onClick={() => inventory.refetch()}
          disabled={inventory.isFetching || !selectedId}
        >
          <RefreshCw size={16} className={inventory.isFetching ? "spin" : ""} />
          {inventory.isFetching ? "Refreshing" : "Refresh utilities"}
        </Button>
      </header>

      <div className="upgrade-live-summary">
        <div>
          <strong>{components.length}</strong>
          <span>Expected or discovered utilities</span>
        </div>
        <div>
          <strong>{reported}</strong>
          <span>Versions reported</span>
        </div>
        <div>
          <strong>{inventory.data?.status ?? "—"}</strong>
          <span>Inventory health</span>
        </div>
      </div>

      <div className="upgrade-utility-layout">
        <div className="upgrade-live-form">
          <ClusterPicker
            items={fleet}
            selectedId={selectedId}
            onSelect={(value) => {
              onSelect(value);
              setComponentCode("");
              setTargetVersion("");
            }}
          />
          <label className="upgrade-live-field">
            <span>System utility</span>
            <select
              aria-label="System utility"
              value={effectiveCode}
              disabled={!components.length}
              onChange={(event) => {
                setComponentCode(event.target.value);
                setTargetVersion("");
              }}
            >
              {!components.length && <option>No utilities reported</option>}
              {components.map((component) => (
                <option
                  key={component.componentCode}
                  value={component.componentCode}
                >
                  {componentLabel(component.componentCode)}
                </option>
              ))}
            </select>
          </label>
          <label className="upgrade-live-field">
            <span>Installed version</span>
            <input
              value={selectedComponent?.version ?? "Not reported"}
              readOnly
            />
          </label>
          <label className="upgrade-live-field">
            <span>Requested target version</span>
            <input
              aria-label="Requested target version"
              value={targetVersion}
              onChange={(event) => setTargetVersion(event.target.value)}
              placeholder="Example: 0.46.0"
              disabled={!selectedComponent}
            />
          </label>
          <div className="upgrade-live-selection-note">
            <Wrench />
            <p>
              {selectedComponent
                ? `${componentLabel(selectedComponent.componentCode)} on ${selected?.clusterName} is selected. Compatibility, chart availability and recovery evidence must be verified before approval.`
                : "Select a cluster with a reported platform-component inventory."}
            </p>
          </div>
          <Button
            disabled
            title="Utility plan persistence and approval are not connected"
          >
            Create utility upgrade plan
          </Button>
        </div>

        <div className="upgrade-utility-table-wrap">
          {inventory.isPending ? (
            <InventoryMessage kind="loading">
              Loading installed utilities…
            </InventoryMessage>
          ) : inventory.isError ? (
            <InventoryMessage kind="error">
              Utility inventory could not be loaded for this cluster.
            </InventoryMessage>
          ) : !components.length ? (
            <InventoryMessage kind="empty">
              No platform components have been reported for this cluster.
            </InventoryMessage>
          ) : (
            <table className="upgrade-utility-table">
              <thead>
                <tr>
                  <th>Utility</th>
                  <th>Installed version</th>
                  <th>Component</th>
                  <th>GitOps sync</th>
                  <th>Observed</th>
                </tr>
              </thead>
              <tbody>
                {components.map((component) => (
                  <tr
                    key={component.componentCode}
                    className={
                      component.componentCode === effectiveCode
                        ? "selected"
                        : ""
                    }
                  >
                    <td>
                      <strong>{componentLabel(component.componentCode)}</strong>
                    </td>
                    <td>{component.version ?? "Not reported"}</td>
                    <td>
                      <span
                        className={`utility-state state-${component.status.toLowerCase()}`}
                      >
                        {component.status}
                      </span>
                    </td>
                    <td>{component.syncStatus ?? "Unknown"}</td>
                    <td>
                      {component.observedAt
                        ? new Date(component.observedAt).toLocaleString()
                        : "Not reported"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </section>
  );
}

export function LiveUpgradeInventory({
  mode,
  onPlan,
}: {
  mode: InventoryMode;
  onPlan?: (cluster: UpgradeCluster) => void;
}) {
  const [selectedId, setSelectedId] = useState("");
  const fleet = useQuery({
    queryKey: ["upgrade-managed-clusters"],
    queryFn: () => clusters.list({ page: 0, pageSize: 100, status: "ACTIVE" }),
    staleTime: 30_000,
  });
  const items = fleet.data?.items ?? [];
  const effectiveId = items.some((item) => item.clusterId === selectedId)
    ? selectedId
    : (items[0]?.clusterId ?? "");
  const detail = useQuery({
    queryKey: ["upgrade-cluster-detail", effectiveId],
    queryFn: () => clusters.get(effectiveId),
    enabled: Boolean(effectiveId),
    staleTime: 30_000,
  });
  const selected =
    detail.data ?? items.find((item) => item.clusterId === effectiveId);

  if (fleet.isPending)
    return (
      <InventoryMessage kind="loading">
        Loading managed cluster inventory…
      </InventoryMessage>
    );
  if (fleet.isError)
    return (
      <InventoryMessage kind="error">
        Managed clusters could not be loaded.
      </InventoryMessage>
    );
  if (!items.length)
    return (
      <InventoryMessage kind="empty">
        No active managed clusters are available for upgrade planning.
      </InventoryMessage>
    );

  if (mode === "containers") {
    return (
      <ContainerInventory
        clusters={items}
        selected={selected}
        selectedId={effectiveId}
        onSelect={setSelectedId}
        isFetching={fleet.isFetching || detail.isFetching}
        onRefresh={() => {
          void fleet.refetch();
          if (effectiveId) void detail.refetch();
        }}
        onPlan={onPlan ?? (() => undefined)}
      />
    );
  }
  return (
    <UtilityInventory
      fleet={items}
      selected={selected}
      selectedId={effectiveId}
      onSelect={setSelectedId}
    />
  );
}
