import { ClusterAccessPage } from "@/modules/cluster-management";

export const metadata = { title: "Kubernetes Access" };

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ cluster?: string }>;
}) {
  const cluster = (await searchParams).cluster;
  return (
    <ClusterAccessPage
      initialClusterId={
        cluster && /^CLU-[A-Za-z0-9-]+$/.test(cluster) ? cluster : ""
      }
    />
  );
}
