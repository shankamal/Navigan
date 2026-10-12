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
import { evaluateTargetCompatibility } from "./compatibility-intelligence";
import { inspectTargetCapabilitySnapshot } from "./target-capabilities";
import { recommendResource, recommendDependencies, recommendFinding, analyzeRemediationFinding } from "./planning-recommendations";
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
  const hasMigrationEditPermission = hasPermission(identity, "migration.edit");
  const editableMigrationStatus = [
    "ASSESSMENT_READY",
    "SUBMITTED",
    "UNDER_REVIEW",
    "APPROVED",
    "REJECTED",
  ].includes(migration.status);
  const canEdit = hasMigrationEditPermission && editableMigrationStatus;
  const editRestriction = !hasMigrationEditPermission
    ? "Your current account does not have the migration.edit permission. Ask your platform administrator to assign an editing role or privilege."
    : !editableMigrationStatus
      ? `Migration status ${migration.status} does not allow planning edits. Complete the required assessment or migration workflow first.`
      : null;
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
  const [scopeNamespaces, setScopeNamespaces] = useState<string[]>(() => {
    const requested = migration.migrationScope?.namespaces;
    return Array.isArray(requested) ? requested.filter((value): value is string => typeof value === "string") : [];
  });
  const scopeNamespaceKey = scopeNamespaces.slice().sort().join("|");
  const scopeNamespaceSet = new Set(scopeNamespaces);
  const [search, setSearch] = useState("");
  const [resourceView, setResourceView] = useState<"ALL" | "WORKLOADS" | "DEPENDENCIES" | "CONFIGURATION" | "DATA">("WORKLOADS");
  const [severity, setSeverity] = useState("ALL");
  const [remediationCategory, setRemediationCategory] = useState("ALL");
  const [remediationView, setRemediationView] = useState<"FIXES" | "MAPPINGS" | "PLAN">("FIXES");
  const [selectedFindingIds, setSelectedFindingIds] = useState<number[]>([]);
  const [customizeFinding, setCustomizeFinding] = useState(false);
  const [editingFromPlan, setEditingFromPlan] = useState<number | null>(null);
  const editFormRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (editingFromPlan !== null && remediationView === "FIXES") {
      editFormRef.current?.scrollIntoView?.({block:"center",behavior:"smooth"});
    }
  }, [editingFromPlan, remediationView]);
  const [findingView, setFindingView] = useState<"SCOPE" | "SHARED" | "ALL">("SCOPE");
  const [findingIndex, setFindingIndex] = useState(0);
  const [message, setMessage] = useState("");
  const [dirty, setDirty] = useState(false);
  const [scopeReviewOpen, setScopeReviewOpen] = useState(false);
  const [scopeAnalysisNamespace, setScopeAnalysisNamespace] = useState<string | null>(null);
  const [scopeAnalysisSignature, setScopeAnalysisSignature] = useState<string | null>(null);
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
  const targetCompatibility = evaluateTargetCompatibility({
    platform:targetPlatform,
    targetId:String(migration.targetConfiguration?.clusterId ?? ""),
    snapshot:null, // An authorized read-only adapter must provide this; never substitute inferred capabilities.
    requirements:[],
    claims:scopedStorageClaims.map(pvc=>({namespace:pvc.namespace??null,name:pvc.name,requestedStorage:typeof pvc.requestedStorage==="string"?pvc.requestedStorage:null})),
    mappings:(draft.storageMappings??[]).length ? draft.storageMappings??[] : scopedStorageClaims.map(pvc=>suggestedMapping(pvc)),
  });
  const readiness = evaluateScopeReadiness(
    graph, draft.resources, draft.dataStrategy,
    resources.some((r) => r.kind === "PersistentVolumeClaim" && (draft.mode === "FULL_CLUSTER" || draft.resources.some((item) => item.namespace === r.namespace))),
    workloadRelationships.filter((entry) => entry.selected).reduce((count, entry) => count + entry.observedClaimCandidates.length, 0),
    scopedStorageClaims.map((r) => ({namespace: r.namespace ?? null, name: r.name!})),
    draft.storageMappings ?? [],
    storageCompatibility
  );
  // Scope-entry checks are distinct from remediation/final-readiness findings.
  const currentScopeSignature = JSON.stringify(draft.resources.filter(resource=>resource.namespace && scopeNamespaceSet.has(resource.namespace)).map(resourceKey).sort());
  const scopeGateIssues = [
    ...(!scopeNamespaces.length ? ["Select one or more namespaces for scope analysis."] : []),
    ...(scopeAnalysisNamespace !== scopeNamespaceKey || scopeAnalysisSignature !== currentScopeSignature ? ["Review selected scope after making resource selections."] : []),
    ...(!draft.resources.some(resource => !resource.dependency && ["Deployment","StatefulSet","DaemonSet","Job","CronJob"].includes(resource.kind) && resource.namespace && scopeNamespaceSet.has(resource.namespace)) ? ["Select at least one workload in the selected namespaces."] : []),
    ...(stale ? ["The assessment changed. Refresh the planning draft before continuing."] : []),
  ];
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
  const recommendationIntelligence = activeFindingIndex >= 0 ? analyzeRemediationFinding(assessment,activeFindingIndex,targetPlatform) : null;
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
  function navigateFinding(direction: 1 | -1) {
    if (!categorizedFindings.length) return;
    const position = categorizedFindings.findIndex(({index}) => index === activeFindingIndex);
    const nextPosition = (position + direction + categorizedFindings.length) % categorizedFindings.length;
    setFindingIndex(categorizedFindings[nextPosition].index);
    setCustomizeFinding(false);
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
      {tab !== "remediate" && <section className={styles.guide} aria-label="Migration planning guide">
        <div className={styles.guideHeading}>
          <strong>{tab === "scope" ? "1 · Define application scope" : "3 · Review planning readiness"}</strong>
          <span>Assessment v{assessment.assessmentVersion} · Read-only planning</span>
        </div>
        <p>{tab === "scope"
          ? "Choose candidate workloads, verify dependencies and review the migration action for each resource. The selected resources become the working migration scope."
          : "Check scope completeness, planned remediation, unresolved risks and data strategy before saving the draft."}</p>
        <div className={styles.guideStats}>
          <span><strong>{draft.resources.length}</strong> resources selected</span>
          <span><strong>{dependencies}</strong> confirmed dependencies</span>
          <span><strong>{draft.remediations.length}</strong> remediation decisions</span>
          <span><strong>{draft.dataStrategy === "UNDECIDED" ? "Pending" : "Chosen"}</strong> data strategy</span>
        </div>
      </section>}
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
          Read-only planning view. {editRestriction}
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
                  onChange={(e) => {const next=e.target.value;setNamespace(next);if(next)setScopeNamespaces(current=>current.includes(next)?current:[...current,next]);setScopeReviewOpen(false);setScopeAnalysisNamespace(null);}}
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
              <details className={styles.scopeNamespacePicker}>
                <summary>Analyze namespaces ({scopeNamespaces.length})</summary>
                <div>{namespaces.map(item=><label key={item}>
                  <input type="checkbox" aria-label={`Analyze namespace ${item}`} checked={scopeNamespaceSet.has(item)}
                    onChange={event=>{setScopeNamespaces(current=>event.target.checked?[...new Set([...current,item])]:current.filter(name=>name!==item));setScopeReviewOpen(false);setScopeAnalysisNamespace(null);}} />{item}
                </label>)}</div>
              </details>
              <div className={styles.scopeFilterActions}>
              <button type="button" className="button button-secondary" aria-expanded={scopeReviewOpen}
                aria-controls="scope-selection-review" onClick={() => {setScopeAnalysisNamespace(scopeNamespaceKey);setScopeAnalysisSignature(currentScopeSignature);setScopeReviewOpen(open => !open);}}
                disabled={!scopeNamespaces.length || !canEdit || stale || save.isPending}>

                {scopeReviewOpen ? "Hide scope analysis" : "Review selected scope"}
              </button>
              </div>
            </div>
            {scopeReviewOpen && (
              <section id="scope-selection-review" className={styles.scopeReview} aria-label="Selected migration scope review">
                <div className={styles.scopeReviewHeading}>
                  <strong>Namespace analysis · {scopeNamespaces.join(", ")}</strong>
                  <span>{draft.resources.filter(resource => resource.namespace && scopeNamespaceSet.has(resource.namespace)).length} selected resources · Assessment v{assessment.assessmentVersion}</span>
                </div>
                <div className={styles.scopeReviewItems}>
                  {draft.resources.filter(resource => resource.namespace && scopeNamespaceSet.has(resource.namespace)).map(resource => (
                    <span key={resourceKey(resource)} title={`${resource.namespace || "Cluster"} / ${resource.kind} / ${resource.treatment}`}>
                      {resource.name} <small>{resource.kind}</small>
                    </span>
                  ))}
                </div>
                <p className={styles.scopeReviewData}>Suggested dependencies from observed references: {uniqueSuggestions.filter(item => item.resource.namespace && scopeNamespaceSet.has(item.resource.namespace)).length} · Reference coverage: {graph.coverage === "REFERENCES_AVAILABLE" ? "Collected" : "Unknown; reassessment required"}</p>
                <div className={styles.scopeIntelligence}>
                  <strong>Required resources from observed relationships</strong>
                  {unselectedDependencyResources.filter(item=>item.namespace && scopeNamespaceSet.has(item.namespace)).length>0 ?
                    unselectedDependencyResources.filter(item=>item.namespace && scopeNamespaceSet.has(item.namespace)).map(item=><p key={item.kind+item.name}>{item.kind} · {item.name} — referenced by a selected workload
                      <button type="button" className="button button-secondary" disabled={!canEdit || stale || save.isPending}
                        onClick={()=>{const proposal=recommendResource(item).resource;change({...draft,resources:[...draft.resources,{...proposal,dependency:true}]});}}>
                        Include dependency
                      </button></p>)
                    : <p>No additional referenced resources are evidenced. Missing reference coverage is not confirmation of completeness.</p>}
                  <p>Reassessment required: {graph.coverage === "REFERENCES_AVAILABLE" ? "No additional reference-coverage warning" : "This snapshot does not contain reliable dependency references."}</p>
                </div>
                <p className={styles.scopeReviewData}>Data strategy: <strong>{draft.dataStrategy === "UNDECIDED" ? "Decision required" : draft.dataStrategy.replaceAll("_", " ")}</strong></p>
              </section>
            )}
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
            <div className={styles.scopeInstructions} aria-live="polite">
              <strong>What to do now</strong>
              <p>{resourceView === "WORKLOADS" ? "Select application workloads, then analyze the namespace to identify evidenced dependencies." : resourceView === "DEPENDENCIES" ? "Confirm required supporting resources and investigate missing or unknown references." : resourceView === "CONFIGURATION" ? "Review application settings, access controls and secrets references without exposing secret values." : resourceView === "DATA" ? "Include the required PVCs, check proposed target mappings and select a data migration strategy." : "Advanced review: verify selected resources and the proposed migration action for each."}</p>
            </div>
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
                {graph.coverage !== "REFERENCES_AVAILABLE" && <p className={styles.scopeCoverageWarning}>Relationship evidence was not collected. Run a fresh dependency-aware source assessment before claiming scope completeness.</p>}
                <div className={styles.workloadGraph} role="list" aria-label="Observed workload dependency relationships">
                  {workloadRelationships.filter(item=>item.selected || item.references.length>0).map(({workload,references,selected,observedClaimCandidates}) => (
                    <div className={styles.workloadGraphRow} role="listitem" key={resourceKey({...workload,namespace:workload.namespace??null})}>
                      <div className={styles.workloadGraphNode}>
                        <strong>{workload.name}</strong><small>{workload.kind} · {selected?"Selected":"Additional evidence"}</small>
                      </div>
                      <div className={styles.workloadGraphConnector} aria-hidden="true">{references.length || observedClaimCandidates.length ? "→" : "?"}</div>
                      <div className={styles.workloadGraphDependencies}>
                        {references.map((ref,index)=><div className={styles.workloadGraphDependency} key={index}>
                          <strong>{ref.name}</strong><small>{ref.kind} · {ref.present?"Found in source inventory":"Missing from inventory"}</small>
                        </div>)}
                        {observedClaimCandidates.map(pvc=><div className={styles.workloadGraphDependency} key={pvc.name}><strong>{pvc.name}</strong><small>PVC candidate · Ownership unverified</small></div>)}
                        {!references.length&&!observedClaimCandidates.length&&<span className={styles.caption}>No observed references in this assessment</span>}
                      </div>
                    </div>
                  ))}
                  {!applicationWorkloads.length && <p>No controllers discovered for this namespace.</p>}
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
            {resourceView === "DATA" && <div className={styles.dataStrategyEditor}>
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
            </div>}
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
                    <th>Migration action</th>
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
                              aria-label={`Migration action ${r.name}`}
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
            <p className={styles.caption}>Data strategy: <strong>{draft.dataStrategy==="UNDECIDED"?"Decision required":draft.dataStrategy.replaceAll("_"," ")}</strong></p>
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
            <div className={styles.scopeReadinessCompact} aria-label="Scope readiness assessment">
              <strong>Migration readiness · {readiness.issues.length} follow-up checks</strong>
              <p>{targetCapability.status === "CURRENT" ? "Target evidence available for evaluation." : "Target capabilities not verified."} Missing evidence stays open for remediation and final review.</p>
              <details><summary>Review compatibility and readiness details</summary>
                <ul>{readiness.issues.map((issue,index)=><li key={index}><strong>{issue.type.replaceAll("_"," ")}</strong> — {issue.detail}</li>)}</ul>
                <p>Storage checks: {storageCompatibility.length}. Target evidence: {targetCapability.status.toLowerCase()}.</p>
              </details>
            </div>
          </aside>
        </div>
      )}
      {tab === "remediate" && (
        <section className={styles.surface}>
          <section className={styles.remediationKpis} aria-label="Remediation overview">
            <div><strong>{draft.resources.length}</strong><span>Resources in scope</span></div>
            <div><strong>{findings.length}</strong><span>Assessment findings</span></div>
            <div><strong>{draft.remediations.length}</strong><span>Decisions recorded</span></div>
            <div><strong>{readiness.issues.length}</strong><span>Outstanding checks</span></div>
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
                      <div className={styles.mappingDecisionFooter}>
                        <span>{(draft.storageMappings ?? []).some(item => item.namespace === pvc.namespace && item.sourceClaim === pvc.name) ? "Mapping recorded in draft" : "Suggested values · not recorded"}</span>
                        <button className="button button-secondary" disabled={!canEdit || stale || save.isPending}
                          onClick={() => updateStorageMapping(pvc.namespace ?? "",pvc.name,{targetStorageClass:current.targetStorageClass,targetCapacity:current.targetCapacity,targetAccessMode:current.targetAccessMode,status:"PROPOSED"})}>
                          Add mapping to draft
                        </button>
                      </div>
                      <p className={styles.caption}>The target class and access-mode capabilities remain unverified. This action records a proposal only.</p>
                    </div>;
                  })}
                </div>}
            </section>
          )}
          {remediationView === "PLAN" && (
            <section className={styles.applicationMap} aria-label="Consolidated remediation plan">
              <div className={styles.applicationMapHeader}><div><strong>Remediation decision register</strong><p>Decisions recorded in this migration draft. Evidence references do not mean verified remediation.</p></div><span>{draft.remediations.length} recorded decisions</span></div>
              <div className={styles.remediationKpis}>
                <div><strong>{draft.remediations.filter(item => item.treatment !== "REVIEW").length}</strong><span>Actions selected</span></div>
                <div><strong>{draft.remediations.filter(item => !item.owner.trim()).length}</strong><span>Need an owner</span></div>
                <div><strong>{draft.remediations.filter(item => !item.targetMapping.trim()).length}</strong><span>Need target mapping</span></div>
                <div><strong>{draft.remediations.filter(item => !item.evidenceReference.trim()).length}</strong><span>Await evidence</span></div>
              </div>
              {draft.remediations.length === 0 ? <p>No remediation decisions yet. Open Recommended fixes to accept or customize a recommendation.</p> :
                <div className={styles.applicationCards}>
                {draft.remediations.map((item) => {
                  const decisionChecks = remediationDecisionChecks(item);
                  const complete = Object.values(decisionChecks).filter(Boolean).length;
                  return <article className={styles.applicationCard} key={item.findingIndex}>
                    <div className={styles.applicationCardTitle}><strong>{assessment.findings[item.findingIndex]?.code.replaceAll("_"," ") ?? "Unknown finding"}</strong>
                      <span>{assessment.findings[item.findingIndex]?.resourceName ?? "Assessment-wide"} · {item.treatment}</span></div>
                    <p><strong>{complete}/4</strong> decision fields documented · independent verification pending</p>
                    <p className={styles.caption}>Owner: {item.owner || "Assign owner"}</p>
                    <p className={styles.caption}>Mapping: {item.targetMapping || "Define target mapping"}</p>
                    <p className={styles.caption}>Evidence: {item.evidenceReference ? "Attached, not verified" : "Required"}</p>
                    <button className="button button-secondary" onClick={() => {setFindingView("ALL");setRemediationCategory("ALL");setSeverity("ALL");setNamespace("");setFindingIndex(item.findingIndex);setCustomizeFinding(true);setEditingFromPlan(item.findingIndex);setRemediationView("FIXES");}}>Edit decision</button>
                  </article>;
                })}
                </div>}
              <p>{readiness.issues.length} planning checks and {storageCompatibility.length} storage compatibility findings remain subject to validation.</p>
            </section>
          )}
          {remediationView === "FIXES" && (<>
          <p className={styles.remediationInfoLine}>Review findings, customize or record decisions, then save the draft. No changes are applied to infrastructure.</p>
          <div className={styles.remediationFilterBar} aria-label="Remediation filters">
            <label>Scope
              <select aria-label="Findings view" value={findingView} onChange={(e) => setFindingView(e.target.value as "SCOPE" | "SHARED" | "ALL")}>
                <option value="SCOPE">Selected resources</option>
                <option value="SHARED">Shared risks</option>
                <option value="ALL">Entire assessment</option>
              </select>
            </label>
            <label>Namespace
              <select aria-label="Remediation namespace" value={namespace} disabled={findingView === "SCOPE"} onChange={(e) => setNamespace(e.target.value)}>
                <option value="">All namespaces</option>
                {namespaces.map(item => <option key={item} value={item}>{item}</option>)}
              </select>
            </label>
            <label>Category
              <select aria-label="Finding category" value={remediationCategory} onChange={e => setRemediationCategory(e.target.value)}>
                {["ALL","Storage","Networking","Security","Configuration","Other"].map(item => <option key={item} value={item}>{item === "ALL" ? "All categories" : item}</option>)}
              </select>
            </label>
            <label>Severity
              <select aria-label="Finding severity" value={severity} onChange={e => setSeverity(e.target.value)}>
                <option value="ALL">All severities</option><option value="BLOCKER">Blockers</option><option value="WARNING">Warnings</option><option value="INFO">Information</option>
              </select>
            </label>
            <span className={styles.remediationFilterCount}>{categorizedFindings.length} findings</span>
          </div>
          {categorizedFindings.some(({index}) => selectedFindingIds.includes(index)) && (
            <div className={styles.remediationBulkBar} aria-label="Remediation bulk actions">
              <strong>{categorizedFindings.filter(({index}) => selectedFindingIds.includes(index)).length} findings selected</strong>
              <button className="button button-secondary" disabled={!canEdit || stale || save.isPending}
                onClick={acceptSelectedRecommendations}>Accept eligible selections</button>
              <button className="button button-secondary" onClick={() => setSelectedFindingIds(ids => ids.filter(id => !categorizedFindings.some(item => item.index === id)))}>Clear selection</button>
              <span className={styles.caption}>Review-only findings are skipped. No infrastructure changes.</span>
            </div>
          )}
          <div className={styles.remediationColumns}>
            <div className={styles.remediationFindingList} aria-label="Remediation findings list">
              <div className={styles.findingListHeader}><strong>Findings &amp; recommendations</strong><span>{categorizedFindings.length} findings</span></div>
              <div className={styles.findingTableHead}><span></span><span>Severity</span><span>Finding / resource</span><span>Category</span><span>Decision</span><span>Recommended action</span></div>
              {categorizedFindings.length === 0 && <p className={styles.caption}>No findings match these filters.</p>}
              {categorizedFindings.map(({finding:f,index}) => {
                const item=draft.remediations.find(r=>r.findingIndex===index);
                const checks=remediationDecisionChecks(item);
                const progress=[checks.treatment,checks.owner,checks.mapping,checks.evidence].filter(Boolean).length;
                const recommendation=recommendFinding(assessment,index);
                return <div key={index} className={index===activeFindingIndex ? styles.remediationFindingActive : styles.remediationFinding}>
                  <input aria-label={`Select finding ${index}`} type="checkbox" checked={selectedFindingIds.includes(index)}
                    onChange={e=>setSelectedFindingIds(e.target.checked?[...selectedFindingIds,index]:selectedFindingIds.filter(id=>id!==index))}/>
                  <span className={styles.findingSeverity} data-severity={f.severity}>{f.severity}</span>
                  <button className={styles.remediationFindingButton} onClick={()=>{setFindingIndex(index);setCustomizeFinding(false);setEditingFromPlan(null);}}>
                    <strong>{f.message}</strong><small>{f.resourceName??"Assessment-wide"} · {f.resourceKind??findingCategory(f.category)}</small>
                  </button>
                  <span className={styles.findingCategory}>{findingCategory(f.category)}</span>
                  <span className={styles.findingProgress}><strong>{progress}/4</strong><span><i style={{width:`${progress*25}%`}} /></span></span>
                  <span className={styles.findingTreatment} data-review={recommendation?.treatment==="REVIEW"}>{item?.treatment??(recommendation?.treatment==="REVIEW"?"REVIEW NEEDED":recommendation?.treatment??"REVIEW")}</span>
                </div>;
              })}
            </div>
                        <aside className={styles.detail}>
              {finding ? (
                <>
                  {editingFromPlan === activeFindingIndex && <div className={styles.editDecisionBanner} role="status">
                    <div><strong>Editing recorded decision</strong><p>Update Migration Action, Owner, Target mapping, Evidence reference or Work status below. Then select <strong>Save remediation decision</strong> to persist changes.</p></div>
                    <button className="button button-secondary" onClick={() => {setEditingFromPlan(null);setRemediationView("PLAN");}}>Back to remediation plan</button>
                  </div>}
                  <div className={styles.recommendationProgress} aria-label="Finding decision navigation">
                    <span>Finding {categorizedFindings.findIndex(({index}) => index === activeFindingIndex) + 1} of {categorizedFindings.length}</span>
                    <div>
                      <button className="button button-secondary" disabled={categorizedFindings.length < 2} onClick={() => navigateFinding(-1)}>Previous finding</button>
                      <button className="button button-secondary" disabled={categorizedFindings.length < 2} onClick={() => navigateFinding(1)}>Next finding</button>
                    </div>
                  </div>
                  <div className={styles.recommendationHeader} aria-live="polite">
                    <div><strong>Guided recommendation</strong><span>Rule-based · {finding.severity} · {findingCategory(finding.category)}</span></div>
                    <span>{acceptedSuggestion ? "Decision in draft" : "Decision required"}</span>
                  </div>
                  <div className={styles.recommendationProblem}>
                    <strong>{finding.code.replaceAll("_"," ").toLowerCase().replace(/^./,letter=>letter.toUpperCase())}</strong>
                    <p>{finding.message}</p>
                    <small>{finding.namespace ?? "Cluster"} / {finding.resourceKind ?? finding.category} / {finding.resourceName ?? "Shared resource"}</small>
                  </div>
                  {recommendationIntelligence && <section className={styles.remediationExplanation} aria-label="Remediation intelligence explanation">
                    <strong>{recommendationIntelligence.title}</strong>
                    <p>{recommendationIntelligence.rationale}</p>
                    <details><summary>Required actions and verification</summary>
                      <strong>Proposed actions</strong>
                      <ol>{recommendationIntelligence.proposedActions.map((action,index)=><li key={index}>{action}</li>)}</ol>
                      <strong>Verification requirements</strong>
                      <ul>{recommendationIntelligence.verificationRequirements.map((requirement,index)=><li key={index}>{requirement}</li>)}</ul>
                    </details>
                    <small>Rule-based planning guidance · Human review required · No target compatibility implied</small>
                  </section>}
                  <section className={styles.mappingComparison} aria-label="Source to target remediation comparison">
                    <div><span>Detected source issue</span><p>{finding.message}</p></div>
                    <div><span>Recommended treatment · {suggestedRemediation?.treatment ?? "REVIEW"}</span><p>{suggestedRemediation?.targetMapping || "Manual review required; no specific mapping can be verified."}</p></div>
                    <div><span>Target evidence · {targetPlatform}</span><p>{targetCapability.status === "CURRENT" ? "Capability snapshot available; validate finding-specific compatibility" : "Target configuration not verified"}</p></div>
                  </section>
                  <div className={styles.recommendationActions}>
                    <button className="button button-primary" disabled={!canEdit || stale || save.isPending || !suggestedRemediation || acceptedSuggestion}
                      onClick={() => {if(suggestedRemediation) {changeRemediation(suggestedRemediation); if(suggestedRemediation.treatment === "REVIEW")setCustomizeFinding(true);}}}>
                      {acceptedSuggestion ? "Decision in draft" : suggestedRemediation?.treatment === "REVIEW" ? "Record for manual review" : "Accept recommendation"}
                    </button>
                    <button className="button button-secondary" disabled={!canEdit || stale || save.isPending}
                      onClick={() => setCustomizeFinding(value => !value)}>{customizeFinding ? "Hide customization" : "Customize recommendation"}</button>
                    <button className="button button-secondary" disabled={!canEdit || stale || save.isPending}
                      onClick={() => {changeRemediation({status:"PLANNED",treatment:"REVIEW",targetMapping:"Deferred for manual review; target mapping not approved."});setCustomizeFinding(false);}}>
                      Defer for review</button>
                  </div>
                  {suggestedRemediation?.treatment === "REVIEW" && !acceptedSuggestion && <p className={styles.caption}>This finding has no evidence-backed automatic fix. Record it for manual review, assign an owner and validate the target configuration before approval.</p>}
                  {acceptedSuggestion && <p className={styles.recommendationConfirmation} role="status">Decision recorded in the planning draft. Save draft to persist it; target configuration remains unverified.</p>}
                  <details className={styles.notice} aria-label="Selected remediation completion criteria">
                    <summary><strong>Decision completion · {[...Object.values(remediationDecisionChecks(acceptedSuggestion ? remediation : undefined))].filter(Boolean).length}/4</strong></summary>
                    <ul><li>Migration action {remediationDecisionChecks(acceptedSuggestion ? remediation : undefined).treatment ? "recorded" : "pending"}</li><li>Owner {remediation.owner ? "recorded" : "pending"}</li><li>Target mapping {remediation.targetMapping ? "recorded" : "pending"}</li><li>Evidence {remediation.evidenceReference ? "attached, unverified" : "pending"}</li></ul>
                  </details>
                  <div ref={editFormRef} />
                  <div className={styles.remediationFormHeading}><strong>Customize decision</strong><span>Change the proposal and record ownership or evidence</span></div>
                  {(customizeFinding || acceptedSuggestion) && <fieldset
                    className={styles.fields}
                    disabled={!canEdit || stale || save.isPending}
                  >

                    <div className={styles.remediationFormGrid}>
                    <label>
                      Migration action
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
                    </div>
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
                    <div className={styles.remediationFormGrid}>
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
                    </div>
                    <p className={styles.caption}>Evidence references are not independent verification.</p>
                  </fieldset>}
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
          <details className={styles.remediationEvidence} aria-label="Target compatibility intelligence">
            <summary>Target compatibility · {targetCompatibility.evidenceStatus.toLowerCase()} · {targetCompatibility.findings.length} evidence checks</summary>
            <p>Planning intelligence only. Target observations are not yet connected to this workspace.</p>
            {targetCompatibility.findings.map(item=><p key={item.id}><strong>{item.status} · {item.capability} · {item.resource}</strong> — {item.reason} {item.nextAction}</p>)}
          </details>
          <details className={styles.remediationEvidence} aria-label="Technical readiness evidence">
            <summary>Technical readiness evidence · {readiness.issues.length} planning checks · {storageCompatibility.length} storage checks</summary>
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
          </details>
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
      {tab==="scope" && scopeGateIssues.length>0 && <div className={styles.scopeGateNotice} role="status" aria-label="Required scope checks">
        <strong>Before remediation · {scopeGateIssues.length} checks outstanding</strong>
        <ul>{scopeGateIssues.map((issue,index)=><li key={index}>{issue}</li>)}</ul>
      </div>}
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
          disabled={tab === "review" || (tab === "scope" && scopeGateIssues.length > 0)}
          title={tab === "scope" && scopeGateIssues.length ? scopeGateIssues[0] : undefined}
        >
          {tab === "scope" ? "Continue to remediation" : "Continue to review draft"}
          <ArrowRight size={16} />
        </button>
      </footer>
    </div>
  );
}
