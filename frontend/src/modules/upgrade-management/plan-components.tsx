"use client";

import { CheckCircle2, Circle, AlertTriangle } from "lucide-react";
import type { EksUpgradeReadiness } from "@/modules/cluster-management/model";

export function PlanComponents({
  evidence,
  target,
}: {
  evidence?: EksUpgradeReadiness;
  target: string;
}) {
  return (
    <div className="table-scroll">
      <table className="upgrade-fleet-table">
        <thead>
          <tr>
            <th>Component</th>
            <th>Current</th>
            <th>Target</th>
            <th>Planned action</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Control plane</td>
            <td>{evidence?.controlPlane.version ?? "Unknown"}</td>
            <td>{target}</td>
            <td>Upgrade first</td>
          </tr>
          {(evidence?.addons ?? []).map((addon) => (
            <tr key={addon.name}>
              <td>Managed add-on · {addon.name}</td>
              <td>{addon.version}</td>
              <td>{addon.targetVersion ?? "Unknown"}</td>
              <td>
                {!addon.targetVersion
                  ? "Compatibility required"
                  : addon.targetVersion === addon.version
                    ? "Keep version"
                    : "Upgrade after control plane"}
              </td>
            </tr>
          ))}
          {(evidence?.nodeGroups ?? []).map((node) => (
            <tr key={node.name}>
              <td>Node group · {node.name}</td>
              <td>{node.version}</td>
              <td>{target}</td>
              <td>Rolling upgrade after add-ons</td>
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
}: {
  label: string;
  passed: boolean;
  pending?: boolean;
}) {
  const Icon = passed ? CheckCircle2 : pending ? Circle : AlertTriangle;
  return (
    <li className={passed ? "check-passed" : "check-pending"}>
      <Icon size={18} aria-hidden="true" />
      <span>
        {label}
        <small>{passed ? "Complete" : pending ? "Pending" : "Required"}</small>
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
