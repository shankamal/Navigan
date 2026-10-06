import { MigrationDetails } from "@/modules/migration-management/migration-details";

export default async function Page({
  params,
}: {
  params: Promise<{ migrationId: string }>;
}) {
  const { migrationId } = await params;
  return <MigrationDetails migrationId={migrationId} />;
}
