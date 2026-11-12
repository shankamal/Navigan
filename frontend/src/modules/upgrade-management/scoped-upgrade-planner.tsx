"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Cpu, Layers3, Puzzle } from "lucide-react";
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
  return (
    <section className="upgrade-scoped-planner">
      <button type="button" className="upgrade-back-link" onClick={onClose}>
        <ArrowLeft size={16} /> Back to Upgrade Centre
      </button>
      <header className="upgrade-planner-heading">
        <h2>Create upgrade plan</h2>
        <p>
          Select a component scope, review the provider-supported path and
          request a maintenance window for each step.
        </p>
      </header>
      <ClusterContext
        cluster={{
          clusterId: cluster.id,
          clusterName: cluster.name,
          environmentName: cluster.environment,
        }}
      />
      {options.isPending && (
        <p role="status">Loading live component versions and compatibility…</p>
      )}
      {options.isError && (
        <div role="alert">
          {options.error.message}{" "}
          <Button variant="secondary" onClick={() => void options.refetch()}>
            Retry discovery
          </Button>
        </div>
      )}
      {created ? (
        <>
          <p role="status">
            {created.status === "SUBMITTED"
              ? "Submitted for Platform Architect approval."
              : "Draft saved. Review the exact operations below before submitting."}
          </p>
          {created.planSpec && <UpgradePathDetails spec={created.planSpec} />}
        </>
      ) : (
        data && (
          <fieldset disabled={locked}>
            <legend>1. Upgrade scope</legend>
            <div className="upgrade-scope-options">
              {(
                [
                  {
                    id: "CONTROL_PLANE",
                    label: "Control plane only",
                    Icon: Cpu,
                  },
                  { id: "CLUSTER", label: "Full platform upgrade", Icon: Cpu },
                  { id: "NODES", label: "Node groups", Icon: Layers3 },
                  { id: "ADDONS", label: "Managed add-ons", Icon: Puzzle },
                ] as const
              ).map((s) => (
                <label key={s.id}>
                  <input
                    type="radio"
                    name="upgradeScope"
                    checked={scope === s.id}
                    onChange={() => {
                      setScope(s.id);
                      setWindows([
                        { start: calendarSchedule(initialDate), duration: 120 },
                      ]);
                    }}
                  />
                  <s.Icon size={18} />
                  {s.label}
                </label>
              ))}
            </div>
            <div className="upgrade-scoped-version">
              <PlatformIdentity
                identity={containerIdentity("EKS")}
                kind="platform"
              />
              <span>
                Control plane: <strong>{data.currentVersion}</strong> ·{" "}
                {data.region}
              </span>
            </div>
            {["CLUSTER", "CONTROL_PLANE"].includes(scope) ? (
              <>
                <label className="upgrade-live-field">
                  <span>Final Kubernetes target</span>
                  <select
                    value={finalTarget}
                    onChange={(e) => {
                      setTarget(e.target.value);
                      setWindows([
                        { start: calendarSchedule(initialDate), duration: 120 },
                      ]);
                    }}
                  >
                    {!data.targetVersions.length && (
                      <option value="">No supported target</option>
                    )}
                    {data.targetVersions.map((v) => (
                      <option key={v}>{v}</option>
                    ))}
                  </select>
                </label>
                <p>
                  Upgrade path:{" "}
                  {[
                    data.currentVersion,
                    ...Array.from(
                      { length: Math.max(0, count) },
                      (_, i) =>
                        `1.${Number(data.currentVersion.split(".")[1]) + i + 1}`,
                    ),
                  ].join(" → ")}
                </p>
                <p>
                  {scope === "CONTROL_PLANE"
                    ? "Changes only the managed Kubernetes control plane. Node groups and add-ons stay unchanged; installed add-ons must already be compatible with every target version."
                    : "Full platform upgrade: control plane, managed node groups and any add-on changes required for compatibility. Versions cannot be skipped."}{" "}
                  Future steps are checked again before execution.
                </p>
              </>
            ) : scope === "NODES" ? (
              <>
                <p>
                  {data.nodeUpgradeNote} Same-version AMI patching is not
                  included.
                </p>
                {data.nodeGroups.map((n) => (
                  <label key={n.name} className="upgrade-node-selection">
                    <input
                      type="checkbox"
                      checked={nodes.includes(n.name)}
                      disabled={
                        n.version === data.currentVersion ||
                        n.amiType === "CUSTOM"
                      }
                      onChange={(e) =>
                        setNodes(
                          e.target.checked
                            ? [...nodes, n.name]
                            : nodes.filter((v) => v !== n.name),
                        )
                      }
                    />
                    {n.name} · {n.version ?? "Unknown"} → {data.currentVersion}
                    {n.version === data.currentVersion
                      ? " · Already aligned"
                      : n.amiType === "CUSTOM"
                        ? " · Custom AMI requires a separate workflow"
                        : ""}
                  </label>
                ))}
                {!data.nodeGroups.length && (
                  <p>No managed node groups discovered.</p>
                )}
              </>
            ) : (
              <>
                {data.addons.map((a) => (
                  <label key={a.name} className="upgrade-live-field">
                    <span>
                      {a.name} · Installed {a.version}
                    </span>
                    <select
                      value={addons[a.name] || ""}
                      onChange={(e) =>
                        setAddons((prev) => {
                          const next = { ...prev };
                          if (e.target.value) next[a.name] = e.target.value;
                          else delete next[a.name];
                          return next;
                        })
                      }
                    >
                      <option value="">Keep installed version</option>
                      {a.versions
                        .filter((v) => v.version !== a.version)
                        .map((v) => (
                          <option key={v.version} value={v.version}>
                            {v.version}
                            {v.recommended ? " · Provider recommended" : ""}
                          </option>
                        ))}
                    </select>
                  </label>
                ))}
                <p>
                  Only provider-compatible releases are listed. Saving validates
                  that each selected target is newer and that intermediate minor
                  releases are available.
                </p>
              </>
            )}
            <h3>2. Maintenance windows</h3>
            <p>
              Separate windows allow application checks between Kubernetes
              version steps. Times shown in{" "}
              {Intl.DateTimeFormat().resolvedOptions().timeZone}. Leave all
              dates empty to save an unscheduled draft.
            </p>
            {dates.map((w, i) => (
              <div key={i} className="upgrade-window-fields">
                <label className="upgrade-live-field">
                  <span>Step {i + 1} maintenance start</span>
                  <input
                    type="datetime-local"
                    aria-label={`Step ${i + 1} maintenance start`}
                    value={w.start}
                    onChange={(e) =>
                      setWindows(
                        dates.map((d, j) =>
                          j === i ? { ...d, start: e.target.value } : d,
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
                    value={w.duration}
                    onChange={(e) =>
                      setWindows(
                        dates.map((d, j) =>
                          j === i
                            ? { ...d, duration: Number(e.target.value) }
                            : d,
                        ),
                      )
                    }
                  />
                </label>
              </div>
            ))}
            <label className="upgrade-live-field">
              <span>3. Change reason</span>
              <textarea
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                maxLength={2000}
              />
            </label>
          </fieldset>
        )
      )}
      {(mutation.isError || submit.isError) && (
        <div role="alert">
          {mutation.error?.message || submit.error?.message}
        </div>
      )}
      <footer className="upgrade-scoped-actions">
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
                {created.planSpec?.steps.some((s) => !s.window)
                  ? "Add all maintenance windows from the plan details before submission."
                  : "Saving and approval do not start an upgrade."}
              </span>
              <Button
                disabled={
                  submit.isPending ||
                  created.planSpec?.steps.some((s) => !s.window)
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
