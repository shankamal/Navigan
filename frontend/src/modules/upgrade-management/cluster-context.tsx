"use client";
import { useQuery } from "@tanstack/react-query";
import { clusters } from "@/modules/cluster-management/service";
import { useAuth } from "@/shared/auth/auth-provider";
import type { Cluster } from "@/modules/cluster-management/model";
export function clusterAccount(cluster?: Partial<Cluster>): string {
  const arn = cluster?.provisioningRoleArn;
  if (arn && /^arn:aws(?:-[a-z]+)?:iam::\d{12}:role\//.test(arn))
    return arn.split(":")[4];
  const outputs = cluster?.outputs ?? {},
    account =
      outputs.accountId ??
      outputs.awsAccountId ??
      cluster?.configuration?.awsAccountId;
  return typeof account === "string" && /^\d{12}$/.test(account)
    ? account
    : "Not reported";
}
export function ClusterContext({
  cluster,
  compact = false,
}: {
  cluster?: Partial<Cluster>;
  compact?: boolean;
}) {
  const { identity } = useAuth();
  const detail = useQuery({
    queryKey: [
      "upgrade-cluster-detail",
      identity?.subject,
      identity?.authorizationRevision,
      cluster?.clusterId,
    ],
    queryFn: () => clusters.get(cluster!.clusterId!),
    enabled: Boolean(cluster?.clusterId && !cluster?.provisioningRoleArn),
    staleTime: 30_000,
    retry: false,
  });
  cluster = detail.data ?? cluster;
  return (
    <dl
      className={
        compact ? "upgrade-cluster-context compact" : "upgrade-cluster-context"
      }
      aria-label="Cluster ownership"
    >
      {[
        [
          "Customer",
          cluster?.customerName || cluster?.customerId || "Not reported",
        ],
        ["AWS account", clusterAccount(cluster)],
        [
          "Environment",
          cluster?.environmentName || cluster?.environmentId || "Not reported",
        ],
        ...(!compact
          ? [["Cluster", cluster?.clusterName || "Not selected"]]
          : []),
      ].map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}
