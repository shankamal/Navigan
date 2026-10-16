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
import { ScopeTopology } from "./scope-topology";
import { restorePlanningNamespaces, preparePlanningDraft } from "./planning-draft-scope";
import { saveAndContinueToTarget, confirmAndClearDraft } from "./planning-draft-actions";
import { evaluateScopeReadiness } from "./migration-readiness";
import { evaluateStorageCompatibility } from "./storage-validation";
import { evaluateTargetCompatibility } from "./compatibility-intelligence";
import { determineMigrationPath } from "./migration-path-decision";
import { analyzeP0Compatibility } from "./source-target-p0";
import { inspectTargetCapabilitySnapshot, targetCapabilityFromAssessment } from "./target-capabilities";
import { recommendResource, recommendDependencies, recommendFinding, analyzeRemediationFinding } from "./planning-recommendations";
import { migrations } from "./service";
import { buildRemediationHandoff } from "./remediation-handoff";
import { buildMigrationPlanPreview } from "./migration-plan-preview";
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
  const workflowSteps = ["scope", "target", "compatibility", "remediate", "plan", "review"] as const;
  type WorkflowStep = (typeof workflowSteps)[number];
  const [tab, setTab] = useState<WorkflowStep>("scope");
  const [targetEvidence, setTargetEvidence] = useState<import("./service").TargetAssessmentRecord | null>(null);
  const [schedulingReport, setSchedulingReport] = useState<import("./service").TargetCompatibilityResponse | null>(null);
  const [schedulingError, setSchedulingError] = useState("");
  const [targetLoading, setTargetLoading] = useState(false);
  const [targetRunning, setTargetRunning] = useState(false);
  const [targetError, setTargetError] = useState("");
  // Refresh stale or absent saved target evidence once per migration/target per page session.
  const autoTargetAttempted = useRef(new Set<string>());
  useEffect(() => {
    if (tab !== "target" && tab !== "compatibility") return;
    let active = true;
    const clusterId = String(migration.targetConfiguration?.clusterId ?? "");
    const key = [migration.migrationId, assessment.assessmentVersion, clusterId].join(":");
    const load = async () => {
      setTargetLoading(true);
      setTargetError("");
      try {
        const stored = await migrations.targetAssessment(migration.migrationId);
        if (!active) return;
        const evidence = stored.assessment;
        const matches = evidence?.targetClusterId === clusterId &&
          evidence.assessmentVersion === assessment.assessmentVersion;
        setTargetEvidence(matches ? evidence : null);
        const observedAt = evidence ? Date.parse(evidence.snapshot.observedAt) : NaN;
        const expiry = evidence?.snapshot.inventoryExpiresAt ?? null;
        const expiresAt = expiry ? Date.parse(expiry) : NaN;
        const staleEvidence = !Number.isFinite(observedAt) ||
          observedAt > Date.now() + 300000 ||
          (Number.isFinite(expiresAt)
            ? expiresAt <= Date.now()
            : Date.now() - observedAt > 60 * 60 * 1000);
        if (!canEdit || !clusterId ||
            String(migration.targetConfiguration?.platform ?? "").toUpperCase() !== "EKS" ||
            (matches && !staleEvidence) || autoTargetAttempted.current.has(key)) return;
        autoTargetAttempted.current.add(key);
        setTargetRunning(true);
        try {
          const refreshed = await migrations.analyzeTarget(migration.migrationId);
          if (active) setTargetEvidence(refreshed.assessment);
        } catch (error: unknown) {
          const api = normalizeApiError(error);
          if (active) setTargetError(`Automatic target refresh unavailable · ${api.code}: ${api.message}. Existing evidence remains reviewable; use Refresh target inventory to retry.`);
        } finally {
          if (active) setTargetRunning(false);
        }
      } catch (error: unknown) {
        const api = normalizeApiError(error);
        if (active) setTargetError(`Target evidence could not be loaded · ${api.code}: ${api.message}`);
      } finally {
        if (active) setTargetLoading(false);
      }
    };
    void load();
    return () => { active = false; };
  }, [tab, migration.migrationId, migration.targetConfiguration?.clusterId, migration.targetConfiguration?.platform, assessment.assessmentVersion, canEdit]);
  useEffect(() => {
    if (tab !== "compatibility" && tab !== "remediate" && tab !== "plan" && tab !== "review") return;
    let active = true;
    setSchedulingReport(null);
    setSchedulingError("");
    void migrations.targetCompatibility(migration.migrationId)
      .then(result => {
        if (active) setSchedulingReport(result);
      })
      .catch((error: unknown) => {
        const api = normalizeApiError(error);
        if (active) setSchedulingError(`Scheduling evidence unavailable · ${api.code}: ${api.message}`);
      });
    return () => { active = false; };
  }, [tab, migration.migrationId, assessment.assessmentVersion, migration.planningDraft, targetEvidence?.snapshot.sourceRevision, targetEvidence?.snapshot.observedAt, targetEvidence?.snapshot.inventoryExpiresAt]);

  async function runTargetAnalysis() {
    if (targetRunning) return;
    setTargetRunning(true); setTargetError("");
    try {
      const result = await migrations.analyzeTarget(migration.migrationId);
      setTargetEvidence(result.assessment);
    } catch (error: unknown) {
      const api = normalizeApiError(error);
      setTargetError(`Analyze Target failed · HTTP ${api.status || "network"} · ${api.code}: ${api.message}${api.correlationId ? ` · Request ID: ${api.correlationId}` : ""}`);
    } finally { setTargetRunning(false); }
  }

  const stepHeadingRef = useRef<HTMLDivElement>(null);
  function navigateToStep(next: WorkflowStep) {
    setTab(next);
    stepHeadingRef.current?.scrollIntoView?.({ block: "start", behavior: "instant" });
  }
  const { setLabel } = useWorkspacePage();
  useEffect(() => {
    const names: Record<WorkflowStep,string> = {scope:"Source discovery & scope",target:"Target discovery & readiness",compatibility:"Source-to-target compatibility",remediate:"Remediation",plan:"Migration planning",review:"Review & export"};
    setLabel(names[tab]);
    return () => setLabel("");
  },[tab,setLabel]);
  // Planning inherits the exact namespaces approved in the source assessment.
  // A multi-namespace source scope must not silently become an empty selection.
  // Keep saved draft resources intact; out-of-scope resources require review.
  const assessedNamespaces = Array.isArray(migration.migrationScope?.namespaces)
    ? migration.migrationScope.namespaces.filter((name): name is string => typeof name === "string" && name.length > 0)
    : [];
  const [scopeNamespaces, setScopeNamespaces] = useState<string[]>(() =>
    restorePlanningNamespaces(assessedNamespaces,
      migration.planningDraft?.schemaVersion === 1
        ? migration.planningDraft as unknown as MigrationPlanningDraft : null));
  const namespace = scopeNamespaces.length === 1 ? scopeNamespaces[0] : "";
  const [remediationNamespace, setNamespace] = useState("");
  const scopeNamespaceKey = scopeNamespaces.slice().sort().join("|");
  const scopeNamespaceSet = new Set(scopeNamespaces);
  const [search, setSearch] = useState("");
  const [resourceView, setResourceView] = useState<"ALL" | "WORKLOADS" | "DEPENDENCIES" | "CONFIGURATION" | "DATA">("DEPENDENCIES");
  const [severity, setSeverity] = useState("ALL");
  const [remediationCategory, setRemediationCategory] = useState("ALL");
  const [remediationView, setRemediationView] = useState<"FIXES" | "MAPPINGS" | "PLAN" | "ARTIFACTS">("FIXES");
  const [remediationWorkload, setRemediationWorkload] = useState("ALL");
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
      resources.map((r) => r.namespace).filter((n): n is string => typeof n === "string" && n.length > 0 && assessedNamespaces.includes(n)),
    ),
  ].sort();
  const filtered = resources.filter(
    (r) =>
      (draft.mode === "FULL_CLUSTER" || (r.namespace && scopeNamespaceSet.has(r.namespace))) &&
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
  const analyzedInventory = resources.filter(r=>r.namespace && scopeNamespaceSet.has(r.namespace));
  const analyzedWorkloadCandidates = analyzedInventory.filter(r=>["Deployment","StatefulSet","DaemonSet","CronJob","Job"].includes(r.kind));
  const pendingAnalyzedWorkloads = analyzedWorkloadCandidates.filter(r=>!selected.has(resourceKey({...r,namespace:r.namespace??null})));
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
    (draft.mode === "FULL_CLUSTER" || (r.namespace && scopeNamespaceSet.has(r.namespace))));

  const graph = graphFromSanitizedInventory(resources);
  const sourceReferences = graph.edges
    .filter((edge) => {
      const owner = graph.nodes.find((node) => node.id === edge.from);
      return owner && (draft.mode === "FULL_CLUSTER" || (owner.namespace && scopeNamespaceSet.has(owner.namespace)));
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

  const relevantPvcs = resources.filter((r) => r.kind === "PersistentVolumeClaim" && (draft.mode === "FULL_CLUSTER" || (r.namespace && scopeNamespaceSet.has(r.namespace))));
  const applicationWorkloads = resources.filter((r) =>
    ["Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"].includes(r.kind) &&
    (draft.mode === "FULL_CLUSTER" || (r.namespace && scopeNamespaceSet.has(r.namespace)))
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
  // Only current, target-bound connector evidence may enter the evaluator.
  // An observed class is not proof of PVC access-mode compatibility.
  const targetClusterId = String(migration.targetConfiguration?.clusterId ?? "");
  const capabilitySnapshot = targetCapabilityFromAssessment(
    targetEvidence, targetPlatform, targetClusterId, assessment.assessmentVersion,
  );
  const targetCapability = inspectTargetCapabilitySnapshot(
    capabilitySnapshot, targetPlatform, targetClusterId,
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
    targetId:targetClusterId,
    snapshot:capabilitySnapshot,
    requirements: draft.resources.filter(item => !item.dependency).flatMap(item => {
      const resource = resources.find(r => resourceKey({...r, namespace:r.namespace ?? null}) === resourceKey(item));
      if (!resource) return [];
      // Sanitized inventory exposes limited pod and ingress evidence only.
      const pod = resource.pod && typeof resource.pod === "object" ? resource.pod as Record<string, unknown> : null;
      return [{
        kind: item.kind,
        name: item.name,
        namespace: item.namespace,
        serviceAccountName: typeof pod?.serviceAccountName === "string" ? pod.serviceAccountName : null,
        ingressClassName: typeof resource.ingressClassName === "string" ? resource.ingressClassName : null,
      }];
    }),
    claims:scopedStorageClaims.map(pvc=>({namespace:pvc.namespace??null,name:pvc.name,requestedStorage:typeof pvc.requestedStorage==="string"?pvc.requestedStorage:null})),
    mappings:(draft.storageMappings??[]).length ? draft.storageMappings??[] : scopedStorageClaims.map(pvc=>suggestedMapping(pvc)),
  });
  const migrationPathDecision = determineMigrationPath({ targetEvidence: targetCompatibility.evidenceStatus, checks: targetCompatibility.findings, coverageComplete: false }); // Target API integration must supply complete verified coverage.
  // Compatibility is tied to the persisted source scope, never unsaved edits.
  const savedDraft = migration.planningDraft?.schemaVersion === 1
    ? migration.planningDraft as unknown as MigrationPlanningDraft
    : null;
  const savedScopeCurrent = Boolean(savedDraft &&
    savedDraft.assessmentVersion === assessment.assessmentVersion &&
    savedDraft.inventoryDigest === assessment.inventoryDigest &&
    !stale);
  const targetExpiryMs = targetEvidence?.snapshot.inventoryExpiresAt
    ? Date.parse(targetEvidence.snapshot.inventoryExpiresAt) : NaN;
  const targetObservedMs = targetEvidence?.snapshot.observedAt
    ? Date.parse(targetEvidence.snapshot.observedAt) : NaN;
  const targetEvidenceCurrent = Number.isFinite(targetObservedMs) &&
    targetObservedMs <= Date.now() + 300000 &&
    (Number.isFinite(targetExpiryMs)
      ? targetExpiryMs > Date.now()
      : Date.now() - targetObservedMs <= 60 * 60 * 1000);
  const savedTargetMatches = Boolean(targetEvidence && targetEvidenceCurrent &&
    targetEvidence.targetClusterId === String(migration.targetConfiguration?.clusterId ?? "") &&
    targetEvidence.assessmentVersion === assessment.assessmentVersion);
  const p0Compatibility = analyzeP0Compatibility(
    savedScopeCurrent && !dirty ? savedDraft!.resources : [],
    resources,
    savedTargetMatches,
    savedTargetMatches ? targetEvidence : null,
    assessment.findings,
  );
  const p0Checks = p0Compatibility.flatMap(item => item.checks);
  const p0Unverified = p0Checks.filter(item => item.status === "NOT_VERIFIED").length;
  const backendEvaluationCurrent = Boolean(
    !dirty && savedScopeCurrent && savedTargetMatches &&
    schedulingReport?.assessmentVersion === assessment.assessmentVersion &&
    schedulingReport?.targetClusterId === targetClusterId &&
    schedulingReport.resourceEvaluations
  );
  const authoritativeResults = backendEvaluationCurrent
    ? schedulingReport?.resourceEvaluations ?? [] : [];
  const authoritativeUnverified = authoritativeResults.flatMap(item => item.checks)
    .filter(check => check.status === "PENDING_EVIDENCE").length;
  const authoritativePartial = authoritativeResults.flatMap(item => item.checks)
    .filter(check => check.status === "PARTIAL").length;
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
    ...(scopeAnalysisNamespace !== scopeNamespaceKey || scopeAnalysisSignature !== currentScopeSignature ? ["Run Analyze selected scope for your current selection."] : []),
    ...(!draft.resources.some(resource => !resource.dependency && ["Deployment","StatefulSet","DaemonSet","Job","CronJob"].includes(resource.kind) && resource.namespace && scopeNamespaceSet.has(resource.namespace)) ? ["Select at least one workload in the selected namespaces."] : []),
    ...(stale ? ["The assessment changed. Refresh the planning draft before continuing."] : []),
  ];
  const draftOutsideScope = draft.resources.filter(item=>item.namespace && !scopeNamespaceSet.has(item.namespace)).length;
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
        ? (!remediationNamespace || finding.namespace === remediationNamespace)
        : findingView === "SHARED"
          ? findingScope(finding) === "SHARED" &&
            (!remediationNamespace || !finding.namespace || finding.namespace === remediationNamespace)
          : findingScope(finding) === "SCOPE")
    );
  const remediationGroups = ["Storage", "Networking", "Security", "Configuration", "Other"].map((category) => ({
    category,
    items: findings.filter(({finding}) => findingCategory(finding.category) === category),
  })).filter((group) => group.items.length > 0);
  const workloadFindingOptions = [...new Map(assessment.findings.filter(item => item.namespace && item.resourceName && ["Deployment","StatefulSet","DaemonSet","Job","CronJob"].includes(item.resourceKind ?? "") && scopeNamespaceSet.has(item.namespace)).map(item => [JSON.stringify([item.namespace,item.resourceName]), {namespace:item.namespace!,name:item.resourceName!}] as const)).values()];
  // Finding category and scope are already applied by the findings selector.
  // Apply only workload focus here to avoid contradictory/double filtering.
  const categorizedFindings = findings.filter(({ finding }) =>
    remediationWorkload === "ALL" ||
    JSON.stringify([finding.namespace, finding.resourceName]) === remediationWorkload
  );
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
    mutationFn: async (nextDraft?: MigrationPlanningDraft) => {
      const payload = nextDraft ?? preparePlanningDraft(draft, scopeNamespaces);
      try {
        return await migrations.update(migration.migrationId, {
          version: migration.version,
          planningDraft: payload,
          changeReason: "Update migration scope and remediation planning draft",
        });
      } catch (error) {
        const api = normalizeApiError(error);
        const details = JSON.stringify(api.details ?? {});
        const rejectedNamespaceField = (api.status === 400 || api.status === 422) &&
          api.code === "VALIDATION_ERROR" &&
          /planningDraft\.selectedNamespaces/.test(details) &&
          /Extra inputs are not permitted/.test(details);
        // Only a legacy backend that explicitly rejects the new field may
        // receive a backward-compatible draft. Never silently lose a
        // namespace selected without an actual saved resource in it.
        const represented = new Set(payload.resources.map(item => item.namespace).filter(Boolean));
        const selection = payload.selectedNamespaces ?? [];
        const safeLegacyScope = selection.length > 0 &&
          selection.every(name => represented.has(name)) &&
          [...represented].every(name => selection.includes(name!));
        if (!rejectedNamespaceField || !safeLegacyScope) throw error;
        const { selectedNamespaces: _unsupported, ...legacyDraft } = payload;
        setMessage("The running backend uses the older draft schema. Saving the resource-backed selection using legacy format.");
        return migrations.update(migration.migrationId, {
          version: migration.version,
          planningDraft: legacyDraft,
          changeReason: "Save migration planning draft using compatible schema",
        });
      }
    },
    onSuccess: async (value) => {
      cache.setQueryData(["migrations", migration.migrationId], value);
      setDraft(value.planningDraft?.schemaVersion === 1 ? value.planningDraft as unknown as MigrationPlanningDraft : draft);
      setDirty(false);
      setMessage("Planning draft saved. No cluster changes were applied.");
      await cache.invalidateQueries({ queryKey: ["migrations"], exact: true });
    },
    onError: (error) => {
      const api = normalizeApiError(error);
      const detail = api.details ? JSON.stringify(api.details).slice(0, 700) : "";
      setMessage(`Save failed · HTTP ${api.status || "network"} · ${api.code}: ${api.message}${detail ? " · " + detail : ""}${api.correlationId ? " · Request ID: " + api.correlationId : ""}`);
    },
  });

  async function continueToTarget() {
    if (!canEdit || stale || save.isPending) return;
    try {
      const advanced = await saveAndContinueToTarget(
        draft, scopeNamespaces,
        next => save.mutateAsync(next),
        () => navigateToStep("target"),
      );
      if (!advanced) setMessage("Select a namespace and include at least one workload before continuing.");
    } catch {
      // onError displays the API error, and navigation remains on Source.
    }
  }
  async function clearPlanningDraft() {
    if (!canEdit || stale || save.isPending) return;
    try {
      const cleared = await confirmAndClearDraft(
        draft,
        () => window.confirm("Clear the saved planning draft and selected namespaces? Source inventory, assessment and target configuration will be preserved."),
        next => save.mutateAsync(next),
      );
      if (!cleared) return;
      setDraft(cleared);
      setScopeNamespaces([]);
      setDirty(false);
      setScopeReviewOpen(false);
      setScopeAnalysisNamespace(null);
      setScopeAnalysisSignature(null);
      setMessage("Planning draft cleared. Source assessment and inventory were preserved.");
    } catch {
      // Failed save leaves existing selection and draft intact.
    }
  }
  const migrationSummary = {
    migration: { id:migration.migrationId,name:migration.name,customer:String(migration.customerName??migration.customerId),status:migration.status,mode:draft.mode },
    assessment: { version:assessment.assessmentVersion,inventoryDigest:assessment.inventoryDigest,stale,dependencyReferenceCoverage:graph.coverage },
    scope: { selectedNamespaces:scopeNamespaces,discoveredWorkloads:analyzedWorkloadCandidates.length,selectedWorkloads:draft.resources.filter(r=>!r.dependency&&["Deployment","StatefulSet","DaemonSet","CronJob","Job"].includes(r.kind)).length,resources:draft.resources.map(r=>({namespace:r.namespace,kind:r.kind,name:r.name,treatment:r.treatment,dependency:r.dependency})),dependencyFlaggedCount:dependencies },
    remediation: { recordedDecisions:draft.remediations.length,findings:assessment.findings.map(f=>({severity:f.severity,description:f.message})) },
    readiness: { openChecks:readiness.issues.map(issue=>({type:issue.type,detail:issue.detail})),dataStrategy:draft.dataStrategy,pvcManifests:pendingPvcs.length },
    evidenceVerification: {
      status: graph.coverage !== "REFERENCES_AVAILABLE" || !savedTargetMatches || !savedScopeCurrent || dirty
        ? "INCOMPLETE" : backendEvaluationCurrent ? "PARTIAL_VERIFICATION" : "AWAITING_BACKEND_COMPATIBILITY",
      sourceDependencyReferences: graph.edges.length,
      dependencyCoverage: graph.coverage,
      sourceScopeSavedAndCurrent: savedScopeCurrent && !dirty,
      targetAssessmentCurrent: savedTargetMatches,
      targetClusterId,
      backendCompatibilityCurrent: backendEvaluationCurrent,
      limitations: [
        ...(graph.coverage !== "REFERENCES_AVAILABLE" ? ["Source dependency references were not collected; zero edges does not mean no dependencies."] : []),
        ...(!savedScopeCurrent || dirty ? ["Source selection is not a current saved assessment scope."] : []),
        ...(!savedTargetMatches ? ["Target capability inventory is unavailable, expired, or mismatched."] : []),
        ...(!backendEvaluationCurrent ? ["Authoritative source-to-target resource checks are not current."] : []),
      ],
    },
    compatibility: {
      authoritative: backendEvaluationCurrent,
      targetClusterId,
      executionReady: false,
      evaluatedResources: authoritativeResults.length,
      checks: authoritativeResults.flatMap(item=>item.checks).length,
      evaluations: authoritativeResults.map(item=>({
        resource:item.resource,status:item.status,sourceStatus:item.sourceStatus,
        targetStatus:item.targetStatus,checks:item.checks,
      })),
      workloadAssessment: backendEvaluationCurrent ? schedulingReport?.workloadAssessmentReport ?? null : null,
      discoveryCoverage: backendEvaluationCurrent ? schedulingReport?.discoveryCoverage ?? null : null,
      remediationHandoff: backendEvaluationCurrent ? buildRemediationHandoff(authoritativeResults) : null,
      migrationPlanPreview: backendEvaluationCurrent ? buildMigrationPlanPreview(authoritativeResults) : null,
    },
    artifactReadiness: { sourceManifests:"NOT_COLLECTED",helmCharts:"NOT_COLLECTED",images:"REFERENCES_ONLY",s3Package:"NOT_CREATED",ecrPromotion:"NOT_STARTED" },
    disclaimer:"Planning export reflects the current UI draft, which may contain unsaved changes. No migration artifacts or cluster resources are exported.",
  };
  function downloadReport(format:"json"|"csv"){
    const json=JSON.stringify(migrationSummary,null,2);
    const escapeCell=(v:unknown)=>'"'+String(v??"").replace(/^[=+@-]/,"'$&").replace(/"/g,'""')+'"';
    const csv=[
      ["Report status",migrationSummary.evidenceVerification.status].map(escapeCell).join(","),
      ["Assessment version",migrationSummary.assessment.version].map(escapeCell).join(","),
      ["Inventory digest",migrationSummary.assessment.inventoryDigest].map(escapeCell).join(","),
      ["Dependency coverage",migrationSummary.evidenceVerification.dependencyCoverage].map(escapeCell).join(","),
      ["Source dependency edges",migrationSummary.evidenceVerification.sourceDependencyReferences].map(escapeCell).join(","),
      ["Target assessment current",migrationSummary.evidenceVerification.targetAssessmentCurrent].map(escapeCell).join(","),
      ["Backend compatibility current",migrationSummary.evidenceVerification.backendCompatibilityCurrent].map(escapeCell).join(","),
      ...migrationSummary.evidenceVerification.limitations.map(limitation=>["Evidence limitation",limitation].map(escapeCell).join(",")),
      ["Authoritative compatibility",migrationSummary.compatibility.authoritative].map(escapeCell).join(","),
      ["Evaluated resources",migrationSummary.compatibility.evaluatedResources].map(escapeCell).join(","),
      ["Compatibility checks",migrationSummary.compatibility.checks].map(escapeCell).join(","),
      ["Execution ready",migrationSummary.compatibility.executionReady].map(escapeCell).join(","),
      "",
      ["Namespace","Kind","Name","Treatment","Dependency"].map(escapeCell).join(","),
      ...migrationSummary.scope.resources.map(r=>[r.namespace,r.kind,r.name,r.treatment,r.dependency].map(escapeCell).join(",")),
      "",
      ["Resource namespace","Resource kind","Resource name","Overall status","Source status","Target status","Capability","Check status","Reason","Next action"].map(escapeCell).join(","),
      ...migrationSummary.compatibility.evaluations.flatMap(item=>
        item.checks.map(check=>[item.resource.namespace,item.resource.kind,item.resource.name,item.status,
          item.sourceStatus,item.targetStatus,check.capability,check.status,check.reason,check.nextAction].map(escapeCell).join(","))),
    ].join("\r\n");
    const file=new Blob([format==="json"?json:"\uFEFF"+csv],{type:format==="json"?"application/json;charset=utf-8":"text/csv;charset=utf-8"});
    const href=URL.createObjectURL(file);
    const link=document.createElement("a");link.href=href;link.download=`navigan-migration-summary-${migration.migrationId}.${format}`;document.body.appendChild(link);link.click();link.remove();URL.revokeObjectURL(href);
  }
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
        {([["scope","1 · Source"],["target","2 · Target"],["compatibility","3 · Compatibility"],["remediate","4 · Remediation"],["plan","5 · Migration Plan"],["review","6 · Review & Export"]] as const).map(([step,label])=>
          <button key={step} type="button" aria-current={tab===step?"step":undefined} onClick={()=>navigateToStep(step)}>{label}</button>
        )}
      </nav>     {tab === "review" && <section className={styles.guide} aria-label="Migration planning guide">
        <div className={styles.guideHeading}>
          <strong>3 · Review planning readiness</strong>
          <span>Assessment v{assessment.assessmentVersion} · Read-only planning</span>
        </div>
        <p>Check scope completeness, planned remediation, unresolved risks and data strategy before saving the draft.</p>
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
      {tab === "target" && <section className={styles.surface} aria-label="Target environment assessment and readiness">
        <div className={styles.workflowStageHeading}><strong>2. Target Environment Assessment &amp; Readiness</strong><p>Understand the selected destination, capture available connector evidence, and identify what must be verified before matching source workloads.</p></div>
        <p className={styles.caption}>Navigan automatically retrieves the destination inventory. Review reported evidence and outstanding checks before continuing to Compatibility.</p>
        <div className={styles.targetAssessmentActions}>
          <button type="button" className="button button-primary" disabled={targetRunning || targetLoading || !canEdit || targetPlatform !== "EKS"} onClick={runTargetAnalysis}>{targetRunning ? "Refreshing target inventory…" : "Refresh target inventory"}</button>
          <span role="status">{targetRunning ? "Refreshing authorized inventory…" : targetLoading ? "Loading saved inventory evidence…" : targetEvidence ? `Last captured: ${new Date(targetEvidence.createdAt).toLocaleString()}` : "Target evidence not yet captured"}</span>
        </div>
        {targetError && <div role="alert" className={styles.warning}>{targetError}</div>}
        <div className={styles.targetOverview}>
          <div><span>Destination cluster</span><strong>{targetEvidence?.snapshot.clusterName || assessment.inventorySummary.target.clusterName || "Not configured"}</strong><small>{targetPlatform} · Existing cluster</small></div>
          <div><span>Connector inventory</span><strong>{targetEvidence ? `${targetEvidence.snapshot.resourceCount ?? 0} resources` : "Not captured"}</strong><small>{targetEvidence ? "Reported by registered connector" : "Collected automatically when available"}</small></div>
          <div><span>Compatibility readiness</span><strong>Pending verification</strong><small>Inventory does not establish workload compatibility</small></div>
        </div>
        {targetEvidence && <div className={styles.targetObservedResult}>
          <strong>Observed destination · {targetEvidence.snapshot.clusterStatus ?? "Status unknown"}</strong>
          <span>{targetEvidence.snapshot.clusterName} · Revision {targetEvidence.snapshot.sourceRevision ?? "Not reported"} · {targetEvidence.snapshot.resourceCount ?? 0} reported resources</span>
          <small>Evidence: {targetEvidence.evidenceLevel} · Observed {targetEvidence.snapshot.observedAt ? new Date(targetEvidence.snapshot.observedAt).toLocaleString() : "time not reported"} · Inventory completeness not established</small>
        </div>}
        {targetEvidence?.snapshot.collectionGaps && <section className={styles.targetCapabilitySection} aria-label="Target connector evidence collection gaps">
          <div className={styles.targetAssessmentHead}><div><strong>Connector collection gaps</strong><p>Missing collection data is not evidence the target cluster lacks a capability.</p></div></div>
          <div className={styles.targetCapabilityGrid}>
            {Object.entries(targetEvidence.snapshot.collectionGaps).map(([capability,status]) =>
              <div key={capability}><strong>{capability.replaceAll(/([A-Z])/g," $1")}</strong><span>{status}</span>
                <p>{targetEvidence.snapshot.collectionLimitations?.[capability] ?? "Capability verification is incomplete."}</p>
              </div>)}
          </div>
        </section>}
        <div className={styles.targetEvidenceDetails}>
          <strong>Target identity &amp; evidence provenance</strong>
          <div><span>Navigan cluster ID</span><strong>{String(migration.targetConfiguration?.clusterId ?? "Not configured")}</strong></div>
          <div><span>Inventory source</span><strong>{targetEvidence ? "Cluster Management connector" : "Not available"}</strong></div>
          <div><span>Inventory revision</span><strong>{targetEvidence?.snapshot.sourceRevision ?? "Not reported"}</strong></div>
          <div><span>Evidence coverage</span><strong>{targetEvidence ? "Partial · Inventory only" : "Unavailable"}</strong></div>
        </div>
        <section className={styles.targetCapabilitySection} aria-label="Target resource inventory coverage">
          <div className={styles.targetAssessmentHead}><div><strong>Observed resource inventory</strong><p>Resource categories come from the existing Cluster Management connector. Only identifiable resource kinds are counted; unknown records are not guessed.</p></div></div>
          <div className={styles.targetOverview}>
            <div><span>Total reported resources</span><strong>{targetEvidence?.snapshot.resourceCount ?? "—"}</strong><small>Connector-observed count</small></div>
            <div><span>Resource kinds identified</span><strong>{targetEvidence?.snapshot.resourceKinds ? Object.keys(targetEvidence.snapshot.resourceKinds).length : "Not yet available"}</strong><small>Detailed breakdown is available after the updated backend assessment</small></div>
            <div><span>Evidence freshness</span><strong>{targetEvidence?.snapshot.inventoryExpiresAt && Date.parse(targetEvidence.snapshot.inventoryExpiresAt) <= Date.now() ? "Expired" : targetEvidence?.snapshot.inventoryExpiresAt ? "Within connector expiry" : "Unknown"}</strong><small>Expiry: {targetEvidence?.snapshot.inventoryExpiresAt ? new Date(targetEvidence.snapshot.inventoryExpiresAt).toLocaleString() : "Not reported"}</small></div>
          </div>
          {targetEvidence?.snapshot.resourceKinds && Object.keys(targetEvidence.snapshot.resourceKinds).length > 0 &&
            <div className={styles.targetCapabilityGrid}>{Object.entries(targetEvidence.snapshot.resourceKinds).map(([kind,count])=>
              <div key={kind}><strong>{kind}</strong><span>{count} observed</span><p>Discovered object count; support on the target for migrated workloads is not yet verified.</p></div>)}</div>}
          {Boolean(targetEvidence?.snapshot.unclassifiedResourceCount) && <p className={styles.caption}>{targetEvidence?.snapshot.unclassifiedResourceCount} resource records did not identify a kind and were not categorized.</p>}
          {!targetEvidence?.snapshot.resourceKinds && <p className={styles.caption}>The current saved report predates resource categorization. The updated backend will populate this after an authorized refresh.</p>}
        </section>
        {targetEvidence?.snapshot.nodeCapacityCoverage && <section className={styles.targetCapabilitySection} aria-label="Observed node capacity">
          <div className={styles.targetAssessmentHead}><div><strong>Node allocatable capacity (observed)</strong><p>Reported by the authorized connector. This is not available scheduling headroom or proof that source workloads fit.</p></div><span className={styles.targetEvidenceUnknown}>{targetEvidence.snapshot.nodeCapacityCoverage.nodesWithCapacity} / {targetEvidence.snapshot.nodeCapacityCoverage.observedNodes} nodes with capacity observations</span></div>
          {targetEvidence.snapshot.nodeCapacity?.length ? <div className={styles.targetCapabilityGrid}>
            {targetEvidence.snapshot.nodeCapacity.map((node, i) => <div key={node.name ?? i}><strong>{node.name ?? "Unknown node"}</strong><span>OBSERVED</span><p>Allocatable CPU: {node.allocatableCpu} · Memory: {node.allocatableMemory}</p></div>)}
          </div> : <p className={styles.caption}>No allocatable capacity values reported by the connector.</p>}
        </section>}
        <section className={styles.targetCapabilitySection} aria-label="Target readiness evidence">
          <div className={styles.targetAssessmentHead}><div><strong>Target capability evidence</strong><p>Partial observations show what the connector discovered, not proof of compatibility with selected source workloads.</p></div><span className={styles.targetEvidenceUnknown}>Migration readiness · Pending verification</span></div>
          <div className={styles.targetCapabilityGrid}>
            {([
              ["Kubernetes APIs", "kubernetesApi"],
              ["Compute & scheduling", "compute"],
              ["Storage & CSI", "storage"],
              ["Networking & ingress", "networking"],
              ["Identity & security", "identity"],
              ["Controllers & dependencies", "dependencies"],
            ] as const).map(([title,key]) => {
              const evidence = targetEvidence?.snapshot.capabilityEvidence?.[key];
              return <div key={key}><strong>{title}</strong><span>{evidence?.status === "PARTIAL" ? "PARTIAL EVIDENCE" : "NOT VERIFIED"}</span><p>{evidence?.reason ?? "An authorized, capability-specific target observation is required."}</p>
                {key === "storage" && targetEvidence?.snapshot.storageDiscovery && <small>
                  StorageClass discovery: {targetEvidence.snapshot.storageDiscovery.StorageClass?.replaceAll("_", " ") ?? "NOT REPORTED"} · CSI discovery: {targetEvidence.snapshot.storageDiscovery.CSIDriver?.replaceAll("_", " ") ?? "NOT REPORTED"}
                </small>}</div>;
            })}
          </div>
        </section>
        <div className={styles.workflowStageWarning}>Inventory collection is read-only and does not establish migration readiness. Continue to Compatibility with the saved Source Draft; unsupported or absent target evidence remains Not Verified.</div>
      </section>}
      {tab === "compatibility" && <section className={styles.surface} aria-label="Source-to-target compatibility">
        <div className={styles.workflowStageHeading}><strong>3. Source-to-Target Mapping &amp; Compatibility</strong><p>Evidence-first comparison of the selected migration scope. No compatibility score or direct migration recommendation is issued without verified target capabilities.</p></div>
        <div className={styles.workflowStageWarning}>{dirty ? "Unsaved source scope changes detected. Save the draft before compatibility is evaluated." : !savedScopeCurrent ? "A current saved Source Draft is required. Save the selected workloads in Step 1 before evaluating compatibility." : !savedTargetMatches ? "Saved scope is available, but target evidence is unavailable, expired, or does not match the selected cluster and assessment. Refresh evidence in Step 2." : `Evaluating saved scope against target evidence · Source assessment v${assessment.assessmentVersion} · Target revision ${targetEvidence?.snapshot.sourceRevision ?? "unknown"} · Evidence remains partial`}</div>
        <div className={styles.compatibilitySnapshot}>
          <div><span>Selected resources</span><strong>{backendEvaluationCurrent ? authoritativeResults.length : p0Compatibility.length}</strong><small>Assessment version {assessment.assessmentVersion}</small></div>
          <div><span>Compatibility checks</span><strong>{backendEvaluationCurrent ? authoritativeResults.reduce((count, item) => count + item.checks.length, 0) : p0Checks.length}</strong><small>{backendEvaluationCurrent ? `${authoritativeUnverified} pending · ${authoritativePartial} partial` : `${p0Unverified} not verified`} · {backendEvaluationCurrent ? "Backend evaluation" : "P0 fallback"}</small></div>
          <div><span>Target evidence</span><strong>{savedTargetMatches ? "Partial" : targetEvidence ? "Expired / mismatched" : "Unavailable"}</strong><small>{savedTargetMatches ? `Connector inventory · ${targetEvidence?.snapshot.resourceCount ?? 0} reported resources` : "Fresh target-bound evidence is required"}</small></div>
          <div><span>Migration path</span><strong>{schedulingReport?.decision?.path?.replaceAll("_", " ") ?? "PENDING EVIDENCE"}</strong><small>{schedulingReport?.decision?.reason ?? "Backend compatibility decision unavailable; no approval can be inferred."}</small></div>
        </div>
        <section className={styles.targetCapabilitySection} aria-label="Workload scheduling evidence">
          <div className={styles.targetAssessmentHead}>
            <div><strong>Workload scheduling evidence</strong><p>Backend-observed CPU/memory fit against target node allocatable capacity. This is not free headroom or confirmed Kubernetes scheduling compatibility.</p></div>
            <span className={styles.targetEvidenceUnknown}>{schedulingReport?.schedulingEvidence?.status?.replaceAll("_", " ") ?? "PENDING EVIDENCE"}</span>
          </div>
          {schedulingError && <p role="alert">{schedulingError}</p>}
          {dirty || !savedScopeCurrent || !savedTargetMatches
            ? <p className={styles.caption}>Save the current source scope and refresh target evidence to review workload scheduling checks.</p>
            : schedulingReport?.schedulingEvidence?.workloads?.length
              ? <div className={styles.targetCapabilityGrid}>{schedulingReport.schedulingEvidence.workloads.map((item, i) =>
                  <div key={`${item.apiVersion}/${item.kind}/${item.namespace ?? ""}/${item.name}/${i}`}>
                    <strong>{item.namespace ?? "Cluster"}/{item.name} · {item.kind}</strong>
                    <span>{item.status.replaceAll("_", " ")}</span>
                    <p>{item.reason}</p>
                    {typeof item.candidateNodes === "number" && <small>Capacity candidates: {item.candidateNodes} · Nodes evaluated: {item.observedNodes ?? "unknown"}</small>}
                  </div>
                )}</div>
              : <p className={styles.caption}>No verified workload-specific scheduling evaluation is available yet. Source resource requests may be missing from the inventory.</p>}
          <p className={styles.caption}>Scheduling observations never override source blockers, missing target capabilities, or the backend migration approval gate.</p>
        </section>
        {schedulingReport?.discoveryCoverage && <section className={styles.targetCapabilitySection} aria-label="Source and target discovery coverage">
          <div className={styles.targetAssessmentHead}><div><strong>Source and Target Discovery Coverage</strong><p>Saved, read-only evidence. Missing or expired evidence is not migration readiness.</p></div></div>
          <div className={styles.targetOverview}>
            <div><span>Source inventory</span><strong>{schedulingReport.discoveryCoverage.source.inventoryResourceCount} resources</strong><small>Freshness: {schedulingReport.discoveryCoverage.source.freshness}</small></div>
            <div><span>Selected source workloads</span><strong>{schedulingReport.discoveryCoverage.source.matchedSelectedWorkloads} / {schedulingReport.discoveryCoverage.source.selectedWorkloadCount}</strong><small>With dependency references: {schedulingReport.discoveryCoverage.source.dependencyEvidence.workloadCoverage.withReferenceEvidence}</small></div>
            <div><span>Target inventory</span><strong>{schedulingReport.discoveryCoverage.target.inventoryResourceCount ?? "Unknown"} resources</strong><small>Freshness: {schedulingReport.discoveryCoverage.target.freshness}</small></div>
          </div>
          <div className={styles.targetCapabilityGrid}>
            {(["source","target"] as const).flatMap(side =>
              Object.entries(schedulingReport.discoveryCoverage![side].capabilities).map(([capability, evidence]) =>
                <div key={side + "-" + capability}>
                  <strong>{side === "source" ? "Source" : "Target"} · {capability}</strong>
                  <span>{evidence.status.replaceAll("_", " ")}</span>
                  <p>{evidence.reason}</p>
                </div>))}
          </div>
          <p className={styles.workflowStageWarning}>{schedulingReport.discoveryCoverage.note}</p>
        </section>}
        {backendEvaluationCurrent && schedulingReport?.workloadAssessmentReport && <section className={styles.targetCapabilitySection} aria-label="Selected workload migration assessment">
          <div className={styles.targetAssessmentHead}><div>
            <strong>Selected Workload Migration Assessment · {schedulingReport.workloadAssessmentReport.workloadCount} workloads</strong>
            <p>Read-only assessment. Pending evidence is not approval or execution readiness.</p>
          </div></div>
          <div className={styles.targetCapabilityGrid}>
            {schedulingReport.workloadAssessmentReport.workloads.map(item =>
              <details key={JSON.stringify(item.source)} className={styles.compatibilityDetails}>
                <summary>{item.source.namespace ?? "Cluster"}/{item.source.name} · {item.source.kind} · {item.compatibilityStatus.replaceAll("_"," ")}</summary>
                <p>Planned treatment: {item.plannedTreatment} · Dependency evidence: {item.dependencyEvidenceStatus.replaceAll("_"," ")}</p>
                <p>Observed dependencies: {item.observedDependencies.length ? item.observedDependencies.map(d=>d.kind+" "+d.name).join(", ") : "None confirmed; evidence may be incomplete"}</p>
                <p>Unresolved dependencies: {item.unresolvedDependencies.length ? item.unresolvedDependencies.map(d=>d.kind+" "+d.name).join(", ") : "None recorded"}</p>
                {item.checks.map((check,index)=><div key={index} className={styles.compatibilityCheck}><div><b>{check.capability}</b><span>{check.status.replaceAll("_"," ")}</span></div><p>{check.reason}</p><small>Next action: {check.nextAction}</small></div>)}
              </details>)}
          </div>
          <p className={styles.workflowStageWarning}>{schedulingReport.workloadAssessmentReport.limitations.join(" ")}</p>
        </section>}
        {backendEvaluationCurrent && !schedulingReport?.workloadAssessmentReport && <section className={styles.targetCapabilitySection} aria-label="Selected workload assessment using existing evaluations">
          <div className={styles.targetAssessmentHead}><div>
            <strong>Selected Workload Assessment · {authoritativeResults.filter(item => ["Deployment","StatefulSet","DaemonSet","Pod","Job","CronJob"].includes(item.resource.kind)).length} evaluated workloads</strong>
            <p>Compatibility evidence from the current backend. Dependency relationships are not available in this response and remain unverified.</p>
          </div></div>
          <div className={styles.targetCapabilityGrid}>
            {authoritativeResults.filter(item => ["Deployment","StatefulSet","DaemonSet","Pod","Job","CronJob"].includes(item.resource.kind)).map(item =>
              <details key={JSON.stringify(item.resource)} className={styles.compatibilityDetails}>
                <summary>{item.resource.namespace ?? "Cluster"}/{item.resource.name} · {item.resource.kind} · {item.status.replaceAll("_"," ")}</summary>
                <p>Dependencies: NOT VERIFIED by this report</p>
                {item.checks.map((check,index)=><div key={index} className={styles.compatibilityCheck}><div><b>{check.capability}</b><span>{check.status.replaceAll("_"," ")}</span></div><p>{check.reason}</p><small>Next action: {check.nextAction}</small></div>)}
              </details>)}
          </div>
          <p className={styles.workflowStageWarning}>Assessment only. Execution readiness is not established.</p>
        </section>}
        {backendEvaluationCurrent && <section className={styles.targetCapabilitySection} aria-label="Backend resource compatibility">
          <div className={styles.targetAssessmentHead}><div><strong>Authoritative resource compatibility</strong><p>Every saved resource is assessed. Expand a resource for evidence, limitations and concrete next actions. Pending evidence is not compatibility approval.</p></div><span className={styles.targetEvidenceUnknown}>{authoritativeResults.length} evaluated</span></div>
          <div className={styles.targetCapabilityGrid}>{authoritativeResults.map(item =>
            <details key={JSON.stringify(item.resource)} className={styles.compatibilityDetails}>
              <summary>{item.resource.namespace ?? "Cluster"}/{item.resource.name} · {item.resource.kind} · Source: {(item.sourceStatus ?? "UNKNOWN").replaceAll("_", " ")} · Target: {(item.targetStatus ?? "UNKNOWN").replaceAll("_", " ")}</summary>
              {item.checks.map((check, index) => <div className={styles.compatibilityCheck} key={index}>
                <div><b>{check.capability}</b><span>{check.status.replaceAll("_", " ")}</span></div>
                <p>{check.reason}</p><small>Next action: {check.nextAction}</small>
              </div>)}
            </details>)}</div>
        </section>}
        {!backendEvaluationCurrent && <p className={styles.workflowStageWarning}>Authoritative backend evaluation is unavailable or not current for this saved scope. The following P0 checklist is diagnostic only; it is not a migration readiness decision.</p>}
        {!backendEvaluationCurrent && <>        <div className={styles.compatibilityMatrixWrap}><table className={styles.compatibilityMatrix}>
          <thead><tr><th>Selected source resource</th><th>Kind</th><th>Target</th><th>Overall result</th><th>P0 checks / next action</th></tr></thead>
          <tbody>{p0Compatibility.map(result => {
            const sourceChecks = result.checks.filter(check => check.capability === "Source assessment");
            const targetChecks = result.checks.filter(check => check.capability !== "Source assessment");
            const sourceStatus = sourceChecks.some(check => check.status === "BLOCKED")
              ? "BLOCKED"
              : sourceChecks.some(check => check.status === "REMEDIATION_REQUIRED")
                ? "REMEDIATION REQUIRED" : "No resource-specific findings";
            const targetStatus = targetChecks.some(check => check.status === "BLOCKED")
              ? "BLOCKED" : targetChecks.every(check => check.status === "COMPATIBLE")
                ? "COMPATIBLE" : "PENDING VERIFICATION";
            const scheduling = savedScopeCurrent && !dirty && savedTargetMatches &&
              schedulingReport?.assessmentVersion === assessment.assessmentVersion &&
              schedulingReport.targetClusterId === String(migration.targetConfiguration?.clusterId ?? "")
              ? schedulingReport.schedulingEvidence?.workloads.find(item =>
                  item.apiVersion === result.resource.apiVersion &&
                  item.kind === result.resource.kind &&
                  (item.namespace ?? null) === (result.resource.namespace ?? null) &&
                  item.name === result.resource.name)
              : undefined;
            const apiMatch = savedScopeCurrent && !dirty && savedTargetMatches &&
              schedulingReport?.assessmentVersion === assessment.assessmentVersion &&
              schedulingReport.targetClusterId === String(migration.targetConfiguration?.clusterId ?? "")
              ? schedulingReport.apiEvidence?.resources.find(item =>
                  item.apiVersion === result.resource.apiVersion &&
                  item.kind === result.resource.kind &&
                  (item.namespace ?? null) === (result.resource.namespace ?? null) &&
                  item.name === result.resource.name)
              : undefined;
            const storage = savedScopeCurrent && !dirty && savedTargetMatches &&
              schedulingReport?.assessmentVersion === assessment.assessmentVersion &&
              schedulingReport.targetClusterId === String(migration.targetConfiguration?.clusterId ?? "")
              ? schedulingReport.storageEvidence?.claims.find(item =>
                  item.apiVersion === result.resource.apiVersion &&
                  item.kind === result.resource.kind &&
                  (item.namespace ?? null) === (result.resource.namespace ?? null) &&
                  item.name === result.resource.name)
              : undefined;
            return <tr key={resourceKey(result.resource)}>
              <td>{result.resource.namespace ?? "Cluster"}/{result.resource.name}</td>
              <td>{result.resource.kind}</td>
              <td>{targetPlatform}</td>
              <td><div className={styles.compatibilityDualStatus}>
                <span>Source readiness <strong>{sourceStatus}</strong></span>
                <span>Target compatibility <strong>{targetStatus}</strong></span>
                {apiMatch && <span>Kubernetes API evidence <strong>{apiMatch.status.replaceAll("_", " ")}</strong></span>}
                {storage && <span>Storage evidence <strong>{storage.status.replaceAll("_", " ")}</strong></span>}
                {scheduling && <span>Compute scheduling <strong>{scheduling.status.replaceAll("_", " ")}</strong></span>}
              </div></td>
              <td><details className={styles.compatibilityDetails}>
                <summary>{result.checks.length} checks · {sourceChecks.length} source findings · {targetChecks.filter(check => check.status === "NOT_VERIFIED").length} target unverified</summary>
                {sourceChecks.length > 0 && <div className={styles.compatibilityCheckGroup}>
                  <strong>Source assessment findings</strong>
                  {sourceChecks.map((check, i) => <div className={styles.compatibilityCheck} key={i}>
                    <div><b>{check.capability}</b><span>{check.status.replaceAll("_", " ")}</span></div>
                    <p>{check.reason}</p><small>Action: {check.nextAction}</small>
                  </div>)}
                </div>}
                {apiMatch && <div className={styles.compatibilityCheckGroup}>
                  <strong>Kubernetes API version observation</strong>
                  <div className={styles.compatibilityCheck}>
                    <div><b>{apiMatch.apiVersion ?? "Unknown API version"}</b><span>{apiMatch.status.replaceAll("_", " ")}</span></div>
                    <p>{apiMatch.reason}</p>
                  </div>
                </div>}
                {storage && <div className={styles.compatibilityCheckGroup}>
                  <strong>PVC target StorageClass observation</strong>
                  <div className={styles.compatibilityCheck}>
                    <div><b>{storage.sourceStorageClass ?? "Source StorageClass unreported"}</b><span>{storage.status.replaceAll("_", " ")}</span></div>
                    <p>{storage.reason}</p>
                    <small>Source: {storage.requestedStorage ?? "capacity unknown"} · {(storage.sourceAccessModes ?? []).join(", ") || "access modes unknown"} · {storage.volumeMode ?? "volume mode unknown"}</small>
                    <small>Target: {storage.targetProvisioner ?? "provisioner unknown"} · {storage.targetVolumeBindingMode ?? "binding unknown"} · CSI driver {storage.csiDriverObserved ? "observed" : "not verified"}</small>
                    <small>StorageClass observation is not evidence of successful volume provisioning or data migration.</small>
                  </div>
                </div>}
                {scheduling && <div className={styles.compatibilityCheckGroup}>
                  <strong>Compute scheduling evidence</strong>
                  <div className={styles.compatibilityCheck}>
                    <div><b>Workload-to-node observation</b><span>{scheduling.status.replaceAll("_", " ")}</span></div>
                    <p>{scheduling.reason}</p>
                    <small>{typeof scheduling.candidateNodes === "number" ? `Capacity candidates: ${scheduling.candidateNodes} · ` : ""}Nodes evaluated: {scheduling.observedNodes ?? "Not verified"} · Read-only evidence, not scheduler approval</small>
                  </div>
                </div>}
                <div className={styles.compatibilityCheckGroup}>
                  <strong>Target capability verification</strong>
                  {targetChecks.map((check, i) => <div className={styles.compatibilityCheck} key={i}>
                    <div><b>{check.capability}</b><span>{check.status.replaceAll("_", " ")}</span></div>
                    <p>{check.reason.replace(/ Source-to-target requirements have not been verified\\.$/, "")}</p>
                    <small>Action: {check.nextAction}</small>
                  </div>)}
                </div>
              </details></td>
            </tr>;
          })}</tbody>
        </table></div>
        {p0Compatibility.length === 0 && <p>Save selected workloads in Step 1 and ensure the target evidence is current to generate scoped checks.</p>}</>}
        <div className={styles.workflowStageWarning}>P0 assessment is read-only and evidence-gated. The saved connector inventory confirms discovery, not target compatibility. Kubernetes API support, scheduling capacity, storage, networking, identity and dependencies require verified target-specific observations before migration readiness can be determined.</div>
      </section>}
      {tab === "plan" && <section className={styles.surface} aria-label="Migration Plan">
        <div className={styles.workflowStageHeading}><strong>5. Migration Plan</strong><p>Plan generation follows evidence-backed source-to-target matching, remediation decisions and artifact readiness.</p></div>
        {backendEvaluationCurrent ? (() => {
          const preview = buildMigrationPlanPreview(authoritativeResults);
          return <>
            <section className={styles.remediationKpis} aria-label="Migration planning summary">
              <div><strong>{preview.workloads.length}</strong><span>Workloads in planning inventory</span></div>
              <div><strong>{preview.remediationCount}</strong><span>Remediation checks</span></div>
              <div><strong>{preview.verificationCount}</strong><span>Evidence checks</span></div>
              <div><strong>Not ready</strong><span>Execution readiness</span></div>
            </section>
            <div className={styles.targetCapabilityGrid}>
              {preview.workloads.map(item => <div key={resourceKey(item.resource)} className={styles.compatibilityDetails}>
                <strong>{item.resource.namespace ?? "Cluster"}/{item.resource.name} · {item.resource.kind}</strong>
                <p>Source: {item.sourceStatus.replaceAll("_", " ")} · Target: {item.targetStatus.replaceAll("_", " ")}</p>
                <small>{item.remediationCount} required-action checks · {item.verificationCount} evidence-verification checks</small>
              </div>)}
            </div>
            <section className={styles.targetCapabilitySection}>
              <strong>Required before sequencing or execution</strong>
              {preview.prerequisites.map(step => <p key={step}>• {step}</p>)}
            </section>
            <p className={styles.workflowStageWarning}>{preview.note} Deployment, rollback and execution remain disabled.</p>
          </>;
        })() : <div className={styles.workflowStageWarning}>A current saved Source scope and authoritative target compatibility evaluations are required for the migration plan preview. No plan is generated from stale or unsaved evidence.</div>}
      </section>}
      {tab === "scope" && (<>
        <section className={styles.sourceDashboard} aria-label="Source discovery dashboard">
          <div className={styles.sourceSummaryTitle}>
            <div><strong>1. Source · Discover and define migration scope</strong><span>Live summary of the saved source inventory and current planning draft. No target readiness is inferred.</span></div>
            <div className={styles.sourceStatusPill}>Assessment v{assessment.assessmentVersion} · {stale ? "Refresh required" : "Inventory loaded"}</div>
          </div>
          <div className={styles.sourceDashboardCards}>
            <div className={styles.sourceClusterCard}>
              <div className={styles.sourceClusterHeading}><PlatformIcon platform="SELF_MANAGED_KUBERNETES" size="medium"/><div><small>SOURCE CLUSTER</small><strong>{String(migration.sourceConfiguration.clusterName ?? "Self-managed Kubernetes")}</strong><span>Self-managed Kubernetes</span></div></div>
              <div className={styles.sourceClusterStats}><span><b>{namespaces.length}</b> Assessed namespaces</span><span><b>{applicationWorkloads.length}</b> Discovered workloads</span><span><b>{resources.length}</b> Inventory resources</span></div>
            </div>
            <div className={styles.sourceChartCard}>
              <strong>Workload types</strong>
              {(() => {const kinds=[...new Set(applicationWorkloads.map(r=>r.kind))].map(kind=>({kind,count:applicationWorkloads.filter(r=>r.kind===kind).length})).sort((a,b)=>b.count-a.count);const colors=["#2c86df","#86bc25","#8664c9","#f0ae32","#7c91a8"];let offset=0;const stops=kinds.map((k,i)=>{const start=offset;offset+=k.count/Math.max(applicationWorkloads.length,1)*100;return `${colors[i%colors.length]} ${start}% ${offset}%`;});return <div className={styles.sourceChartBody}><div className={styles.sourceDonut} style={{background:applicationWorkloads.length?`conic-gradient(${stops.join(",")})`:"#e4eaf0"}}><span><b>{applicationWorkloads.length}</b><small>workloads</small></span></div><div className={styles.sourceLegend}>{kinds.slice(0,5).map((k,i)=><div key={k.kind}><i style={{background:colors[i%colors.length]}}/>{k.kind}<b>{k.count}</b></div>)}</div></div>})()}
            </div>
            <div className={styles.sourceChartCard}>
              <strong>Namespace distribution</strong>
              {(() => {const counts=namespaces.map(name=>({name,count:applicationWorkloads.filter(r=>r.namespace===name).length})).sort((a,b)=>b.count-a.count);const top=counts.slice(0,5);const colors=["#2c86df","#86bc25","#8664c9","#f0ae32","#7c91a8"];let offset=0;const stops=counts.map((k,i)=>{const start=offset;offset+=k.count/Math.max(applicationWorkloads.length,1)*100;return `${colors[i%colors.length]} ${start}% ${offset}%`;});return <div className={styles.sourceChartBody}><div className={styles.sourceDonut} style={{background:applicationWorkloads.length?`conic-gradient(${stops.join(",")})`:"#e4eaf0"}}><span><b>{namespaces.length}</b><small>namespaces</small></span></div><div className={styles.sourceLegend}>{top.map((k,i)=><div key={k.name}><i style={{background:colors[i%colors.length]}}/>{k.name}<b>{k.count}</b></div>)}</div></div>})()}
            </div>
            <div className={styles.sourceEvidenceCard}>
              <strong>Source evidence &amp; draft</strong>
              <div><span>Selected namespaces</span><b>{scopeNamespaces.length} / {namespaces.length}</b></div>
              <div><span>Included workloads</span><b>{workloadRelationships.filter(item=>item.selected).length}</b></div>
              <div><span>Draft resources</span><b>{draft.resources.length}</b></div>
              <div><span>Relationship coverage</span><b>{graph.coverage==="REFERENCES_AVAILABLE"?"Captured":"Not collected"}</b></div>
              <small>Unknown relationships are never shown as verified connections.</small>
            </div>
          </div>
        </section>
        <div className={styles.sourceFullWidthColumns}>
          <section className={styles.surface}>
            <div className={styles.scopeOptionSectionTitle}><span>1</span><strong>Migration details and mode</strong><small>Confirm assessed source, target and planning approach</small></div>
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
              <PlatformIcon platform={targetPlatform} size="medium" />
              <div>
                <span>Selected target (unverified)</span>
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
            <div className={styles.scopeOptionSectionTitle}><span>2</span><strong>Assessed source namespaces</strong><small>Only namespaces from the existing Source Assessment are available for planning</small></div>
            <div className={styles.scopeSelectionBar}>
              <details className={styles.scopeNamespacePicker}>
                <summary aria-label="Application namespaces">Select namespaces · {scopeNamespaces.length} selected</summary>
                <div>{namespaces.map(item=><label key={item}>
                  <input type="checkbox" aria-label={`Select namespace ${item}`} checked={scopeNamespaceSet.has(item)}
                    onChange={event=>{setScopeNamespaces(current=>event.target.checked?[...new Set([...current,item])]:current.filter(name=>name!==item));setDirty(true);setMessage("");setScopeReviewOpen(false);setScopeAnalysisNamespace(null);setScopeAnalysisSignature(null);}} />{item}
                </label>)}</div>
              </details>
              <label className={styles.scopeSearchLabel}>Search selected resources
                <div className={styles.search}><Search size={16} /><input value={search} onChange={event=>setSearch(event.target.value)} placeholder="Name or kind"/></div>
              </label>
              <div className={styles.scopeFilterActions}>
                <button type="button" className="button button-primary" aria-expanded={scopeReviewOpen}
                  aria-controls="scope-selection-review"
                  onClick={()=>{setScopeAnalysisNamespace(scopeNamespaceKey);setScopeAnalysisSignature(currentScopeSignature);setScopeReviewOpen(true);}}
                  disabled={!scopeNamespaces.length}>Analyze selected scope</button>
              </div>
            </div>
            {scopeNamespaces.length>0 && <div className={styles.scopeNamespaceChips}><strong>{scopeNamespaces.length} selected</strong>{scopeNamespaces.map(ns=><span key={ns}>{ns}<small>{applicationWorkloads.filter(r=>r.namespace===ns).length} workloads</small></span>)}</div>}
            {scopeReviewOpen && (
              <section id="scope-selection-review" className={styles.scopeReview} aria-label="Selected migration scope review">
                <div className={styles.scopeReviewHeading}>
                  <strong>3. Select application workloads</strong>
                  <span>{draft.resources.filter(resource => resource.namespace && scopeNamespaceSet.has(resource.namespace)).length} total draft resources in selected namespaces · Assessment v{assessment.assessmentVersion}</span>
                </div>
                <p className={styles.caption}>Review discovered workloads and use Add to Draft to include them in the migration scope.</p>
                <div className={styles.scopeWorkloadTableWrap}>
                  <div className={styles.scopeWorkloadTableHeading}>
                    <div><strong>Choose workloads for migration</strong><p>Choose workloads directly. A discovered workload is not included until added to the draft.</p></div>
                    <span>{workloadRelationships.length} discovered · {workloadRelationships.filter(item=>item.selected).length} included · {workloadRelationships.filter(item=>!item.selected).length} not selected</span>
                  </div>
                  <div className={styles.scopeWorkloadTableScroll}>
                    <table className={styles.scopeWorkloadTable}>
                      <thead><tr><th>Workload</th><th>Namespace</th><th>Type</th><th>Draft status</th><th>Dependency evidence</th><th>Action</th></tr></thead>
                      <tbody>
                        {workloadRelationships.map(({workload,references,selected:included})=><tr key={resourceKey({...workload,namespace:workload.namespace??null})}>
                          <td><strong>{workload.name}</strong></td>
                          <td>{workload.namespace??"Cluster"}</td>
                          <td>{workload.kind}</td>
                          <td><span className={included?styles.scopeTableIncluded:styles.scopeTableDiscovered}>{included?"Included in draft":"Discovered"}</span></td>
                          <td>{graph.coverage!=="REFERENCES_AVAILABLE"?"Not collected":references.length+" references"}</td>
                          <td>{included?<span className={styles.scopeTableIncluded}>Included</span>:<button type="button" className={styles.scopeTableAdd} disabled={!canEdit||stale||save.isPending} title={!canEdit?"Read-only planning: editing is unavailable":stale?"Refresh assessment before editing":save.isPending?"Saving draft":"Add workload to migration draft"} onClick={()=>{
                            if(!draft.resources.some(item=>item.kind===workload.kind&&item.namespace===workload.namespace&&item.name===workload.name)){
                              change({...draft,resources:[...draft.resources,{...recommendResource(workload).resource,dependency:false}]});
                            }
                          }}>Add to Draft</button>}</td>
                        </tr>)}
                      </tbody>
                    </table>
                  </div>
                </div>
                <section className={styles.sourceTopologyPanel} aria-label="Source topology and dependencies">
                  <div className={styles.sourceTopologyHeading}>
                    <strong>Source topology &amp; dependencies</strong>
                    <span>Discovered references within the selected migration scope · no assumed connections</span>
                  </div>
                  <ScopeTopology
                    namespaces={scopeNamespaces}
                    coverageKnown={graph.coverage === "REFERENCES_AVAILABLE"}
                    resources={workloadRelationships.map(({workload, references, selected:included}) => ({
                      kind: workload.kind,
                      namespace: workload.namespace ?? null,
                      name: workload.name,
                      selected: included,
                      references: references.map(ref => ({
                        kind: ref.kind,
                        name: ref.name,
                        present: ref.present,
                      })),
                      potentialClaims: [],
                    }))}
                    supportingResources={resources.filter(r =>
                      Boolean(r.namespace && scopeNamespaceSet.has(r.namespace)) &&
                      !workloadKinds.has(r.kind)
                    ).map(r => ({
                      kind: r.kind,
                      namespace: r.namespace ?? null,
                      name: r.name,
                      selected: draft.resources.some(item =>
                        item.kind === r.kind && item.namespace === r.namespace && item.name === r.name
                      ),
                    }))}
                    readOnly
                  />
                </section>
                <section className={styles.scopeResourceReview} aria-label="Resource Review and Migration Actions">
                  <div className={styles.scopeResourceReviewHead}><strong>4. Resource Review &amp; Migration Actions</strong><p>Review dependencies, configuration, storage, and migration treatments. Use the tabs below for detailed resource decisions.</p></div>
                  <div className={styles.scopeResourceReviewMetrics}><span><b>{resources.filter(r=>r.namespace&&scopeNamespaceSet.has(r.namespace)&&["Service","Ingress","ConfigMap","Secret","ServiceAccount","NetworkPolicy","PersistentVolumeClaim"].includes(r.kind)).length}</b> Supporting resources</span><span><b>{pendingPvcs.length}</b> PVCs to review</span><span><b>{graph.coverage==="REFERENCES_AVAILABLE"?sourceReferences.length:0}</b> Recorded references</span></div>
                <details className={styles.compactReviewDetails}><summary>4. Dependencies and storage · evidence and recommendations</summary>
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
                </details>

            <div className={styles.scopeReviewTabbedActions}>
            <nav className={styles.scopeViews} aria-label="Scope resource views">
              {([
                ["DEPENDENCIES", "Dependencies"],
                ["WORKLOADS", "Workloads"],
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
            </div>

                </section>
                <details className={styles.compactReviewDetails} open><summary>5. Confirm migration scope · {scopeNamespaces.length} namespaces · {draft.resources.filter(resource => resource.namespace && scopeNamespaceSet.has(resource.namespace)).length} draft resources</summary>
                  <div className={styles.confirmScopeGroups}>
                    {scopeNamespaces.map(namespace => {
                      const selectedResources = draft.resources.filter(resource => resource.namespace === namespace);
                      const workloadCount = selectedResources.filter(resource => !resource.dependency && ["Deployment","StatefulSet","DaemonSet","CronJob","Job"].includes(resource.kind)).length;
                      return <div className={styles.confirmScopeGroup} key={namespace}>
                        <div className={styles.confirmScopeGroupHeader}><strong>{namespace}</strong><small>{workloadCount} workload{workloadCount === 1 ? "" : "s"} · {selectedResources.length} draft resource{selectedResources.length === 1 ? "" : "s"}</small></div>
                        {selectedResources.length ? <div className={styles.scopeReviewItems}>{selectedResources.map(resource => <span key={resourceKey(resource)} title={`${resource.namespace || "Cluster"} / ${resource.kind} / ${resource.treatment}`}>{resource.name} <small>{resource.kind}</small></span>)}</div> : <p className={styles.confirmScopeMissing}>No workloads added to draft from this namespace. Select its workload in Step 3 using Add to Draft if it should be migrated.</p>}
                      </div>;
                    })}
                  </div>
                </details>
                <div className={styles.scopeReviewReadiness}><strong>6. Readiness and next steps</strong><span>Data strategy: {draft.dataStrategy === "UNDECIDED" ? "Decision required" : draft.dataStrategy.replaceAll("_", " ")} · {readiness.issues.length} follow-up checks</span></div>
              </section>
            )}
          </section>
          <aside className={styles.surface}>
            <div className={styles.optionScopeSidebar}>
              <div className={styles.optionScopeHeader}><strong>Migration scope summary</strong><small>Current planning draft</small></div>
              <div className={styles.optionScopeMetric}><span>Namespaces selected</span><strong>{scopeNamespaces.length} / {namespaces.length}</strong><div className={styles.optionScopeTrack}><i style={{width:`${namespaces.length?scopeNamespaces.length/namespaces.length*100:0}%`}}/></div></div>
              <div className={styles.optionScopeMetric}><span>Workloads included</span><strong>{workloadRelationships.filter(r=>r.selected).length} / {workloadRelationships.length}</strong><div className={styles.optionScopeTrack}><i style={{width:`${workloadRelationships.length?workloadRelationships.filter(r=>r.selected).length/workloadRelationships.length*100:0}%`}}/></div></div>
              <div className={styles.optionScopeMetric}><span>Draft resources</span><strong>{draft.resources.length}</strong><small>{draft.resources.length-dependencies} explicitly selected · {dependencies} dependency-flagged</small></div>
              <div className={styles.optionScopeDivider}/>
              <strong className={styles.optionScopeSubheading}>Selected namespaces</strong>
              <div className={styles.optionScopeNamespaceList}>{scopeNamespaces.map(ns=><div key={ns}><Boxes size={16}/><span><b>{ns}</b><small>{applicationWorkloads.filter(r=>r.namespace===ns).length} workloads · {workloadRelationships.filter(r=>r.workload.namespace===ns&&r.selected).length} included</small></span></div>)}</div>
              <div className={styles.optionScopeDivider}/>
              <strong className={styles.optionScopeSubheading}>Current draft</strong>
              <div className={styles.optionScopeRow}><span>Selected resources</span><strong>{draft.resources.length-dependencies}</strong></div>
              <div className={styles.optionScopeRow}><span>Dependency-flagged</span><strong>{dependencies}</strong></div>
              <div className={styles.optionScopeRow}><span>PVC manifests to review</span><strong>{pendingPvcs.length}</strong></div>
              {draftOutsideScope>0&&<p className={styles.scopeOutsideNotice}>{draftOutsideScope} draft resources are outside the selected namespaces.</p>}
              <div className={styles.optionScopeDivider}/>
              <strong className={styles.optionScopeSubheading}>Assessment evidence</strong>
              <p className={styles.optionScopeEvidence}>{graph.coverage==="REFERENCES_AVAILABLE"?"Resource references collected":"Resource relationships not collected; reassessment required"}</p>
              <div className={styles.optionScopeRow}><span>Recorded references</span><strong>{graph.coverage==="REFERENCES_AVAILABLE"?sourceReferences.length:0}</strong></div>
              <div className={styles.optionScopeRow}><span>Readiness follow-ups</span><strong>{readiness.issues.length}</strong></div>
              <div className={styles.optionScopeRow}><span>Data strategy</span><strong>{draft.dataStrategy==="UNDECIDED"?"Pending":"Selected"}</strong></div>
              <div className={styles.optionScopeSafe}><ShieldCheck size={16}/><span>Source remains unchanged · Execution not enabled</span></div>
              {draft.mode==="FULL_CLUSTER"&&<p className={styles.warning}>{unaccounted} resources need a treatment decision.</p>}
              <details className={styles.optionScopeMore}><summary>Review readiness details</summary><ul>{readiness.issues.map((issue,index)=><li key={index}>{issue.type.replaceAll("_"," ")} — {issue.detail}</li>)}</ul><p>Storage checks: {storageCompatibility.length}. Target evidence: {targetCapability.status.toLowerCase()}.</p></details>
            </div>
          </aside>
        </div>
      </>)}
      {tab === "remediate" && (
        <section className={styles.surface}>
          {backendEvaluationCurrent && (() => {
            const handoff = buildRemediationHandoff(authoritativeResults);
            return <section className={styles.targetCapabilitySection} aria-label="Compatibility remediation handoff">
              <div className={styles.targetAssessmentHead}><div><strong>Compatibility → Remediation handoff</strong>
                <p>{handoff.resourceCount} assessed resources · {handoff.actions.length} actionable checks · {handoff.evidence.length} evidence-verification checks. No migration execution.</p></div></div>
              <div className={styles.targetCapabilityGrid}>
                <details className={styles.compatibilityDetails}><summary>Source changes / remediation actions · {handoff.actions.length}</summary>
                  {handoff.actions.length === 0 && <p>No confirmed changes identified by current compatibility checks.</p>}
                  {handoff.actions.map((item,index) => <div className={styles.compatibilityCheck} key={index}>
                    <b>{item.resource.namespace ?? "Cluster"}/{item.resource.name} · {item.capability} · {item.status}</b>
                    <p>{item.reason}</p><small>Action: {item.nextAction}</small>
                  </div>)}
                </details>
                <details className={styles.compatibilityDetails}><summary>Evidence blockers / verification tasks · {handoff.evidence.length}</summary>
                  {handoff.evidence.map((item,index) => <div className={styles.compatibilityCheck} key={index}>
                    <b>{item.resource.namespace ?? "Cluster"}/{item.resource.name} · {item.capability} · {item.status}</b>
                    <p>{item.reason}</p><small>Verify: {item.nextAction}</small>
                  </div>)}
                </details>
              </div>
              <p className={styles.workflowStageWarning}>{handoff.note}</p>
            </section>;
          })()}
          {!backendEvaluationCurrent && <p className={styles.workflowStageWarning}>Current authoritative compatibility evaluations are unavailable. Remediation handoff remains unverified; existing draft findings below are preserved.</p>}
          <section className={styles.remediationKpis} aria-label="Remediation overview">
            <div><strong>{draft.resources.length}</strong><span>Resources in scope</span></div>
            <div><strong>{findings.length}</strong><span>Assessment findings</span></div>
            <div><strong>{draft.remediations.length}</strong><span>Decisions recorded</span></div>
            <div><strong>{readiness.issues.length}</strong><span>Outstanding checks</span></div>
          </section>
          <div className={styles.remediationWorkflowIntro}>
            <div><strong>Remediation workspace</strong><p>Resolve assessment findings, record target mappings, assign owners, and review artifact readiness. Draft decisions do not modify the source or target cluster.</p></div>
            <span>{draft.remediations.length} decisions recorded · {readiness.issues.length} readiness checks</span>
          </div>
          <nav className={styles.scopeViews} aria-label="Remediation workspace views">
            <button aria-current={remediationView === "FIXES" ? "page" : undefined} onClick={() => setRemediationView("FIXES")}>Recommended fixes · {findings.length}</button>
            <button aria-current={remediationView === "MAPPINGS" ? "page" : undefined} onClick={() => setRemediationView("MAPPINGS")}>Target mappings · {scopedStorageClaims.length}</button>
            <button aria-current={remediationView === "PLAN" ? "page" : undefined} onClick={() => setRemediationView("PLAN")}>Remediation plan · {draft.remediations.length}</button>
            <button aria-current={remediationView === "ARTIFACTS" ? "page" : undefined} onClick={() => setRemediationView("ARTIFACTS")}>Migration artifacts · Readiness</button>
          </nav>
          {remediationView === "ARTIFACTS" && <section className={styles.artifactReadinessPanel} aria-label="Migration Artifact Management">
        <div className={styles.artifactReadinessHead}><div><strong>Migration Artifact Management</strong><p>Artifact readiness is separate from resource discovery. Upload and ECR promotion must be authorized and validated before migration execution.</p></div><span>Foundation · Pending integration</span></div>
        <div className={styles.artifactReadinessGrid}>
          <div><strong>YAML manifests</strong><span>Not collected</span><small>S3 ingestion not yet connected</small></div>
          <div><strong>Helm packages</strong><span>Not collected</span><small>Charts and values require secure capture</small></div>
          <div><strong>Container images</strong><span>References only</span><small>Registry digest verification / ECR promotion pending</small></div>
          <div><strong>Migration artifact package</strong><span>Not generated</span><small>Approval and validation required</small></div>
        </div>
        <p>Artifact foundation: tenant-scoped S3 object paths and KMS-encrypted presigned upload contracts are available in the backend module. No artifact has been uploaded, validated or promoted by this screen.</p>
      </section>}

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
              <select aria-label="Remediation namespace" value={remediationNamespace} disabled={findingView === "SCOPE"} onChange={(e) => setNamespace(e.target.value)}>
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
          <section className={styles.remediationWorkloadPicker} aria-label="Workload-first remediation navigation">
            <div><strong>Review by workload</strong><p>Choose an application workload to focus its findings and remediation decisions. Select All workloads to review the complete assessment scope.</p></div>
            <div className={styles.remediationWorkloadChoices}>
              <button type="button" aria-pressed={remediationWorkload==="ALL"} onClick={()=>{setRemediationWorkload("ALL");setFindingView("SCOPE");setNamespace("");setSeverity("ALL");setRemediationCategory("ALL");}}>All workloads <small>{assessment.findings.length} total findings</small></button>
              {workloadFindingOptions.map(item=>{const key=JSON.stringify([item.namespace,item.name]);const count=assessment.findings.filter(f=>f.namespace===item.namespace&&f.resourceName===item.name).length;return <button type="button" key={key} aria-pressed={remediationWorkload===key} onClick={()=>{setRemediationWorkload(key);setFindingView("ALL");setNamespace(item.namespace);setSeverity("ALL");setRemediationCategory("ALL");const next=assessment.findings.findIndex(f=>f.namespace===item.namespace&&f.resourceName===item.name);if(next>=0)setFindingIndex(next);}}><strong>{item.name}</strong><small>{item.namespace} · {count} finding{count===1?"":"s"}</small></button>})}
              {remediationWorkload !== "ALL" && <button type="button" className={styles.remediationClearFocus} onClick={()=>{setRemediationWorkload("ALL");setFindingView("SCOPE");setNamespace("");setSeverity("ALL");setRemediationCategory("ALL");}}>Clear workload focus</button>}
            </div>
          </section>
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
      {tab === "review" && <section className={styles.migrationSummaryPanel} aria-label="Migration Summary and Export">
        <div className={styles.migrationSummaryHead}><div><strong>Migration Summary &amp; Export</strong><p>Review the current scope and download a planning report. Exports are snapshots of the current draft, including unsaved changes.</p></div><div className={styles.migrationExportActions}><button type="button" onClick={()=>downloadReport("json")}>Export JSON</button><button type="button" onClick={()=>downloadReport("csv")}>Export CSV</button><button type="button" onClick={()=>window.print()}>Print / Save PDF</button></div></div>
        <div role="status" className={styles.workflowStageWarning}>Report evidence: {migrationSummary.evidenceVerification.status.replaceAll("_", " ")}. {migrationSummary.evidenceVerification.limitations.length ? migrationSummary.evidenceVerification.limitations.join(" ") : "Source and target evidence are available; final migration approval remains separate."}</div>
      <section className={styles.targetCapabilitySection} aria-label="Consolidated source-to-target assessment">
        <div className={styles.targetAssessmentHead}><div><strong>Consolidated compatibility and remediation report</strong>
          <p>Exports include the selected resources, every authoritative compatibility check, evidence gaps, remediation actions and a non-executable planning preview.</p></div></div>
        {backendEvaluationCurrent ? <>
          <div className={styles.remediationKpis}>
            <div><strong>{migrationSummary.compatibility.evaluatedResources}</strong><span>Evaluated resources</span></div>
            <div><strong>{migrationSummary.compatibility.checks}</strong><span>Compatibility checks</span></div>
            <div><strong>{migrationSummary.compatibility.remediationHandoff?.actions.length ?? 0}</strong><span>Remediation actions</span></div>
            <div><strong>{migrationSummary.compatibility.remediationHandoff?.evidence.length ?? 0}</strong><span>Evidence tasks</span></div>
          </div>
          <p className={styles.workflowStageWarning}>Assessment only · Execution NOT READY · Source dependency and target capability evidence remain subject to verification.</p>
          <details className={styles.compatibilityDetails}><summary>Workload-level report · {migrationSummary.compatibility.migrationPlanPreview?.workloads.length ?? 0} workloads</summary>
            {migrationSummary.compatibility.migrationPlanPreview?.workloads.map(item=><div className={styles.compatibilityCheck} key={resourceKey(item.resource)}>
              <strong>{item.resource.namespace ?? "Cluster"}/{item.resource.name} · {item.resource.kind}</strong>
              <p>Source: {item.sourceStatus.replaceAll("_"," ")} · Target: {item.targetStatus.replaceAll("_"," ")}</p>
              <small>{item.remediationCount} actions · {item.verificationCount} evidence checks</small>
            </div>)}
          </details>
        </> : <p className={styles.workflowStageWarning}>Saved, current authoritative compatibility evidence is not available. Exports clearly mark the compatibility section unavailable; they are not approval-ready reports.</p>}
      </section>
      <div className={styles.migrationSummaryGrid}><div><span>Discovered workloads</span><b>{analyzedWorkloadCandidates.length}</b></div><div><span>Draft resources</span><b>{draft.resources.length}</b></div><div><span>Dependency-flagged</span><b>{dependencies}</b></div><div><span>Readiness checks</span><b>{readiness.issues.length}</b></div></div>
        <p className={styles.migrationSummaryEvidence}>Evidence: {graph.coverage==="REFERENCES_AVAILABLE"?"References collected":"Relationship references not collected"} · Data strategy: {draft.dataStrategy.replaceAll("_"," ")} · Artifact package: Not created</p>
        <p className={styles.migrationSummaryEvidence}>YAML / Helm artifacts have not been collected into S3; container images have not been promoted to ECR. Reports include metadata only.</p>
      </section>}
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
        <button className="button button-secondary" type="button" disabled={tab==="scope"} onClick={()=>navigateToStep(workflowSteps[Math.max(0,workflowSteps.indexOf(tab)-1)]!)}><ArrowLeft size={16}/> Previous step</button>
        <p>{save.isPending?"Saving draft…":message||(dirty?"Unsaved planning changes":`Assessment v${assessment.assessmentVersion} · Draft only`)}</p>
        {tab==="scope" && <button className="button button-secondary" type="button" disabled={!canEdit||stale||save.isPending} onClick={()=>void clearPlanningDraft()}>Clear Draft</button>}
        <button className="button button-secondary" type="button" disabled={!canEdit||stale||!dirty||save.isPending} onClick={()=>save.mutate(preparePlanningDraft(draft,scopeNamespaces))}>{save.isPending?"Saving…":"Save draft"}</button>
        <button className="button button-primary" type="button" disabled={tab==="review"||save.isPending||(tab==="scope"&&(!canEdit||stale||scopeGateIssues.length>0))} title={tab==="scope"&&scopeGateIssues.length?scopeGateIssues[0]:undefined} onClick={()=>{if(tab==="scope")void continueToTarget();else navigateToStep(workflowSteps[Math.min(workflowSteps.length-1,workflowSteps.indexOf(tab)+1)]!);}}>Continue to {tab==="scope"?"target":tab==="target"?"compatibility":tab==="compatibility"?"remediation":tab==="remediate"?"migration plan":"review"} <ArrowRight size={16}/></button>
      </footer>
    </div>
  );
}
