"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, ShieldCheck, XCircle } from "lucide-react";
import Link from "next/link";

import { normalizeApiError } from "@/shared/api/client";
import { useAuth } from "@/shared/auth/auth-provider";
import { hasPermission } from "@/shared/auth/permissions";
import { PageHeading } from "@/shared/components/ui";

import { AssessmentReportCard } from "./assessment-report";
import { useMigration, useMigrationAssessment } from "./hooks";
import { migrations } from "./service";
import styles from "./migration-management.module.css";

export function MigrationDetails({ migrationId }: { migrationId: string }) {
  const { identity } = useAuth();
  const cache = useQueryClient();
  const migrationQuery = useMigration(migrationId);
  const migration = migrationQuery.data;
  const assessmentQuery = useMigrationAssessment(migrationId, true);
  const assessment = assessmentQuery.data?.assessment ?? null;

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
        <section className={`panel ${styles.approvalPanel}`}>
          <div>
            <span className="status-badge">
              {migration.status.replaceAll("_", " ")}
            </span>
            <h2>Approval gate</h2>
            <p className="muted">
              Approval records management authorization for migration planning.
              It does not execute workload changes.
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
