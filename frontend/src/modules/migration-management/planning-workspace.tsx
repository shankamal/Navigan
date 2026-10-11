"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowRight,
  Boxes,
  ClipboardCheck,
  Database,
  LockKeyhole,
  Search,
  ShieldCheck,
  Wrench,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useWorkspacePage } from "@/shared/components/workspace-page-context";

import { normalizeApiError } from "@/shared/api/client";
import { useAuth } from "@/shared/auth/auth-provider";
import { hasPermission } from "@/shared/auth/permissions";
import { PageHeading } from "@/shared/components/ui";
import {
  useMigration,
  useMigrationAssessment,
  useSourceInventory,
} from "./hooks";
import type {
  Assessment,
  Migration,
  MigrationPlanningDraft,
  PlannedResource,
  RemediationDraft,
  SourceInventory,
  SourceInventoryResource,
} from "./model";
import { PlatformIcon } from "./platform-icon";
import { graphFromSanitizedInventory } from "./migration-graph";
import { evaluateScopeReadiness } from "./migration-readiness";
import { evaluateStorageCompatibility } from "./storage-validation";
import { inspectTargetCapabilitySnapshot } from "./target-capabilities";
import { recommendResource, recommendDependencies, recommendFinding } from "./planning-recommendations";
import { migrations } from "./service";
import styles from "./planning-workspace.module.css";

export function resourceKey(
  resource: Pick<PlannedResource, "apiVersion" | "kind" | "namespace" | "name">,
) {
  return JSON.stringify([
    resource.apiVersion,
    resource.kind,
    resource.namespace ?? null,
    resource.name,
  ]);
}

function emptyDraft(assessment: Assessment): MigrationPlanningDraft {
  return {
    schemaVersion: 1,
    mode: "SELECTED_WORKLOADS",
    assessmentVersion: assessment.assessmentVersion,
    inventoryDigest: assessment.inventoryDigest,
    resources: [],
    remediations: [],
    dataStrategy: "UNDECIDED",
    notes: "",
  };
}

export function MigrationPlanningWorkspace({
  migrationId,
}: {
  migrationId: string;
}) {
  const migration = useMigration(migrationId);
  const assessment = useMigrationAssessment(migrationId, true);
  const inventory = useSourceInventory(
    migrationId,
    Boolean(assessment.data?.assessment),
  );
  if (migration.isError || assessment.isError || inventory.isError)
    return (
      <section className="panel" role="alert">
        Unable to load planning evidence.{" "}
        <Link href={`/migrations/${migrationId}`}>Back to assessment</Link>
      </section>
    );
  if (migration.isPending || assessment.isPending || inventory.isPending)
    return <section className="panel">Loading migration evidence…</section>;
  if (
    !migration.data ||
    !assessment.data?.assessment ||
    !inventory.data?.inventory
  )
    return (
      <section className="panel">
        Complete the source inventory and assessment before planning.{" "}
        <Link href={`/migrations/${migrationId}`}>Open assessment</Link>
      </section>
    );
  return (
    <PlanningEditor
      migration={migration.data}
      assessment={assessment.data.assessment}
      inventory={inventory.data.inventory}
    />
  );
}

export function PlanningEditor({
  migration,
  assessment,
  inventory,
}: {
  migration: Migration;
  assessment: Assessment;
  inventory: SourceInventory;
}) {
  const { identity } = useAuth();
  const cache = useQueryClient();
  const canEdit =
    hasPermission(identity, "migration.edit") &&
    [
      "ASSESSMENT_READY",
      "SUBMITTED",
      "UNDER_REVIEW",
      "APPROVED",
      "REJECTED",
    ].includes(migration.status);
  const [draft, setDraft] = useState<MigrationPlanningDraft>(() =>
    migration.planningDraft?.schemaVersion === 1
      ? (migration.planningDraft as unknown as MigrationPlanningDraft)
      : emptyDraft(assessment),
  );
  const [tab, setTab] = useState<"scope" | "remediate" | "review">("scope");
  const stepHeadingRef = useRef<HTMLDivElement>(null);
  function navigateToStep(next: "scope" | "remediate" | "review") {
    setTab(next);
    stepHeadingRef.current?.scrollIntoView?.({ block: "start", behavior: "instant" });
  }
  const { setLabel } = useWorkspacePage();
  useEffect(() => {
    setLabel(
      tab === "scope"
        ? "Scope & target"
        : tab === "remediate"
          ? "Remediation & target mapping"
          : "Review migration draft",
    );
    return () => setLabel("");
  }, [tab, setLabel]);
  const [namespace, setNamespace] = useState(() => {
    const requested = migration.migrationScope?.namespaces;
    const namespaces = Array.isArray(requested) ? requested.filter((value): value is string => typeof value === "string") : [];
    return namespaces.length === 1 ? namespaces[0] : "";
  });
  const [search, setSearch] = useState("");
  const [resourceView, setResourceView] = useState<"ALL" | "WORKLOADS" | "DEPENDENCIES" | "CONFIGURATION" | "DATA">("WORKLOADS");
  const [severity, setSeverity] = useState("ALL");
  const [remediationCategory, setRemediationCategory] = useState("ALL");
  const [remediationView, setRemediationView] = useState<"FIXES" | "MAPPINGS" | "PLAN">("FIXES");
  const [selectedFindingIds, setSelectedFindingIds] = useState<number[]>([]);
  const [findingView, setFindingView] = useState<"SCOPE" | "SHARED" | "ALL">("SCOPE");
  const [findingIndex, setFindingIndex] = useState(0);
  const [message, setMessage] = useState("");
  const [dirty, setDirty] = useState(false);
  const [scopeReviewOpen, setScopeReviewOpen] = useState(false);
  const stale =
    draft.assessmentVersion !== assessment.assessmentVersion ||
    draft.inventoryDigest !== assessment.inventoryDigest ||
    inventory.inventoryDigest !== assessment.inventoryDigest;
  const resources = inventory.resources.filter(
    (r): r is SourceInventoryResource & { name: string } => Boolean(r.name),
  );
  const namespaces = [
    ...new Set(
      resources.map((r) => r.namespace).filter((n): n is string => Boolean(n)),
    ),
  ].sort();
  const filtered = resources.filter(
    (r) =>
      (!namespace || r.namespace === namespace) &&
      `${r.name} ${r.kind}`.toLowerCase().includes(search.toLowerCase()),
  );
  const workloadKinds = new Set(["Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob", "Pod"]);
  const configurationKinds = new Set(["ConfigMap", "Secret", "ServiceAccount", "Ingress", "Namespace", "Role", "RoleBinding", "ClusterRole", "ClusterRoleBinding", "NetworkPolicy", "CustomResourceDefinition"]);
  const dataKinds = new Set(["PersistentVolumeClaim", "PersistentVolume", "StorageClass", "VolumeSnapshot"]);
  const viewResources = filtered.filter((r) =>
    resourceView === "ALL" ||
    (resourceView === "WORKLOADS" && workloadKinds.has(r.kind)) ||
    (resourceView === "DEPENDENCIES" && (
      draft.resources.some((item) => item.dependency && resourceKey(item) === resourceKey({...r, namespace: r.namespace ?? null})) ||
      ["Service", "ConfigMap", "Secret", "ServiceAccount", "PersistentVolumeClaim"].includes(r.kind)
    )) ||
    (resourceView === "CONFIGURATION" && configurationKinds.has(r.kind)) ||
    (resourceView === "DATA" && dataKinds.has(r.kind))
  );
  const selected = new Map(draft.resources.map((r) => [resourceKey(r), r]));
  const displayedRecommendations = filtered.map((r) => recommendResource(r));
  const pendingRecommendations = displayedRecommendations.filter((r) => r.safeToBulkAdd && !selected.has(resourceKey(r.resource)));
  const managedRecommendations = displayedRecommendations.filter((r) => r.classification === "PLATFORM_MANAGED").length;
  const reviewRecommendations = displayedRecommendations.filter((r) => r.resource.treatment === "REVIEW").length;
  const recommendations = new Map(resources.map((r) => [resourceKey({ ...r, namespace: r.namespace ?? null }), recommendResource(r)]));
  const unaccounted = resources.filter(
    (r) =>
      !selected.has(resourceKey({ ...r, namespace: r.namespace ?? null })) ||
      selected.get(resourceKey({ ...r, namespace: r.namespace ?? null }))
        ?.treatment === "REVIEW",
  ).length;
  const dependencies = draft.resources.filter((r) => r.dependency).length;
  const blockers = assessment.findings.filter(
    (f) => f.severity === "BLOCKER",
  ).length;
  const suggestions = draft.resources.filter((r) => !r.dependency && ["Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"].includes(r.kind)).flatMap((r) => {
    const source = resources.find((x) => resourceKey({ ...x, namespace: x.namespace ?? null }) === resourceKey(r));
    return source ? recommendDependencies(source, resources) : [];
  }).filter((suggestion) => !selected.has(resourceKey(suggestion.resource)));
  const uniqueSuggestions = [...new Map(suggestions.map((r) => [resourceKey(r.resource), r])).values()];
  // Resolve dependencies against the proposed workloads before asking for confirmation.
  // This avoids a second acceptance button appearing only after workloads are added.
  const proposedWorkloads = [...draft.resources.filter((r) => !r.dependency), ...pendingRecommendations.map((r) => r.resource)];
  const proposedDependencies = proposedWorkloads
    .filter((r) => ["Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"].includes(r.kind))
    .flatMap((r) => {
      const source = resources.find((x) => resourceKey({ ...x, namespace: x.namespace ?? null }) === resourceKey(r));
      return source ? recommendDependencies(source, resources) : [];
    })
    .filter((r) => !selected.has(resourceKey(r.resource)));
  const recommendedScopeAdditions = [...new Map(
    [...pendingRecommendations.map((r) => r.resource), ...proposedDependencies.map((r) => r.resource)]
      .filter((r) => !selected.has(resourceKey(r)))
      .map((r) => [resourceKey(r), r] as const),
  ).values()];
  const recommendedDependencyCount = recommendedScopeAdditions.filter((r) => r.dependency).length;
  const pendingPvcs = resources.filter((r) => r.kind === "PersistentVolumeClaim" &&
    (draft.mode === "FULL_CLUSTER" || (!namespace || r.namespace === namespace)));

  const graph = graphFromSanitizedInventory(resources);
  const sourceReferences = graph.edges
    .filter((edge) => {
      const owner = graph.nodes.find((node) => node.id === edge.from);
      return owner && (!namespace || owner.namespace === namespace);
    })
    .map((edge) => {
      const owner = graph.nodes.find((node) => node.id === edge.from)!;
      return { owner: owner.kind + " " + owner.name, namespace: owner.namespace, kind: edge.kind, name: edge.name, present: edge.resolution === "IN_INVENTORY" };
    });
  const chosenOwners = new Set(draft.resources.filter((item) => !item.dependency).map((item) => JSON.stringify([item.kind, item.namespace, item.name])));
  const scopedReferences = sourceReferences.filter((ref) => chosenOwners.has(JSON.stringify([ref.owner.split(" ")[0], ref.namespace, ref.owner.slice(ref.owner.indexOf(" ") + 1)])));
  const missingReferences = scopedReferences.filter((ref) => !ref.present);
  const unselectedReferences = scopedReferences.filter((ref) => ref.present && !draft.resources.some((item) => item.kind === ref.kind && item.name === ref.name && item.namespace === ref.namespace));
  const unselectedDependencyResources = resources.filter((r) => unselectedReferences.some((ref) => ref.kind === r.kind && ref.name === r.name && ref.namespace === r.namespace));
  function includeReferencedDependencies() {
    const additions = unselectedDependencyResources.map((r) => ({
      apiVersion: r.apiVersion, kind: r.kind, namespace: r.namespace ?? null, name: r.name,
      treatment: recommendResource(r).resource.treatment, dependency: true,
    } as PlannedResource));
    const next = new Map(draft.resources.map((item) => [resourceKey(item), item]));
    additions.forEach((item) => next.set(resourceKey(item), item));
    change({ ...draft, resources: [...next.values()] });
    setMessage("Referenced supporting resources added to draft for review. Save the draft to persist.");
  }

  const relevantPvcs = resources.filter((r) => r.kind === "PersistentVolumeClaim" && (!namespace || r.namespace === namespace));
  const applicationWorkloads = resources.filter((r) =>
    ["Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"].includes(r.kind) &&
    (!namespace || r.namespace === namespace)
  );
  const plannedWorkloadKeys = new Set(draft.resources.filter((r) => !r.dependency).map((r) =>
    JSON.stringify([r.kind, r.namespace, r.name])
  ));
  const workloadRelationships = applicationWorkloads.map((workload) => {
    const references = sourceReferences.filter((ref) =>
      ref.owner === workload.kind + " " + workload.name && ref.namespace === workload.namespace
    );
    const selected = plannedWorkloadKeys.has(JSON.stringify([workload.kind, workload.namespace, workload.name]));
    const observedClaimCandidates = workload.kind === "StatefulSet" ? relevantPvcs.filter((pvc) =>
      typeof pvc.name === "string" && pvc.name.endsWith("-" + workload.name + "-0") && pvc.namespace === workload.namespace &&
      !references.some((ref) => ref.kind === "PersistentVolumeClaim" && ref.name === pvc.name)
    ) : [];
    return { workload, references, selected, observedClaimCandidates };
  });
  const evidenceCoverage = graph.coverage === "REFERENCES_AVAILABLE" ? "References captured" : "Reference evidence unavailable in this snapshot";
  const targetPlatform = String(migration.targetConfiguration?.platform ?? "UNKNOWN").toUpperCase();
  // Provider-specific candidates are guidance, not verified StorageClasses.
  function suggestedMapping(pvc: SourceInventoryResource & {name: string}) {
    const modes = Array.isArray(pvc.accessModes) ? pvc.accessModes.filter((m): m is string => typeof m === "string") : [];
    return {
      namespace: pvc.namespace ?? "",
      sourceClaim: pvc.name,
      targetStorageClass: targetPlatform === "EKS" ? "gp3" : "",
      targetCapacity: typeof pvc.requestedStorage === "string" ? pvc.requestedStorage : "",
      targetAccessMode: modes[0] ?? "",
      status: "PROPOSED" as const,
    };
  }
  const scopedStorageClaims = resources.filter((r) => r.kind === "PersistentVolumeClaim" && typeof r.name === "string" && r.namespace && (
    draft.mode === "FULL_CLUSTER" || draft.resources.some((item) => item.namespace === r.namespace &&
      item.kind === "PersistentVolumeClaim" && item.name === r.name)
  ));
  // Until a target adapter supplies verified StorageClass evidence, no class
  // can be certified by a provider-level naming recommendation.
  const targetCapability = inspectTargetCapabilitySnapshot(
    null, targetPlatform, String(migration.targetConfiguration?.clusterId ?? "")
  );
  const storageCompatibility = evaluateStorageCompatibility(
    scopedStorageClaims.map((pvc) => ({
      namespace: pvc.namespace ?? null,
      name: pvc.name,
      requestedStorage: typeof pvc.requestedStorage === "string" ? pvc.requestedStorage : null,
    })),
    (draft.storageMappings ?? []).length ? draft.storageMappings ?? [] : scopedStorageClaims.map((pvc) => suggestedMapping(pvc)),
    targetCapability.evidence,
  );
  const readiness = evaluateScopeReadiness(
    graph, draft.resources, draft.dataStrategy,
    resources.some((r) => r.kind === "PersistentVolumeClaim" && (draft.mode === "FULL_CLUSTER" || draft.resources.some((item) => item.namespace === r.namespace))),
    workloadRelationships.filter((entry) => entry.selected).reduce((count, entry) => count + entry.observedClaimCandidates.length, 0),
    scopedStorageClaims.map((r) => ({namespace: r.namespace ?? null, name: r.name!})),
    draft.storageMappings ?? [],
    storageCompatibility
  );
  const scopedResourceKeys = new Set(draft.resources.map((r) =>
    JSON.stringify([r.kind, r.namespace ?? null, r.name])));
  const scopedNamespaces = new Set(draft.resources.map((r) => r.namespace).filter((n): n is string => Boolean(n)));
  const findingScope = (item: Assessment["findings"][number]) => {
    if (!item.resourceName || !item.resourceKind || !item.namespace) return "SHARED";
    return scopedResourceKeys.has(JSON.stringify([item.resourceKind, item.namespace, item.resourceName]))
      ? "SCOPE" : "OUTSIDE";
  };
  function findingCategory(rawValue: string | undefined) {
    const raw = (rawValue ?? "").toLowerCase();
    if (/stor|volume|persist|data/.test(raw)) return "Storage";
    if (/network|ingress|route|service/.test(raw)) return "Networking";
    if (/secur|identity|iam|secret|policy/.test(raw)) return "Security";
    if (/config|api|deploy/.test(raw)) return "Configuration";
    return "Other";
  }
  const findings = assessment.findings
    .map((finding, index) => ({ finding, index }))
    .filter(({ finding }) =>
      (severity === "ALL" || finding.severity === severity) &&
      (remediationCategory === "ALL" || findingCategory(finding.category) === remediationCategory) &&
      (findingView === "ALL"
        ? (!namespace || finding.namespace === namespace)
        : findingView === "SHARED"
          ? findingScope(finding) === "SHARED" &&
            (!namespace || !finding.namespace || finding.namespace === namespace)
          : findingScope(finding) === "SCOPE")
    );
  const remediationGroups = ["Storage", "Networking", "Security", "Configuration", "Other"].map((category) => ({
    category,
    items: findings.filter(({finding}) => findingCategory(finding.category) === category),
  })).filter((group) => group.items.length > 0);
  const categorizedFindings = findings.filter(({finding}) => {
    if (remediationCategory === "ALL") return true;
    const raw = (finding.category ?? "").toLowerCase();
    const matched = remediationCategory === "Storage" ? /stor|volume|persist|data/.test(raw) :
      remediationCategory === "Networking" ? /network|ingress|route|service/.test(raw) :
      remediationCategory === "Security" ? /secur|identity|iam|secret|policy/.test(raw) :
      remediationCategory === "Configuration" ? /config|api|deploy/.test(raw) : false;
    return remediationCategory === "Other"
      ? !/stor|volume|persist|data|network|ingress|route|service|secur|identity|iam|secret|policy|config|api|deploy/.test(raw)
      : matched;
  });
  const remediationDecisionChecks = (item: RemediationDraft | undefined) => ({
    treatment: Boolean(item && item.treatment !== "REVIEW"),
    owner: Boolean(item?.owner.trim()),
    mapping: Boolean(item?.targetMapping.trim()),
    evidence: Boolean(item?.evidenceReference.trim()),
  });
  // The previous selection may no longer be visible after filtering.
  const activeFindingIndex = categorizedFindings.some(({ index }) => index === findingIndex)
    ? findingIndex
    : (categorizedFindings[0]?.index ?? -1);
  const finding = activeFindingIndex >= 0 ? assessment.findings[activeFindingIndex] : undefined;
  const suggestedRemediation = activeFindingIndex >= 0 ? recommendFinding(assessment, activeFindingIndex) : null;
  const acceptedSuggestion = draft.remediations.some((r) => r.findingIndex === activeFindingIndex);
  const remediation =
    draft.remediations.find((r) => r.findingIndex === activeFindingIndex) ??
    ({
      findingIndex: activeFindingIndex,
      treatment: "REVIEW",
      owner: "",
      targetMapping: "",
      evidenceReference: "",
      status: "PLANNED",
    } satisfies RemediationDraft);
  function change(next: MigrationPlanningDraft) {
    setDraft(next);
    setDirty(true);
    setMessage("");
  }
  function updateStorageMapping(namespace: string, sourceClaim: string, patch: Partial<NonNullable<MigrationPlanningDraft["storageMappings"]>[number]>) {
    const existing = (draft.storageMappings ?? []).find((m) => m.namespace === namespace && m.sourceClaim === sourceClaim);
    const entry = {...{namespace, sourceClaim, targetStorageClass:"", targetCapacity:"", targetAccessMode:"", status:"PROPOSED" as const}, ...existing, ...patch};
    change({...draft, storageMappings: [...(draft.storageMappings ?? []).filter((m) => !(m.namespace === namespace && m.sourceClaim === sourceClaim)), entry]});
  }
  function acceptSelectedRecommendations() {
    const selectedIds = categorizedFindings.filter(({index}) => selectedFindingIds.includes(index)).map(({index}) => index);
    const updated = new Map(draft.remediations.map(item => [item.findingIndex,item]));
    let applied = 0;
    for (const index of selectedIds) {
      const suggestion = recommendFinding(assessment,index);
      if (!suggestion || suggestion.treatment === "REVIEW" || updated.has(index)) continue;
      updated.set(index, suggestion);
      applied += 1;
    }
    if (applied) {
      change({...draft,remediations:[...updated.values()]});
      setSelectedFindingIds([]);
    } else setMessage("No eligible unrecorded recommendations selected. Review these findings individually.");
  }
  function changeRemediation(patch: Partial<RemediationDraft>) {
    change({
      ...draft,
      remediations: [
        ...draft.remediations.filter((r) => r.findingIndex !== activeFindingIndex),
        { ...remediation, ...patch },
      ],
    });
  }
  function toggle(resource: SourceInventoryResource & { name: string }) {
    const item: PlannedResource = {
      apiVersion: resource.apiVersion,
      kind: resource.kind,
      namespace: resource.namespace ?? null,
      name: resource.name,
      treatment: recommendResource(resource).resource.treatment,
      dependency: false,
    };
    change({
      ...draft,
      resources: selected.has(resourceKey(item))
        ? draft.resources.filter((r) => resourceKey(r) !== resourceKey(item))
        : [...draft.resources, item],
    });
  }
  const save = useMutation({
    mutationFn: () =>
      migrations.update(migration.migrationId, {
        version: migration.version,
        planningDraft: draft,
        changeReason: "Update migration scope and remediation planning draft",
      }),
    onSuccess: async (value) => {
      cache.setQueryData(["migrations", migration.migrationId], value);
      setDirty(false);
      setMessage("Planning draft saved. No cluster changes were applied.");
      await cache.invalidateQueries({ queryKey: ["migrations"], exact: true });
    },
    onError: (error) => setMessage(normalizeApiError(error).message),
  });
  return (
    <div className={styles.workspace}>
      <PageHeading
        icon={
          tab === "remediate" ? (
            <Wrench />
          ) : tab === "review" ? (
            <ShieldCheck />
          ) : (
            <Boxes />
          )
        }
        eyebrow="MIGRATION PLANNING"
        title={
          tab === "remediate"
            ? "Remediation & target mapping"
            : tab === "review"
              ? "Review migration draft"
              : "Plan your migration"
        }
        description={`${migration.name} · Self-managed Kubernetes → Amazon EKS`}
        action={
          <Link
            className="button button-secondary"
            href={`/migrations/${migration.migrationId}`}
          >
            <ArrowLeft size={16} /> Assessment report
          </Link>
        }
      />
      <div ref={stepHeadingRef} className={styles.navigationAnchor} />
      <nav className={styles.steps} aria-label="Migration workflow">
        <button
          aria-current={tab === "scope" ? "step" : undefined}
          onClick={() => navigateToStep("scope")}
        >
          <Boxes size={17} />
          Scope & target
        </button>
        <button
          aria-current={tab === "remediate" ? "step" : undefined}
          onClick={() => navigateToStep("remediate")}
        >
          <Wrench size={17} />
          Remediate
        </button>
        <button disabled title="Execution plan generation is not available yet">
          Plan
        </button>
        <button
          aria-current={tab === "review" ? "step" : undefined}
          onClick={() => navigateToStep("review")}
        >
          <ShieldCheck size={17} />
          Review draft
        </button>
      </nav>
      <section className={styles.guide} aria-label="Migration planning guide">
        <div className={styles.guideHeading}>
          <strong>{tab === "scope" ? "1 · Define application scope" : tab === "remediate" ? "2 · Resolve relevant findings" : "3 · Review planning readiness"}</strong>
          <span>Assessment v{assessment.assessmentVersion} · Read-only planning</span>
        </div>
        <p>{tab === "scope"
          ? "Choose candidate workloads, verify dependencies and review each resource treatment. The selected resources become the working migration scope."
          : tab === "remediate"
            ? "Address findings for selected resources first, then review shared risks. Accepting a suggestion creates a draft action; it does not remediate EKS."
            : "Check scope completeness, planned remediation, unresolved risks and data strategy before saving the draft."}</p>
        <div className={styles.guideStats}>
          <span><strong>{draft.resources.length}</strong> resources selected</span>
          <span><strong>{dependencies}</strong> confirmed dependencies</span>
          <span><strong>{draft.remediations.length}</strong> remediation decisions</span>
          <span><strong>{draft.dataStrategy === "UNDECIDED" ? "Pending" : "Chosen"}</strong> data strategy</span>
        </div>
      </section>
      {(message || save.isPending) && (
        <div
          className={save.isError ? styles.warning : styles.notice}
          role={save.isError ? "alert" : "status"}
          aria-live="polite"
        >
          {save.isPending ? "Saving draft…" : message}
        </div>
      )}
      {stale && (
        <div className={styles.warning} role="alert">
          Assessment evidence has changed. This draft cannot be saved.{" "}
          <button
            onClick={() => {
              change(emptyDraft(assessment));
              setFindingIndex(0);
            }}
          >
            Start a new draft from current evidence
          </button>
        </div>
      )}
      {!canEdit && (
        <div className={styles.notice}>
          Read-only planning view. Editing requires migration permission and a
          completed assessment.
        </div>
      )}
      {tab === "scope" && (
        <div className={styles.columns}>
          <section className={styles.surface}>
            <div className={styles.context}>
              <div>
                <span>Migration name</span>
                <strong>{migration.name}</strong>
              </div>
              <div>
                <span>Customer</span>
                <strong>
                  {String(migration.customerName ?? migration.customerId)}
                </strong>
              </div>
              <div>
                <span>Assessment snapshot</span>
                <strong>Version {assessment.assessmentVersion}</strong>
              </div>
            </div>
            <fieldset
              disabled={!canEdit || stale || save.isPending}
              className={styles.fields}
            >
              <legend>Migration mode</legend>
              <div className={styles.modes}>
                {(["SELECTED_WORKLOADS", "FULL_CLUSTER"] as const).map(
                  (mode) => (
                    <label
                      className={draft.mode === mode ? styles.selectedMode : ""}
                      key={mode}
                    >
                      <input
                        type="radio"
                        name="migration-mode"
                        checked={draft.mode === mode}
                        onChange={() => change({ ...draft, mode })}
                      />
                      <Boxes size={21} />
                      <span>
                        <strong>
                          {mode === "FULL_CLUSTER"
                            ? "Full cluster"
                            : "Selected workloads"}
                        </strong>
                        <small>
                          {mode === "FULL_CLUSTER"
                            ? "Account for the estate; replace platform services as needed."
                            : "Choose applications and explicitly confirm dependencies."}
                        </small>
                      </span>
                    </label>
                  ),
                )}
              </div>
            </fieldset>
            <div className={styles.target}>
              <PlatformIcon platform="SELF_MANAGED_KUBERNETES" size="medium" />
              <div>
                <span>Assessed source</span>
                <strong>
                  {String(
                    migration.sourceConfiguration.clusterName ??
                      "Self-managed Kubernetes",
                  )}
                </strong>
              </div>
              <ArrowRight size={18} />
              <PlatformIcon platform="EKS" size="medium" />
              <div>
                <span>Assessed target</span>
                <strong>
                  {assessment.inventorySummary.target.clusterName ??
                    "Target not selected"}
                </strong>
                <small>
                  {String(migration.targetConfiguration.environmentId ?? "")} ·{" "}
                  {String(migration.targetConfiguration.awsRegion ?? "")}
                </small>
              </div>
            </div>
            <p className={styles.caption}>
              Target changes require a fresh assessment.{" "}
              <Link href="/clusters/new">
                Create a cluster through Cluster Management
              </Link>
            </p>
            <div className={styles.sectionHeading}>
              <h2>
                {draft.mode === "FULL_CLUSTER"
                  ? "Resource accounting"
                  : "Choose workloads & dependencies"}
              </h2>
              <span>{draft.resources.length} selected</span>
            </div>
            <p className={styles.caption}>
              {draft.mode === "FULL_CLUSTER"
                ? "This inventory may exclude system namespaces or cluster-scoped resources. Full-estate coverage must be confirmed before execution planning."
                : "Inventory contains sanitized metadata, not deployment manifests or data. Dependency names are incomplete; confirm them with the application owner."}
            </p>
            <div className={styles.filters}>
              <label>
                Namespace
                <select
                  value={namespace}
                  onChange={(e) => setNamespace(e.target.value)}
                >
                  <option value="">All assessed namespaces</option>
                  {namespaces.map((n) => (
                    <option key={n}>{n}</option>
                  ))}
                </select>
              </label>
              <label>
                Search resources
                <div className={styles.search}>
                  <Search size={16} />
                  <input
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Name or kind"
                  />
                </div>
              </label>
            </div>
            <nav className={styles.scopeViews} aria-label="Scope resource views">
              {([
                ["WORKLOADS", "Workloads"],
                ["DEPENDENCIES", "Dependencies"],
                ["CONFIGURATION", "Configuration"],
                ["DATA", "Data & Storage"],
                ["ALL", "All resources · Technical view"],
              ] as const).map(([view, label]) => (
                <button
                  key={view}
                  type="button"
                  aria-current={resourceView === view ? "page" : undefined}
                  onClick={() => setResourceView(view)}
                >
                  {label}
                </button>
              ))}
            </nav>
            <div className={styles.notice} aria-live="polite">
              <strong>{resourceView === "WORKLOADS" ? "Workloads — application scope" : resourceView === "DEPENDENCIES" ? "Dependencies — source relationship evidence" : resourceView === "CONFIGURATION" ? "Configuration — application settings" : resourceView === "DATA" ? "Data & Storage — PVC readiness" : "All resources — technical inventory"}</strong>
              <p>{resourceView === "DEPENDENCIES" ? "Review references, unresolved inventory objects and supporting resources for selected workloads." : resourceView === "DATA" ? "Review claim consumers, requested capacity and storage migration decisions." : resourceView === "WORKLOADS" ? "Select the application workloads to migrate; supporting resources are reviewed separately." : resourceView === "CONFIGURATION" ? "Review metadata-only configuration evidence without collecting sensitive values." : "Advanced inventory view. Selections here affect the same draft."}</p>
            </div>
            {(resourceView === "WORKLOADS" || resourceView === "DEPENDENCIES") && (
              <div className={styles.applicationMap} aria-label="Application workload dependency map">
                <div className={styles.applicationMapHeader}>
                  <div>
                    <strong>Application workload map</strong>
                    <p>{applicationWorkloads.length} inventoried controllers · {workloadRelationships.filter((entry) => entry.selected).length} included in draft · {evidenceCoverage}</p>
                  </div>
                  <span>Source inventory · Assessment v{assessment.assessmentVersion}</span>
                </div>
                <div className={styles.applicationCards}>
                  {workloadRelationships.map(({workload, references, selected, observedClaimCandidates}) => (
                    <article key={resourceKey({...workload, namespace: workload.namespace ?? null})} className={styles.applicationCard}>
                      <div className={styles.applicationCardTitle}>
                        <strong>{workload.name}</strong>
                        <span>{workload.kind} · {selected ? "Selected" : "Not selected"}</span>
                      </div>
                      <div className={styles.applicationCardLinks}>
                        {references.length > 0 ? references.map((ref, index) => (
                          <div key={index} className={styles.applicationRelationship}>
                            <span>{ref.kind} · {ref.name}</span>
                            <span>{ref.present ? "Found in inventory" : "Not found in inventory"}</span>
                          </div>
                        )) : <p>No direct dependency references recorded in this snapshot.</p>}
                        {observedClaimCandidates.map((pvc) => (
                          <div key={pvc.name} className={styles.applicationRelationship}>
                            <span>PVC · {pvc.name}</span>
                            <span>Possible StatefulSet claim — verify ownership</span>
                          </div>
                        ))}
                      </div>
                    </article>
                  ))}
                  {applicationWorkloads.length === 0 && <p>No application controllers found for this namespace filter.</p>}
                </div>
                <p className={styles.caption}>Relationships come from sanitized inventory only. PVC name similarities are explicitly unverified and cannot establish readiness. Older assessments may not contain direct references.</p>
              </div>
            )}
            {resourceView === "DEPENDENCIES" && (
              <div className={styles.notice}>
                <strong>Source reference evidence · {sourceReferences.length} relationships</strong>
                {sourceReferences.length === 0 ? <p>No references in this snapshot; collect fresh inventory before concluding dependencies are absent.</p> : <ul>{sourceReferences.map((ref, i) => <li key={i}>{ref.owner} → {ref.kind} {ref.name} — {ref.present ? "Found in inventory" : "Not found in inventory"}</li>)}</ul>}
                <p><strong>{scopedReferences.length} references from selected primary resources</strong> · {missingReferences.length} missing inventory objects · {unselectedReferences.length} not included in draft.</p>
                {missingReferences.length > 0 && <p>Missing: {missingReferences.map((ref) => ref.kind + " " + ref.name).join(", ")}. Confirm collection coverage before proceeding.</p>}
                {unselectedReferences.length > 0 && <button type="button" className="button button-secondary" disabled={!canEdit || stale || save.isPending} onClick={includeReferencedDependencies}>Include {unselectedReferences.length} referenced dependencies in draft</button>}
                <p>Presence in inventory does not establish target readiness or complete discovery. All dependency additions require review.</p>
              </div>
            )}
            {resourceView === "DATA" && (
              <div className={styles.notice}>
                <strong>PVC consumer references</strong>
                {sourceReferences.filter((ref) => ref.kind === "PersistentVolumeClaim").length === 0 ? <p>No PVC consumer references in this snapshot. This does not prove there is no persistent data.</p> : <ul>{sourceReferences.filter((ref) => ref.kind === "PersistentVolumeClaim").map((ref, i) => <li key={i}>{ref.owner} → PVC {ref.name} — {ref.present ? "Claim inventoried" : "Claim missing from inventory"}</li>)}</ul>}
                <strong>Discovered PVC inventory · {relevantPvcs.length} claims</strong>
                <p>Review discovered storage in the selected namespace. Include only the claims required for this migration; proposed target values are not verified target capabilities.</p>
                <div className={styles.tableScroll} aria-label="Storage discovery and mapping">
                  <table>
                    <thead><tr><th>Source PVC</th><th>Source</th><th>Ownership evidence</th><th>Include</th><th>Target class</th><th>Target capacity</th><th>Access mode</th><th>Review</th></tr></thead>
                    <tbody>{relevantPvcs.map((pvc) => {
                      const included = draft.resources.some((item) => item.kind === "PersistentVolumeClaim" && item.name === pvc.name && item.namespace === pvc.namespace);
                      const ownerEdges = graph.edges.filter((edge) => edge.to === JSON.stringify(["PersistentVolumeClaim", pvc.namespace ?? null, pvc.name]) && draft.resources.some((item) => !item.dependency && edge.from === JSON.stringify([item.kind, item.namespace, item.name])));
                      const saved = (draft.storageMappings ?? []).find((m) => m.namespace === pvc.namespace && m.sourceClaim === pvc.name);
                      const current = saved ?? suggestedMapping(pvc);
                      const disabled = !canEdit || stale || save.isPending;
                      return <tr key={pvc.namespace + "/" + pvc.name}>
                        <td><strong>{pvc.namespace}/{pvc.name}</strong></td>
                        <td>{typeof pvc.requestedStorage === "string" ? pvc.requestedStorage : "Unknown"} · {typeof pvc.storageClassName === "string" ? pvc.storageClassName : "Class unknown"}</td>
                        <td>{ownerEdges.length ? ownerEdges.some((edge) => edge.evidence === "INFERRED") ? "Inferred · review" : "Source reference · review" : "Not established"}</td>
                        <td><button type="button" className="button button-secondary" disabled={disabled} onClick={() => {
                          const key = resourceKey({apiVersion:pvc.apiVersion,kind:pvc.kind,namespace:pvc.namespace ?? null,name:pvc.name});
                          if (included) {
                            change({...draft,resources:draft.resources.filter((item) => resourceKey(item) !== key),
                              storageMappings:(draft.storageMappings ?? []).filter((m) => !(m.namespace === pvc.namespace && m.sourceClaim === pvc.name))});
                          } else {
                            change({...draft,resources:[...draft.resources,{
                              apiVersion:pvc.apiVersion,kind:pvc.kind,namespace:pvc.namespace ?? null,name:pvc.name,
                              treatment:recommendResource(pvc).resource.treatment,dependency:true,
                            }],storageMappings:[...(draft.storageMappings ?? []).filter((m) => !(m.namespace === pvc.namespace && m.sourceClaim === pvc.name)),current]});
                          }
                        }}>{included ? "Remove PVC" : "Include PVC"}</button></td>
                        <td><input aria-label={`Storage class for ${pvc.name}`} value={included ? current.targetStorageClass : ""} disabled={disabled || !included} onChange={(e) => updateStorageMapping(pvc.namespace!,pvc.name,{targetStorageClass:e.target.value,status:"PROPOSED"})} placeholder={included ? "Verify target" : "Select claim"} /></td>
                        <td><input aria-label={`Target capacity for ${pvc.name}`} value={included ? current.targetCapacity : ""} disabled={disabled || !included} onChange={(e) => updateStorageMapping(pvc.namespace!,pvc.name,{targetCapacity:e.target.value,status:"PROPOSED"})} placeholder={included ? "Required size" : "Select claim"} /></td>
                        <td><select aria-label={`Target access mode for ${pvc.name}`} value={included ? current.targetAccessMode : ""} disabled={disabled || !included} onChange={(e) => updateStorageMapping(pvc.namespace!,pvc.name,{targetAccessMode:e.target.value,status:"PROPOSED"})}>
                          <option value="">Select mode</option>{["ReadWriteOnce","ReadWriteMany","ReadOnlyMany","ReadWriteOncePod"].map((mode) => <option key={mode} value={mode}>{mode}</option>)}
                        </select></td>
                        <td><select aria-label={`Mapping status for ${pvc.name}`} value={included ? current.status : "PROPOSED"} disabled={disabled || !included || !current.targetStorageClass || !current.targetCapacity || !current.targetAccessMode} onChange={(e) => updateStorageMapping(pvc.namespace!,pvc.name,{status:e.target.value as "PROPOSED" | "REVIEWED"})}>
                          <option value="PROPOSED">Proposed</option><option value="REVIEWED">Reviewed (human)</option>
                        </select></td>
                      </tr>;
                    })}</tbody>
                  </table>
                </div>
                <p>{scopedStorageClaims.filter((pvc) => !namespace || pvc.namespace === namespace).length} in-scope PVCs · Target {targetPlatform}. Source capacity/access mode and target-class suggestions are editable, not verified against the target cluster.</p>
                <p>PVC metadata does not include volume data. Verify StorageClass, access mode, capacity, and approved transfer strategy. StatefulSet volume claim templates may not appear as explicit workload dependency references in historical inventory.</p>
              </div>
            )}
            {resourceView === "CONFIGURATION" && (
              <p className={styles.caption}>Configuration resources are metadata-only inventory; secrets and Helm values are not exported by this planning view. Artifact collection requires separate authorization.</p>
            )}
            <div className={styles.toolbar}>
              <button
                className="button button-secondary"
                disabled={
                  !canEdit || stale || save.isPending || !viewResources.length
                }
                onClick={() => {
                  const next = new Map(
                    draft.resources.map((r) => [resourceKey(r), r]),
                  );
                  for (const r of viewResources) {
                    const item: PlannedResource = {
                      apiVersion: r.apiVersion,
                      kind: r.kind,
                      namespace: r.namespace ?? null,
                      name: r.name,
                      treatment: recommendResource(r).resource.treatment,
                      dependency: false,
                    };
                    if (!next.has(resourceKey(item)))
                      next.set(resourceKey(item), item);
                  }
                  change({ ...draft, resources: [...next.values()] });
                }}
              >
                Select all filtered resources (manual override)
              </button>
              <button
                className="button button-secondary"
                disabled={
                  !canEdit || stale || save.isPending || !viewResources.length
                }
                onClick={() => {
                  const keys = new Set(
                    viewResources.map((r) =>
                      resourceKey({ ...r, namespace: r.namespace ?? null }),
                    ),
                  );
                  change({
                    ...draft,
                    resources: draft.resources.filter(
                      (r) => !keys.has(resourceKey(r)),
                    ),
                  });
                }}
              >
                Clear filtered selection
              </button>
              <span>
                {viewResources.length} resources shown · Dependencies require review
              </span>
            </div>
            <div className={styles.tableScroll}>
              <table>
                <thead>
                  <tr>
                    <th>Include</th>
                    <th>Name / kind</th>
                    <th>Namespace</th>
                    <th>Treatment</th>
                    <th>Navigan recommendation</th>
                    <th>Dependency</th>
                  </tr>
                </thead>
                <tbody>
                  {viewResources.map((r) => {
                    const key = resourceKey({
                      ...r,
                      namespace: r.namespace ?? null,
                    });
                    const chosen = selected.get(key);
                    return (
                      <tr key={key}>
                        <td>
                          <input
                            aria-label={`Include ${r.kind} ${r.namespace ?? "cluster"}/${r.name}`}
                            type="checkbox"
                            checked={Boolean(chosen)}
                            disabled={!canEdit || stale || save.isPending}
                            onChange={() => toggle(r)}
                          />
                        </td>
                        <td>
                          <strong>{r.name}</strong>
                          <small>{r.kind}</small>
                        </td>
                        <td>{r.namespace ?? "Cluster scoped"}</td>
                        <td>
                          {chosen ? (
                            <select
                              aria-label={`Treatment ${r.name}`}
                              value={chosen.treatment}
                              disabled={!canEdit || stale || save.isPending}
                              onChange={(e) =>
                                change({
                                  ...draft,
                                  resources: draft.resources.map((item) =>
                                    resourceKey(item) === key
                                      ? {
                                          ...item,
                                          treatment: e.target
                                            .value as PlannedResource["treatment"],
                                        }
                                      : item,
                                  ),
                                })
                              }
                            >
                              {[
                                "MIGRATE",
                                "RECREATE",
                                "REPLACE",
                                "RETIRE",
                                "REVIEW",
                              ]
                                .filter(
                                  (t) => r.kind !== "Node" || t !== "MIGRATE",
                                )
                                .map((t) => (
                                  <option key={t} value={t}>
                                    {t.toLowerCase()}
                                  </option>
                                ))}
                            </select>
                          ) : (
                            "Not selected"
                          )}
                        </td>
                        <td>
                          <strong>{recommendations.get(key)?.resource.treatment}</strong>
                          <small>{recommendations.get(key)?.reason}</small>
                          <small>Confidence: {recommendations.get(key)?.confidence} · {recommendations.get(key)?.classification.replaceAll("_", " ")}</small>
                        </td>
                        <td>
                          <input
                            aria-label={`Required dependency ${r.name}`}
                            type="checkbox"
                            checked={chosen?.dependency ?? false}
                            disabled={
                              !chosen || !canEdit || stale || save.isPending
                            }
                            onChange={(e) =>
                              change({
                                ...draft,
                                resources: draft.resources.map((item) =>
                                  resourceKey(item) === key
                                    ? { ...item, dependency: e.target.checked }
                                    : item,
                                ),
                              })
                            }
                          />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {viewResources.length === 0 && (
                <p className={styles.caption}>No matching resources.</p>
              )}
            </div>
            <p className={styles.caption}>
              Showing {viewResources.length} of {resources.length} inventoried
              resources. Historical Jobs and node agents need explicit treatment
              decisions.
            </p>
          </section>
          <aside className={styles.surface}>
            <section className={styles.notice} aria-label="Target capability evidence status">
              <strong>Target capability discovery · {targetCapability.status.toLowerCase()}</strong>
              <p>No verified, fresh, target-bound capability snapshot has been collected for this planning session. Storage-class recommendations cannot be approved using provider naming conventions alone.</p>
            </section>
            <section className={styles.notice} aria-label="Storage compatibility findings">
              <strong>Target storage compatibility · {storageCompatibility.length} checks</strong>
              {storageCompatibility.length ? <ul>{storageCompatibility.map((issue,index) => <li key={index}>{issue.type.replaceAll("_"," ")} — {issue.detail}</li>)}</ul> : <p>No scoped storage compatibility issues detected in available evidence. Target verification and approval remain separate.</p>}
            </section>
            <section className={styles.notice} aria-label="Scope readiness assessment">
              <strong>Scope readiness · {readiness.state === "INCOMPLETE" ? "Decisions outstanding" : "Manual validation required"}</strong>
              <p>{readiness.selectedWorkloads} primary resources selected · {readiness.confirmedDependencies} confirmed dependencies · {readiness.issues.length} open planning checks</p>
              {readiness.issues.length > 0 ? (
                <ul>{readiness.issues.map((issue, index) => <li key={index}><strong>{issue.type.replaceAll("_", " ")}</strong> — {issue.detail}</li>)}</ul>
              ) : <p>No outstanding checks detected in collected evidence. This is not target readiness or migration approval.</p>}
              {unselectedDependencyResources.length > 0 && (
                <button type="button" className="button button-secondary" disabled={!canEdit || stale || save.isPending} onClick={includeReferencedDependencies}>
                  Add {unselectedDependencyResources.length} inventoried dependencies to draft
                </button>
              )}
            </section>
            <div className={styles.intelligencePanel}>
              <h2>Navigan analysis</h2>
              <p className={styles.caption}>{namespace || "All assessed namespaces"} · {filtered.length} inventoried resources in view</p>
              <p>{draft.resources.length - dependencies} already selected resources · {dependencies} confirmed dependencies in draft.</p>
              <p>{pendingRecommendations.length} additional workload candidates · {recommendedDependencyCount} additional referenced dependencies available.</p>
              <p className={styles.caption}>{reviewRecommendations} inventoried resources classified for manual review; {managedRecommendations} are platform-managed or generated. Zero additional suggestions does not mean discovery is complete. Only inventoried dependency references are included. Recommendations do not establish complete target readiness.</p>
              <button
                className="button button-primary"
                disabled={!canEdit || stale || save.isPending || (recommendedScopeAdditions.length === 0 && draft.resources.length === 0)}
                onClick={() => {
                  if (recommendedScopeAdditions.length > 0) {
                    change({ ...draft, resources: [...draft.resources, ...recommendedScopeAdditions] });
                    setMessage("Recommended resources added to the planning draft. Review storage and data strategy, then save.");
                  } else {
                    setScopeReviewOpen((open) => !open);
                  }
                }}
              >
                {recommendedScopeAdditions.length > 0
                  ? `Add ${recommendedScopeAdditions.length} recommended resource${recommendedScopeAdditions.length === 1 ? "" : "s"} to draft`
                  : scopeReviewOpen ? "Hide scope review" : "Review selected scope"}
              </button>
              <p className={styles.caption}>Confirms planning selections only. Inspect the table and data strategy before saving; no resources are migrated.</p>
            </div>
            {scopeReviewOpen && (
              <section className={styles.scopeReview} aria-label="Selected migration scope review">
                <h2>Selected migration scope review</h2>
                <p className={styles.caption}>{draft.resources.length} selected resources · {dependencies} confirmed dependencies · assessment v{assessment.assessmentVersion}</p>
                <ul>
                  {draft.resources.map((resource) => (
                    <li key={resourceKey(resource)}>
                      <strong>{resource.name}</strong>
                      <span>{resource.namespace || "Cluster-scoped"} · {resource.kind} · {resource.dependency ? "Dependency" : "Workload/resource"} · {resource.treatment}</span>
                    </li>
                  ))}
                </ul>
                <p><strong>Data migration:</strong> {draft.dataStrategy === "UNDECIDED" ? "Decision required" : draft.dataStrategy.replaceAll("_", " ")}</p>
                <p className={styles.caption}>This is a draft review, not a target-readiness approval. Check missing dependencies and PVC data migration before proceeding.</p>
              </section>
            )}
            <h2>Scope summary</h2>
            <div className={styles.summaryItem}>
              <Boxes size={22} />
              <div>
                <strong>
                  {draft.resources.length - dependencies} selected resources
                </strong>
                <small>Explicitly selected by you</small>
              </div>
            </div>
            <div className={styles.summaryItem}>
              <ClipboardCheck size={22} />
              <div>
                <strong>{dependencies} confirmed dependencies</strong>
                <small>Manual confirmation; discovery is not complete</small>
              </div>
            </div>
            <div className={styles.summaryItem}>
              <Database size={22} />
              <div>
                <strong>Storage dependencies</strong>
                <small>{pendingPvcs.length} PVC manifest{pendingPvcs.length === 1 ? "" : "s"} in the current inventory scope. Data content is not included in inventory.</small>
              </div>
            </div>
            <div className={styles.summaryItem}>
              <Database size={22} />
              <div>
                <strong>Data migration</strong>
                <label>
                  Strategy
                  <select
                    aria-label="Data strategy"
                    value={draft.dataStrategy}
                    disabled={!canEdit || stale || save.isPending}
                    onChange={(e) =>
                      change({
                        ...draft,
                        dataStrategy: e.target
                          .value as MigrationPlanningDraft["dataStrategy"],
                      })
                    }
                  >
                    {(
                      [
                        "UNDECIDED",
                        "BACKUP_RESTORE",
                        "REPLICATION",
                        "NO_PERSISTENT_DATA",
                      ] as const
                    ).map((s) => (
                      <option value={s} key={s}>
                        {s.replaceAll("_", " ").toLowerCase()}
                      </option>
                    ))}
                  </select>
                </label>
                <small>A choice records intent; it does not move data.</small>
              </div>
            </div>
            <div className={styles.summaryItem}>
              <ShieldCheck size={22} />
              <div>
                <strong>Source remains unchanged</strong>
                <small>No workload, data, or traffic changes</small>
              </div>
            </div>
            <div className={styles.summaryItem}>
              <LockKeyhole size={22} />
              <div>
                <strong>Execution not enabled</strong>
                <small>Separate plan approval and cutover gates required</small>
              </div>
            </div>
            {draft.mode === "FULL_CLUSTER" && (
              <p className={styles.warning}>
                {unaccounted} resources need a treatment decision. Inventory
                coverage is not yet certified for full-cluster migration.
              </p>
            )}
          </aside>
        </div>
      )}
      {tab === "remediate" && (
        <section className={styles.surface}>
          <section className={styles.notice} aria-label="Remediation overview">
            <strong>Migration remediation workspace</strong>
            <div className={styles.guideStats}>
              <span><strong>{draft.resources.length}</strong> scoped resources</span>
              <span><strong>{findings.length}</strong> assessment findings</span>
              <span><strong>{readiness.issues.length}</strong> planning checks</span>
              <span><strong>{storageCompatibility.length}</strong> storage compatibility findings</span>
            </div>
            <p>Choose recommended treatments, adjust target mappings, assign owners and save the plan. No changes are made to source or target infrastructure.</p>
            {draft.resources.length === 0 && <p>Select application workloads in Scope &amp; target to populate relevant findings.</p>}
          </section>
          <nav className={styles.scopeViews} aria-label="Remediation workspace views">
            <button aria-current={remediationView === "FIXES" ? "page" : undefined} onClick={() => setRemediationView("FIXES")}>Recommended fixes · {findings.length}</button>
            <button aria-current={remediationView === "MAPPINGS" ? "page" : undefined} onClick={() => setRemediationView("MAPPINGS")}>Target mappings · {scopedStorageClaims.length}</button>
            <button aria-current={remediationView === "PLAN" ? "page" : undefined} onClick={() => setRemediationView("PLAN")}>Remediation plan · {draft.remediations.length}</button>
          </nav>
          {remediationView === "MAPPINGS" && (
            <section className={styles.applicationMap} aria-label="Target mapping workspace">
              <div className={styles.applicationMapHeader}>
                <div><strong>Source-to-target storage mappings</strong><p>Review selected persistent data claims and configure proposed target settings.</p></div>
                <span>{targetPlatform} · Target capabilities {targetCapability.status.toLowerCase()}</span>
              </div>
              {scopedStorageClaims.length === 0 ? <p>No PVCs are selected. Include storage claims in Scope &amp; target to configure storage mappings.</p> :
                <div className={styles.applicationCards}>
                  {scopedStorageClaims.map((pvc) => {
                    const source = suggestedMapping(pvc);
                    const current = (draft.storageMappings ?? []).find((item) => item.namespace === pvc.namespace && item.sourceClaim === pvc.name) ?? source;
                    return <div className={styles.applicationCard} key={pvc.namespace + "/" + pvc.name}>
                      <div className={styles.applicationCardTitle}>
                        <strong>{pvc.name}</strong><span>{pvc.namespace} · PVC</span>
                      </div>
                      <p className={styles.caption}>Source · {typeof pvc.requestedStorage === "string" ? pvc.requestedStorage : "Unknown capacity"} · {typeof pvc.storageClassName === "string" ? pvc.storageClassName : "Unknown class"}</p>
                      <label>Target StorageClass
                        <input aria-label={`Target class for ${pvc.name}`} value={current.targetStorageClass} disabled={!canEdit || stale || save.isPending}
                          onChange={(e) => updateStorageMapping(pvc.namespace ?? "",pvc.name,{targetStorageClass:e.target.value,status:"PROPOSED"})}/>
                      </label>
                      <label>Target capacity
                        <input aria-label={`Target capacity for ${pvc.name}`} value={current.targetCapacity} disabled={!canEdit || stale || save.isPending}
                          onChange={(e) => updateStorageMapping(pvc.namespace ?? "",pvc.name,{targetCapacity:e.target.value,status:"PROPOSED"})}/>
                      </label>
                      <label>Target access mode
                        <select aria-label={`Target access mode for ${pvc.name}`} value={current.targetAccessMode} disabled={!canEdit || stale || save.isPending}
                          onChange={(e) => updateStorageMapping(pvc.namespace ?? "",pvc.name,{targetAccessMode:e.target.value,status:"PROPOSED"})}>
                          <option value="">Select mode</option>
                          <option value="ReadWriteOnce">ReadWriteOnce</option><option value="ReadWriteMany">ReadWriteMany</option><option value="ReadOnlyMany">ReadOnlyMany</option><option value="ReadWriteOncePod">ReadWriteOncePod</option>
                        </select>
                      </label>
                      <p className={styles.caption}>Proposed only. Target class and access mode support must be independently verified.</p>
                    </div>;
                  })}
                </div>}
            </section>
          )}
          {remediationView === "PLAN" && (
            <section className={styles.applicationMap} aria-label="Consolidated remediation plan">
              <div className={styles.applicationMapHeader}><div><strong>Remediation decision register</strong><p>Decisions recorded in this migration draft. Evidence references do not mean verified remediation.</p></div><span>{draft.remediations.length} recorded decisions</span></div>
              {draft.remediations.length === 0 ? <p>No remediation decisions yet. Open Recommended fixes to accept or customize a recommendation.</p> :
                <div className={styles.tableScroll}><table><thead><tr><th>Finding</th><th>Treatment</th><th>Owner</th><th>Target mapping</th><th>Evidence</th><th>Action</th></tr></thead><tbody>
                {draft.remediations.map((item) => <tr key={item.findingIndex}>
                  <td>{assessment.findings[item.findingIndex]?.code ?? "Unknown finding"}</td>
                  <td>{item.treatment}</td><td>{item.owner || "Needs owner"}</td><td>{item.targetMapping || "Needs mapping"}</td><td>{item.evidenceReference ? "Attached · unverified" : "Pending"}</td>
                  <td><button className="button button-secondary" onClick={() => {setFindingView("ALL");setRemediationCategory("ALL");setSeverity("ALL");setNamespace("");setFindingIndex(item.findingIndex);setRemediationView("FIXES");}}>Edit decision</button></td>
                </tr>)}
                </tbody></table></div>}
              <p>{readiness.issues.length} planning checks and {storageCompatibility.length} storage compatibility findings remain subject to validation.</p>
            </section>
          )}
          {remediationView === "FIXES" && (<>
          <details className={styles.notice} aria-label="Planning readiness issues for remediation">
            <summary><strong>Review {readiness.issues.length} outstanding migration intelligence checks</strong></summary>
            {readiness.issues.length === 0 ? <p>No detected scope gaps; independent target validation is still required.</p> :
              <ul>{readiness.issues.map((issue,index) => <li key={index}>{issue.type.replaceAll("_"," ")} — {issue.detail}</li>)}</ul>}
          </details>
          <details className={styles.notice} aria-label="Storage compatibility issues for remediation">
            <summary><strong>Review {storageCompatibility.length} target storage checks</strong></summary>
            {storageCompatibility.length > 0 && <ul>{storageCompatibility.map((issue,index) => <li key={index}>{issue.detail}</li>)}</ul>}
            <p>Target StorageClass recommendations remain unverified until trusted capability evidence is collected.</p>
          </details>
          <div className={styles.toolbar}>
            <label>
              Findings view
              <select aria-label="Findings view" value={findingView} onChange={(e) => setFindingView(e.target.value as "SCOPE" | "SHARED" | "ALL")}>
                <option value="SCOPE">Selected migration scope</option>
                <option value="SHARED">Shared and unassigned risks</option>
                <option value="ALL">All assessment findings</option>
              </select>
            </label>
            <label>
              Namespace
              <select aria-label="Remediation namespace" value={namespace} disabled={findingView === "SCOPE"} onChange={(e) => setNamespace(e.target.value)}>
                <option value="">All assessed namespaces</option>
                {namespaces.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            </label>
            <strong>{categorizedFindings.filter(({ finding }) => finding.severity === "BLOCKER").length} assessment blockers in view · {readiness.issues.length} outstanding planning checks</strong>
            <span>
              {draft.remediations.filter((r) => r.evidenceReference).length}{" "}
              evidence references · verification pending
            </span>
            <label>
              Category
              <select aria-label="Finding category" value={remediationCategory} onChange={(e) => setRemediationCategory(e.target.value)}>
                {["ALL","Storage","Networking","Security","Configuration","Other"].map((item) => <option key={item} value={item}>{item === "ALL" ? "All categories" : item}</option>)}
              </select>
            </label>
            <label>
              Severity
              <select
                aria-label="Finding severity"
                value={severity}
                onChange={(e) => setSeverity(e.target.value)}
              >
                <option value="ALL">All findings</option>
                <option value="BLOCKER">Blockers</option>
                <option value="WARNING">Warnings</option>
                <option value="INFO">Information</option>
              </select>
            </label>
          </div>
          <p className={styles.caption}>
            {categorizedFindings.length} findings shown · {draft.resources.length} resources in draft · {scopedNamespaces.size} selected namespace(s).
            {findingView === "SCOPE" ? " Only findings for exact selected resources are shown. No findings does not imply readiness; dependencies may be incomplete." : " Full assessment evidence is preserved; filtering does not resolve findings."}
          </p>
          <section className={styles.notice} aria-label="Remediation decision coverage">
            <strong>Remediation decision coverage</strong>
            <div className={styles.guideStats}>
              <span><strong>{findings.length}</strong> findings</span>
              <span><strong>{findings.filter(({index}) => remediationDecisionChecks(draft.remediations.find((r) => r.findingIndex === index)).treatment).length}</strong> treatments selected</span>
              <span><strong>{findings.filter(({index}) => {
                const checks = remediationDecisionChecks(draft.remediations.find((r) => r.findingIndex === index));
                return checks.treatment && checks.owner && checks.mapping && checks.evidence;
              }).length}</strong> fully documented</span>
              <span><strong>{readiness.issues.length}</strong> outstanding scope checks</span>
            </div>
            <p>{remediationGroups.map((group) => group.category + ": " + group.items.length).join(" · ") || "No findings in selected filters"}. Documentation is not independent verification.</p>
          </section>
          <div className={styles.toolbar} aria-label="Remediation bulk actions">
            <label><input type="checkbox" aria-label="Select all visible remediation findings"
              checked={categorizedFindings.length > 0 && categorizedFindings.every(({index}) => selectedFindingIds.includes(index))}
              onChange={(event) => setSelectedFindingIds(event.target.checked ? Array.from(new Set([...selectedFindingIds,...categorizedFindings.map(({index}) => index)])) : selectedFindingIds.filter(index => !categorizedFindings.some(item => item.index === index)))} />
              Select visible findings
            </label>
            <span>{categorizedFindings.filter(({index}) => selectedFindingIds.includes(index)).length} selected</span>
            <button className="button button-primary" disabled={!canEdit || stale || save.isPending || !categorizedFindings.some(({index}) => selectedFindingIds.includes(index))}
              onClick={acceptSelectedRecommendations}>Accept selected recommendations</button>
            <span className={styles.caption}>Only specific, non-Review recommendations are added to the planning draft; existing decisions are preserved.</span>
          </div>
          <div className={styles.remediationColumns}>
            <div className={styles.remediationFindingList} aria-label="Remediation findings list">
              <div className={styles.findingListHeader}><strong>Findings &amp; recommendations</strong><span>{categorizedFindings.length} in view</span></div>
              {categorizedFindings.length === 0 && <p className={styles.caption}>No findings match these filters.</p>}
              {categorizedFindings.map(({finding:f,index}) => {
                const item=draft.remediations.find(r=>r.findingIndex===index);
                const checks=remediationDecisionChecks(item);
                const progress=[checks.treatment,checks.owner,checks.mapping,checks.evidence].filter(Boolean).length;
                return <div key={index} className={index===activeFindingIndex ? styles.remediationFindingActive : styles.remediationFinding}>
                  <input aria-label={`Select finding ${index}`} type="checkbox" checked={selectedFindingIds.includes(index)}
                    onChange={(e)=>setSelectedFindingIds(e.target.checked?[...selectedFindingIds,index]:selectedFindingIds.filter(id=>id!==index))}/>
                  <button className={styles.remediationFindingButton} onClick={()=>setFindingIndex(index)}>
                    <span className={styles.findingListMeta}><strong>{f.severity}</strong> · {findingCategory(f.category)} · {f.resourceName??"Assessment-wide"}</span>
                    <span>{f.message}</span>
                    <span className={styles.findingListMeta}>{item?.treatment??"Review required"} · {progress}/4 decision fields · {item?.evidenceReference?"Evidence attached, unverified":"Evidence pending"}</span>
                  </button>
                </div>;
              })}
            </div>
            <aside className={styles.detail}>
              {finding ? (
                <>
                  <div className={styles.recommendationHeader} aria-live="polite">
                    <div><strong>Guided recommendation</strong><span>Rule-based · {finding.severity} · {findingCategory(finding.category)}</span></div>
                    <span>{acceptedSuggestion ? "Decision in draft" : "Decision required"}</span>
                  </div>
                  <div className={styles.recommendationProblem}>
                    <strong>{finding.code.replaceAll("_"," ").toLowerCase().replace(/^./,letter=>letter.toUpperCase())}</strong>
                    <p>{finding.message}</p>
                    <small>{finding.namespace ?? "Cluster"} / {finding.resourceKind ?? finding.category} / {finding.resourceName ?? "Shared resource"}</small>
                  </div>
                  <section className={styles.mappingComparison} aria-label="Source to target remediation comparison">
                    <div><span>Detected source issue</span><p>{finding.message}</p></div>
                    <div><span>Recommended treatment · {suggestedRemediation?.treatment ?? "REVIEW"}</span><p>{suggestedRemediation?.targetMapping || "Manual review required; no specific mapping can be verified."}</p></div>
                    <div><span>Target evidence · {targetPlatform}</span><p>{targetCapability.status === "CURRENT" ? "Capability snapshot available; validate finding-specific compatibility" : "Target configuration not verified"}</p></div>
                  </section>
                  <div className={styles.recommendationActions}>
                    <button className="button button-primary" disabled={!canEdit || stale || save.isPending || !suggestedRemediation || acceptedSuggestion || suggestedRemediation.treatment === "REVIEW"}
                      onClick={() => {if(suggestedRemediation)changeRemediation(suggestedRemediation);}}>
                      {acceptedSuggestion ? "Recommendation in draft" : "Accept recommendation"}
                    </button>
                    <button className="button button-secondary" disabled={!canEdit || stale || save.isPending} onClick={() => changeRemediation({status:"PLANNED",treatment:"REVIEW"})}>Defer for review</button>
                  </div>
                  <details className={styles.notice} aria-label="Selected remediation completion criteria">
                    <summary><strong>Decision completion · {[...Object.values(remediationDecisionChecks(acceptedSuggestion ? remediation : undefined))].filter(Boolean).length}/4</strong></summary>
                    <ul><li>Treatment {remediationDecisionChecks(acceptedSuggestion ? remediation : undefined).treatment ? "recorded" : "pending"}</li><li>Owner {remediation.owner ? "recorded" : "pending"}</li><li>Target mapping {remediation.targetMapping ? "recorded" : "pending"}</li><li>Evidence {remediation.evidenceReference ? "attached, unverified" : "pending"}</li></ul>
                  </details>
                  <fieldset
                    className={styles.fields}
                    disabled={!canEdit || stale || save.isPending}
                  >
                    <p className={styles.caption}>
                      Draft fields may remain incomplete. Evidence reference is
                      required when Work status is Evidence attached.
                    </p>
                    <label>
                      Treatment
                      <select
                        value={remediation.treatment}
                        onChange={(e) =>
                          changeRemediation({
                            treatment: e.target
                              .value as RemediationDraft["treatment"],
                          })
                        }
                      >
                        {[
                          "REVIEW",
                          "RECONFIGURE",
                          "RECREATE",
                          "REPLACE",
                          "RETIRE",
                        ].map((t) => (
                          <option value={t} key={t}>
                            {t.toLowerCase()}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Owner
                      <input
                        value={remediation.owner}
                        maxLength={150}
                        onChange={(e) =>
                          changeRemediation({ owner: e.target.value })
                        }
                        placeholder="Optional: person or team responsible"
                      />
                    </label>
                    <label>
                      Target mapping
                      <textarea
                        value={remediation.targetMapping}
                        maxLength={1000}
                        rows={3}
                        onChange={(e) =>
                          changeRemediation({ targetMapping: e.target.value })
                        }
                        placeholder="Optional: proposed EKS storage, ingress, identity or replacement mapping"
                      />
                    </label>
                    <label>
                      Evidence reference
                      <input
                        value={remediation.evidenceReference}
                        maxLength={1000}
                        onChange={(e) =>
                          changeRemediation({
                            evidenceReference: e.target.value,
                          })
                        }
                        placeholder="Required for Evidence attached: artifact ID or report reference"
                      />
                    </label>
                    <label>
                      Work status
                      <select
                        value={remediation.status}
                        onChange={(e) =>
                          changeRemediation({
                            status: e.target
                              .value as RemediationDraft["status"],
                          })
                        }
                      >
                        <option value="PLANNED">Planned</option>
                        <option value="IN_PROGRESS">In progress</option>
                        <option value="EVIDENCE_ATTACHED">
                          Evidence attached
                        </option>
                      </select>
                    </label>
                  </fieldset>
                  <p className={styles.notice}>
                    Evidence attachment is not verification. Target preparation
                    requires a separate authorized action.
                  </p>
                  <div className={styles.detailActions}>
                    <button className="button button-secondary" disabled={!canEdit || stale || !dirty || save.isPending}
                      onClick={() => save.mutate()}>
                      {save.isPending ? "Saving…" : "Save remediation decision"}
                    </button>
                    <span className={styles.caption}>Saves the entire planning draft, including this decision. No cluster changes.</span>
                  </div>
                </>
              ) : (
                <p>No findings match the selected namespace and severity.</p>
              )}
            </aside>
          </div>
          </>)}
        </section>
      )}
      {tab === "review" && (
        <section className={styles.surface}>
          <h2>Draft readiness</h2>
          <div className={styles.context}>
            <div>
              <span>Migration mode</span>
              <strong>{draft.mode.replaceAll("_", " ")}</strong>
            </div>
            <div>
              <span>Resources / dependencies</span>
              <strong>
                {draft.resources.length} / {dependencies}
              </strong>
            </div>
            <div>
              <span>Assessment evidence</span>
              <strong>
                {stale
                  ? "Changed; reload required"
                  : `Version ${draft.assessmentVersion}`}
              </strong>
            </div>
          </div>
          <div className={styles.reviewChecklist}>
            <strong>Planning readiness checks</strong>
            <p>{draft.resources.length === 0 ? "Action required: select at least one workload." : "Scope selected: review supporting dependencies before approval."}</p>
            <p>{uniqueSuggestions.length > 0 ? `Action required: ${uniqueSuggestions.length} explicit dependencies have not yet been included.` : "No unmatched explicit dependencies in the currently available inventory; discovery may still be incomplete."}</p>
            <p>{draft.resources.some((r) => r.treatment === "REVIEW") ? "Action required: one or more selected resources still need a treatment decision." : "No selected resources currently marked REVIEW."}</p>
            <p>{draft.dataStrategy === "UNDECIDED" ? "Action required: confirm the persistent-data strategy." : "Data strategy recorded; this does not move data."}</p>
            <p>{blockers} blockers in the full assessment remain unverified. Shared findings must be considered separately.</p>
            <p>No execution plan has been generated or approved. Saving records planning intent only.</p>
          </div>
          <label>
            Planning notes
            <textarea
              rows={3}
              maxLength={2000}
              value={draft.notes}
              disabled={!canEdit || stale || save.isPending}
              onChange={(e) => change({ ...draft, notes: e.target.value })}
            />
          </label>
          <p className={styles.notice}>
            Next: confirm dependencies and data consistency requirements,
            implement target verification, then generate a versioned execution
            plan with validation and rollback checkpoints.
          </p>
          <button
            disabled
            title="Execution engine and plan approval are not implemented"
          >
            Approve & execute migration
          </button>
        </section>
      )}
      <footer className={styles.footer}>
        <button
          className="button button-secondary"
          onClick={() => navigateToStep(tab === "review" ? "remediate" : "scope")}
          disabled={tab === "scope"}
        >
          <ArrowLeft size={16} />
          {tab === "scope" ? "Previous step" : tab === "remediate" ? "Back to scope" : "Back to remediation"}
        </button>
        <p>
          {save.isPending
            ? "Saving draft…"
            : message ||
              (dirty
                ? "Unsaved planning changes"
                : `Assessment v${assessment.assessmentVersion} · Draft only`)}
        </p>
        <button
          className="button button-secondary"
          disabled={!canEdit || stale || !dirty || save.isPending}
          onClick={() => save.mutate()}
        >
          {save.isPending ? "Saving…" : "Save draft"}
        </button>
        <button
          className="button button-primary"
          onClick={() => navigateToStep(tab === "scope" ? "remediate" : "review")}
          disabled={tab === "review"}
        >
          {tab === "scope" ? "Continue to remediation" : "Continue to review draft"}
          <ArrowRight size={16} />
        </button>
      </footer>
    </div>
  );
}
