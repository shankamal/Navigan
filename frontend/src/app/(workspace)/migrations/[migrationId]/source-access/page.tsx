import { SourceAccessSetup } from "@/modules/migration-management/source-access-setup";

export default async function Page({ params }: { params: Promise<{ migrationId: string }> }) {
  const { migrationId } = await params;
  return <SourceAccessSetup migrationId={migrationId} />;
}
