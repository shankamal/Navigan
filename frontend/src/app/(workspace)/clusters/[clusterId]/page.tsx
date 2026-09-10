import { ClusterRequestPage } from "@/modules/cluster-management";

export const metadata = { title: "Container environment request" };
export default async function Page({
  params,
}: {
  params: Promise<{ clusterId: string }>;
}) {
  return <ClusterRequestPage id={(await params).clusterId} />;
}
