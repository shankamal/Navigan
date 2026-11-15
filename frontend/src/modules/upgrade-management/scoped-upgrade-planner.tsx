"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  CalendarClock,
  CheckCircle2,
  Cpu,
  GitBranch,
  Layers3,
  Puzzle,
  Server,
  ShieldCheck,
} from "lucide-react";
import { clusters } from "@/modules/cluster-management/service";
import type {
  EksUpgradePlan,
  UpgradeSpec,
} from "@/modules/cluster-management/model";
import { Button } from "@/shared/components/ui";
import { useAuth } from "@/shared/auth/auth-provider";
import { hasPermission } from "@/shared/auth/permissions";
import { PlatformIdentity, containerIdentity } from "./platform-identity";
import { calendarSchedule } from "./schedule-state";
import type { UpgradeCluster } from "./upgrade-workspace";

const labels = {
  CONTROL_PLANE: "Control plane",
  NODEGROUP: "Managed node group",
  ADDON: "Managed add-on",
};
const stageLabels = {
  PREREQUISITE_COMPONENTS: "Prerequisite components",
  CONTROL_PLANE: "Control plane",
  COMPATIBILITY_COMPONENTS: "Compatibility components",
  DATA_PLANE: "Data plane",
};
function operationStage(
  operation: UpgradeSpec["steps"][number]["operations"][number],
) {
  if (operation.stage) return stageLabels[operation.stage];
  if (operation.kind === "CONTROL_PLANE") return stageLabels.CONTROL_PLANE;
  if (operation.kind === "NODEGROUP") return stageLabels.DATA_PLANE;
  return operation.prerequisite
    ? stageLabels.PREREQUISITE_COMPONENTS
    : stageLabels.COMPATIBILITY_COMPONENTS;
}
export function UpgradePathDetails({
  spec,
  execution = {},
}: {
  spec: UpgradeSpec;
  execution?: Record<string, unknown>;
}) {
  const results = Array.isArray(execution.results)
    ? (execution.results as Record<string, unknown>[])
    : [];
  const postValidation = execution.postValidation;
  const postValidationStatus =
    typeof postValidation === "object" &&
    postValidation !== null &&
    "status" in postValidation
      ? String(postValidation.status)
      : null;
  return (
    <section
      className="upgrade-path-details"
      aria-label="Reviewed upgrade path"
    >
      <h3>
        {spec.scope === "CLUSTER"
          ? "Full platform upgrade path"
          : spec.scope === "CONTROL_PLANE"
            ? "Control plane upgrade path"
            : spec.scope === "NODES"
              ? "Selected node group upgrades"
              : "Selected managed add-on upgrades"}
      </h3>
      {spec.steps.map((step, index) => (
        <section key={index} className="upgrade-path-step">
          <h4>
            Step {index + 1}
            {spec.scope === "CLUSTER"
              ? ` · ${step.fromVersion} → ${step.targetVersion}`
              : ""}
          </h4>
          <p>
            {step.window
              ? `${new Date(step.window.scheduledFor).toLocaleString()} – ${new Date(new Date(step.window.scheduledFor).getTime() + step.window.durationMinutes * 60000).toLocaleString()}`
              : "Maintenance window required before submission"}
          </p>
          <div className="upgrade-table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Component</th>
                  <th>Version change</th>
                  <th>Stage</th>
                  <th>Execution</th>
                </tr>
              </thead>
              <tbody>
                {step.operations.map((op, i) => (
                  <tr key={i}>
                    <td>
                      <strong>{labels[op.kind]}</strong>
                      <small>
                        {op.name}
                        {op.prerequisite
                          ? " · required before control-plane update"
                          : ""}
                      </small>
                    </td>
                    <td>
                      {op.from} → {op.to}
                    </td>
                    <td>{operationStage(op)}</td>
                    <td>
                      {results.some(
                        (r) =>
                          r.hopIndex === index &&
                          r.kind === op.kind &&
                          r.name === op.name &&
                          r.to === op.to,
                      )
                        ? "Completed"
                        : execution.hopIndex === index &&
                            execution.operationIndex === i &&
                            !String(execution.phase ?? "").startsWith(
                              "AWAITING_",
                            )
                          ? String(execution.providerStatus ?? "Pending")
                          : "Pending"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}
      <p>
        {spec.validation} Each version step must be started by a Cloud Engineer
        inside its approved window. Check application health before starting the
        next step.
      </p>
      {postValidationStatus && (
        <p role="status">
          Provider post-validation: {postValidationStatus}
          {" · "}
          Application validation remains operator-confirmed until workload
          health evidence is integrated.
        </p>
      )}
    </section>
  );
}
export function ScopedUpgradePlanner({
  cluster,
  initialDate,
  onClose,
}: {
  cluster: UpgradeCluster;
  initialDate?: string;
  onClose: () => void;
}) {
  const cache = useQueryClient();
  const { identity } = useAuth();
  const options = useQuery({
    queryKey: [
      "eks-upgrade-options",
      cluster.id,
      identity?.subject,
      identity?.authorizationRevision,
    ],
    queryFn: () => clusters.upgradeOptions(cluster.id),
    retry: false,
  });
  const [scope, setScope] = useState<
    "CLUSTER" | "CONTROL_PLANE" | "NODES" | "ADDONS"
  >("CLUSTER");
  const [target, setTarget] = useState("");
  const [nodes, setNodes] = useState<string[]>([]);
  const [addons, setAddons] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const [windows, setWindows] = useState<{ start: string; duration: number }[]>(
    [{ start: calendarSchedule(initialDate), duration: 120 }],
  );
  const [created, setCreated] = useState<EksUpgradePlan>();

  const data = options.data;
  const finalTarget = target || data?.targetVersions[0] || "";
  const count =
    ["CLUSTER", "CONTROL_PLANE"].includes(scope) && data && finalTarget
      ? Number(finalTarget.split(".")[1]) -
        Number(data.currentVersion.split(".")[1])
      : 1;
  const dates = Array.from(
    { length: Math.max(1, count) },
    (_, index) => windows[index] || { start: "", duration: 120 },
  );
  const supplied = dates.filter((window) => window.start).length;
  const validDates = dates.every(
    (window, index) =>
      !window.start ||
      (Number.isFinite(new Date(window.start).getTime()) &&
        new Date(window.start).getTime() > Date.now() &&
        (index === 0 ||
          !dates[index - 1].start ||
          new Date(window.start).getTime() >=
            new Date(dates[index - 1].start).getTime() +
              dates[index - 1].duration * 60000)),
  );

  const missing = !hasPermission(identity, "cluster.upgrade.plan")
    ? "Your account needs upgrade planning permission."
    : !data
      ? "Load live component options before saving."
      : reason.trim().length < 8
        ? "Enter a change reason of at least 8 characters."
        : ["CLUSTER", "CONTROL_PLANE"].includes(scope) && !finalTarget
          ? "No supported cluster upgrade path is available. You can still select a component-only scope."
          : scope === "NODES" && !nodes.length
            ? "Select a node group that needs a Kubernetes version update."
            : scope === "ADDONS" && !Object.keys(addons).length
              ? "Select an add-on target version."
              : dates.some(
                    (window) =>
                      !Number.isInteger(window.duration) ||
                      window.duration < 30 ||
                      window.duration > 1440,
                  ) ||
                  !validDates ||
                  (supplied > 0 && supplied !== dates.length)
                ? "Choose future, ordered, non-overlapping windows for every step, or leave all windows empty for a draft."
                : "";

  const mutation = useMutation({
    mutationFn: async () => {
      const plan = await clusters.createScopedUpgradePlan(cluster.id, {
        upgradeScope: scope,
        ...(["CLUSTER", "CONTROL_PLANE"].includes(scope)
          ? { targetVersion: finalTarget }
          : scope === "NODES"
            ? { nodeGroups: nodes }
            : { addons }),
        hopWindows: supplied
          ? dates.map((window) => ({
              scheduledFor: new Date(window.start).toISOString(),
              durationMinutes: window.duration,
            }))
          : [],
        changeReason: reason.trim(),
      });
      setCreated(plan);
      return plan;
    },
    onSettled: () => {
      void cache.invalidateQueries({ queryKey: ["eks-upgrade-plans"] });
    },
  });

  const submit = useMutation({
    mutationFn: async () => {
      const plan = await clusters.changeUpgradePlan(
        cluster.id,
        created!.planId,
        "submit",
        created!.version,
      );
      setCreated(plan);
      return plan;
    },
    onSettled: () => {
      void cache.invalidateQueries({ queryKey: ["eks-upgrade-plans"] });
    },
  });

  const locked = Boolean(created) || mutation.isPending;
  const isFullUpgrade = scope === "CLUSTER";
  const scopeLabel =
    scope === "CLUSTER"
      ? "Full Upgrade"
      : scope === "CONTROL_PLANE"
        ? "Control Plane"
        : scope === "NODES"
          ? "Node Groups"
          : "Managed Add-ons";
  const windowSummary =
    supplied === 0
      ? "Draft / unscheduled"
      : supplied === dates.length
        ? supplied === 1
          ? new Date(dates[0].start).toLocaleString()
          : supplied + " maintenance windows"
        : supplied + " of " + dates.length + " selected";

  const resetWindows = () =>
    setWindows([
      {
        start: calendarSchedule(initialDate),
        duration: 120,
      },
    ]);

  const selectPlanType = (type: "FULL" | "SCOPED") => {
    setScope(type === "FULL" ? "CLUSTER" : "CONTROL_PLANE");
    setNodes([]);
    setAddons({});
    resetWindows();
  };

  const nodeVersionSummary =
    data?.nodeGroups
      .map((node) => node.version)
      .filter((value): value is string => Boolean(value))
      .filter((value, index, values) => values.indexOf(value) === index)
      .join(", ") || "Not reported";

  const readinessChecks = [
    {
      label: "Live upgrade options loaded",
      complete: Boolean(data),
    },
    {
      label: "Provider-supported upgrade path enforced",
      complete:
        scope === "NODES" ||
        scope === "ADDONS" ||
        Boolean(finalTarget && data?.targetVersions.includes(finalTarget)),
    },
    {
      label: "Cluster readiness evidence is available",
      complete: Boolean(cluster.evidence),
    },
    {
      label: missing || "Required planning inputs are complete",
      complete: !missing,
    },
  ];

  return (
    <section className="upgrade-scoped-planner upgrade-plan-console">
      <header className="upgrade-plan-console-header">
        <button
          type="button"
          className="upgrade-back-link upgrade-plan-back"
          onClick={onClose}
        >
          <ArrowLeft size={16} aria-hidden="true" />
          <span>Back to Upgrade Centre</span>
        </button>
        <div className="upgrade-plan-console-title">
          <div>
            <h2>Create Upgrade Plan</h2>
            <p>
              Configure a governed Kubernetes upgrade with scope, versions,
              maintenance windows and approval controls.
            </p>
          </div>
        </div>
      </header>

      <section className="upgrade-plan-context" aria-label="Selected cluster">
        <div className="upgrade-plan-context-primary">
          <Server size={20} aria-hidden="true" />
          <div>
            <span>Cluster</span>
            <strong>{cluster.name}</strong>
          </div>
        </div>
        <div>
          <span>Customer</span>
          <strong>{cluster.customerName ?? cluster.customerId ?? "Customer"}</strong>
        </div>
        <div>
          <span>Environment</span>
          <strong>{cluster.environment}</strong>
        </div>
        <div>
          <span>Platform</span>
          <PlatformIdentity
            identity={containerIdentity(cluster.providerLabel || cluster.provider)}
            kind="platform"
          />
        </div>
        <div className="upgrade-plan-context-version">
          <span>Current</span>
          <strong>{data?.currentVersion ?? cluster.currentVersion}</strong>
          <b aria-hidden="true">→</b>
          <span>Target</span>
          <strong>{finalTarget || cluster.targetVersion}</strong>
        </div>
      </section>

      {options.isPending && (
        <div className="upgrade-planner-loading" role="status">
          <span className="upgrade-plan-loading-spinner" aria-hidden="true" />
          Loading live component versions and compatibility…
        </div>
      )}

      {options.isError && (
        <>
          <div role="alert" className="upgrade-planner-alert">
            <span>{options.error.message}</span>
            <Button variant="secondary" onClick={() => void options.refetch()}>
              Retry discovery
            </Button>
          </div>
          <footer className="upgrade-plan-console-actions">
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <span>Load live component options before saving.</span>
            <Button disabled>Save draft &amp; review</Button>
          </footer>
        </>
      )}

      {created ? (
        <section className="upgrade-planner-created">
          <div className="upgrade-planner-created-status" role="status">
            <CheckCircle2 size={18} aria-hidden="true" />
            <span>
              {created.status === "SUBMITTED"
                ? "Submitted for Platform Architect approval."
                : "Draft saved. Review the exact operations below before submitting."}
            </span>
          </div>
          {created.planSpec && <UpgradePathDetails spec={created.planSpec} />}
          {(mutation.isError || submit.isError) && (
            <div role="alert" className="upgrade-planner-alert">
              {mutation.error?.message || submit.error?.message}
            </div>
          )}
          <footer className="upgrade-plan-console-actions">
            <Button variant="secondary" onClick={onClose}>
              Close
            </Button>
            {created.status === "DRAFT" && (
              <Button
                disabled={
                  submit.isPending ||
                  created.planSpec?.steps.some((step) => !step.window)
                }
                onClick={() => submit.mutate()}
              >
                Submit for approval
              </Button>
            )}
          </footer>
        </section>
      ) : (
        data && (
          <fieldset disabled={locked} className="upgrade-plan-console-fieldset">
            <legend className="sr-only">Create upgrade plan inputs</legend>

            <div className="upgrade-plan-console-layout">
              <div className="upgrade-plan-console-main">
                <section className="upgrade-plan-section">
                  <header>
                    <div>
                      <h3>Plan Type <span aria-hidden="true">*</span></h3>
                      <p>Select the breadth of this upgrade plan.</p>
                    </div>
                  </header>
                  <div className="upgrade-plan-type-options">
                    <label>
                      <input
                        type="radio"
                        name="planType"
                        aria-label="Full Upgrade"
                        checked={isFullUpgrade}
                        onChange={() => selectPlanType("FULL")}
                      />
                      <Layers3 size={22} aria-hidden="true" />
                      <span>
                        <strong>Full Upgrade</strong>
                        <small>
                          Control plane, managed node groups, compatible managed
                          add-ons and required validations.
                        </small>
                      </span>
                    </label>
                    <label>
                      <input
                        type="radio"
                        name="planType"
                        aria-label="Targeted Upgrade"
                        checked={!isFullUpgrade}
                        onChange={() => selectPlanType("SCOPED")}
                      />
                      <Server size={22} aria-hidden="true" />
                      <span>
                        <strong>Targeted Upgrade</strong>
                        <small>
                          Upgrade a selected control plane, node group or
                          managed add-on scope with governed safety gates.
                        </small>
                      </span>
                    </label>
                  </div>
                </section>

                <section className="upgrade-plan-section">
                  <header>
                    <div>
                      <h3>Upgrade Scope <span aria-hidden="true">*</span></h3>
                      <p>
                        {isFullUpgrade
                          ? "The governed full-upgrade path includes all required platform stages."
                          : "Choose the specific cluster component scope to upgrade."}
                      </p>
                    </div>
                  </header>

                  {isFullUpgrade ? (
                    <div className="upgrade-plan-included-scope">
                      {(
                        [
                          { label: "Control Plane", Icon: Cpu },
                          { label: "Node Groups", Icon: Server },
                          { label: "Managed Add-ons", Icon: Puzzle },
                          { label: "Validation", Icon: ShieldCheck },
                          { label: "IaC Reconciliation", Icon: GitBranch },
                        ] as const
                      ).map(({ label, Icon }) => (
                        <div key={label}>
                          <CheckCircle2 size={16} aria-hidden="true" />
                          <Icon size={16} aria-hidden="true" />
                          <span>{label}</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="upgrade-plan-scope-options">
                      {(
                        [
                          {
                            id: "CONTROL_PLANE",
                            label: "Control Plane",
                            description: "Managed Kubernetes control plane only.",
                            Icon: Cpu,
                          },
                          {
                            id: "NODES",
                            label: "Node Groups",
                            description: "Selected managed node groups.",
                            Icon: Server,
                          },
                          {
                            id: "ADDONS",
                            label: "Managed Add-ons",
                            description: "Selected provider-managed add-ons.",
                            Icon: Puzzle,
                          },
                        ] as const
                      ).map((item) => (
                        <label key={item.id}>
                          <input
                            type="radio"
                            name="upgradeScope"
                            aria-label={
                              item.id === "CONTROL_PLANE"
                                ? "Control plane only"
                                : item.label
                            }
                            checked={scope === item.id}
                            onChange={() => {
                              setScope(item.id);
                              setNodes([]);
                              setAddons({});
                              resetWindows();
                            }}
                          />
                          <item.Icon size={18} aria-hidden="true" />
                          <span>
                            <strong>{item.label}</strong>
                            <small>{item.description}</small>
                          </span>
                        </label>
                      ))}
                    </div>
                  )}
                </section>

                <section className="upgrade-plan-section">
                  <header>
                    <div>
                      <h3>Version &amp; Component Details</h3>
                      <p>
                        Review the exact live component versions used to build
                        this governed plan.
                      </p>
                    </div>
                  </header>

                  {["CLUSTER", "CONTROL_PLANE"].includes(scope) && (
                    <div className="upgrade-plan-target-row">
                      <label className="upgrade-live-field">
                        <span>Final Kubernetes target</span>
                        <select
                          aria-label="Final Kubernetes target"
                          value={finalTarget}
                          onChange={(event) => {
                            setTarget(event.target.value);
                            resetWindows();
                          }}
                        >
                          {!data.targetVersions.length && (
                            <option value="">No supported target</option>
                          )}
                          {data.targetVersions.map((version) => (
                            <option key={version} value={version}>
                              {version}
                              {version === data.targetVersions[0]
                                ? " · Recommended"
                                : ""}
                            </option>
                          ))}
                        </select>
                      </label>
                      <div>
                        <span>Upgrade path</span>
                        <strong>
                          {[
                            data.currentVersion,
                            ...Array.from(
                              { length: Math.max(0, count) },
                              (_, index) =>
                                "1." +
                                (Number(data.currentVersion.split(".")[1]) +
                                  index +
                                  1),
                            ),
                          ].join(" → ")}
                        </strong>
                      </div>
                    </div>
                  )}

                  <div className="upgrade-plan-component-table-wrap">
                    <table className="upgrade-plan-component-table">
                      <thead>
                        <tr>
                          <th>Component</th>
                          <th>Current Version</th>
                          <th>Target Version</th>
                          <th>Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {["CLUSTER", "CONTROL_PLANE"].includes(scope) && (
                          <tr>
                            <td>
                              <span className="upgrade-plan-component-name">
                                <Cpu size={16} aria-hidden="true" />
                                Kubernetes Control Plane
                              </span>
                            </td>
                            <td>{data.currentVersion}</td>
                            <td>{finalTarget || "Not available"}</td>
                            <td>
                              <span className="upgrade-plan-action-label">
                                Upgrade
                              </span>
                            </td>
                          </tr>
                        )}

                        {scope === "CLUSTER" && (
                          <tr>
                            <td>
                              <span className="upgrade-plan-component-name">
                                <Server size={16} aria-hidden="true" />
                                Managed Node Groups ({data.nodeGroups.length})
                              </span>
                            </td>
                            <td>{nodeVersionSummary}</td>
                            <td>{finalTarget || "Not available"}</td>
                            <td>
                              <span className="upgrade-plan-action-label">
                                Upgrade
                              </span>
                            </td>
                          </tr>
                        )}

                        {scope === "NODES" &&
                          data.nodeGroups.map((node) => {
                            const selectable =
                              node.version !== data.currentVersion &&
                              node.amiType !== "CUSTOM";
                            return (
                              <tr key={node.name}>
                                <td>
                                  <label className="upgrade-plan-component-check">
                                    <input
                                      type="checkbox"
                                      aria-label={
                                        node.name +
                                        " · " +
                                        (node.version ?? "Unknown")
                                      }
                                      checked={nodes.includes(node.name)}
                                      disabled={!selectable}
                                      onChange={(event) =>
                                        setNodes(
                                          event.target.checked
                                            ? [...nodes, node.name]
                                            : nodes.filter(
                                                (value) => value !== node.name,
                                              ),
                                        )
                                      }
                                    />
                                    <Server size={16} aria-hidden="true" />
                                    <span>{node.name}</span>
                                  </label>
                                </td>
                                <td>{node.version ?? "Unknown"}</td>
                                <td>{data.currentVersion}</td>
                                <td>
                                  {selectable ? "Upgrade" : "Keep"}
                                </td>
                              </tr>
                            );
                          })}

                        {(scope === "CLUSTER" || scope === "ADDONS") &&
                          data.addons.map((addon) => {
                            const recommended =
                              addon.versions.find(
                                (version) =>
                                  version.recommended &&
                                  version.version !== addon.version,
                              )?.version ?? addon.version;
                            const selected =
                              scope === "ADDONS"
                                ? addons[addon.name] || ""
                                : recommended;
                            return (
                              <tr key={addon.name}>
                                <td>
                                  <span className="upgrade-plan-component-name">
                                    <Puzzle size={16} aria-hidden="true" />
                                    {addon.name}
                                  </span>
                                </td>
                                <td>{addon.version}</td>
                                <td>
                                  {scope === "ADDONS" ? (
                                    <select
                                      aria-label={addon.name}
                                      value={selected}
                                      onChange={(event) =>
                                        setAddons((previous) => {
                                          const next = { ...previous };
                                          if (event.target.value)
                                            next[addon.name] =
                                              event.target.value;
                                          else delete next[addon.name];
                                          return next;
                                        })
                                      }
                                    >
                                      <option value="">
                                        Keep installed version
                                      </option>
                                      {addon.versions
                                        .filter(
                                          (version) =>
                                            version.version !== addon.version,
                                        )
                                        .map((version) => (
                                          <option
                                            key={version.version}
                                            value={version.version}
                                          >
                                            {version.version}
                                            {version.recommended
                                              ? " · Recommended"
                                              : ""}
                                          </option>
                                        ))}
                                    </select>
                                  ) : (
                                    recommended
                                  )}
                                </td>
                                <td>
                                  {selected && selected !== addon.version
                                    ? "Upgrade"
                                    : "Keep"}
                                </td>
                              </tr>
                            );
                          })}
                      </tbody>
                    </table>
                  </div>

                  {scope === "NODES" && (
                    <p className="upgrade-plan-inline-guidance">
                      {data.nodeUpgradeNote} Same-version AMI patching remains
                      in the separate Patching capability.
                    </p>
                  )}
                </section>

                <section className="upgrade-plan-section">
                  <header>
                    <div>
                      <h3>Maintenance &amp; Approval</h3>
                      <p>
                        Define the requested window and change reason. Platform
                        Architect approval remains mandatory before execution.
                      </p>
                    </div>
                  </header>

                  <div className="upgrade-plan-maintenance-grid">
                    <div className="upgrade-plan-window-list">
                      {dates.map((window, index) => (
                        <div className="upgrade-plan-window-row" key={index}>
                          <label className="upgrade-live-field">
                            <span>
                              {dates.length > 1
                                ? "Step " + (index + 1) + " start"
                                : "Maintenance start"}
                            </span>
                            <input
                              type="datetime-local"
                              aria-label={
                                "Step " + (index + 1) + " maintenance start"
                              }
                              value={window.start}
                              onChange={(event) =>
                                setWindows(
                                  dates.map((date, dateIndex) =>
                                    dateIndex === index
                                      ? { ...date, start: event.target.value }
                                      : date,
                                  ),
                                )
                              }
                            />
                          </label>
                          <label className="upgrade-live-field">
                            <span>Duration (minutes)</span>
                            <input
                              type="number"
                              min={30}
                              max={1440}
                              step={30}
                              value={window.duration}
                              onChange={(event) =>
                                setWindows(
                                  dates.map((date, dateIndex) =>
                                    dateIndex === index
                                      ? {
                                          ...date,
                                          duration: Number(event.target.value),
                                        }
                                      : date,
                                  ),
                                )
                              }
                            />
                          </label>
                        </div>
                      ))}
                    </div>

                    <label className="upgrade-live-field upgrade-plan-reason">
                      <span>Change reason</span>
                      <textarea
                        aria-label="3. Change reason"
                        value={reason}
                        onChange={(event) => setReason(event.target.value)}
                        maxLength={2000}
                        placeholder="Describe why this upgrade is required…"
                      />
                    </label>

                  </div>
                </section>
              </div>

              <aside className="upgrade-plan-console-side">
                <section className="upgrade-plan-side-card">
                  <header>
                    <Layers3 size={18} aria-hidden="true" />
                    <h3>Plan Summary</h3>
                  </header>
                  <dl>
                    <div>
                      <dt>Plan Type</dt>
                      <dd>{isFullUpgrade ? "Full Upgrade" : "Targeted Upgrade"}</dd>
                    </div>
                    <div>
                      <dt>Cluster</dt>
                      <dd>{cluster.name}</dd>
                    </div>
                    <div>
                      <dt>Environment</dt>
                      <dd>{cluster.environment}</dd>
                    </div>
                    <div>
                      <dt>Platform</dt>
                      <dd>{cluster.providerLabel}</dd>
                    </div>
                    <div>
                      <dt>Upgrade Path</dt>
                      <dd>
                        {["CLUSTER", "CONTROL_PLANE"].includes(scope)
                          ? data.currentVersion + " → " + (finalTarget || "—")
                          : scopeLabel}
                      </dd>
                    </div>
                    <div>
                      <dt>Scope</dt>
                      <dd>{scopeLabel}</dd>
                    </div>
                    <div>
                      <dt>Maintenance</dt>
                      <dd>{windowSummary}</dd>
                    </div>
                    <div>
                      <dt>Approval</dt>
                      <dd>Platform Architect</dd>
                    </div>
                  </dl>
                </section>

                <section className="upgrade-plan-side-card">
                  <header>
                    <GitBranch size={18} aria-hidden="true" />
                    <h3>Workflow Preview</h3>
                  </header>
                  <ol className="upgrade-plan-workflow-list upgrade-plan-workflow-12">
                    <li>Readiness</li>
                    <li>Plan</li>
                    <li>Approval</li>
                    <li>Maintenance Window</li>
                    <li data-applicable={scope === "CLUSTER" || scope === "CONTROL_PLANE"}>
                      Control Plane
                    </li>
                    <li data-applicable={scope === "CLUSTER"}>Health Gate</li>
                    <li data-applicable={scope === "CLUSTER" || scope === "ADDONS"}>
                      Add-ons
                    </li>
                    <li data-applicable={scope === "CLUSTER" || scope === "NODES"}>
                      Node Groups
                    </li>
                    <li data-applicable={scope === "CLUSTER"}>Health Gate</li>
                    <li>Post Validation</li>
                    <li data-applicable={scope !== "ADDONS"}>IaC Sync</li>
                    <li>Upgraded</li>
                  </ol>
                </section>

                <section className="upgrade-plan-side-card">
                  <header>
                    <ShieldCheck size={18} aria-hidden="true" />
                    <h3>Readiness Checks</h3>
                  </header>
                  <div className="upgrade-plan-readiness-list">
                    {readinessChecks.map((check) => (
                      <div key={check.label} data-complete={check.complete}>
                        {check.complete ? (
                          <CheckCircle2 size={15} aria-hidden="true" />
                        ) : (
                          <span className="upgrade-plan-readiness-dot" />
                        )}
                        <span>{check.label}</span>
                      </div>
                    ))}
                  </div>
                </section>
              </aside>
            </div>

            {(mutation.isError || submit.isError) && (
              <div role="alert" className="upgrade-planner-alert">
                {mutation.error?.message || submit.error?.message}
              </div>
            )}

            <footer className="upgrade-plan-console-actions">
              <Button variant="secondary" onClick={onClose}>
                Cancel
              </Button>
              <span>{missing}</span>
              <Button
                disabled={Boolean(missing) || mutation.isPending}
                onClick={() => mutation.mutate()}
              >
                Save draft &amp; review
              </Button>
            </footer>
          </fieldset>
        )
      )}
    </section>
  );
}
