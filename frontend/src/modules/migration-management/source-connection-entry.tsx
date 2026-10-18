"use client";
import { useMigration } from "./hooks";
import { SourceDiscoveryScreen } from "./source-discovery-screen";
import { SourceConnectionScreen } from "./source-connection-screen";

export function SourceConnectionEntry({
  migrationId,
}: {
  migrationId: string;
}) {
  const query = useMigration(migrationId);
  if (query.isPending) return <p role="status">Loading migration…</p>;
  if (query.isError)
    return (
      <p role="alert">
        Unable to load this migration.{" "}
        <button onClick={() => query.refetch()}>Retry</button>
      </p>
    );
  return query.data.sourceConfiguration.discoveryMode === "MANUAL" &&
    query.data.status === "DRAFT" ? (
    <SourceConnectionScreen initialDraftId={migrationId} />
  ) : (
    <SourceDiscoveryScreen migrationId={migrationId} />
  );
}
