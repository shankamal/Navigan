import { UpgradeWorkspace } from "@/modules/upgrade-management/upgrade-workspace";
import { redirect } from "next/navigation";

export const metadata = { title: "Upgrades" };

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  if (params.tab === "utilities" || params.tab === "patching") {
    const query = new URLSearchParams();
    for (const key of ["plan", "date"])
      if (typeof params[key] === "string") query.set(key, params[key]);
    redirect(`/upgrades/${params.tab}${query.size ? `?${query}` : ""}`);
  }
  return <UpgradeWorkspace />;
}
