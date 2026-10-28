import type { Assessment, Migration, SourceInventory } from "./model";

export const sourceDiscoveryRunning = (status: string) =>
  [
    "SOURCE_ENROLLMENT_PENDING",
    "INVENTORY_DISCOVERING",
    "DISCOVERY_PENDING",
    "DISCOVERING",
    "ASSESSING",
  ].includes(status);

export function sourceWorkspaceReady(
  migration: Migration,
  assessment: Assessment | null,
  inventory: SourceInventory | null,
) {
  return Boolean(
    [
      "ASSESSMENT_READY",
      "SUBMITTED",
      "UNDER_REVIEW",
      "APPROVED",
      "REJECTED",
    ].includes(migration.status) &&
    assessment &&
    inventory &&
    assessment.inventoryDigest === inventory.inventoryDigest &&
    assessment.migrationVersion === inventory.migrationVersion &&
    (assessment.inventorySummary.sourceClusterId
      ? assessment.inventorySummary.sourceClusterId ===
          migration.sourceConfiguration.sourceClusterId &&
        migration.version >= assessment.migrationVersion + 2
      : migration.version === assessment.migrationVersion + 2),
  );
}
