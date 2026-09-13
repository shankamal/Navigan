import { Building2, Layers3, Network, Boxes, LayoutDashboard } from "lucide-react";
export const platformModules = [
  {
    id: "dashboard",
    title: "Platform Dashboard",
    shortTitle: "Dashboard",
    href: "/dashboard",
    icon: LayoutDashboard,
    available: true,
  },
  {
    id: "customers",
    title: "Customer Management",
    shortTitle: "Customers",
    href: "/customers",
    icon: Building2,
    available: true,
  },
  {
    id: "environments",
    title: "Environment Management",
    shortTitle: "Environments",
    href: "/environments",
    icon: Layers3,
    available: true,
  },
  {
    id: "clusters",
    title: "Cluster Management",
    shortTitle: "Clusters",
    href: "/clusters",
    icon: Network,
    available: false,
  },
  {
    id: "applications",
    title: "Application Management",
    shortTitle: "Applications",
    href: "/applications",
    icon: Boxes,
    available: false,
  },
] as const;
