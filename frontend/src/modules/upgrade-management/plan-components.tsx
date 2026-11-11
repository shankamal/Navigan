"use client";

import {
  CheckCircle2,
  Circle,
  AlertTriangle,
  CloudCog,
  Layers,
  Puzzle,
} from "lucide-react";
import type { EksUpgradeReadiness } from "@/modules/cluster-management/model";

export function PlanComponents({
  evidence,
  target,
  compact = false,
}: {
  evidence?: EksUpgradeReadiness;
  target: string;
  compact?: boolean;
}) {
  if (compact)
    return (
      <ul className="upgrade-drawer-components" aria-label="Upgrade components">
        <li>
          <CloudCog size={20} />
          <div>
            <strong>Control plane</strong>
            <span>
              {evidence?.controlPlane.version ?? "Not reported"} → {target}
            </span>
          </div>
          <small>Upgrade</small>
        </li>
        {(evidence?.nodeGroups ?? []).map((node) => (
          <li key={node.name}>
            <Layers size={20} />
            <div>
              <strong>Managed node group</strong>
              <span>{node.name}</span>
              <span>
                {node.version ?? "Not reported"} → {target}
              </span>
            </div>
            <small>
              {node.version === target ? "Keep version" : "Rolling upgrade"}
            </small>
          </li>
        ))}
        {(evidence?.addons ?? []).map((addon) => (
          <li key={addon.name}>
            <Puzzle size={20} />
            <div>
              <strong>Managed add-on</strong>
              <span>{addon.name}</span>
              <span>
                {addon.version ?? "Not reported"}
                {addon.targetVersion && addon.targetVersion !== addon.version
                  ? " → " + addon.targetVersion
                  : ""}
              </span>
            </div>
            <small>
              {!addon.targetVersion
                ? "Compatibility required"
                : addon.targetVersion === addon.version
                  ? "Keep version"
                  : "Upgrade"}
            </small>
          </li>
        ))}
      </ul>
    );
  return (
    <div className="table-scroll">
      <table className="upgrade-fleet-table">
        <thead>
          <tr>
            <th>Component</th>
            <th>Current</th>
            <th>Target</th>
            <th>Planned action</th>
            <th>Readiness</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>
              <span className="upgrade-component-name">
                <CloudCog size={22} />
                Control plane
              </span>
            </td>
            <td>{evidence?.controlPlane.version ?? "Unknown"}</td>
            <td>{target}</td>
            <td>Upgrade first</td>
            <td>
              <span
                className={
                  evidence?.readiness.checks.controlPlaneActive
                    ? "upgrade-component-ready"
                    : "upgrade-component-warning"
                }
              >
                {evidence?.readiness.checks.controlPlaneActive ? (
                  <CheckCircle2 size={15} />
                ) : (
                  <AlertTriangle size={15} />
                )}{" "}
                {evidence?.readiness.checks.controlPlaneActive
                  ? "Control plane active"
                  : "Evidence required"}
              </span>
            </td>
          </tr>
          {(evidence?.addons ?? []).map((addon) => (
            <tr key={addon.name}>
              <td>
                <span className="upgrade-component-name">
                  <Puzzle size={22} />
                  <span>
                    Managed add-on<small>{addon.name}</small>
                  </span>
                </span>
              </td>
              <td>{addon.version}</td>
              <td>{addon.targetVersion ?? "Unknown"}</td>
              <td>
                {!addon.targetVersion
                  ? "Compatibility required"
                  : addon.targetVersion === addon.version
                    ? "Keep version"
                    : "Upgrade after control plane"}
              </td>
              <td>
                <span
                  className={
                    addon.targetVersion
                      ? "upgrade-component-ready"
                      : "upgrade-component-warning"
                  }
                >
                  {addon.targetVersion ? (
                    <CheckCircle2 size={15} />
                  ) : (
                    <AlertTriangle size={15} />
                  )}{" "}
                  {addon.targetVersion
                    ? "Add-on compatible"
                    : "Compatibility required"}
                </span>
              </td>
            </tr>
          ))}
          {(evidence?.nodeGroups ?? []).map((node) => (
            <tr key={node.name}>
              <td>
                <span className="upgrade-component-name">
                  <Layers size={22} />
                  <span>
                    Managed node group<small>{node.name}</small>
                  </span>
                </span>
              </td>
              <td>{node.version}</td>
              <td>{target}</td>
              <td>Rolling upgrade after add-ons</td>
              <td>
                <span
                  className={
                    node.status === "ACTIVE" && !node.healthIssues.length
                      ? "upgrade-component-ready"
                      : "upgrade-component-warning"
                  }
                >
                  {node.status === "ACTIVE" && !node.healthIssues.length ? (
                    <CheckCircle2 size={15} />
                  ) : (
                    <AlertTriangle size={15} />
                  )}{" "}
                  {node.status === "ACTIVE" && !node.healthIssues.length
                    ? "Node group healthy"
                    : "Readiness required"}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function PlanCheck({
  label,
  passed,
  pending = false,
  completeLabel = "Complete",
}: {
  label: string;
  passed: boolean;
  pending?: boolean;
  completeLabel?: string;
}) {
  const Icon = passed ? CheckCircle2 : pending ? Circle : AlertTriangle;
  return (
    <li className={passed ? "check-passed" : "check-pending"}>
      <Icon size={18} aria-hidden="true" />
      <span>
        {label}
        <small>
          {passed ? completeLabel : pending ? "Pending" : "Required"}
        </small>
      </span>
    </li>
  );
}

export function EvidenceChecks({
  evidence,
}: {
  evidence?: EksUpgradeReadiness;
}) {
  return (
    <>
      <PlanCheck
        label="Control plane active"
        passed={evidence?.readiness.checks.controlPlaneActive === true}
      />
      <PlanCheck
        label="Managed node groups aligned"
        passed={evidence?.readiness.checks.nodeGroupsAligned === true}
      />
      <PlanCheck
        label="Managed add-ons healthy"
        passed={evidence?.readiness.checks.addonsHealthy === true}
      />
      <PlanCheck
        label="Upgrade insights passing"
        passed={evidence?.readiness.checks.upgradeInsightsPassing === true}
      />
      <PlanCheck
        label="No provider update in progress"
        passed={evidence?.readiness.checks.noUpdateInProgress === true}
      />
      <PlanCheck
        label="Supported sequential target"
        passed={Boolean(evidence?.recommendedTarget)}
      />
    </>
  );
}
