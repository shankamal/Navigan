import { connection } from "next/server";
import { isSourceFirstEnabled } from "@/modules/migration-management/source-first-config";
import { SourceDiscoveryScreen } from "@/modules/migration-management/source-discovery-screen";
import { MigrationDetails } from "@/modules/migration-management/migration-details";

export default async function Page({
  params,
}: {
  params: Promise<{ migrationId: string }>;
}) {
  await connection();
  const { migrationId } = await params;
  return isSourceFirstEnabled() ? (
    <SourceDiscoveryScreen migrationId={migrationId} />
  ) : (
    <MigrationDetails migrationId={migrationId} />
  );
}
