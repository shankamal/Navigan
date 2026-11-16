import { UpgradeWorkspace } from "@/modules/upgrade-management/upgrade-workspace";

export const metadata = { title: "Patching" };

export default function Page() {
  return <UpgradeWorkspace initialTab="patching" />;
}
