import { ClusterAdminPage } from "@/modules/cluster-management";

export const metadata = { title: "Cluster Operations" };

export default function Page() {
  return <ClusterAdminPage mode="operations" />;
}
