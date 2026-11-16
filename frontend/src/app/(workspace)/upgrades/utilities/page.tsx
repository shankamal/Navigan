import { UpgradeWorkspace } from "@/modules/upgrade-management/upgrade-workspace";
export const metadata = { title: "System Utilities" };
export default function Page() {
  return <UpgradeWorkspace initialTab="utilities" />;
}
