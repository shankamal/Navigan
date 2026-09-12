"use client";

import { useMutation } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, ShieldCheck, Sparkles } from "lucide-react";
import { Button, ErrorNotice } from "@/shared/components/ui";
import { environments } from "../services/environments";
import type { EnvironmentInput } from "../model/types";
import type { BlueprintReadiness } from "../model/types";

export function BlueprintReadinessPanel({
  distribution,
  configuration,
  onResult,
}: {
  distribution: string;
  configuration: EnvironmentInput["configuration"];
  onResult?: (report: BlueprintReadiness) => void;
}) {
  const validation = useMutation({
    mutationFn: () =>
      environments.validateBlueprints(distribution, configuration),
    onSuccess: (report) => onResult?.(report),
  });
  const report = validation.data;
  return (
    <section className="panel panel-padding blueprint-readiness-panel">
      <div className="blueprint-page-heading">
        <div>
          <p className="eyebrow">PROVISIONING READINESS</p>
          <h2>Blueprint Readiness Gate</h2>
          <p className="muted">
            Verify AWS access, IAM policies, encryption and worker compatibility
            before submitting this environment.
          </p>
        </div>
        <Button
          type="button"
          variant="secondary"
          disabled={validation.isPending}
          onClick={() => validation.mutate()}
        >
          <ShieldCheck size={17} aria-hidden="true" />
          {validation.isPending ? "Validating…" : "Validate blueprint"}
        </Button>
      </div>
      {validation.error && <ErrorNotice error={validation.error} />}
      {report && (
        <>
          <div
            className={
              report.status === "PASSED"
                ? "blueprint-readiness-summary passed"
                : "blueprint-readiness-summary failed"
            }
          >
            {report.status === "PASSED" ? (
              <CheckCircle2 size={22} aria-hidden="true" />
            ) : (
              <AlertTriangle size={22} aria-hidden="true" />
            )}
            <div>
              <strong>
                {report.status === "PASSED"
                  ? "Blueprint is ready for submission"
                  : `${report.blockingCount} blocking issue${report.blockingCount === 1 ? "" : "s"} found`}
              </strong>
              <p>
                Readiness score {report.score}/100 · {report.warningCount} warning
                {report.warningCount === 1 ? "" : "s"}
              </p>
            </div>
          </div>
          {!!report.findings.length && (
            <ul className="blueprint-finding-list">
              {report.findings.map((item) => (
                <li key={`${item.code}-${item.field}`}>
                  <span className={item.severity.toLowerCase()}>
                    {item.severity}
                  </span>
                  <div>
                    <strong>{item.message}</strong>
                    <code>{item.field}</code>
                    <p>{item.recommendation}</p>
                  </div>
                </li>
              ))}
            </ul>
          )}
          <div className="blueprint-advisor">
            <Sparkles size={18} aria-hidden="true" />
            <div>
              <strong>
                {report.advisor.mode === "BEDROCK"
                  ? "AI Blueprint Advisor"
                  : "Blueprint Advisor"}
              </strong>
              <p>{report.advisor.summary}</p>
            </div>
          </div>
        </>
      )}
    </section>
  );
}
