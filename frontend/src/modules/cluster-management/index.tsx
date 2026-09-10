import { ModulePlaceholder } from "@/shared/components/module-placeholder";

export function ClusterAdminPage() {
  return (
    <ModulePlaceholder
      title="Cluster Admin"
      description="Monitor EKS provisioning requests and manage cluster lifecycle from one place."
    />
  );
}

export function NewClusterPage() {
  return (
    <ModulePlaceholder
      title="New EKS cluster"
      description="Select an approved environment profile and define a governed EKS provisioning request."
    />
  );
}
