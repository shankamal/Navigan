import { MigrationDetails } from "@/modules/migration-management/migration-details";

import { SourceConnectionEntry } from "@/modules/migration-management/source-connection-entry";

export default async function Page({
  params,
}: {
  params: Promise<{ migrationId: string }>;
}) {
  const { migrationId } = await params;
  return process.env.NODE_ENV === "development" &&
    process.env.MIGRATION_SOURCE_FIRST_ENABLED !== "false" ? (
    <SourceConnectionEntry migrationId={migrationId} />
  ) : (
    <MigrationDetails migrationId={migrationId} />
  );
}
