import { connection } from "next/server";
import { isSourceFirstEnabled } from "@/modules/migration-management/source-first-config";
import { MigrationCreatePage } from "@/modules/migration-management/create-page";
import { SourceConnectionScreen } from "@/modules/migration-management/source-connection-screen";

export const metadata = { title: "New Migration Assessment" };

export default async function Page() {
  await connection();
  return isSourceFirstEnabled() ? (
    <SourceConnectionScreen />
  ) : (
    <MigrationCreatePage />
  );
}
