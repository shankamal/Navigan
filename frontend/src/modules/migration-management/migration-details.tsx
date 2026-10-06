"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, ShieldCheck, XCircle } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { normalizeApiError } from "@/shared/api/client";
import { useAuth } from "@/shared/auth/auth-provider";
import { hasPermission } from "@/shared/auth/permissions";
import { PageHeading } from "@/shared/components/ui";

import { AssessmentReportCard } from "./assessment-report";
import {
  useMigration,
  useMigrationAssessment,
  useSourceClusters,
} from "./hooks";
import type { SourceClusterRegistration, SourceEnrollment } from "./model";
import { migrations, sourceClusters } from "./service";
import styles from "./migration-management.module.css";

export function MigrationDetails({ migrationId }: { migrationId: string }) {
  const { identity } = useAuth();
  const cache = useQueryClient();
  const [sourceEnrollment, setSourceEnrollment] =
    useState<SourceEnrollment | null>(null);
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
  const migrationQuery = useMigration(migrationId);
  const migration = migrationQuery.data;
  const assessmentQuery = useMigrationAssessment(migrationId, true);
  const assessment = assessmentQuery.data?.assessment ?? null;
  const sourceClustersQuery = useSourceClusters(migration?.customerId ?? "");
  const sourceClusterId =
    typeof migration?.sourceConfiguration.sourceClusterId === "string"
      ? migration.sourceConfiguration.sourceClusterId
      : "";
  const sourceCluster = sourceClustersQuery.data?.items.find(
    (item) => item.sourceClusterId === sourceClusterId,
  );
  const effectiveSourceCluster = registeredSource ?? sourceCluster;
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
          registrationMethod: "LOCAL_KUBECONFIG",
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
  const sourceRegistrationMissing =
    migration?.status === "SOURCE_ENROLLMENT_PENDING" &&
    !sourceClustersQuery.isPending &&
    (!sourceClusterId || !sourceCluster);

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

  return (
    <>
      <PageHeading
        eyebrow="MIGRATION"
        title={migration?.name ?? "Migration assessment"}
        description="Review the trusted feasibility report and govern approval independently from the request creator."
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

      {migration && (
        <>
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
                      Reissue a short-lived setup file for the existing
                      registered source cluster. This does not create another
                      source cluster or migration request.
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
                </>
              )}
            </section>
          )}

          <section className={`panel ${styles.approvalPanel}`}>
            <div>
              <span className="status-badge">
                {migration.status.replaceAll("_", " ")}
              </span>
              <h2>Approval gate</h2>
              <p className="muted">
                Approval records management authorization for migration
                planning. It does not execute workload changes.
              </p>
            </div>

            <div className={styles.approvalActions}>
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
                    Approve
                  </button>
                  <button
                    type="button"
                    className="button button-secondary"
                    disabled={action.isPending}
                    onClick={() =>
                      action.mutate({
                        name: "reject",
                        reason: "Return migration assessment for remediation",
                      })
                    }
                  >
                    <XCircle size={17} />
                    Reject
                  </button>
                </>
              )}
              {!canSubmit && !canReview && !canDecide && (
                <span className="muted">
                  No approval action is available for your role at this stage.
                </span>
              )}
            </div>

            {action.isError && (
              <p role="alert">{normalizeApiError(action.error).message}</p>
            )}
          </section>
        </>
      )}

      {assessment && <AssessmentReportCard report={assessment} />}
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
