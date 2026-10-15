import type { MigrationPlanningDraft } from "./model";
import { hasSelectedWorkload, preparePlanningDraft } from "./planning-draft-scope";

export async function saveAndContinueToTarget(
  draft: MigrationPlanningDraft,
  namespaces: readonly string[],
  persist: (draft: MigrationPlanningDraft) => Promise<unknown>,
  navigate: () => void,
): Promise<boolean> {
  if (!namespaces.length || !hasSelectedWorkload(draft, namespaces)) return false;
  await persist(preparePlanningDraft(draft, namespaces));
  navigate();
  return true;
}

export async function confirmAndClearDraft(
  draft: MigrationPlanningDraft,
  confirm: () => boolean,
  persist: (draft: MigrationPlanningDraft) => Promise<unknown>,
): Promise<MigrationPlanningDraft | null> {
  if (!confirm()) return null;
  const cleared: MigrationPlanningDraft = {
    schemaVersion: 1, mode: "SELECTED_WORKLOADS",
    assessmentVersion: draft.assessmentVersion, inventoryDigest: draft.inventoryDigest,
    selectedNamespaces: [], resources: [], remediations: [],
    storageMappings: [], dataStrategy: "UNDECIDED", notes: "",
  };
  await persist(cleared);
  return cleared;
}
