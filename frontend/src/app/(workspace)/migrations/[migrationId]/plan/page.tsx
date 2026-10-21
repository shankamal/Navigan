import { MigrationPlanningWorkspace } from "@/modules/migration-management/planning-workspace";

export default async function Page({
  params,
}: {
  params: Promise<{ migrationId: string }>;
}) {
  const { migrationId } = await params;
  return <MigrationPlanningWorkspace migrationId={migrationId} />;
}
