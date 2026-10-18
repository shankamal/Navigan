import { SourceDiscoveryScreen } from "@/modules/migration-management/source-discovery-screen";
import { MigrationDetails } from "@/modules/migration-management/migration-details";

export default async function Page({
  params,
}: {
  params: Promise<{ migrationId: string }>;
}) {
  const { migrationId } = await params;
  return process.env.NODE_ENV === "development" &&
    process.env.MIGRATION_SOURCE_FIRST_ENABLED !== "false" ? (
    <SourceDiscoveryScreen migrationId={migrationId} />
  ) : (
    <MigrationDetails migrationId={migrationId} />
  );
}
