"use client";

import { useMutation, useQueries, useQuery } from "@tanstack/react-query";
import { AlertTriangle, CalendarDays, History, RefreshCw } from "lucide-react";
import { clusters } from "@/modules/cluster-management/service";
import type { EksUpgradePlan } from "@/modules/cluster-management/model";
import { Button } from "@/shared/components/ui";

interface PlanRow {
  clusterName: string;
  environment: string;
  plan: EksUpgradePlan;
}

export function UpgradePlansWorkspace({
  mode,
}: {
  mode: "schedule" | "history";
}) {
  const fleet = useQuery({
    queryKey: ["upgrade-plan-fleet"],
    queryFn: () => clusters.list({ page: 0, pageSize: 100, status: "ACTIVE" }),
    staleTime: 30_000,
  });
  const items = fleet.data?.items ?? [];
  const planQueries = useQueries({
    queries: items.map((cluster) => ({
      queryKey: ["eks-upgrade-plans", cluster.clusterId],
      queryFn: () => clusters.upgradePlans(cluster.clusterId),
      staleTime: 10_000,
    })),
  });
  const rows: PlanRow[] = items.flatMap((cluster, index) =>
    (planQueries[index]?.data?.items ?? []).map((plan) => ({
      clusterName: cluster.clusterName,
      environment: cluster.environmentName ?? "Environment",
      plan,
    })),
  );
  const visible =
    mode === "schedule"
      ? rows.filter((row) =>
          ["APPROVED", "SCHEDULED", "EXECUTING"].includes(row.plan.status),
        )
      : rows;
  const action = useMutation({
    mutationFn: ({
      row,
      name,
    }: {
      row: PlanRow;
      name: "approve" | "reject" | "execute" | "refresh";
    }) =>
      clusters.changeUpgradePlan(
        row.plan.clusterId,
        row.plan.planId,
        name,
        row.plan.version,
        name === "reject" ? "Rejected during independent review." : undefined,
      ),
    onSuccess: () => {
      for (const query of planQueries) void query.refetch();
    },
  });
  const pending =
    fleet.isPending || planQueries.some((query) => query.isPending);
  const failed = fleet.isError || planQueries.some((query) => query.isError);
  const Icon = mode === "schedule" ? CalendarDays : History;

  return (
    <section
      className="upgrade-live-capability"
      aria-labelledby={`${mode}-plans-title`}
    >
      <header className="upgrade-live-header">
        <div>
          <p className="eyebrow">Governed upgrade records</p>
          <h2 id={`${mode}-plans-title`}>
            {mode === "schedule"
              ? "Maintenance schedule"
              : "Plans and execution history"}
          </h2>
          <p>
            {mode === "schedule"
              ? "Approved and executing EKS plans ordered by their maintenance window."
              : "Durable draft, approval and provider-execution evidence across managed clusters."}
          </p>
        </div>
        <Button
          variant="secondary"
          disabled={pending}
          onClick={() => {
            void fleet.refetch();
            for (const query of planQueries) void query.refetch();
          }}
        >
          <RefreshCw size={16} className={pending ? "spin" : ""} /> Refresh
          plans
        </Button>
      </header>
      {failed ? (
        <div className="upgrade-live-message error" role="alert">
          <AlertTriangle />
          <p>Upgrade plans could not be loaded.</p>
        </div>
      ) : pending ? (
        <div className="upgrade-live-message loading" role="status">
          <RefreshCw className="spin" />
          <p>Loading governed upgrade plans…</p>
        </div>
      ) : !visible.length ? (
        <div className="upgrade-live-message empty" role="status">
          <Icon />
          <p>
            {mode === "schedule"
              ? "No approved maintenance windows are scheduled."
              : "No upgrade plans have been created."}
          </p>
        </div>
      ) : (
        <div className="table-scroll">
          <table className="upgrade-fleet-table">
            <thead>
              <tr>
                <th>Plan</th>
                <th>Cluster</th>
                <th>Version change</th>
                <th>Status</th>
                <th>Maintenance start</th>
                <th>Updated</th>
                <th>
                  <span className="sr-only">Action</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {visible.map((row) => (
                <tr key={row.plan.planId}>
                  <td>
                    <strong>{row.plan.planId}</strong>
                  </td>
                  <td>
                    <strong>{row.clusterName}</strong>
                    <br />
                    <small>{row.environment}</small>
                  </td>
                  <td>
                    {row.plan.currentVersion} → {row.plan.targetVersion}
                  </td>
                  <td>
                    <span
                      className={`utility-state state-${row.plan.status.toLowerCase()}`}
                    >
                      {row.plan.status}
                    </span>
                  </td>
                  <td>
                    {row.plan.scheduledFor
                      ? new Date(row.plan.scheduledFor).toLocaleString()
                      : "Not scheduled"}
                  </td>
                  <td>{new Date(row.plan.updatedAt).toLocaleString()}</td>
                  <td>
                    {row.plan.status === "SUBMITTED" && (
                      <Button
                        disabled={action.isPending}
                        onClick={() => action.mutate({ row, name: "approve" })}
                      >
                        Approve
                      </Button>
                    )}
                    {["APPROVED", "SCHEDULED"].includes(row.plan.status) && (
                      <Button
                        disabled={action.isPending}
                        onClick={() => action.mutate({ row, name: "execute" })}
                      >
                        Start approved upgrade
                      </Button>
                    )}
                    {row.plan.status === "EXECUTING" && (
                      <Button
                        disabled={action.isPending}
                        onClick={() => action.mutate({ row, name: "refresh" })}
                      >
                        Refresh execution
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {action.isError && (
        <div className="upgrade-blocker-notice" role="alert">
          <strong>
            <AlertTriangle size={17} /> Plan action failed
          </strong>
          <p>{action.error.message}</p>
        </div>
      )}
    </section>
  );
}
