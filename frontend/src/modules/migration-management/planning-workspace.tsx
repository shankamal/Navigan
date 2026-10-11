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
  const [namespace, setNamespace] = useState("");
  const [search, setSearch] = useState("");
  const [resourceView, setResourceView] = useState<"ALL" | "WORKLOADS" | "DEPENDENCIES" | "CONFIGURATION" | "DATA">("ALL");
  const [severity, setSeverity] = useState("ALL");
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

  const sourceReferences = resources.flatMap((r) => {
    const input = r.kind === "Ingress" ? r.backendServiceReferences : workloadKinds.has(r.kind) ? r.dependencyReferences : null;
    if (!Array.isArray(input)) return [];
    return input.flatMap((ref: unknown) => {
      if (!ref || typeof ref !== "object") return [];
      const entry = ref as Record<string, unknown>;
      if (typeof entry.kind !== "string" || typeof entry.name !== "string") return [];
      return [{
        owner: r.kind + " " + r.name, namespace: r.namespace,
        kind: entry.kind, name: entry.name,
        present: resources.some((other) => other.kind === entry.kind && other.name === entry.name && other.namespace === r.namespace),
      }];
    });
  }).filter((ref) => !namespace || ref.namespace === namespace);
  const chosenOwners = new Set(draft.resources.filter((item) => !item.dependency).map((item) => JSON.stringify([item.kind, item.namespace, item.name])));
  const scopedReferences = sourceReferences.filter((ref) => chosenOwners.has(JSON.stringify([ref.owner.split(" ")[0], ref.namespace, ref.owner.slice(ref.owner.indexOf(" ") + 1)])));
  const missingReferences = scopedReferences.filter((ref) => !ref.present);
  const unselectedReferences = scopedReferences.filter((ref) => ref.present && !draft.resources.some((item) => item.kind === ref.kind && item.name === ref.name && item.namespace === ref.namespace));
  const relevantPvcs = resources.filter((r) => r.kind === "PersistentVolumeClaim" && (!namespace || r.namespace === namespace));
  const scopedResourceKeys = new Set(draft.resources.map((r) =>
    JSON.stringify([r.kind, r.namespace ?? null, r.name])));
  const scopedNamespaces = new Set(draft.resources.map((r) => r.namespace).filter((n): n is string => Boolean(n)));
  const findingScope = (item: Assessment["findings"][number]) => {
    if (!item.resourceName || !item.resourceKind || !item.namespace) return "SHARED";
    return scopedResourceKeys.has(JSON.stringify([item.resourceKind, item.namespace, item.resourceName]))
      ? "SCOPE" : "OUTSIDE";
  };
  const findings = assessment.findings
    .map((finding, index) => ({ finding, index }))
    .filter(({ finding }) =>
      (severity === "ALL" || finding.severity === severity) &&
      (findingView === "ALL"
        ? (!namespace || finding.namespace === namespace)
        : findingView === "SHARED"
          ? findingScope(finding) === "SHARED" &&
            (!namespace || !finding.namespace || finding.namespace === namespace)
          : findingScope(finding) === "SCOPE")
    );
  // The previous selection may no longer be visible after filtering.
  const activeFindingIndex = findings.some(({ index }) => index === findingIndex)
    ? findingIndex
    : (findings[0]?.index ?? -1);
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
            {resourceView === "DEPENDENCIES" && (
              <div className={styles.notice}>
                <strong>Source reference evidence · {sourceReferences.length} relationships</strong>
                {sourceReferences.length === 0 ? <p>No references in this snapshot; collect fresh inventory before concluding dependencies are absent.</p> : <ul>{sourceReferences.map((ref, i) => <li key={i}>{ref.owner} → {ref.kind} {ref.name} — {ref.present ? "Found in inventory" : "Not found in inventory"}</li>)}</ul>}
                <p><strong>{scopedReferences.length} references from selected primary resources</strong> · {missingReferences.length} missing inventory objects · {unselectedReferences.length} not included in draft.</p>
                {missingReferences.length > 0 && <p>Missing: {missingReferences.map((ref) => ref.kind + " " + ref.name).join(", ")}. Confirm collection coverage before proceeding.</p>}
                {unselectedReferences.length > 0 && <button type="button" className="button button-secondary" disabled={!canEdit || stale || save.isPending} onClick={() => {
                  const additions = resources.filter((r) => unselectedReferences.some((ref) => ref.kind === r.kind && ref.name === r.name && ref.namespace === r.namespace)).map((r) => ({
                    apiVersion: r.apiVersion, kind: r.kind, namespace: r.namespace ?? null, name: r.name,
                    treatment: recommendResource(r).resource.treatment, dependency: true,
                  } as PlannedResource));
                  const next = new Map(draft.resources.map((item) => [resourceKey(item), item]));
                  additions.forEach((item) => next.set(resourceKey(item), item));
                  change({ ...draft, resources: [...next.values()] });
                  setMessage("Referenced supporting resources added to draft for review. Save the draft to persist.");
                }}>Include {unselectedReferences.length} referenced dependencies in draft</button>}
                <p>Presence in inventory does not establish target readiness or complete discovery. All dependency additions require review.</p>
              </div>
            )}
            {resourceView === "DATA" && (
              <div className={styles.notice}>
                <strong>PVC consumer references</strong>
                {sourceReferences.filter((ref) => ref.kind === "PersistentVolumeClaim").length === 0 ? <p>No PVC consumer references in this snapshot. This does not prove there is no persistent data.</p> : <ul>{sourceReferences.filter((ref) => ref.kind === "PersistentVolumeClaim").map((ref, i) => <li key={i}>{ref.owner} → PVC {ref.name} — {ref.present ? "Claim inventoried" : "Claim missing from inventory"}</li>)}</ul>}
                <strong>Discovered PVC inventory · {relevantPvcs.length} claims</strong>
                {relevantPvcs.length === 0 ? <p>No PVC definitions inventoried in this view.</p> : <ul>{relevantPvcs.map((pvc) => <li key={resourceKey({...pvc, namespace: pvc.namespace ?? null})}><strong>{pvc.name}</strong> · {pvc.namespace} · {pvc.requestedStorage ?? "capacity unknown"} · {pvc.storageClassName ?? "StorageClass unspecified"} · {Array.isArray(pvc.accessModes) ? pvc.accessModes.join(", ") : "access mode unknown"} · {draft.resources.some((item) => item.kind === "PersistentVolumeClaim" && item.name === pvc.name && item.namespace === pvc.namespace) ? "Selected" : "Not selected"} · {scopedReferences.some((ref) => ref.kind === "PersistentVolumeClaim" && ref.name === pvc.name && ref.namespace === pvc.namespace) ? "Referenced by selected workload" : "No selected-workload reference captured"}</li>)}</ul>}
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
          <div className={styles.notice}>
            <strong>Guided remediation · {draft.resources.length} selected resources</strong>
            <p>Start with selected-scope findings. Review shared risks separately, then consult all assessment findings for audit. Changing the migration scope updates this view without modifying the assessment.</p>
            {draft.resources.length === 0 && (
              <p>No workloads have been included in the planning draft. Return to Scope &amp; target, select your workloads, and confirm required dependencies before remediation.</p>
            )}
          </div>
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
            <strong>{findings.filter(({ finding }) => finding.severity === "BLOCKER").length} visible blockers</strong>
            <span>
              {draft.remediations.filter((r) => r.evidenceReference).length}{" "}
              evidence references · verification pending
            </span>
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
            {findings.length} findings shown · {draft.resources.length} resources in draft · {scopedNamespaces.size} selected namespace(s).
            {findingView === "SCOPE" ? " Only findings for exact selected resources are shown. No findings does not imply readiness; dependencies may be incomplete." : " Full assessment evidence is preserved; filtering does not resolve findings."}
          </p>
          <div className={styles.remediationColumns}>
            <div className={styles.tableScroll}>
              <table>
                <thead>
                  <tr>
                    <th>Finding</th>
                    <th>Affected resource</th>
                    <th>Owner</th>
                    <th>Evidence status</th>
                  </tr>
                </thead>
                <tbody>
                  {findings.map(({ finding: f, index }) => {
                    const item = draft.remediations.find(
                      (r) => r.findingIndex === index,
                    );
                    return (
                      <tr
                        key={index}
                        className={
                          index === activeFindingIndex ? styles.selectedRow : ""
                        }
                      >
                        <td>
                          <button
                            className={styles.findingButton}
                            onClick={() => setFindingIndex(index)}
                          >
                            <span
                              className={
                                f.severity === "BLOCKER"
                                  ? styles.blocker
                                  : styles.severity
                              }
                            >
                              {f.severity}
                            </span>
                            {f.message}
                          </button>
                        </td>
                        <td>
                          {f.resourceName ?? "Assessment-wide"}
                          <small>
                            {f.namespace ?? "Cluster"} ·{" "}
                            {f.resourceKind ?? f.category}
                          </small>
                        </td>
                        <td>{item?.owner || "Unassigned"}</td>
                        <td>
                          {item?.evidenceReference
                            ? "Evidence attached; not verified"
                            : "Not verified"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <aside className={styles.detail}>
              {finding ? (
                <>
                  <div className={styles.notice} aria-live="polite">
                    {acceptedSuggestion ? (
                      <p><strong>Remediation added to draft — not yet saved.</strong> Review the treatment and target mapping below, assign an owner, then save the draft. This does not change EKS resources.</p>
                    ) : (
                      <>
                        <strong>Navigan suggested remediation</strong>
                        <p>Treatment: {suggestedRemediation?.treatment ?? "REVIEW"}</p>
                        <p>Proposed target mapping: {suggestedRemediation?.targetMapping ?? "Review required"}</p>
                        <button className="button button-secondary" disabled={!canEdit || stale || save.isPending || !suggestedRemediation} onClick={() => { if (suggestedRemediation) changeRemediation(suggestedRemediation); }}>
                          Apply recommendation to draft
                        </button>
                      </>
                    )}
                  </div>
                  <h2>
                    <Wrench size={20} />
                    {finding.code
                      .replaceAll("_", " ")
                      .toLowerCase()
                      .replace(/^./, (letter) => letter.toUpperCase())}
                  </h2>
                  <p>{finding.message}</p>
                  <p className={styles.caption}>
                    {finding.remediation ??
                      "Review this finding with the application owner."}
                  </p>
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
                    <button
                      disabled
                      title="Target action runner not implemented"
                    >
                      Apply change
                    </button>
                    <button
                      disabled
                      title="Target verification runner not implemented"
                    >
                      Verify remediation
                    </button>
                  </div>
                </>
              ) : (
                <p>No findings match the selected namespace and severity.</p>
              )}
            </aside>
          </div>
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
