"use client";

import Link from "next/link";
import { SourceMigrationWorkspace } from "./source-migration-workspace";
import { useSourceDiscoverySnapshot } from "./source-discovery-screen";
import { sourceWorkspaceReady } from "./source-discovery-state";

export function SourceWorkspaceEntry({ migrationId }: { migrationId: string }) {
  const query = useSourceDiscoverySnapshot(migrationId, false);
  if (query.isPending) return <p role="status">Checking source assessment…</p>;
  const data = query.data;
  if (
    query.isError ||
    !data ||
    !sourceWorkspaceReady(data.migration, data.assessment, data.inventory)
  )
    return (
      <section className="panel">
        <h1>Complete Source Discovery & Assessment</h1>
        <p>
          A completed assessment with matching inventory evidence is required
          before opening the workspace.
        </p>
        <Link href={`/migrations/${migrationId}/discovery`}>
          Return to source discovery
        </Link>
      </section>
    );
  return (
    <SourceMigrationWorkspace
      migration={data.migration}
      assessment={data.assessment!}
      inventory={data.inventory!}
    />
  );
}
