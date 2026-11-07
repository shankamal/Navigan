"use client";

import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, RefreshCw, Wrench } from "lucide-react";
import { clusters } from "@/modules/cluster-management/service";
import type { Cluster } from "@/modules/cluster-management/model";
import { Button } from "@/shared/components/ui";
import type { UpgradeCluster } from "./upgrade-workspace";
import { supportLabel } from "./support-label";
import { PlanComponents, EvidenceChecks } from "./plan-components";
import { containerIdentity, PlatformIdentity } from "./platform-identity";
import { useUpgradePlans } from "./upgrade-plan-data";
import {
  planningBlockReason,
  rescheduleBlockReason,
} from "./plan-availability";
import { scheduleOverdue, useScheduleClock } from "./schedule-state";

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
  onReview,
}: {
  clusters: Cluster[];
  selected?: Cluster;
  selectedId: string;
  onSelect: (value: string) => void;
  isFetching: boolean;
  onRefresh: () => void;
  onPlan: (cluster: UpgradeCluster) => void;
  onReview?: (planId: string | null, reschedule?: boolean) => void;
}) {
  const readiness = useQuery({
    queryKey: ["eks-upgrade-readiness", selectedId],
    queryFn: () => clusters.upgradeReadiness(selectedId),
    enabled: Boolean(selectedId),
    staleTime: 30_000,
    retry: false,
  });
  const evidence = readiness.isError ? undefined : readiness.data;
  const plans = useUpgradePlans();
  const now = useScheduleClock();
  const planState = plans.stateForCluster(selectedId);
  const activePlan = plans.rows
    .filter(
      (row) =>
        row.plan.clusterId === selectedId &&
        ["DRAFT", "SUBMITTED", "APPROVED", "SCHEDULED", "EXECUTING"].includes(
          row.plan.status,
        ),
    )
    .sort((a, b) => b.plan.updatedAt.localeCompare(a.plan.updatedAt))[0]?.plan;
  const refreshing = isFetching || readiness.isFetching;
  const blocked = planningBlockReason(plans.identity, evidence, {
    readinessPending: refreshing,
    readinessError: readiness.isError,
    planPending: planState.pending,
    planError: planState.error,
    activePlan,
  });
  const findings = [
    ...(evidence?.readiness.blockers ?? []),
    ...(evidence?.readiness.warnings ?? []),
  ];
  const identity = containerIdentity(selected?.platform ?? "EKS");
  const overdue = Boolean(activePlan && scheduleOverdue(activePlan, now));
  const canReschedule = Boolean(
    activePlan && !rescheduleBlockReason(plans.identity, activePlan),
  );
  const create = () => {
    if (!selected || !evidence?.recommendedTarget || blocked) return;
    onPlan({
      id: selected.clusterId,
      name: selected.clusterName,
      environment: selected.environmentName ?? "Environment",
      provider: "EKS",
      providerLabel: "Amazon EKS",
      currentVersion: evidence.controlPlane.version,
      targetVersion: evidence.recommendedTarget.version,
      path: [evidence.controlPlane.version, evidence.recommendedTarget.version],
      support:
        evidence.controlPlane.support?.supportStatus === "EXTENDED_SUPPORT"
          ? "EXTENDED_SUPPORT"
          : "SUPPORTED",
      readiness: evidence.readiness.status,
      findings: findings.length + " findings",
      window: "",
      evidence,
    });
  };
  return (
    <section
      className="upgrade-live-capability upgrade-container-workbench"
      aria-labelledby="containers-title"
    >
      <header className="upgrade-live-header">
        <div>
          <h2 id="containers-title">Container upgrades</h2>
          <p>
            Choose a cluster, review its version change and component readiness,
            then create a plan.
          </p>
        </div>
        <Button
          variant="secondary"
          onClick={() => {
            onRefresh();
            void readiness.refetch();
            plans.refresh();
          }}
          disabled={refreshing}
        >
          <RefreshCw size={16} className={refreshing ? "spin" : ""} />
          {refreshing ? "Refreshing" : "Refresh evidence"}
        </Button>
      </header>
      <div className="upgrade-container-scope">
        <ClusterPicker
          items={fleet}
          selectedId={selectedId}
          onSelect={onSelect}
        />
        <div className="upgrade-container-platform">
          <PlatformIdentity identity={identity} kind="cloud" />
          <PlatformIdentity identity={identity} kind="platform" />
          <span>{evidence?.region ?? "Region not reported"}</span>
        </div>
        <div className="upgrade-container-version">
          <span>
            Current{" "}
            <strong>
              {evidence?.controlPlane.version ?? declaredVersion(selected)}
            </strong>
          </span>
          <span aria-hidden="true">→</span>
          <span>
            Target{" "}
            <strong>
              {evidence?.recommendedTarget?.version ?? "Not reported"}
            </strong>
          </span>
        </div>
      </div>
      <div className="upgrade-container-review">
        <section
          className="upgrade-container-components"
          aria-labelledby="container-components-title"
        >
          <h3 id="container-components-title">Proposed component changes</h3>
          <p>
            Control plane first, compatible managed add-ons next, then rolling
            managed node-group updates.
          </p>
          {readiness.isPending ? (
            <InventoryMessage kind="loading">
              Collecting provider evidence…
            </InventoryMessage>
          ) : readiness.isError ? (
            <InventoryMessage kind="error">
              Live discovery unavailable. Refresh evidence to retry.
            </InventoryMessage>
          ) : (
            <PlanComponents
              evidence={evidence}
              target={evidence?.recommendedTarget?.version ?? "Not reported"}
            />
          )}
          {findings.length > 0 && (
            <div className="upgrade-eks-findings">
              <h3>Readiness findings</h3>
              <ul>
                {findings.map((finding, index) => (
                  <li key={finding.code + index}>
                    <AlertTriangle size={16} />
                    <span>{finding.message}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
        <aside
          className="upgrade-container-checks"
          aria-label="Container upgrade readiness"
        >
          <h3>
            {readiness.isPending
              ? "Checking readiness"
              : readiness.isError
                ? "Evidence unavailable"
                : evidence?.readiness.status === "READY"
                  ? "Ready for planning"
                  : "Readiness needs attention"}
          </h3>
          <ul className="upgrade-review-checks">
            <EvidenceChecks evidence={evidence} />
          </ul>
          {evidence && (
            <p>
              Support:{" "}
              {supportLabel(evidence.controlPlane.support?.supportStatus)} ·
              Checked {new Date(evidence.observedAt).toLocaleString()}
            </p>
          )}
        </aside>
      </div>
      <footer className="upgrade-container-actions">
        <div>
          {activePlan ? (
            <>
              <strong>
                {overdue
                  ? "Existing request is overdue"
                  : "An active upgrade plan already exists"}
              </strong>
              <p>
                Review its scope and requested time before creating another
                plan.
              </p>
            </>
          ) : (
            <>
              <strong id="container-plan-availability">
                {blocked ?? "Ready to create an upgrade plan"}
              </strong>
              <p>
                Creating a plan does not start an upgrade. You will add the
                reason and maintenance time next.
              </p>
            </>
          )}
        </div>
        {activePlan && onReview ? (
          <Button
            variant="secondary"
            onClick={() =>
              onReview(activePlan.planId, overdue && canReschedule)
            }
          >
            {overdue && canReschedule
              ? "Review & reschedule"
              : "Review existing plan"}
          </Button>
        ) : (
          <Button
            onClick={create}
            disabled={Boolean(blocked)}
            aria-describedby="container-plan-availability"
          >
            Create upgrade plan
          </Button>
        )}
      </footer>
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
  onReview,
}: {
  mode: InventoryMode;
  onPlan?: (cluster: UpgradeCluster) => void;
  onReview?: (planId: string | null, reschedule?: boolean) => void;
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
        onReview={onReview}
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
