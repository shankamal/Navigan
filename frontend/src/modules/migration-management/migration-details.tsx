"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { useClusters } from "@/modules/cluster-management/hooks/queries";
import { normalizeApiError } from "@/shared/api/client";
import { useAuth } from "@/shared/auth/auth-provider";
import { hasPermission } from "@/shared/auth/permissions";
import { PageHeading } from "@/shared/components/ui";

import { AssessmentReportCard } from "./assessment-report";
import {
  useMigration,
  useMigrationAssessment,
  useSourceCatalogue,
  useSourceClusters,
  useSourceInventory,
} from "./hooks";
import type {
  SourceClusterRegistration,
  SourceEnrollment,
  SourceInstallation,
} from "./model";
import { PlatformIcon } from "./platform-icon";
import { migrations, sourceClusters } from "./service";
import styles from "./migration-management.module.css";

export function MigrationDetails({ migrationId }: { migrationId: string }) {
  const { identity } = useAuth();
  const cache = useQueryClient();
  const [sourceEnrollment, setSourceEnrollment] =
    useState<SourceEnrollment | null>(null);
  const [sourceInstallation, setSourceInstallation] =
    useState<SourceInstallation | null>(null);
  const [registeredSource, setRegisteredSource] =
    useState<SourceClusterRegistration | null>(null);
  const [sourceName, setSourceName] = useState("");
  const [sourceDistribution, setSourceDistribution] = useState("kubeadm");
  const [sourceRegion, setSourceRegion] = useState("ap-south-1");
  const [sourceAwsAccountId, setSourceAwsAccountId] = useState("");
  const [sourceManagedInstanceId, setSourceManagedInstanceId] = useState("");
  const [sourceRoleArn, setSourceRoleArn] = useState("");
  const [sourceKubeconfigPath, setSourceKubeconfigPath] = useState(
    "/etc/kubernetes/admin.conf",
  );
  const [sourceError, setSourceError] = useState("");
  const [assessmentNamespaces, setAssessmentNamespaces] = useState<string[]>(
    [],
  );
  const [assessmentTargetClusterId, setAssessmentTargetClusterId] =
    useState("");
  const [assessmentScopeSaved, setAssessmentScopeSaved] = useState(false);
  const [assessmentMigrationVersion, setAssessmentMigrationVersion] = useState<
    number | null
  >(null);
  const [assessmentError, setAssessmentError] = useState("");
  const migrationQuery = useMigration(migrationId);
  const migration = migrationQuery.data;
  const assessmentQuery = useMigrationAssessment(migrationId, true);
  const assessment = assessmentQuery.data?.assessment ?? null;
  const criticalFindingCount =
    assessment?.findings.filter((finding) => finding.severity === "BLOCKER")
      .length ?? 0;
  const sourceInventoryQuery = useSourceInventory(
    migrationId,
    Boolean(assessment),
  );
  const sourceInventory = sourceInventoryQuery.data?.inventory ?? null;
  const catalogueQuery = useSourceCatalogue(migrationId);
  const sourceCatalogue = catalogueQuery.data?.catalogue ?? null;
  const clustersQuery = useClusters({
    page: 0,
    pageSize: 100,
    status: "ACTIVE",
  });
  const sourceClustersQuery = useSourceClusters(migration?.customerId ?? "");
  const sourceClusterId =
    typeof migration?.sourceConfiguration.sourceClusterId === "string"
      ? migration.sourceConfiguration.sourceClusterId
      : "";
  const sourceCluster = sourceClustersQuery.data?.items.find(
    (item) => item.sourceClusterId === sourceClusterId,
  );
  const effectiveSourceCluster = registeredSource ?? sourceCluster;
  const targetEnvironmentId =
    typeof migration?.targetConfiguration.environmentId === "string"
      ? migration.targetConfiguration.environmentId
      : "";
  const targetClusters = (clustersQuery.data?.items ?? []).filter(
    (cluster) =>
      cluster.customerId === migration?.customerId &&
      cluster.platform === "EKS" &&
      cluster.status === "ACTIVE",
  );
  const selectedAssessmentTarget = targetClusters.find(
    (cluster) => cluster.clusterId === assessmentTargetClusterId,
  );
  const persistedNamespaces = Array.isArray(
    migration?.migrationScope.namespaces,
  )
    ? migration.migrationScope.namespaces.filter(
        (namespace): namespace is string => typeof namespace === "string",
      )
    : [];
  const persistedTargetClusterId =
    typeof migration?.targetConfiguration.clusterId === "string"
      ? migration.targetConfiguration.clusterId
      : "";
  const persistedScopeReady =
    persistedNamespaces.length > 0 && Boolean(persistedTargetClusterId);
  const matchingPendingSource =
    registeredSource ??
    sourceClustersQuery.data?.items.find(
      (item) =>
        item.status !== "REVOKED" &&
        item.name.toLowerCase() === sourceName.trim().toLowerCase(),
    );

  const sourceRegistration = useMutation({
    mutationFn: async () => {
      if (!migration) {
        throw new Error("Migration is unavailable.");
      }
      const registered =
        matchingPendingSource ??
        (await sourceClusters.create({
          customerId: migration.customerId,
          name: sourceName.trim(),
          distribution: sourceDistribution.trim() || undefined,
          registrationMethod: "PROVIDER_AUTOMATION",
          location: {
            type: "CLOUD",
            cloudProvider: "AWS",
            region: sourceRegion.trim() || undefined,
          },
          delivery: {
            method: "AWS_SSM",
            awsSsm: {
              accountId: sourceAwsAccountId.trim(),
              region: sourceRegion.trim(),
              managedInstanceId: sourceManagedInstanceId.trim(),
              roleArn: sourceRoleArn.trim() || undefined,
              kubeconfigPath: sourceKubeconfigPath.trim(),
            },
          },
        }));
      setRegisteredSource(registered);
      await migrations.update(migration.migrationId, {
        version: migration.version,
        source: {
          platform: "SELF_MANAGED_KUBERNETES",
          sourceClusterId: registered.sourceClusterId,
          clusterName: registered.name,
          accessMode: "READ_ONLY_CONNECTOR",
        },
        changeReason: "Attach registered source cluster",
      });
      const issuedEnrollment = await sourceClusters.enroll(
        registered.sourceClusterId,
        registered.version,
      );
      return { registered, issuedEnrollment };
    },
    onSuccess: async ({ registered, issuedEnrollment }) => {
      setRegisteredSource(registered);
      setSourceEnrollment(issuedEnrollment);
      setSourceError("");
      await cache.invalidateQueries({
        queryKey: ["migrations", migrationId],
      });
      await cache.invalidateQueries({
        queryKey: ["source-clusters", migration?.customerId],
      });
    },
    onError: (error) => {
      setSourceError(normalizeApiError(error).message);
    },
  });

  const enrollment = useMutation({
    mutationFn: async () => {
      if (!effectiveSourceCluster) {
        throw new Error("The registered source cluster is unavailable.");
      }
      return sourceClusters.enroll(
        effectiveSourceCluster.sourceClusterId,
        effectiveSourceCluster.version,
      );
    },
    onSuccess: setSourceEnrollment,
  });

  const deliveryConfiguration = useMutation({
    mutationFn: async () => {
      if (!effectiveSourceCluster) {
        throw new Error("The registered source cluster is unavailable.");
      }
      return sourceClusters.updateDelivery(
        effectiveSourceCluster.sourceClusterId,
        {
          version: effectiveSourceCluster.version,
          delivery: {
            method: "AWS_SSM",
            awsSsm: {
              accountId: sourceAwsAccountId.trim(),
              region: sourceRegion.trim(),
              managedInstanceId: sourceManagedInstanceId.trim(),
              roleArn: sourceRoleArn.trim() || undefined,
              kubeconfigPath: sourceKubeconfigPath.trim(),
            },
          },
          reason: "Configure secure source connector delivery",
        },
      );
    },
    onSuccess: async (updated) => {
      setRegisteredSource(updated);
      setSourceError("");
      await cache.invalidateQueries({
        queryKey: ["source-clusters", migration?.customerId],
      });
    },
    onError: (error) => {
      setSourceError(normalizeApiError(error).message);
    },
  });

  const automaticInstallation = useMutation({
    mutationFn: async () => {
      if (!effectiveSourceCluster) {
        throw new Error("The registered source cluster is unavailable.");
      }
      return sourceClusters.install(
        effectiveSourceCluster.sourceClusterId,
        effectiveSourceCluster.version,
      );
    },
    onSuccess: (installation) => {
      setSourceInstallation(installation);
      setSourceError("");
    },
    onError: (error) => {
      setSourceError(normalizeApiError(error).message);
    },
  });

  const assessmentScope = useMutation({
    mutationFn: async () => {
      if (
        !migration ||
        !sourceClusterId ||
        !selectedAssessmentTarget ||
        assessmentNamespaces.length === 0
      ) {
        throw new Error("Select workloads and an eligible target cluster.");
      }
      const environmentApprovedVersion = Number(
        selectedAssessmentTarget.environmentApprovedVersion,
      );
      if (
        !selectedAssessmentTarget.environmentId ||
        !environmentApprovedVersion
      ) {
        throw new Error("The approved target environment is unavailable.");
      }

      return migrations.update(migration.migrationId, {
        version: catalogueQuery.data?.version ?? migration.version,
        source: {
          platform: "SELF_MANAGED_KUBERNETES",
          sourceClusterId,
          accessMode: "READ_ONLY_CONNECTOR",
        },
        target: {
          platform: "EKS",
          targetType: "EXISTING_CLUSTER",
          environmentId: selectedAssessmentTarget.environmentId,
          environmentApprovedVersion,
          clusterId: selectedAssessmentTarget.clusterId,
          clusterName: selectedAssessmentTarget.clusterName,
          endpointAccess: "PRIVATE",
        },
        scope: {
          namespaces: assessmentNamespaces,
          excludeNamespaces: ["kube-node-lease", "kube-public", "kube-system"],
          includeClusterScopedResources: false,
          includePersistentData: false,
        },
        changeReason: "Save discovered workload scope and target cluster",
      });
    },
    onSuccess: async (updated) => {
      setAssessmentScopeSaved(true);
      setAssessmentMigrationVersion(updated.version);
      setAssessmentError("");
      await cache.invalidateQueries({
        queryKey: ["migrations", migrationId],
      });
    },
    onError: (error) => {
      setAssessmentError(normalizeApiError(error).message);
    },
  });

  const detailedAssessment = useMutation({
    mutationFn: async () => {
      if (!migration) {
        throw new Error("Migration is unavailable.");
      }
      return migrations.assess(
        migration.migrationId,
        assessmentMigrationVersion ?? migration.version,
      );
    },
    onSuccess: async () => {
      setAssessmentError("");
      await cache.invalidateQueries({
        queryKey: ["migrations", migrationId],
      });
      await cache.invalidateQueries({
        queryKey: ["migrations", migrationId, "assessment"],
      });
    },
    onError: (error) => {
      setAssessmentError(normalizeApiError(error).message);
    },
  });

  const action = useMutation({
    mutationFn: async ({
      name,
      reason,
    }: {
      name: "submit" | "review" | "approve" | "reject";
      reason: string;
    }) => {
      if (!migration) throw new Error("Migration is unavailable.");
      return migrations.action(
        migration.migrationId,
        name,
        migration.version,
        reason,
      );
    },
    onSuccess: async () => {
      await cache.invalidateQueries({
        queryKey: ["migrations", migrationId],
      });
      await cache.invalidateQueries({ queryKey: ["migrations"] });
    },
  });

  const canSubmit =
    migration?.status === "ASSESSMENT_READY" &&
    hasPermission(identity, "migration.submit");
  const canReview =
    migration?.status === "SUBMITTED" &&
    hasPermission(identity, "migration.review");
  const canDecide =
    migration?.status === "UNDER_REVIEW" &&
    hasPermission(identity, "migration.approve");
  const canPrepareSource =
    migration?.status === "SOURCE_ENROLLMENT_PENDING" &&
    hasPermission(identity, "migration.edit");
  const canEditAssessment = hasPermission(identity, "migration.edit");
  const sourceRegistrationMissing =
    migration?.status === "SOURCE_ENROLLMENT_PENDING" &&
    !sourceClustersQuery.isPending &&
    (!sourceClusterId || !sourceCluster);

  useEffect(() => {
    if (assessmentNamespaces.length === 0) {
      if (persistedNamespaces.length > 0) {
        setAssessmentNamespaces(persistedNamespaces);
      } else if (sourceCatalogue) {
        setAssessmentNamespaces(
          sourceCatalogue.namespaces.map((namespace) => namespace.name),
        );
      }
    }
    if (!assessmentTargetClusterId && persistedTargetClusterId) {
      setAssessmentTargetClusterId(persistedTargetClusterId);
    }
  }, [
    assessmentNamespaces.length,
    assessmentTargetClusterId,
    persistedNamespaces,
    persistedTargetClusterId,
    sourceCatalogue,
  ]);

  function downloadSourceBootstrap() {
    if (!sourceEnrollment || !effectiveSourceCluster) return;

    const apiBaseUrl =
      process.env.NEXT_PUBLIC_MIGRATION_CONNECTOR_API_BASE_URL ?? "";
    const imageRepository =
      process.env.NEXT_PUBLIC_MIGRATION_CONNECTOR_IMAGE_REPOSITORY ?? "";
    const imageDigest =
      process.env.NEXT_PUBLIC_MIGRATION_CONNECTOR_IMAGE_DIGEST ?? "";
    if (!apiBaseUrl || !imageRepository || !imageDigest) return;

    const bootstrap = JSON.stringify(
      {
        apiBaseUrl,
        sourceClusterId: effectiveSourceCluster.sourceClusterId,
        enrollmentToken: sourceEnrollment.enrollmentToken,
        enrollmentExpiresAt: sourceEnrollment.expiresAt,
        imageRepository,
        imageDigest,
      },
      null,
      2,
    );
    const url = URL.createObjectURL(
      new Blob([bootstrap], { type: "application/json" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `navigan-source-${effectiveSourceCluster.sourceClusterId}.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  const approvalControls = (
    <>
      {canSubmit && (
        <button
          type="button"
          className="button button-primary"
          disabled={action.isPending}
          onClick={() =>
            action.mutate({
              name: "submit",
              reason: "Submit feasibility assessment for review",
            })
          }
        >
          <ShieldCheck size={17} />
          Submit for review
        </button>
      )}
      {canReview && (
        <button
          type="button"
          className="button button-primary"
          disabled={action.isPending}
          onClick={() =>
            action.mutate({
              name: "review",
              reason: "Begin independent feasibility review",
            })
          }
        >
          <ShieldCheck size={17} />
          Start review
        </button>
      )}
      {canDecide && (
        <>
          <button
            type="button"
            className="button button-primary"
            disabled={action.isPending}
            onClick={() =>
              action.mutate({
                name: "approve",
                reason: "Approve migration for controlled planning",
              })
            }
          >
            <CheckCircle2 size={17} />
            Approve assessment
          </button>
          <button
            type="button"
            className={`button button-secondary ${styles.rejectAction}`}
            disabled={action.isPending}
            onClick={() =>
              action.mutate({
                name: "reject",
                reason: "Return migration assessment for remediation",
              })
            }
          >
            <XCircle size={17} />
            Return for changes
          </button>
        </>
      )}
      {!canSubmit && !canReview && !canDecide && (
        <span className={styles.approvalUnavailable}>
          No approval action is available for your role at this stage.
        </span>
      )}
    </>
  );

  return (
    <>
      <PageHeading
        eyebrow="MIGRATION"
        title={migration?.name ?? "Migration assessment"}
        description={
          assessment
            ? `Self-managed Kubernetes (${effectiveSourceCluster?.name ?? "source cluster"}) → Amazon EKS (${
                assessment.inventorySummary.target.clusterName ??
                "target cluster"
              }) · ${migration?.status.replaceAll("_", " ").toLowerCase()}`
            : "Review the trusted feasibility report and govern approval independently from the request creator."
        }
        className={migration ? styles.assessmentHeading : undefined}
        action={
          <Link href="/migrations" className="button button-secondary">
            <ArrowLeft size={17} />
            Back to migrations
          </Link>
        }
      />

      {migrationQuery.isPending && <div className="panel">Loading…</div>}
      {migrationQuery.isError && (
        <div className="panel" role="alert">
          Unable to load this migration assessment.
        </div>
      )}

      {assessment && (
        <section
          className={styles.migrationContextBar}
          aria-label="Migration source and target"
        >
          <div className={styles.migrationContextCluster}>
            <PlatformIcon platform="SELF_MANAGED_KUBERNETES" size="medium" />
            <div>
              <span>Source cluster</span>
              <strong>
                {effectiveSourceCluster?.name ?? "Self-managed Kubernetes"}
              </strong>
              <small>
                Kubernetes {assessment.sourceKubernetesVersion} ·{" "}
                {sourceCatalogue?.nodeCount ?? "—"} nodes
              </small>
            </div>
          </div>

          <div className={styles.migrationContextPath}>
            <span>
              {persistedNamespaces.length > 0
                ? `${persistedNamespaces.length} namespaces`
                : "Selected workloads"}
            </span>
            <ArrowRight size={20} aria-hidden="true" />
          </div>

          <div className={styles.migrationContextCluster}>
            <PlatformIcon platform="EKS" size="medium" />
            <div>
              <span>Target cluster</span>
              <strong>
                {assessment.inventorySummary.target.clusterName ?? "Amazon EKS"}
              </strong>
              <small>
                Amazon EKS ·{" "}
                {assessment.inventorySummary.target.readyNodeCount ?? "—"} /{" "}
                {assessment.inventorySummary.target.nodeCount ?? "—"} nodes
                ready
              </small>
            </div>
          </div>

          <div className={styles.migrationContextMeta}>
            <span
              className={`status-badge ${migration?.status === "APPROVED" ? styles.approvedStatus : ""}`}
            >
              {migration?.status.replaceAll("_", " ")}
            </span>
            <small>Report generated</small>
            <strong>{new Date(assessment.createdAt).toLocaleString()}</strong>
          </div>
        </section>
      )}

      {migration && (
        <>
          {!assessment && (
            <section className={`panel ${styles.approvalPanel}`}>
              <div className={styles.approvalSummary}>
                <div className={styles.approvalIcon} aria-hidden="true">
                  <ShieldCheck size={24} />
                </div>
                <div>
                  <div className={styles.approvalStatusLine}>
                    <span
                      className={`status-badge ${migration?.status === "APPROVED" ? styles.approvedStatus : ""}`}
                    >
                      {migration.status.replaceAll("_", " ")}
                    </span>
                    <span>Independent governance checkpoint</span>
                  </div>
                  <h2>
                    {canDecide
                      ? "Management decision required"
                      : canReview
                        ? "Assessment ready for independent review"
                        : canSubmit
                          ? "Assessment ready to submit"
                          : "Approval gate"}
                  </h2>
                  <p className="muted">
                    Review feasibility, blockers, and remediation evidence
                    before authorizing migration planning. Approval does not
                    change either cluster.
                  </p>
                </div>
              </div>

              <div className={styles.approvalActions}>{approvalControls}</div>

              {action.isError && (
                <p role="alert">{normalizeApiError(action.error).message}</p>
              )}
            </section>
          )}

          {migration.status === "REJECTED" && canEditAssessment && (
            <section className={`panel ${styles.connectionCard}`}>
              <div>
                <h2>Refresh migration assessment</h2>
                <p className="muted">
                  Reuse the connected source cluster, saved workload scope, and
                  selected target cluster to collect a new inventory and
                  generate the next assessment version.
                </p>
              </div>
              <button
                type="button"
                className="button button-primary"
                disabled={
                  detailedAssessment.isPending ||
                  migration.sourceConfiguration.sourceClusterId == null ||
                  !persistedScopeReady
                }
                onClick={() => detailedAssessment.mutate()}
              >
                {detailedAssessment.isPending
                  ? "Refreshing assessment…"
                  : "Refresh assessment"}
              </button>
              {detailedAssessment.isError && (
                <p role="alert">
                  {normalizeApiError(detailedAssessment.error).message}
                </p>
              )}
            </section>
          )}

          {migration.status === "SOURCE_ENROLLMENT_PENDING" && (
            <section
              className={`panel ${styles.bootstrapNotice} ${
                sourceRegistrationMissing
                  ? styles.sourceRegistrationWarning
                  : ""
              }`}
            >
              {effectiveSourceCluster &&
                effectiveSourceCluster.deliveryMethod !== "AWS_SSM" && (
                  <div className={styles.deliveryConfiguration}>
                    <div>
                      <h2>Configure secure connector delivery</h2>
                      <p className="muted">
                        Record the AWS Systems Manager destination for the
                        one-shot connector. No inbound SSH access or kubeconfig
                        upload is required.
                      </p>
                    </div>
                    <div className={styles.contextGrid}>
                      <label className="field">
                        <span>AWS account ID</span>
                        <input
                          value={sourceAwsAccountId}
                          inputMode="numeric"
                          minLength={12}
                          maxLength={12}
                          placeholder="123456789012"
                          onChange={(event) =>
                            setSourceAwsAccountId(event.target.value)
                          }
                        />
                      </label>
                      <label className="field">
                        <span>AWS region</span>
                        <input
                          value={sourceRegion}
                          onChange={(event) =>
                            setSourceRegion(event.target.value)
                          }
                        />
                      </label>
                      <label className="field">
                        <span>Control-plane managed instance ID</span>
                        <input
                          value={sourceManagedInstanceId}
                          placeholder="i-0123456789abcdef0"
                          onChange={(event) =>
                            setSourceManagedInstanceId(event.target.value)
                          }
                        />
                      </label>
                      <label className="field">
                        <span>Cross-account role ARN (optional)</span>
                        <input
                          value={sourceRoleArn}
                          placeholder="Leave blank for this AWS account"
                          onChange={(event) =>
                            setSourceRoleArn(event.target.value)
                          }
                        />
                      </label>
                      <label className="field">
                        <span>Kubeconfig path</span>
                        <input
                          value={sourceKubeconfigPath}
                          onChange={(event) =>
                            setSourceKubeconfigPath(event.target.value)
                          }
                        />
                      </label>
                    </div>
                    <button
                      type="button"
                      className="button button-primary"
                      disabled={
                        deliveryConfiguration.isPending ||
                        !/^\d{12}$/.test(sourceAwsAccountId.trim()) ||
                        !/^(i-[0-9a-f]{8,17}|mi-[A-Za-z0-9-]+)$/.test(
                          sourceManagedInstanceId.trim(),
                        ) ||
                        sourceRegion.trim().length < 3 ||
                        !sourceKubeconfigPath.trim().startsWith("/")
                      }
                      onClick={() => deliveryConfiguration.mutate()}
                    >
                      {deliveryConfiguration.isPending
                        ? "Saving delivery profile…"
                        : "Save connector delivery profile"}
                    </button>
                    {sourceError && <p role="alert">{sourceError}</p>}
                  </div>
                )}
              {sourceRegistrationMissing ? (
                <>
                  <div role="alert">
                    <h2>Source registration was not completed</h2>
                    <p className="muted">
                      This earlier migration request has no registered source
                      cluster attached. Register it here to continue this same
                      migration request.
                    </p>
                  </div>
                  {sourceEnrollment ? (
                    <button
                      type="button"
                      className="button button-primary"
                      onClick={downloadSourceBootstrap}
                    >
                      Download connector setup
                    </button>
                  ) : (
                    <div className={styles.sourceRecoveryForm}>
                      <label className="field">
                        <span>Source cluster name</span>
                        <input
                          value={sourceName}
                          minLength={3}
                          maxLength={100}
                          placeholder="navigan-migration-lab"
                          onChange={(event) =>
                            setSourceName(event.target.value)
                          }
                        />
                      </label>
                      <label className="field">
                        <span>Kubernetes distribution</span>
                        <input
                          value={sourceDistribution}
                          maxLength={100}
                          onChange={(event) =>
                            setSourceDistribution(event.target.value)
                          }
                        />
                      </label>
                      <label className="field">
                        <span>AWS region</span>
                        <input
                          value={sourceRegion}
                          maxLength={64}
                          onChange={(event) =>
                            setSourceRegion(event.target.value)
                          }
                        />
                      </label>
                      <label className="field">
                        <span>AWS account ID</span>
                        <input
                          value={sourceAwsAccountId}
                          inputMode="numeric"
                          minLength={12}
                          maxLength={12}
                          placeholder="123456789012"
                          onChange={(event) =>
                            setSourceAwsAccountId(event.target.value)
                          }
                        />
                      </label>
                      <label className="field">
                        <span>Control-plane managed instance ID</span>
                        <input
                          value={sourceManagedInstanceId}
                          placeholder="i-0123456789abcdef0"
                          onChange={(event) =>
                            setSourceManagedInstanceId(event.target.value)
                          }
                        />
                      </label>
                      <label className="field">
                        <span>Cross-account role ARN (optional)</span>
                        <input
                          value={sourceRoleArn}
                          placeholder="Leave blank for this AWS account"
                          onChange={(event) =>
                            setSourceRoleArn(event.target.value)
                          }
                        />
                      </label>
                      <label className="field">
                        <span>Kubeconfig path</span>
                        <input
                          value={sourceKubeconfigPath}
                          onChange={(event) =>
                            setSourceKubeconfigPath(event.target.value)
                          }
                        />
                      </label>
                      <button
                        type="button"
                        className="button button-primary"
                        disabled={
                          sourceName.trim().length < 3 ||
                          !/^\d{12}$/.test(sourceAwsAccountId.trim()) ||
                          !/^(i-[0-9a-f]{8,17}|mi-[A-Za-z0-9-]+)$/.test(
                            sourceManagedInstanceId.trim(),
                          ) ||
                          sourceRegion.trim().length < 3 ||
                          !sourceKubeconfigPath.trim().startsWith("/") ||
                          sourceRegistration.isPending
                        }
                        onClick={() => sourceRegistration.mutate()}
                      >
                        {sourceRegistration.isPending
                          ? "Attaching source cluster…"
                          : matchingPendingSource
                            ? "Attach existing source cluster"
                            : "Register source cluster"}
                      </button>
                      {sourceError && <p role="alert">{sourceError}</p>}
                    </div>
                  )}
                </>
              ) : (
                <>
                  <div>
                    <strong>Source connector setup required</strong>
                    <p className="muted">
                      {effectiveSourceCluster?.deliveryMethod === "AWS_SSM"
                        ? "Install the read-only connector through the approved AWS Systems Manager delivery role."
                        : "Reissue a short-lived setup file for the existing registered source cluster. This does not create another source cluster or migration request."}
                    </p>
                  </div>
                  {sourceInstallation ? (
                    <div role="status">
                      <strong>Connector installation started</strong>
                      <p className="muted">
                        Systems Manager command {sourceInstallation.commandId}{" "}
                        is running on {sourceInstallation.managedInstanceId}.
                      </p>
                    </div>
                  ) : effectiveSourceCluster?.deliveryMethod === "AWS_SSM" ? (
                    <button
                      type="button"
                      className="button button-primary"
                      disabled={
                        !canPrepareSource || automaticInstallation.isPending
                      }
                      onClick={() => automaticInstallation.mutate()}
                    >
                      {automaticInstallation.isPending
                        ? "Starting secure installation…"
                        : "Install source connector"}
                    </button>
                  ) : sourceEnrollment ? (
                    <button
                      type="button"
                      className="button button-primary"
                      onClick={downloadSourceBootstrap}
                    >
                      Download connector setup
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="button button-primary"
                      disabled={
                        !canPrepareSource ||
                        !sourceCluster ||
                        enrollment.isPending
                      }
                      onClick={() => enrollment.mutate()}
                    >
                      {enrollment.isPending
                        ? "Preparing connector setup…"
                        : "Prepare new connector setup"}
                    </button>
                  )}
                  {enrollment.isError && (
                    <p role="alert">
                      {normalizeApiError(enrollment.error).message}
                    </p>
                  )}
                  {sourceError && <p role="alert">{sourceError}</p>}
                </>
              )}
            </section>
          )}

          {migration.status === "INVENTORY_READY" && (
            <section className={`panel ${styles.connectionCard}`}>
              <div>
                <h2>Continue migration assessment</h2>
                <p className="muted">
                  Select the discovered workloads and target EKS cluster, then
                  assign detailed read-only inventory collection.
                </p>
              </div>

              {catalogueQuery.isPending && <p>Loading source catalogue…</p>}
              {catalogueQuery.isError && (
                <p role="alert">Unable to load the source catalogue.</p>
              )}

              {sourceCatalogue && (
                <>
                  <fieldset className={styles.namespaceList}>
                    <legend>Workloads to assess</legend>
                    {sourceCatalogue.namespaces.map((namespace) => (
                      <label key={namespace.name}>
                        <input
                          type="checkbox"
                          checked={assessmentNamespaces.includes(
                            namespace.name,
                          )}
                          onChange={() =>
                            setAssessmentNamespaces((current) =>
                              current.includes(namespace.name)
                                ? current.filter(
                                    (item) => item !== namespace.name,
                                  )
                                : [...current, namespace.name],
                            )
                          }
                        />
                        <span>{namespace.name}</span>
                        <small>
                          {Object.values(namespace.resourceCounts).reduce(
                            (total, count) => total + count,
                            0,
                          )}{" "}
                          discovered resources
                        </small>
                      </label>
                    ))}
                  </fieldset>

                  <label className="field">
                    <span>Target EKS cluster</span>
                    <select
                      value={
                        assessmentTargetClusterId || persistedTargetClusterId
                      }
                      onChange={(event) =>
                        setAssessmentTargetClusterId(event.target.value)
                      }
                    >
                      <option value="">
                        Select an eligible target cluster
                      </option>
                      {targetClusters.map((cluster) => (
                        <option
                          key={cluster.clusterId}
                          value={cluster.clusterId}
                        >
                          {cluster.clusterName}
                        </option>
                      ))}
                    </select>
                  </label>

                  {!assessmentScopeSaved && !persistedScopeReady ? (
                    <button
                      type="button"
                      className="button button-primary"
                      disabled={
                        !canEditAssessment ||
                        assessmentScope.isPending ||
                        assessmentNamespaces.length === 0 ||
                        !assessmentTargetClusterId
                      }
                      onClick={() => assessmentScope.mutate()}
                    >
                      {assessmentScope.isPending
                        ? "Saving assessment scope…"
                        : "Save assessment scope"}
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="button button-primary"
                      disabled={
                        !canEditAssessment ||
                        detailedAssessment.isPending ||
                        detailedAssessment.isSuccess
                      }
                      onClick={() => detailedAssessment.mutate()}
                    >
                      {detailedAssessment.isPending
                        ? "Starting detailed assessment…"
                        : detailedAssessment.isSuccess
                          ? "Assessment assigned"
                          : "Start detailed assessment"}
                    </button>
                  )}

                  {assessmentError && <p role="alert">{assessmentError}</p>}
                </>
              )}
            </section>
          )}
        </>
      )}

      {assessment && (
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>Plan migration</h2>
              <p>
                Choose workloads and track remediation against this assessment.
                Assessment approval does not authorize execution.
              </p>
            </div>
            <Link
              href={`/migrations/${migrationId}/plan`}
              className="button button-primary"
            >
              Open migration workspace <ArrowRight size={17} />
            </Link>
          </div>
        </section>
      )}
      {assessment && (
        <AssessmentReportCard
          report={assessment}
          inventory={sourceInventory}
          inventoryLoading={sourceInventoryQuery.isPending}
          inventoryError={sourceInventoryQuery.isError}
          source={{
            name: effectiveSourceCluster?.name,
            nodeCount: sourceCatalogue?.nodeCount,
            namespaceCount: sourceCatalogue?.namespaces.length,
            namespaces:
              persistedNamespaces.length > 0
                ? persistedNamespaces
                : sourceCatalogue?.namespaces.map(
                    (namespace) => namespace.name,
                  ),
            architectures: sourceCatalogue?.architectures,
          }}
          governance={{
            status: migration?.status,
          }}
        />
      )}
      {assessment && (
        <section className={styles.reportDecisionBar}>
          <div>
            <strong>
              {criticalFindingCount > 0
                ? "Approval requires remediation"
                : "Management decision required"}
            </strong>
            <span>
              {criticalFindingCount > 0
                ? `Resolve ${criticalFindingCount} critical finding${
                    criticalFindingCount === 1 ? "" : "s"
                  } before approval.`
                : "Review the findings, evidence, target mappings, and approval conditions."}
            </span>
          </div>
          <div className={styles.reportDecisionActions}>{approvalControls}</div>
          {action.isError && (
            <p role="alert">{normalizeApiError(action.error).message}</p>
          )}
        </section>
      )}
      {migration && !assessment && !assessmentQuery.isPending && (
        <section className="panel">
          <p className="muted">
            The feasibility report will appear after source inventory assessment
            completes.
          </p>
        </section>
      )}
    </>
  );
}
