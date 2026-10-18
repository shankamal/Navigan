import { MigrationPlanningWorkspace } from "@/modules/migration-management/planning-workspace";

import { SourceWorkspaceEntry } from "@/modules/migration-management/source-workspace-entry";

export default async function Page({
  params,
}: {
  params: Promise<{ migrationId: string }>;
}) {
  const { migrationId } = await params;
  return process.env.NODE_ENV === "development" &&
    process.env.MIGRATION_SOURCE_FIRST_ENABLED !== "false" ? (
    <SourceWorkspaceEntry migrationId={migrationId} />
  ) : (
    <MigrationPlanningWorkspace migrationId={migrationId} />
  );
}
