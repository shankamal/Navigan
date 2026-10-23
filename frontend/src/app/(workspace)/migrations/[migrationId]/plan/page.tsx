import { connection } from "next/server";
import { isSourceFirstEnabled } from "@/modules/migration-management/source-first-config";
import { MigrationPlanningWorkspace } from "@/modules/migration-management/planning-workspace";

import { SourceWorkspaceEntry } from "@/modules/migration-management/source-workspace-entry";

export default async function Page({
  params,
}: {
  params: Promise<{ migrationId: string }>;
}) {
  await connection();
  const { migrationId } = await params;
  return isSourceFirstEnabled() ? (
    <SourceWorkspaceEntry migrationId={migrationId} />
  ) : (
    <MigrationPlanningWorkspace migrationId={migrationId} />
  );
}
