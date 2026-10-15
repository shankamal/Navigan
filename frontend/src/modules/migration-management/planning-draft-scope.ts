import type { MigrationPlanningDraft } from "./model";

/** New drafts start empty; saved selections take priority, including []. */
export function restorePlanningNamespaces(
  assessed: readonly string[],
  saved: MigrationPlanningDraft | null | undefined,
): string[] {
  const allowed = new Set(assessed);
  if (Array.isArray(saved?.selectedNamespaces)) {
    return [...new Set(saved.selectedNamespaces.filter(name => allowed.has(name)))];
  }
  if (saved?.resources?.length) {
    return [...new Set(saved.resources
      .map(resource => resource.namespace)
      .filter((name): name is string => typeof name === "string" && allowed.has(name)))];
  }
  return [];
}

export function preparePlanningDraft(
  draft: MigrationPlanningDraft,
  namespaces: readonly string[],
): MigrationPlanningDraft {
  return {...draft, selectedNamespaces: [...new Set(namespaces)]};
}

export function hasSelectedWorkload(
  draft: MigrationPlanningDraft,
  namespaces: readonly string[],
): boolean {
  const selected = new Set(namespaces);
  return draft.resources.some(resource =>
    !resource.dependency && !!resource.namespace &&
    selected.has(resource.namespace) &&
    ["Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"].includes(resource.kind));
}
