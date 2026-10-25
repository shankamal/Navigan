"use client";

import Link from "next/link";
import { HelpTip } from "@/shared/components/help-tip";
import { useQuery } from "@tanstack/react-query";
import { PageHeading } from "@/shared/components/ui";
import { migrations, sourceClusters } from "./service";
import { deploymentDiscovery } from "./deployment-evidence-service";
import { SourceConnectionsPanel } from "./source-connections-panel";
import styles from "./source-connection-screen.module.css";
import { MigrationActions } from "./migration-actions";
import flow from "./migration-experience.module.css";
import { ArrowLeft, ArrowRight } from "lucide-react";

export function SourceAccessSetup({ migrationId }: { migrationId: string }) {
  const assessment = useQuery({
    queryKey: ["source-access-assessment", migrationId],
    queryFn: () => migrations.get(migrationId),
    retry: false,
  });
  const sourceId = String(
    assessment.data?.sourceConfiguration.sourceClusterId ?? "",
  );
  const source = useQuery({
    queryKey: ["source-access-registration", migrationId, sourceId],
    queryFn: () => sourceClusters.get(sourceId),
    enabled: Boolean(sourceId),
    retry: false,
  });
  const owned = Boolean(
    source.data &&
    source.data.sourceClusterId === sourceId &&
    source.data.customerId === assessment.data?.customerId &&
    source.data.status !== "REVOKED",
  );
  const settings = useQuery({
    queryKey: ["deployment-sources", sourceId],
    queryFn: ({ signal }) => deploymentDiscovery.settings(sourceId, signal),
    enabled: owned,
    retry: false,
  });
  const failed =
    assessment.isError ||
    source.isError ||
    (source.data && !owned) ||
    (assessment.isSuccess && !sourceId);
  const ready = owned && settings.isSuccess && settings.data.readyForDiscovery;

  return (
    <div className={styles.screen}>
      <PageHeading
        title="Source access setup"
        description="Complete repository and registry access before source discovery and assessment."
      />
      {assessment.data && <p>{assessment.data.name}</p>}
      {failed ? (
        <section className={styles.panel}>
          <p role="alert">
            Unable to load an authorized source registration for this
            assessment.
          </p>
          <button
            type="button"
            onClick={() => {
              void assessment.refetch();
              if (sourceId) void source.refetch();
            }}
          >
            Retry
          </button>
        </section>
      ) : !owned ? (
        <p role="status">Loading source registration…</p>
      ) : (
        <>
          <section
            className={styles.panel}
            aria-label="Repository and registry setup"
          >
            <h2>
              {source.data?.name}
              <HelpTip label="Source access setup">
                Configure and verify GitHub repositories and container
                registries. Inventory-only discovery is an explicit alternative;
                repository and image evidence may be incomplete.
              </HelpTip>
            </h2>
            <SourceConnectionsPanel
              key={sourceId}
              sourceId={sourceId}
              compact
              openRequest={1}
              showConnector={false}
            />
          </section>
          <section
            className={styles.panel}
            aria-label="Discovery setup readiness"
          >
            <p role="status">
              {ready
                ? "Source access setup is ready for discovery."
                : settings.isError
                  ? "Unable to check setup readiness. Retry the check."
                  : "Save and verify source access, or save your inventory-only choice, before continuing."}
            </p>
            {settings.isError && (
              <button type="button" onClick={() => settings.refetch()}>
                Check readiness again
              </button>
            )}
          </section>
        </>
      )}
      <MigrationActions
        back={
          <Link href={`/migrations/${migrationId}/discovery`}>
            <ArrowLeft size={15} /> Back to discovery status
          </Link>
        }
        status={
          ready
            ? settings.data?.configuration?.inventoryOnly
              ? "Inventory-only setup saved · Ready for discovery"
              : "Access verified · Ready for discovery"
            : "Complete source access to continue"
        }
      >
        {ready ? (
          <Link
            className={flow.primary}
            href={`/migrations/${migrationId}/discovery`}
          >
            Continue to discovery <ArrowRight size={15} />
          </Link>
        ) : (
          <button className={flow.primary} type="button" disabled>
            Continue to discovery
          </button>
        )}
      </MigrationActions>
    </div>
  );
}
