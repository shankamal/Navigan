import { ClusterAdminPage } from "@/modules/cluster-management";

export const metadata = { title: "Cluster Reviews" };

export default function Page() {
  return <ClusterAdminPage mode="reviews" />;
}
