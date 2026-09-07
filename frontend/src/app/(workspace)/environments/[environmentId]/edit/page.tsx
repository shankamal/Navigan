import { EnvironmentEditor } from "@/modules/environment-management/components/environment-form";
export default async function Page({
  params,
}: {
  params: Promise<{ environmentId: string }>;
}) {
  const { environmentId } = await params;
  return <EnvironmentEditor id={environmentId} />;
}
