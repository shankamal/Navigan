import { MigrationCreatePage } from "@/modules/migration-management";
import { SourceConnectionScreen } from "@/modules/migration-management/source-connection-screen";

export const metadata = { title: "New Migration Assessment" };

export default function Page() {
  return process.env.NODE_ENV === "development" &&
    process.env.MIGRATION_SOURCE_FIRST_ENABLED !== "false" ? (
    <SourceConnectionScreen />
  ) : (
    <MigrationCreatePage />
  );
}
