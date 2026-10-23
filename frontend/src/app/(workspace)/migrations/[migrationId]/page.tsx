import { connection } from "next/server";
import { isSourceFirstEnabled } from "@/modules/migration-management/source-first-config";
import { MigrationDetails } from "@/modules/migration-management/migration-details";

import { SourceConnectionEntry } from "@/modules/migration-management/source-connection-entry";

export default async function Page({
  params,
}: {
  params: Promise<{ migrationId: string }>;
}) {
  await connection();
  const { migrationId } = await params;
  return isSourceFirstEnabled() ? (
    <SourceConnectionEntry migrationId={migrationId} />
  ) : (
    <MigrationDetails migrationId={migrationId} />
  );
}
