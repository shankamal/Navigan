import { EnvironmentDetails } from "@/modules/environment-management/components/environment-details";
export default async function Page({
  params,
}: {
  params: Promise<{ environmentId: string }>;
}) {
  const { environmentId } = await params;
  return <EnvironmentDetails id={environmentId} />;
}
