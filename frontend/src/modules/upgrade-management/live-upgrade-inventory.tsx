"use client";

import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, RefreshCw, Wrench } from "lucide-react";
import { clusters } from "@/modules/cluster-management/service";
import type { Cluster } from "@/modules/cluster-management/model";
import { useAuth } from "@/shared/auth/auth-provider";
import { hasPermission } from "@/shared/auth/permissions";
import { ClusterContext } from "./cluster-context";
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
import {
  calendarSchedule,
  scheduleOverdue,
  useScheduleClock,
} from "./schedule-state";

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
        row.plan.kind !== "UTILITY" &&
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
      <ClusterContext cluster={selected} />
      {activePlan && (
        <div className="upgrade-existing-plan" role="status">
          <strong>
            Existing container upgrade:{" "}
            {activePlan.status === "SUBMITTED"
              ? "Awaiting approval"
              : activePlan.status}
          </strong>
          <span>
            Requested start:{" "}
            {activePlan.scheduledFor
              ? new Date(activePlan.scheduledFor).toLocaleString()
              : "Not scheduled"}{" "}
            · {Intl.DateTimeFormat().resolvedOptions().timeZone}
          </span>
        </div>
      )}
      <div className="upgrade-container-scope">
        <ClusterPicker
          items={fleet}
          selectedId={selectedId}
          onSelect={onSelect}
        />
        <div className="upgrade-container-platform">
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
  requestedDate,
  onReview,
  fleet,
  selected,
  selectedId,
  onSelect,
}: {
  onReview?: (planId: string | null, reschedule?: boolean) => void;
  requestedDate?: string;
  fleet: Cluster[];
  selected?: Cluster;
  selectedId: string;
  onSelect: (value: string) => void;
}) {
  const { identity } = useAuth();
  const planInventory = useUpgradePlans();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [scheduledFor, setScheduledFor] = useState(() =>
    calendarSchedule(requestedDate),
  );
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
  const ready = components.filter(
    (item) => item.status === "READY" && item.syncStatus === "Synced",
  ).length;
  const options = useQuery({
    queryKey: [
      "utility-upgrade-options",
      identity?.subject,
      selectedId,
      effectiveCode,
    ],
    queryFn: () =>
      clusters.utilityUpgradeOptions(selectedId, effectiveCode.toLowerCase()),
    enabled: Boolean(selectedId && effectiveCode),
    retry: false,
    staleTime: 60_000,
  });
  const activeUtility = planInventory.rows.find(
    (row) =>
      row.plan.kind === "UTILITY" &&
      row.plan.clusterId === selectedId &&
      row.plan.managedGroup === options.data?.chart &&
      ["DRAFT", "SUBMITTED", "APPROVED", "SCHEDULED", "EXECUTING"].includes(
        row.plan.status,
      ),
  )?.plan;
  const planState = planInventory.stateForCluster(selectedId);
  const target = options.data?.versions.includes(targetVersion)
    ? targetVersion
    : (options.data?.versions[0] ?? "");
  const create = useMutation({
    mutationFn: () =>
      clusters.createUtilityUpgradePlan(selectedId, {
        utilityCode: effectiveCode.toLowerCase(),
        targetVersion: target,
        changeReason: reason.trim(),
        ...(scheduledFor
          ? { scheduledFor: new Date(scheduledFor).toISOString() }
          : {}),
      }),
    onSuccess: (plan) => {
      queryClient.setQueryData<
        Awaited<ReturnType<typeof clusters.upgradePlans>>
      >(
        [
          "eks-upgrade-plans",
          identity?.subject,
          identity?.authorizationRevision,
          selectedId,
        ],
        (previous) => ({
          clusterId: selectedId,
          customerId: plan.customerId,
          items: [
            ...(previous?.items ?? []).filter(
              (item) => item.planId !== plan.planId,
            ),
            plan,
          ],
        }),
      );
      void queryClient.invalidateQueries({ queryKey: ["eks-upgrade-plans"] });
      onReview?.(plan.planId);
    },
  });
  const blocked = !hasPermission(identity, "cluster.upgrade.plan")
    ? "Your account does not have upgrade planning permission."
    : activeUtility
      ? "An active request already exists for this chart. Review it before creating another."
      : planState.pending
        ? "Checking existing utility plans…"
        : planState.error
          ? "Existing plans could not be checked. Refresh plans before creating another."
          : options.isPending
            ? "Loading official chart releases…"
            : (options.error?.message ??
              options.data?.blockReason ??
              (!target
                ? "No supported release available."
                : !reason.trim() || reason.trim().length < 8
                  ? "Provide a change reason of at least 8 characters."
                  : scheduledFor &&
                      (!Number.isFinite(new Date(scheduledFor).getTime()) ||
                        new Date(scheduledFor).getTime() <= Date.now())
                    ? "Choose a future maintenance start."
                    : undefined));

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
          onClick={() => {
            void inventory.refetch();
            void options.refetch();
          }}
          disabled={inventory.isFetching || !selectedId}
        >
          <RefreshCw size={16} className={inventory.isFetching ? "spin" : ""} />
          {inventory.isFetching ? "Refreshing" : "Refresh utilities"}
        </Button>
      </header>

      <div className="upgrade-live-summary">
        <div>
          <strong>{components.length}</strong>
          <span>Utilities tracked in this cluster</span>
          <small>Includes required components not yet reporting</small>
        </div>
        <div>
          <strong>{reported}</strong>
          <span>
            Chart versions reported · {reported} of {components.length}
          </span>
          <small>{components.length - reported} need version evidence</small>
        </div>
        <div>
          <strong>
            {ready} / {components.length}
          </strong>
          <span>Healthy and GitOps synced</span>
          <small>
            {components.length - ready} need attention; see component state
            below
          </small>
        </div>
      </div>

      <ClusterContext cluster={selected} />
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
            <span>Installed chart version</span>
            <input
              value={selectedComponent?.version ?? "Not reported"}
              readOnly
            />
          </label>
          <label className="upgrade-live-field">
            <span>Requested target version</span>
            <select
              aria-label="Requested target version"
              value={target}
              onChange={(event) => setTargetVersion(event.target.value)}
              disabled={options.isPending || !options.data?.versions.length}
            >
              {!options.data?.versions.length && (
                <option value="">
                  {options.isPending
                    ? "Loading releases…"
                    : "No verified target available"}
                </option>
              )}
              {options.data?.versions.map((version) => (
                <option key={version} value={version}>
                  {version} · chart release
                </option>
              ))}
            </select>
            <small>
              {options.data?.label}. Targets come from the official chart
              release catalogue. Chart and application versions can differ.
            </small>
          </label>
          <div className="upgrade-live-selection-note">
            <Wrench />
            <p>
              {selectedComponent
                ? `${componentLabel(selectedComponent.componentCode)} on ${selected?.clusterName} is selected. Compatibility, chart availability and recovery evidence must be verified before execution.`
                : "Select a cluster with a reported platform-component inventory."}
            </p>
          </div>
          <label className="upgrade-live-field">
            <span>Requested maintenance start (optional)</span>
            <input
              aria-label="Utility maintenance start"
              type="datetime-local"
              value={scheduledFor}
              onChange={(event) => setScheduledFor(event.target.value)}
            />
          </label>
          <label className="upgrade-live-field">
            <span>Change reason</span>
            <textarea
              aria-label="Utility change reason"
              maxLength={2000}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          </label>
          {activeUtility && (
            <div className="upgrade-existing-plan">
              <strong>
                {activeUtility.utilityEvidence?.label} · {activeUtility.status}
              </strong>
              <span>
                {activeUtility.scheduledFor
                  ? new Date(activeUtility.scheduledFor).toLocaleString()
                  : "Not scheduled"}
              </span>
              <Button
                variant="secondary"
                onClick={() => onReview?.(activeUtility.planId)}
              >
                Review utility plan
              </Button>
            </div>
          )}
          {blocked && <p role="status">{blocked}</p>}
          {create.error && <p role="alert">{create.error.message}</p>}
          <Button
            disabled={Boolean(blocked) || create.isPending}
            onClick={() => create.mutate()}
          >
            Create utility upgrade plan
          </Button>
          <small>
            Saves a governed draft. Approval does not deploy; GitOps execution
            is not enabled yet.
          </small>
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
                  <th>Reported version</th>
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
  requestedDate,
  onPlan,
  onReview,
}: {
  requestedDate?: string;
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
      requestedDate={requestedDate}
      onReview={onReview}
      fleet={items}
      selected={selected}
      selectedId={effectiveId}
      onSelect={setSelectedId}
    />
  );
}
