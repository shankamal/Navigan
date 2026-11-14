"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  CalendarClock,
  CheckCircle2,
  Cpu,
  Layers3,
  Puzzle,
  ShieldCheck,
  Target,
} from "lucide-react";
import { clusters } from "@/modules/cluster-management/service";
import type {
  EksUpgradePlan,
  UpgradeSpec,
} from "@/modules/cluster-management/model";
import { Button } from "@/shared/components/ui";
import { useAuth } from "@/shared/auth/auth-provider";
import { hasPermission } from "@/shared/auth/permissions";
import { ClusterContext } from "./cluster-context";
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
  >("CONTROL_PLANE");
  const [target, setTarget] = useState("");
  const [nodes, setNodes] = useState<string[]>([]);
  const [addons, setAddons] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const [windows, setWindows] = useState<{ start: string; duration: number }[]>(
    [{ start: calendarSchedule(initialDate), duration: 120 }],
  );
  const [created, setCreated] = useState<EksUpgradePlan>();
  const data = options.data,
    finalTarget = target || data?.targetVersions[0] || "";
  const count =
    ["CLUSTER", "CONTROL_PLANE"].includes(scope) && data && finalTarget
      ? Number(finalTarget.split(".")[1]) -
        Number(data.currentVersion.split(".")[1])
      : 1;
  const dates = Array.from(
    { length: Math.max(1, count) },
    (_, i) => windows[i] || { start: "", duration: 120 },
  );
  const supplied = dates.filter((w) => w.start).length;
  const validDates = dates.every(
    (w, i) =>
      !w.start ||
      (Number.isFinite(new Date(w.start).getTime()) &&
        new Date(w.start).getTime() > Date.now() &&
        (i === 0 ||
          !dates[i - 1].start ||
          new Date(w.start).getTime() >=
            new Date(dates[i - 1].start).getTime() +
              dates[i - 1].duration * 60000)),
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
                    (w) =>
                      !Number.isInteger(w.duration) ||
                      w.duration < 30 ||
                      w.duration > 1440,
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
          ? dates.map((w) => ({
              scheduledFor: new Date(w.start).toISOString(),
              durationMinutes: w.duration,
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
  const scopeLabel =
    scope === "CONTROL_PLANE"
      ? "Control plane only"
      : scope === "CLUSTER"
        ? "Full platform upgrade"
        : scope === "NODES"
          ? "Node groups"
          : "Managed add-ons";
  const selectedComponents =
    scope === "NODES"
      ? nodes.length
      : scope === "ADDONS"
        ? Object.keys(addons).length
        : 1;
  const planTarget =
    ["CLUSTER", "CONTROL_PLANE"].includes(scope)
      ? finalTarget || "Not available"
      : scope === "NODES"
        ? data?.currentVersion ?? cluster.currentVersion
        : selectedComponents + " selected";
  const windowSummary =
    supplied === 0
      ? "Draft / unscheduled"
      : supplied === dates.length
        ? supplied + " of " + dates.length + " scheduled"
        : supplied + " of " + dates.length + " selected";
  return (
    <section className="upgrade-scoped-planner upgrade-scoped-planner-v2">
      <header className="upgrade-planner-topbar">
        <button type="button" className="upgrade-back-link" onClick={onClose}>
          <ArrowLeft size={16} aria-hidden="true" />
          Back to Upgrade Centre
        </button>
        <div className="upgrade-planner-heading">
          <h2>Create upgrade plan</h2>
          <p>
            Define the upgrade scope, supported target, maintenance window and
            change reason before saving a governed draft.
          </p>
        </div>
      </header>

      <section className="upgrade-planner-context-card" aria-label="Selected cluster">
        <ClusterContext
          cluster={{
            clusterId: cluster.id,
            clusterName: cluster.name,
            environmentName: cluster.environment,
          }}
        />
        {data && (
          <div className="upgrade-planner-context-meta">
            <PlatformIdentity
              identity={containerIdentity("EKS")}
              kind="platform"
            />
            <span>
              Current Kubernetes <strong>{data.currentVersion}</strong>
            </span>
            <span>
              Recommended target{" "}
              <strong>{data.targetVersions[0] ?? "Not available"}</strong>
            </span>
            <span>
              Region <strong>{data.region}</strong>
            </span>
          </div>
        )}
      </section>

      {options.isPending && (
        <div className="upgrade-planner-loading" role="status">
          Loading live component versions and compatibility…
        </div>
      )}
      {options.isError && (
        <div role="alert" className="upgrade-planner-alert">
          <span>{options.error.message}</span>
          <Button variant="secondary" onClick={() => void options.refetch()}>
            Retry discovery
          </Button>
        </div>
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
        </section>
      ) : (
        data && (
          <fieldset
            disabled={locked}
            className="upgrade-planner-fieldset upgrade-planner-v2-fieldset"
          >
            <legend className="sr-only">Create upgrade plan inputs</legend>

            <div className="upgrade-planner-v2-layout">
              <div className="upgrade-planner-v2-main">
                <section className="upgrade-planner-step-card">
                  <header className="upgrade-planner-step-heading">
                    <span className="upgrade-planner-step-number">1</span>
                    <div>
                      <h3>Upgrade scope</h3>
                      <p>
                        Choose exactly which Kubernetes components this plan
                        is allowed to change.
                      </p>
                    </div>
                  </header>

                  <div className="upgrade-scope-options upgrade-scope-options-v2">
                    {(
                      [
                        {
                          id: "CONTROL_PLANE",
                          label: "Control plane only",
                          description:
                            "Upgrade the managed Kubernetes control plane only.",
                          Icon: Cpu,
                        },
                        {
                          id: "CLUSTER",
                          label: "Full platform upgrade",
                          description:
                            "Control plane, required add-ons and managed node groups.",
                          Icon: Layers3,
                        },
                        {
                          id: "NODES",
                          label: "Node groups",
                          description:
                            "Upgrade selected managed node groups to the control-plane version.",
                          Icon: Layers3,
                        },
                        {
                          id: "ADDONS",
                          label: "Managed add-ons",
                          description:
                            "Upgrade selected provider-managed Kubernetes add-ons.",
                          Icon: Puzzle,
                        },
                      ] as const
                    ).map((item) => (
                      <label
                        key={item.id}
                        className={scope === item.id ? "selected" : ""}
                      >
                        <input
                          type="radio"
                          name="upgradeScope"
                          checked={scope === item.id}
                          onChange={() => {
                            setScope(item.id);
                            setWindows([
                              {
                                start: calendarSchedule(initialDate),
                                duration: 120,
                              },
                            ]);
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
                </section>

                <section className="upgrade-planner-step-card">
                  <header className="upgrade-planner-step-heading">
                    <span className="upgrade-planner-step-number">2</span>
                    <div>
                      <h3>Target & components</h3>
                      <p>
                        Review the live version evidence and select the exact
                        component change for this plan.
                      </p>
                    </div>
                  </header>

                  <div className="upgrade-scoped-version upgrade-scoped-version-v2">
                    <PlatformIdentity
                      identity={containerIdentity("EKS")}
                      kind="platform"
                    />
                    <span>
                      Control plane <strong>{data.currentVersion}</strong>
                    </span>
                    <span>
                      Scope <strong>{scopeLabel}</strong>
                    </span>
                  </div>

                  {["CLUSTER", "CONTROL_PLANE"].includes(scope) ? (
                    <div className="upgrade-target-panel">
                      <label className="upgrade-live-field">
                        <span>Final Kubernetes target</span>
                        <select
                          value={finalTarget}
                          onChange={(e) => {
                            setTarget(e.target.value);
                            setWindows([
                              {
                                start: calendarSchedule(initialDate),
                                duration: 120,
                              },
                            ]);
                          }}
                        >
                          {!data.targetVersions.length && (
                            <option value="">No supported target</option>
                          )}
                          {data.targetVersions.map((version) => (
                            <option key={version}>{version}</option>
                          ))}
                        </select>
                      </label>

                      <div className="upgrade-path-summary">
                        <Target size={17} aria-hidden="true" />
                        <div>
                          <span>Upgrade path</span>
                          <strong>
                            {[
                              data.currentVersion,
                              ...Array.from(
                                { length: Math.max(0, count) },
                                (_, i) =>
                                  "1." +
                                  (Number(data.currentVersion.split(".")[1]) +
                                    i +
                                    1),
                              ),
                            ].join(" → ")}
                          </strong>
                        </div>
                      </div>

                      <p className="upgrade-planner-guidance">
                        {scope === "CONTROL_PLANE"
                          ? "Changes only the managed Kubernetes control plane. Node groups and add-ons stay unchanged; installed add-ons must already be compatible with every target version."
                          : "Full platform upgrade includes the control plane, managed node groups and add-on changes required for compatibility. Kubernetes minor versions cannot be skipped."}{" "}
                        Future steps are checked again before execution.
                      </p>
                    </div>
                  ) : scope === "NODES" ? (
                    <div className="upgrade-component-selection-panel">
                      <p className="upgrade-planner-guidance">
                        {data.nodeUpgradeNote} Same-version AMI patching is not
                        included.
                      </p>
                      <div className="upgrade-component-selection-list">
                        {data.nodeGroups.map((node) => (
                          <label
                            key={node.name}
                            className="upgrade-node-selection upgrade-component-choice"
                          >
                            <input
                              type="checkbox"
                              checked={nodes.includes(node.name)}
                              disabled={
                                node.version === data.currentVersion ||
                                node.amiType === "CUSTOM"
                              }
                              onChange={(e) =>
                                setNodes(
                                  e.target.checked
                                    ? [...nodes, node.name]
                                    : nodes.filter((value) => value !== node.name),
                                )
                              }
                            />
                            <Layers3 size={17} aria-hidden="true" />
                            <span>
                              <strong>{node.name}</strong>
                              <small>
                                {node.version ?? "Unknown"} → {data.currentVersion}
                                {node.version === data.currentVersion
                                  ? " · Already aligned"
                                  : node.amiType === "CUSTOM"
                                    ? " · Custom AMI requires a separate workflow"
                                    : ""}
                              </small>
                            </span>
                          </label>
                        ))}
                      </div>
                      {!data.nodeGroups.length && (
                        <p>No managed node groups discovered.</p>
                      )}
                    </div>
                  ) : (
                    <div className="upgrade-component-selection-panel">
                      <div className="upgrade-addon-selection-list">
                        {data.addons.map((addon) => (
                          <label
                            key={addon.name}
                            className="upgrade-live-field upgrade-addon-choice"
                          >
                            <span>
                              <strong>{addon.name}</strong>
                              <small>Installed {addon.version}</small>
                            </span>
                            <select
                              value={addons[addon.name] || ""}
                              onChange={(e) =>
                                setAddons((previous) => {
                                  const next = { ...previous };
                                  if (e.target.value)
                                    next[addon.name] = e.target.value;
                                  else delete next[addon.name];
                                  return next;
                                })
                              }
                            >
                              <option value="">Keep installed version</option>
                              {addon.versions
                                .filter(
                                  (version) => version.version !== addon.version,
                                )
                                .map((version) => (
                                  <option
                                    key={version.version}
                                    value={version.version}
                                  >
                                    {version.version}
                                    {version.recommended
                                      ? " · Provider recommended"
                                      : ""}
                                  </option>
                                ))}
                            </select>
                          </label>
                        ))}
                      </div>
                      <p className="upgrade-planner-guidance">
                        Only provider-compatible releases are listed. Saving
                        validates that each selected target is newer and that
                        required intermediate releases are available.
                      </p>
                    </div>
                  )}
                </section>

                <section className="upgrade-planner-step-card">
                  <header className="upgrade-planner-step-heading">
                    <span className="upgrade-planner-step-number">3</span>
                    <div>
                      <h3>Maintenance window</h3>
                      <p>
                        Schedule each Kubernetes version step independently so
                        health checks can complete before the next step.
                      </p>
                    </div>
                  </header>

                  <div className="upgrade-maintenance-note">
                    <CalendarClock size={17} aria-hidden="true" />
                    <span>
                      Times shown in{" "}
                      {Intl.DateTimeFormat().resolvedOptions().timeZone}.
                      Leave every date empty to save an unscheduled draft.
                    </span>
                  </div>

                  <div className="upgrade-maintenance-windows">
                    {dates.map((window, index) => (
                      <div key={index} className="upgrade-window-fields">
                        <label className="upgrade-live-field">
                          <span>Step {index + 1} maintenance start</span>
                          <input
                            type="datetime-local"
                            aria-label={"Step " + (index + 1) + " maintenance start"}
                            value={window.start}
                            onChange={(e) =>
                              setWindows(
                                dates.map((date, dateIndex) =>
                                  dateIndex === index
                                    ? { ...date, start: e.target.value }
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
                            onChange={(e) =>
                              setWindows(
                                dates.map((date, dateIndex) =>
                                  dateIndex === index
                                    ? {
                                        ...date,
                                        duration: Number(e.target.value),
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
                </section>

                <section className="upgrade-planner-step-card">
                  <header className="upgrade-planner-step-heading">
                    <span className="upgrade-planner-step-number">4</span>
                    <div>
                      <h3>Change reason</h3>
                      <p>
                        Record the operational reason that reviewers should use
                        when evaluating this change.
                      </p>
                    </div>
                  </header>
                  <label className="upgrade-live-field upgrade-change-reason">
                    <span>Change reason</span>
                    <textarea
                      value={reason}
                      onChange={(e) => setReason(e.target.value)}
                      maxLength={2000}
                      placeholder="Describe why this upgrade is required…"
                    />
                    <small>{reason.length} / 2000 characters</small>
                  </label>
                </section>
              </div>

              <aside className="upgrade-planner-review-panel">
                <section className="upgrade-planner-review-card">
                  <header>
                    <ShieldCheck size={18} aria-hidden="true" />
                    <div>
                      <h3>Plan Summary</h3>
                      <p>Review before saving the governed draft.</p>
                    </div>
                  </header>

                  <dl className="upgrade-planner-review-list">
                    <div>
                      <dt>Cluster</dt>
                      <dd>{cluster.name}</dd>
                    </div>
                    <div>
                      <dt>Environment</dt>
                      <dd>{cluster.environment}</dd>
                    </div>
                    <div>
                      <dt>Scope</dt>
                      <dd>{scopeLabel}</dd>
                    </div>
                    <div>
                      <dt>Current version</dt>
                      <dd>{data.currentVersion}</dd>
                    </div>
                    <div>
                      <dt>Target / selection</dt>
                      <dd>{planTarget}</dd>
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

                  <div className="upgrade-planner-review-checks">
                    <div>
                      <CheckCircle2 size={15} aria-hidden="true" />
                      <span>Live upgrade options loaded</span>
                    </div>
                    <div>
                      <CheckCircle2 size={15} aria-hidden="true" />
                      <span>Provider-supported path enforced</span>
                    </div>
                    <div className={missing ? "pending" : ""}>
                      {missing ? (
                        <span className="upgrade-review-dot" aria-hidden="true" />
                      ) : (
                        <CheckCircle2 size={15} aria-hidden="true" />
                      )}
                      <span>
                        {missing || "Required planning inputs are complete"}
                      </span>
                    </div>
                  </div>
                </section>
              </aside>
            </div>
          </fieldset>
        )
      )}

      {(mutation.isError || submit.isError) && (
        <div role="alert" className="upgrade-planner-alert">
          {mutation.error?.message || submit.error?.message}
        </div>
      )}

      <footer className="upgrade-scoped-actions upgrade-scoped-actions-v2">
        <Button variant="secondary" onClick={onClose}>
          Close
        </Button>
        {!created ? (
          <>
            <span>{missing}</span>
            <Button
              disabled={Boolean(missing) || mutation.isPending}
              onClick={() => mutation.mutate()}
            >
              Save draft & review
            </Button>
          </>
        ) : (
          created.status === "DRAFT" && (
            <>
              <span>
                {created.planSpec?.steps.some((step) => !step.window)
                  ? "Add all maintenance windows from the plan details before submission."
                  : "Saving and approval do not start an upgrade."}
              </span>
              <Button
                disabled={
                  submit.isPending ||
                  created.planSpec?.steps.some((step) => !step.window)
                }
                onClick={() => submit.mutate()}
              >
                Submit for approval
              </Button>
            </>
          )
        )}
      </footer>
    </section>
  );
}
